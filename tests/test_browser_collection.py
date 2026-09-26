from types import SimpleNamespace
import json
import sqlite3

import pytest

from hotpost import cli, collectors
from hotpost.collectors.base import CollectionBlocked, CollectError
from hotpost.collectors.browser import BrowserCollector, exact_count, media_nodes
from hotpost.config import Settings
from hotpost.models import Post, Profile
from hotpost.storage import Storage


@pytest.mark.parametrize('raw,expected', [('1,227',1227), ('0',0), ('1.2만',None),
    ('13.7만\n5.7x',None), ('12K',None), ('',None), ('123\n1.1x',None)])
def test_only_exact_screen_counts_are_observations(raw, expected):
    assert exact_count(raw) == expected


def test_auth_preflight_failure_skips_every_account_and_closes(tmp_path, monkeypatch):
    class Blocked:
        closed = False
        def preflight(self):
            raise CollectionBlocked('login_required', '로그인 필요')
        def fetch(self, *args, **kwargs):
            pytest.fail('No account request allowed after failed preflight')
        def close(self):
            self.closed = True
    collector = Blocked()
    monkeypatch.setattr(collectors, 'get_collector', lambda *args: collector)
    settings = Settings(data_dir=tmp_path)
    store = Storage(settings.db_path)
    try:
        assert cli.collect(settings, store, 'browser', ['a','b','c'])[:3] == (0,0,0)
        run = store.last_run()
        assert run['accounts_skipped'] == 3
        assert run['stop_reason'] == 'login_required'
        assert run['finished_at']
        assert store.collection_status()['state'] == 'blocked'
        assert collector.closed
        assert store.conn.execute('select count(*) from account_collection_health').fetchone()[0] == 0
    finally:
        store.close()


def test_rate_limit_mid_run_preserves_completed_account(tmp_path, monkeypatch):
    class Limited:
        called = []
        closed = False
        def fetch(self, name, *args, **kwargs):
            self.called.append(name)
            if name == 'b':
                raise CollectionBlocked('rate_limited', '429')
            return Profile(name), [Post('one',name,1700000000,'image')], []
        def close(self):
            self.closed = True
    collector = Limited()
    monkeypatch.setattr(collectors, 'get_collector', lambda *args: collector)
    monkeypatch.setattr(cli, '_sleep_after_account', lambda *args: 0)
    settings = Settings(data_dir=tmp_path)
    store = Storage(settings.db_path)
    try:
        assert cli.collect(settings, store, 'browser', ['a','b','c'])[:3] == (1,1,1)
        assert collector.called == ['a','b'] and collector.closed
        assert store.last_run()['accounts_skipped'] == 1
        assert len(store.posts_for('a')) == 1
        assert store.collection_status()['last_full_success_at'] is None
    finally:
        store.close()


def test_account_specific_error_continues(tmp_path, monkeypatch):
    def fetch(name, *args, **kwargs):
        if name == 'a':
            raise CollectError('프로필 없음')
        return Profile(name), [], []
    monkeypatch.setattr(collectors, 'get_collector', lambda *args: SimpleNamespace(fetch=fetch))
    monkeypatch.setattr(cli, '_sleep_after_account', lambda *args: 0)
    settings = Settings(data_dir=tmp_path)
    store = Storage(settings.db_path)
    try:
        assert cli.collect(settings, store, 'browser', ['a','b'])[:3] == (1,1,0)
        assert store.last_run()['accounts_skipped'] == 0
        assert store.collection_status()['state'] == 'partial_failure'
    finally:
        store.close()


def test_partial_scope_is_not_reported_as_all_accounts_success(tmp_path):
    store = Storage(Settings(data_dir=tmp_path).db_path)
    try:
        store.upsert_managed_account('a')
        store.upsert_managed_account('b')
        rid = store.start_run(1700000000, 'browser')
        store.finish_run(rid, 1, 0, 1)
        assert store.collection_status()['last_full_success_at'] is None
        rid = store.start_run(1700000001, 'browser')
        store.finish_run(rid, 2, 0, 2)
        assert store.collection_status()['last_full_success_at']
    finally:
        store.close()


def test_response_data_does_not_erase_known_views_with_null():
    collector = BrowserCollector(Settings())
    node = {'code':'one','taken_at':1700000000,'media_type':2,'play_count':1201}
    collector._ingest({'data':{'edges':[{'node':node}]}})
    collector._ingest({'data':{**node,'play_count':None}})
    assert collector.nodes['one']['play_count'] == 1201
    response = SimpleNamespace(url='https://www.instagram.com/api/graphql',status=429,headers={})
    collector._response(response)
    assert collector.blocked.reason == 'rate_limited'


def test_document_media_format_keeps_counts_and_owner():
    raw = {'shortcode':'one', 'taken_at_timestamp':1700000000, 'is_video':True,
           'owner':{'username':'account'}, 'video_view_count':0,
           'edge_media_to_caption':{'edges':[{'node':{'text':'caption'}}]}}
    node = list(media_nodes({'data':raw}))[0]
    assert node['play_count'] == 0
    assert node['user']['username'] == 'account'
    assert node['caption']['text'] == 'caption'


def test_reels_partial_node_merges_views_without_losing_publish_date():
    from hotpost.collectors.web_graphql import _node_to_post
    collector = BrowserCollector(Settings())
    collector._ingest({'code':'one', 'taken_at':1700000000, 'media_type':2,
                       'caption':{'text':'original'}, 'user':{'username':'account'}})
    collector._ingest({'media':{'code':'one', 'media_type':2, 'play_count':1281234}})
    post = _node_to_post(collector.nodes['one'], 'account')
    assert post.views == 1281234
    assert post.taken_at == 1700000000
    assert post.caption == 'original'


@pytest.mark.parametrize('mime', ['application/json', 'text/javascript; charset=utf-8',
                                  'application/x-javascript'])
def test_graphql_json_body_accepts_instagram_content_types(mime):
    collector = BrowserCollector(Settings())
    raw = {'code':'one', 'taken_at':1700000000, 'media_type':2,
           'view_count':123456, 'user':{'username':'account'}}
    response = SimpleNamespace(url='https://www.instagram.com/graphql/query', status=200,
                               headers={'content-type':mime}, json=lambda: {'data':raw})
    collector._response(response)
    assert collector.nodes['one']['view_count'] == 123456


def test_fetch_collects_past_pinned_post_and_marks_approximation(tmp_path):
    settings = Settings(data_dir=tmp_path, collect_recovery_limit=5)
    collector = BrowserCollector(settings)
    codes = ['pinned','new','boundary']
    raw = [{'code':code, 'taken_at':stamp, 'media_type':2, 'product_type':'clips',
            'user':{'username':'account'}} for code,stamp in zip(codes,[100,300,200])]
    class Page:
        mouse = SimpleNamespace(wheel=lambda *args: None)
        def content(self):
            return '<meta property="og:description" content="123 Followers, 2 Following, 3 Posts">'
        def locator(self, selector):
            return SimpleNamespace(all_text_contents=lambda: [json.dumps(raw)])
        def evaluate(self, *args):
            return [{'href':f'/account/reel/{code}/', 'text':'1.2만' if code=='new' else '123',
                     'caption':'caption','thumbnail':''} for code in codes]
        def wait_for_timeout(self, *args): pass
    collector.browser = SimpleNamespace(page=Page(), navigate=lambda *args:None,
                                        verify_identity=lambda:None, guard=lambda:None)
    profile, posts, observations = collector.fetch('account',2,existing={'boundary':Post('boundary','account',200,'reel')})
    assert [p.shortcode for p in posts] == ['new','boundary','pinned']
    observation = next(o for o in observations if o.shortcode=='new')
    assert observation.success is False and observation.views is None
    assert '1.2만' in observation.reason
    assert profile.followers == 123


def test_browser_navigation_timeout_has_bounded_error():
    from playwright.sync_api import TimeoutError
    from hotpost.instagram_browser import InstagramBrowser
    def fail(*args, **kwargs):
        raise TimeoutError('internal URL with secret')
    browser = InstagramBrowser(Settings())
    browser.page = SimpleNamespace(goto=fail)
    with pytest.raises(CollectionBlocked) as error:
        browser.navigate('example/')
    assert error.value.reason == 'network_timeout'
    assert 'secret' not in str(error.value)


def test_reels_enrichment_scrolls_for_profile_posts_without_adding_older_posts(tmp_path):
    collector = BrowserCollector(Settings(data_dir=tmp_path, collect_recovery_limit=5))
    class Page:
        section = ''
        scroll = 0
        def content(self): return ''
        def wait_for_timeout(self, *args): pass
        def wheel(self, *args): self.scroll += 1
        def locator(self, selector):
            if not self.section:
                rows = [{'code':code,'media_type':2,'taken_at':stamp,'user':{'username':'account'}}
                        for code,stamp in [('pinned',100),('new',300)]]
            else:
                rows = [{'code':code,'media_type':2,'play_count':count}
                        for code,count in [('new',12000),('older',9000),('pinned',8000)]]
            return SimpleNamespace(all_text_contents=lambda:[json.dumps(rows)])
        def evaluate(self, *args):
            codes = ['pinned','new'] if not self.section else ['new','older'] + (['pinned'] if self.scroll else [])
            return [{'href':f'/account/reel/{code}/','text':'1.2만','caption':'','thumbnail':''} for code in codes]
    page=Page()
    page.mouse=SimpleNamespace(wheel=page.wheel)
    def navigate(path): page.section = 'reels' if path.endswith('/reels/') else ''
    collector.browser=SimpleNamespace(page=page,navigate=navigate,verify_identity=lambda:None,guard=lambda:None)
    _,posts,obs=collector.fetch('account',2,existing={'new':Post('new','account',300,'reel')})
    assert page.scroll > 0
    assert {p.shortcode for p in posts} == {'new','pinned'}
    assert {o.views for o in obs} == {12000,8000}
    assert all(o.success for o in obs)


@pytest.mark.parametrize('reason,retries', [('login_required',0),('rate_limited',0),('network_timeout',1),('profile_busy',1)])
def test_scheduled_retry_is_bounded_and_does_not_retry_auth(tmp_path, monkeypatch, reason, retries):
    from hotpost import scheduled_run
    settings = Settings(data_dir=tmp_path)
    monkeypatch.setattr(scheduled_run, 'load_settings', lambda: settings)
    calls, sleeps = [], []
    def run(*args, **kwargs):
        assert args[0][-2:] == ['run', '--acquire']
        import time
        store = Storage(settings.db_path)
        rid = store.start_run(int(time.time()), 'browser')
        store.finish_run(rid,0,0,0,skipped=12,stop_reason=reason)
        store.close()
        calls.append(1)
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(scheduled_run.subprocess, 'run', run)
    monkeypatch.setattr(scheduled_run.time, 'sleep', sleeps.append)
    assert scheduled_run.main() == 1
    assert len(calls) == retries + 1
    assert sleeps == [300] * retries
