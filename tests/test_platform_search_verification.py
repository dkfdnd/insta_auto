from types import SimpleNamespace
import json

import pytest

from hotpost.config import Settings
from hotpost.platform_verification import TikTokSearchVerification
from hotpost.platform_session import PlatformSessionManager
from hotpost.search_access import access_record, manual_required


def page_for(verification, text):
    return SimpleNamespace(url=verification.url,
        locator=lambda _: SimpleNamespace(inner_text=lambda:text))


def test_loading_home_and_search_results_are_distinct():
    verify=TikTokSearchVerification('mushroom skewers')
    page=page_for(verify, 'Top Users Videos LIVE')
    assert verify.observe(page)['status']=='loading'
    verify.candidates={'one':{'url':'one'}}
    assert verify.observe(page)=={'status':'results','candidates':1}
    page.url='https://www.tiktok.com/'
    assert verify.observe(page)['status']=='page_changed'
    page.url='https://www.tiktok.com/search/video?q=a+different+query'
    assert verify.observe(page)['status']=='page_changed'


@pytest.mark.parametrize('text,status',[
    ('슬라이더를 드래그하여 퍼즐을 맞추세요','captcha'),
    ('Log in to search','login_required'),
    ('No results found','no_results'),
])
def test_visible_authentication_and_empty_search_are_distinct(text,status):
    verify=TikTokSearchVerification('mushroom skewers')
    assert verify.observe(page_for(verify,text))['status']==status


def test_observation_uses_existing_matching_response_without_new_requests():
    verify=TikTokSearchVerification('mushroom skewers')
    handlers={}
    page=page_for(verify,'Top Users Videos LIVE')
    page.on=lambda event,handler:handlers.update({event:handler})
    verify.attach(page)
    body={'status_code':0,'item_list':[{'id':'1234567890123','author':{'uniqueId':'cook'},'video':{}}]}
    response=lambda keyword:SimpleNamespace(url='https://www.tiktok.com/api/search/item/full/?keyword='+keyword,
        json=lambda:body)
    handlers['response'](response('other'))
    assert verify.observe(page)['status']=='loading'
    handlers['response'](response('mushroom+skewers'))
    assert verify.observe(page)['status']=='results'


@pytest.mark.parametrize('body,explicit,expected_gate',[
    ('Top Users Videos LIVE',True,True),
    ('슬라이더를 드래그하여 퍼즐을 맞추세요',True,True),
    ('No results found',False,True),
    ('No results found',True,False),
])
def test_verification_preserves_window_until_done_and_only_confirmed_search_releases_gate(
        tmp_path,monkeypatch,body,explicit,expected_gate):
    import playwright.sync_api as pw
    import hotpost.platform_session as module
    gate=tmp_path/'search_cooldowns/tiktok.json';gate.parent.mkdir()
    gate.write_text(json.dumps({'reason':'captcha','requires_verification':True}))
    verify=TikTokSearchVerification('mushroom skewers')
    page=page_for(verify,body)
    events=[];handlers={}
    page.on=lambda event,handler:handlers.update({event:handler})
    page.goto=lambda url,**kw:events.append(('navigate',url))
    page.is_closed=lambda:False
    context=SimpleNamespace(pages=[page],cookies=lambda:[dict(domain='.tiktok.com',path='/',
        name='sessionid',value='fixture',expires=-1)],close=lambda:events.append(('closed',None)))
    paths=[]
    def launch(path,**kw): paths.append(path); return context
    class Runtime:
        def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
        def __exit__(self,*a):pass
    monkeypatch.setattr(pw,'sync_playwright',Runtime)
    monkeypatch.setattr(module.time,'sleep',lambda _:None)
    monkeypatch.setattr(module,'probe_platform_auth',lambda *a:pytest.fail('No extra /login request'))
    class Stop:
        count=0
        def wait(self,_):
            self.count+=1
            if self.count<=3:
                assert not any(e[0]=='closed' for e in events)
                return False
            return True
        def is_set(self):return explicit
    manager=PlatformSessionManager(Settings(data_dir=tmp_path))
    manager.stop_event=Stop();manager.active_platform='tiktok'
    manager._work('tiktok',verify)
    assert not manager.error
    assert paths==[str(manager.settings.source_browser_profile_dir)]
    assert len([e for e in events if e[0]=='navigate'])==1
    assert events[-1][0]=='closed'
    assert manual_required(access_record(tmp_path,'tiktok')) is expected_gate
    assert not module.BROWSER_LOCK.locked()


def test_busy_collection_cannot_be_opened_twice_but_lock_is_not_released(tmp_path,monkeypatch):
    import playwright.sync_api as pw
    import hotpost.platform_session as module
    class Runtime:
        def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(
            launch_persistent_context=lambda *a,**kw:pytest.fail('Cannot share busy profile')))
        def __exit__(self,*a):pass
    monkeypatch.setattr(pw,'sync_playwright',Runtime)
    manager=PlatformSessionManager(Settings(data_dir=tmp_path))
    module.BROWSER_LOCK.acquire()
    try:
        manager._work('tiktok',TikTokSearchVerification('mushroom skewers'))
        assert '수집 검색이 진행 중' in manager.error
        assert module.BROWSER_LOCK.locked()
    finally:module.BROWSER_LOCK.release()


def test_query_validation_occurs_before_launch(tmp_path):
    manager=PlatformSessionManager(Settings(data_dir=tmp_path))
    with pytest.raises(ValueError):manager.start('instagram','mushroom skewers')
    for query in ('',None,123,'x'*181):
        with pytest.raises(ValueError):TikTokSearchVerification(query)
    assert not manager.active
