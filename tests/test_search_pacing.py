from types import SimpleNamespace

from hotpost import browser_search as bs
from hotpost.config import Settings


def test_pacing_announces_and_waits_before_each_search(tmp_path, monkeypatch):
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    messages, waits = [], []
    searcher.progress = messages.append
    monkeypatch.setattr(bs.time, 'sleep', waits.append)
    searcher._pace('Google Lens')
    searcher._pace('Google Lens')
    assert waits == [30, 30]
    assert all('30초 대기' in m for m in messages)


def test_captcha_cooldown_survives_worker_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path, source_browser_headless=True), tmp_path)
    page = SimpleNamespace(url='https://www.google.com/sorry/index')
    audit = {}
    messages = []
    searcher.progress = messages.append
    assert searcher._check_block(page, 'google-lens', audit)
    assert audit['status'] == 'captcha'
    assert any('CAPTCHA 인증 대기' in m for m in messages)
    bs.BROWSER_COOLDOWNS.clear()
    later = bs.BrowserSearcher(searcher.settings, tmp_path)
    # A blocked service must not even open a search tab.
    later._google(None, [], 10)
    assert later.searches[0]['status'] == 'verification_required'
    assert not later._cooling_down('yandex-images')


def test_captcha_on_same_url_does_not_masquerade_as_results(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path, source_browser_captcha_wait=0), tmp_path)
    page = SimpleNamespace(url='https://lens.google.com/search',
                           locator=lambda _: SimpleNamespace(inner_text=lambda: 'Unusual traffic'))
    audit = {}
    assert searcher._check_block(page, 'google-lens', audit)
    assert audit['status'] == 'captcha'


def test_tiktok_slider_challenge_stops_search_even_on_http_200(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path, source_browser_headless=True), tmp_path)
    page = SimpleNamespace(url='https://www.tiktok.com/search/video?q=camping',
                           locator=lambda _: SimpleNamespace(inner_text=lambda: 'Top Users Videos LIVE Drag the slider to fit the puzzle'))
    audit = {'http_status': 200}
    assert searcher._check_block(page, 'tiktok', audit)
    assert audit['status'] == 'captcha'
    assert searcher._cooling_down('tiktok')


def test_user_solved_captcha_continues_without_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    page = SimpleNamespace(url='https://www.google.com/sorry/index',
                           locator=lambda _: SimpleNamespace(inner_text=lambda: 'results'))
    page.wait_for_timeout = lambda _: setattr(page, 'url', 'https://lens.google.com/search')
    assert not searcher._check_block(page, 'google-lens', {})
    assert not searcher._cooling_down('google-lens')


def test_429_does_not_wait_or_retry_and_cooldown_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    monkeypatch.setattr(bs.time, 'time', lambda: 100)
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    audit = {}
    assert searcher._check_block(None, 'tiktok', audit, SimpleNamespace(status=429))
    assert audit['status'] == 'rate_limited'
    assert bs.BROWSER_COOLDOWNS['tiktok'] == 700
    monkeypatch.setattr(bs.time, 'time', lambda: 701)
    assert not searcher._cooling_down('tiktok')


def test_repeated_blocks_keep_ten_minute_ceiling_across_worker_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    clock = [100]
    monkeypatch.setattr(bs.time, 'time', lambda: clock[0])
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    searcher._block('tiktok', {}, 'rate_limited')
    clock[0] = 701
    later = bs.BrowserSearcher(searcher.settings, tmp_path)
    later._block('tiktok', {}, 'rate_limited')
    assert bs.BROWSER_COOLDOWNS['tiktok'] == 701 + 600
    clock[0] += 86401
    later._block('tiktok', {}, 'rate_limited')
    assert bs.BROWSER_COOLDOWNS['tiktok'] == clock[0] + 600


def test_old_setting_and_persisted_long_pause_cannot_exceed_ten_minutes(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    clock = [100]
    monkeypatch.setattr(bs.time, 'time', lambda: clock[0])
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path, source_browser_block_cooldown=7200), tmp_path)
    searcher._block('tiktok', {}, 'rate_limited')
    assert bs.BROWSER_COOLDOWNS['tiktok'] == 700
    target = searcher._cooldown_path('tiktok')
    target.write_text(json.dumps({'until': 7300, 'blocked_at': 100, 'reason': 'rate_limited'}))
    bs.BROWSER_COOLDOWNS['tiktok'] = 7300
    clock[0] = 701
    assert not searcher._cooling_down('tiktok')


def test_one_paced_search_request_detects_429_without_extra_auth_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    events = []
    monkeypatch.setattr(bs.time, 'sleep', lambda seconds: events.append(('wait', seconds)))
    page=SimpleNamespace(route=lambda *a:None,close=lambda:None,
        goto=lambda *a,**k:events.append(('search',None)) or SimpleNamespace(status=429))
    context = SimpleNamespace(new_page=lambda:page)
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    searcher._platforms(context, ['minced garlic'], 4, providers={'tiktok'})
    assert events == [('wait', 30), ('search', None)]
    assert searcher.searches[0]['status'] == 'rate_limited'
    assert searcher.searches[0]['requests'][0]['operation'] == 'search_navigation'


def test_login_wall_on_search_stops_provider_without_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    monkeypatch.setattr(bs.time, 'sleep', lambda _: None)
    calls=[]
    page=SimpleNamespace(url='https://www.douyin.com/search/demo',route=lambda *a:None,close=lambda:None,
        goto=lambda *a,**k:calls.append(a[0]) or SimpleNamespace(status=200),wait_for_timeout=lambda _:None,
        locator=lambda _:SimpleNamespace(inner_text=lambda:'登录后即可搜索更多精彩视频 验证码登录'))
    context=SimpleNamespace(new_page=lambda:page)
    searcher=bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    searcher._platforms(context,['蒜泥','大蒜'],4,providers={'douyin'})
    assert len(calls)==1
    assert searcher.searches[0]['status']=='login_required'
    assert searcher._cooling_down('douyin')


def test_expired_legacy_captcha_requires_explicit_recheck_and_reblocks(tmp_path,monkeypatch):
    import json
    from hotpost.search_access import request_manual_recheck
    monkeypatch.setattr(bs,'BROWSER_COOLDOWNS',{})
    searcher=bs.BrowserSearcher(Settings(data_dir=tmp_path),tmp_path)
    target=searcher._cooldown_path('google-lens');target.parent.mkdir()
    target.write_text(json.dumps({'reason':'captcha','blocked_at':1,'until':601}))
    assert searcher._cooling_down('google-lens')
    assert request_manual_recheck(tmp_path,'google-lens')
    assert not searcher._cooling_down('google-lens')
    searcher._block('google-lens',{},'captcha')
    assert searcher._cooling_down('google-lens')


def test_sms_login_label_is_not_captcha(tmp_path):
    from hotpost.search_access import challenge_on_page
    page=SimpleNamespace(url='https://www.douyin.com/',locator=lambda _:SimpleNamespace(inner_text=lambda:'验证码登录 密码登录'))
    assert not challenge_on_page(page)


def test_unfinished_search_page_is_not_empty_results_or_repeated_with_more_queries(tmp_path,monkeypatch):
    monkeypatch.setattr(bs,'BROWSER_COOLDOWNS',{})
    monkeypatch.setattr(bs.time,'sleep',lambda _:None)
    monkeypatch.setattr(bs,'_anchors',lambda *a:[])
    monkeypatch.setattr(bs,'_embedded_candidates',lambda *a:[])
    calls=[]
    page=SimpleNamespace(url='https://www.douyin.com/search/demo',route=lambda *a:None,close=lambda:None,
        goto=lambda *a,**k:calls.append(a[0]) or SimpleNamespace(status=200),wait_for_timeout=lambda _:None,
        mouse=SimpleNamespace(wheel=lambda *a:None),
        locator=lambda _:SimpleNamespace(inner_text=lambda:'精选 推荐 登录 综合 视频 用户'))
    searcher=bs.BrowserSearcher(Settings(data_dir=tmp_path),tmp_path)
    searcher._platforms(SimpleNamespace(new_page=lambda:page),['蒜泥','大蒜'],4,providers={'douyin'})
    assert len(calls)==1
    assert searcher.searches[-1]['status']=='page_unresolved'


def test_budget_closes_browser_saves_cookies_and_retains_partial_candidates(tmp_path,monkeypatch):
    import playwright.sync_api as pw
    saved=[];closed=[]
    context=SimpleNamespace(set_default_timeout=lambda _:None,cookies=lambda:[],close=lambda:closed.append(True))
    runtime=SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=lambda *a,**k:context))
    class Runtime:
        def __enter__(self):return runtime
        def __exit__(self,*a):pass
    monkeypatch.setattr(pw,'sync_playwright',Runtime)
    monkeypatch.setattr(bs,'export_cookies',lambda *a:saved.append('export'))
    monkeypatch.setattr(bs,'save_platform_cookies',lambda *a:saved.append(a[-1]))
    searcher=bs.BrowserSearcher(Settings(data_dir=tmp_path),tmp_path)
    def search(*a,**k):
        searcher.visual_candidates=[{'url':'https://example.com/one'}]
        searcher.candidates=[{'url':'https://example.com/two'}]
        searcher.deadline=bs.time.monotonic()+1
        searcher._pace('douyin')
    monkeypatch.setattr(searcher,'_platforms',search)
    result=searcher.run([],['test'],10)
    assert len(result['candidates'])==2
    assert closed==[True] and 'google' in saved and 'douyin' in saved
    assert result['searches'][-1]['status']=='budget_exhausted'
