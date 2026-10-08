from types import SimpleNamespace

from hotpost import browser_search as bs
from hotpost.config import Settings
from hotpost.source_search.tiktok_results import search_response_candidates


def test_only_video_items_from_matching_search_response_are_candidates():
    body={'status_code':0,'data':[
        {'item':{'id':'123456789012345','author':{'uniqueId':'camping'},
                 'desc':'Tailgate tent setup','video':{'duration':20}}},
        {'user':{'uniqueId':'somebody'}},
        {'item':{'id':'987654321012345','author':{'uniqueId':'activity'},'desc':'Notification'}}]}
    url='https://www.tiktok.com/api/search/item/full/?keyword=tailgate+tent'
    hits=search_response_candidates(url,body,'tailgate tent')
    assert [h['url'] for h in hits]==['https://www.tiktok.com/@camping/video/123456789012345']
    assert hits[0]['title']=='Tailgate tent setup'
    assert not search_response_candidates(url,body,'a different query')
    assert not search_response_candidates(url.replace('/search/item/full/','/notice/'),body,'tailgate tent')
    assert not search_response_candidates(url,{**body,'status_code':1},'tailgate tent')


def test_waits_for_delayed_tiktok_results_without_reading_activity_links(tmp_path,monkeypatch):
    searcher=bs.BrowserSearcher(Settings(data_dir=tmp_path),tmp_path)
    monkeypatch.setattr(searcher,'_check_block',lambda *a:False)
    monkeypatch.setattr(bs,'empty_results_on_page',lambda p:False)
    monkeypatch.setattr(bs,'_anchors',lambda *a:(_ for _ in ()).throw(AssertionError('Must not scrape all activity links')))
    hits=[];waits=[]
    def wait(ms):
        waits.append(ms)
        if len(waits)==5:hits.append({'url':'https://www.tiktok.com/@camping/video/123456789012345'})
    audit={}
    result=searcher._wait_platform_results(SimpleNamespace(wait_for_timeout=wait),'tiktok','tent',audit,hits)
    assert result==hits and waits==[1000]*5
    assert audit['result_method']=='search_response'


def test_authentication_wall_stops_readiness_wait(tmp_path,monkeypatch):
    searcher=bs.BrowserSearcher(Settings(data_dir=tmp_path),tmp_path)
    monkeypatch.setattr(searcher,'_check_block',lambda *a:True)
    page=SimpleNamespace(wait_for_timeout=lambda _:(_ for _ in ()).throw(AssertionError('No retry on authentication')))
    assert searcher._wait_platform_results(page,'tiktok','tent',{},[]) is None


def test_unknown_loading_is_bounded_and_distinct_from_empty_results(tmp_path,monkeypatch):
    searcher=bs.BrowserSearcher(Settings(data_dir=tmp_path),tmp_path)
    monkeypatch.setattr(searcher,'_check_block',lambda *a:False)
    monkeypatch.setattr(bs,'empty_results_on_page',lambda p:False)
    waits=[]
    assert searcher._wait_platform_results(SimpleNamespace(wait_for_timeout=waits.append),'tiktok','tent',{},[])==[]
    assert waits==[1000]*15


def test_challenge_arriving_after_last_poll_cannot_become_parser_failure(tmp_path,monkeypatch):
    from hotpost.search_access import access_record,manual_required
    monkeypatch.setattr(bs,'BROWSER_COOLDOWNS',{})
    searcher=bs.BrowserSearcher(Settings(data_dir=tmp_path,source_browser_headless=True),tmp_path)
    reads=[]
    def text():
        reads.append(1)
        # Each of the sixteen polls reads challenge, login and empty state.
        return '검색 중' if len(reads)<=48 else '슬라이더를 드래그하여 퍼즐을 맞추세요'
    page=SimpleNamespace(url='https://www.tiktok.com/search/video',
        locator=lambda _:SimpleNamespace(inner_text=text),wait_for_timeout=lambda _:None)
    audit={}
    assert searcher._wait_platform_results(page,'tiktok','tent',audit,[]) is None
    assert audit['status']=='captcha' and manual_required(access_record(tmp_path,'tiktok'))


def test_challenge_in_final_diagnostic_snapshot_stops_without_more_queries(tmp_path,monkeypatch):
    from hotpost.search_access import access_record,manual_required
    monkeypatch.setattr(bs,'BROWSER_COOLDOWNS',{})
    monkeypatch.setattr(bs.time,'sleep',lambda _:None)
    monkeypatch.setattr(bs,'empty_results_on_page',lambda _:False)
    calls=[]
    page=SimpleNamespace(url='https://www.tiktok.com/search/video',route=lambda *a:None,
        close=lambda:None,wait_for_timeout=lambda _:None,mouse=SimpleNamespace(wheel=lambda *a:None),
        goto=lambda url,**kw:calls.append(url) or SimpleNamespace(status=200),
        locator=lambda _:SimpleNamespace(inner_text=lambda:'슬라이더를 드래그하여 퍼즐을 맞추세요'))
    searcher=bs.BrowserSearcher(Settings(data_dir=tmp_path,source_browser_headless=True),tmp_path)
    monkeypatch.setattr(searcher,'_check_block',lambda *a:False)
    monkeypatch.setattr(searcher,'_wait_platform_results',lambda *a:[])
    searcher._platforms(SimpleNamespace(new_page=lambda:page),['tent','camping'],10,providers={'tiktok'})
    assert len(calls)==1 and searcher.searches[-1]['status']=='captcha'
    assert manual_required(access_record(tmp_path,'tiktok'))
    assert not (tmp_path/'search_readiness/tiktok.json').exists()
