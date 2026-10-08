from types import SimpleNamespace
import json
import time
import threading

import pytest

from hotpost.config import Settings
from hotpost.platform_session import PlatformSessionManager
from hotpost.browser_profile import _platform_rows, save_platform_cookies, restore_platform_cookies


def test_busy_search_does_not_delay_login(tmp_path, monkeypatch):
    import playwright.sync_api as pw
    from hotpost.browser_profile import BROWSER_LOCK
    launched = threading.Event()
    paths = []
    page = SimpleNamespace(goto=lambda *a, **k: None, bring_to_front=lambda: None)
    context = SimpleNamespace(pages=[page], cookies=lambda: [], close=lambda: None)
    def launch(path, **kwargs):
        paths.append(path)
        launched.set()
        return context
    class Runtime:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
        def __exit__(self, *args): pass
    monkeypatch.setattr(pw, 'sync_playwright', Runtime)
    manager = PlatformSessionManager(Settings(data_dir=tmp_path))
    BROWSER_LOCK.acquire()
    try:
        manager.start('tiktok')
        assert launched.wait(2), 'Login must open while the search owns its profile'
        assert paths == [str(tmp_path/'platform_login_profiles/tiktok')]
        manager.finish()
        deadline = time.monotonic()+3
        while manager.active and time.monotonic() < deadline: time.sleep(.01)
        assert not manager.active and not manager.error
        assert BROWSER_LOCK.locked(), 'Login must not release the search lock'
    finally:
        BROWSER_LOCK.release()
        manager.finish()


def test_closed_login_window_releases_active_state(tmp_path, monkeypatch):
    import playwright.sync_api as pw
    page = SimpleNamespace(goto=lambda *a, **k: None, is_closed=lambda: True)
    context = SimpleNamespace(pages=[page], cookies=lambda: [], close=lambda: None)
    class Runtime:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=lambda *a, **k: context))
        def __exit__(self, *args): pass
    monkeypatch.setattr(pw, 'sync_playwright', Runtime)
    manager = PlatformSessionManager(Settings(data_dir=tmp_path))
    manager._work('tiktok')
    assert not manager.active and not manager.error
    assert '닫혔습니다' in manager.message


def test_session_cookie_restore_preserves_newer_live_cookie_and_platform_boundary(tmp_path):
    cookies = [dict(domain='.tiktok.com', path='/', name='sessionid', value='fixture', expires=-1),
               dict(domain='.instagram.com', path='/', name='sessionid', value='fixture-ig', expires=-1),
               dict(domain='.tiktok.com', path='/', name='expired', value='old', expires=time.time()-10)]
    save_platform_cookies(cookies, tmp_path, 'tiktok')
    saved = json.loads((tmp_path/'platform_sessions/tiktok.json').read_text())
    assert [c['name'] for c in saved['cookies']] == ['sessionid']
    additions = []
    live = dict(cookies[0], value='newer')
    restore_platform_cookies(SimpleNamespace(cookies=lambda:[live], add_cookies=additions.extend), tmp_path, ['tiktok'])
    assert additions == []
    restore_platform_cookies(SimpleNamespace(cookies=lambda:[], add_cookies=additions.extend), tmp_path, ['tiktok'])
    assert len(additions) == 1 and additions[0]['expires'] == -1
    assert not any(c['domain'].endswith('instagram.com') for c in additions)


def test_expired_cookie_and_lookalike_domain_are_not_saved_session():
    rows = _platform_rows([dict(domain='.fake-tiktok.com',name='sessionid',value='fixture'),
        dict(domain='.tiktok.com',name='sessionid',value='fixture',expires=time.time()-1)])
    assert not next(p for p in rows if p['id']=='tiktok')['cookie_present']


def test_one_platform_login_does_not_open_other_sites(tmp_path, monkeypatch):
    import playwright.sync_api as pw
    import hotpost.platform_session as module
    opened = []
    cookies = [dict(domain='.tiktok.com',path='/',name='sessionid',value='fixture',expires=-1)]
    page = SimpleNamespace(goto=lambda url, **kw:opened.append(url))
    context = SimpleNamespace(pages=[page],cookies=lambda:cookies,close=lambda:None)
    playwright = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=lambda *a,**k:context))
    class Runtime:
        def __enter__(self):return playwright
        def __exit__(self,*args):pass
    monkeypatch.setattr(pw,'sync_playwright',Runtime)
    checked = []
    monkeypatch.setattr(module,'probe_platform_auth',lambda ctx,key:checked.append(key) or 'authenticated')
    monkeypatch.setattr(module.time,'sleep',lambda _:None)
    manager=PlatformSessionManager(Settings(data_dir=tmp_path))
    manager.stop_event.set()
    manager._work('tiktok')
    assert len(opened)==1 and 'tiktok.com/login' in opened[0]
    assert checked==['tiktok']
    assert next(p for p in manager.status()['platforms'] if p['id']=='tiktok')['connected']
    assert (tmp_path/'platform_sessions/interactive/tiktok.json').is_file()


def test_instagram_login_uses_existing_collection_profile(tmp_path,monkeypatch):
    import hotpost.instagram_browser as module
    paths=[];opened=[]
    page=SimpleNamespace(goto=lambda url,**kw:opened.append(url))
    context=SimpleNamespace(pages=[page],cookies=lambda:[dict(domain='.instagram.com',path='/',
        name='sessionid',value='fixture',expires=-1)])
    class ExistingBrowser:
        def __init__(self,settings):paths.append(settings.data_dir/'instagram_browser');self.context=context
        def open(self):return self
        def close(self):pass
        def verify_identity(self):pass
    monkeypatch.setattr(module,'InstagramBrowser',ExistingBrowser)
    manager=PlatformSessionManager(Settings(data_dir=tmp_path));manager.stop_event.set()
    manager._work('instagram')
    assert paths==[tmp_path/'instagram_browser']
    assert opened==['https://www.instagram.com/accounts/login/']
    assert (tmp_path/'platform_sessions/instagram.json').is_file()
    assert not manager.settings.source_browser_cookie_file.exists()
    assert next(p for p in manager.status()['platforms'] if p['id']=='instagram')['connected']


def test_unsupported_platform_does_not_launch_and_active_target_cannot_change(tmp_path,monkeypatch):
    import hotpost.platform_session as module
    monkeypatch.setattr(module.threading,'Thread',lambda **kw:SimpleNamespace(start=lambda:None))
    manager=PlatformSessionManager(Settings(data_dir=tmp_path))
    with pytest.raises(ValueError):manager.start('https://untrusted.example')
    assert not manager.active
    assert manager.start('tiktok')['active_platform']=='tiktok'
    with pytest.raises(ValueError):manager.start('instagram')
    assert manager.active_platform=='tiktok'


@pytest.mark.parametrize('explicit,url,body,expected',[
    (True,'https://www.google.com/imghp','Google Images',False),
    (False,'https://www.google.com/imghp','Google Images',True),
    (True,'https://www.google.com/sorry/index','Unusual traffic',True),
    (True,'https://example.com/','Other page',True),
    (True,'https://www.google.com/imghp','',True),
])
def test_only_explicit_save_on_loaded_platform_page_releases_access_gate(tmp_path,monkeypatch,explicit,url,body,expected):
    import playwright.sync_api as pw
    import hotpost.platform_session as module
    from hotpost.search_access import access_record,manual_required
    gate=tmp_path/'search_cooldowns/google-lens.json';gate.parent.mkdir()
    gate.write_text(json.dumps({'reason':'captcha','until':1}))
    page=SimpleNamespace(url=url,goto=lambda *a,**k:None,
        locator=lambda _:SimpleNamespace(inner_text=lambda:body))
    context=SimpleNamespace(pages=[page],cookies=lambda:[],close=lambda:None)
    runtime=SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=lambda *a,**k:context))
    class Runtime:
        def __enter__(self):return runtime
        def __exit__(self,*a):pass
    monkeypatch.setattr(pw,'sync_playwright',Runtime)
    monkeypatch.setattr(module,'probe_platform_auth',lambda *a:pytest.fail('Google must not send an extra auth request'))
    manager=PlatformSessionManager(Settings(data_dir=tmp_path))
    manager.stop_event=SimpleNamespace(wait=lambda _:True,is_set=lambda:explicit)
    manager._work('google')
    assert not manager.error
    assert manual_required(access_record(tmp_path,'google-lens')) is expected
    assert not next(row for row in manager.status()['platforms'] if row['id']=='google')['connected']


def test_locked_cookie_database_is_unknown_not_logged_out(tmp_path):
    from hotpost.browser_profile import profile_cookie_status,source_context_options
    db=tmp_path/'Default/Network/Cookies';db.parent.mkdir(parents=True);db.write_bytes(b'not sqlite')
    rows=profile_cookie_status(tmp_path)
    assert all(row['cookie_readable'] is False and row['auth_status']=='unverified' for row in rows)
    assert source_context_options()['locale']=='ko-KR'
