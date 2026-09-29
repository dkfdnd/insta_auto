import json
import mimetypes
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest

from hotpost.config import Settings
from hotpost.criteria import defaults
from hotpost.display_settings import DEFAULTS
from hotpost.models import Post, Profile
from hotpost.report import build_report
from hotpost.storage import Storage

WEB=Path(__file__).resolve().parents[1]/'web'


@pytest.fixture
def dashboard(tmp_path):
    pw=pytest.importorskip('playwright.sync_api')
    settings=Settings(data_dir=tmp_path,web_dir=tmp_path,download_thumbs=False)
    store=Storage(settings.db_path);now=int(time.time())
    store.upsert_profile(Profile('creator',followers=1000))
    posts=[Post(f'old{i}','creator',now-(i+2)*86400,'reel',100,10,1000,caption='주방 요리') for i in range(12)]
    posts += [Post('camp','creator',now-3600,'reel',2000,100,30000,caption='캠핑 여행 수납 가방'),
              Post('clean','creator',now-7200,'reel',1000,100,20000,caption='청소 세탁 곰팡이')]
    store.upsert_posts(posts,collected_at=now)
    report=build_report(settings,store,'test',[],['creator']);store.close()
    report['acquisition_candidates']=[dict(shortcode='camp',username='creator',views_per_follower=30,views=30000)]
    state={'display':dict(DEFAULTS),'report':report,
           'health':{'collection':{'state':'success','newest_post_update':now},'schedule':{},'hot_tracking':{}},
           'notifications':[dict(id=1,message='새로운 게시물이 있습니다',created_at=now,seen_at=None),
                            dict(id=2,message='이전에 읽은 알림',created_at=now,seen_at=now)]}
    with pw.sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        def route(route):
            request=route.request;path=urlparse(request.url).path
            result={}
            if path=='/api/display-settings':
                if request.method=='PUT':state['display']=request.post_data_json['values']
                result={'values':state['display'],'defaults':DEFAULTS}
            elif path=='/api/criteria':
                if request.method=='PUT':
                    report['criteria']['values']=request.post_data_json['values'];report['criteria']['version']+=1
                    result={'criteria':report['criteria'],'report':report}
                else:result={**report['criteria'],'defaults':defaults(settings)}
            elif path=='/api/accounts':
                result={'accounts':[dict(username='creator',followers=1000,posts_count=14)],'count':1}
            elif path=='/api/notifications':
                result={'notifications':state['notifications'],'unseen':sum(n['seen_at'] is None for n in state['notifications'])}
            elif path=='/api/notifications/seen':
                before=len(state['notifications']);state['notifications']=[n for n in state['notifications'] if n['seen_at'] is None]
                result={'deleted':before-len(state['notifications'])}
            elif path.startswith('/api/notifications/'):
                for n in state['notifications']:
                    if n['id']==int(path.split('/')[3]):n['seen_at']=now
                result={'seen':True}
            elif path=='/api/collection-status':result=state['health']
            elif path=='/api/studio':result={'tasks':[]}
            elif path=='/api/jobs':result={'jobs':[]}
            elif path.startswith('/api/'):
                result={}
            elif path=='/data.js':
                route.fulfill(content_type='application/javascript',body='window.HOTPOST_REPORT='+json.dumps(report)+';');return
            else:
                file=WEB/('index.html' if path=='/' else path.lstrip('/'))
                if file.is_file():route.fulfill(content_type=mimetypes.guess_type(str(file))[0] or 'text/plain',body=file.read_bytes())
                else:route.fulfill(status=404)
                return
            route.fulfill(content_type='application/json',body=json.dumps(result))
        page.route('**/*',lambda r:route(r) if r.request.url.startswith('http://dashboard.test') else r.abort())
        yield page,state
        browser.close()
        assert not errors,errors


def test_main_is_compact_and_search_and_category_filters_work(dashboard):
    page,state=dashboard
    page.goto('http://dashboard.test/')
    page.wait_for_selector('.card')
    assert page.locator('#criteria,#period,#presets,#accounts,#method,#acquisition-candidates').count()==0
    assert not page.locator('#q').is_visible()
    assert '14일' in page.locator('#current-settings').text_content()
    assert page.locator('#result-count').inner_text()=='2'
    assert page.locator('.listing-heading #current-settings,.listing-heading #result-count').count()==0
    topic_box=page.locator('.topic-panel').bounding_box()
    summary_box=page.locator('#current-settings').bounding_box()
    assert summary_box['x']>topic_box['x'] and summary_box['y']==topic_box['y']
    assert not page.locator('.threshold-scale').is_visible()
    page.locator('.discovery-conditions summary').click()
    assert page.locator('.threshold-scale li').count()==3
    assert page.locator('.threshold-scale').is_visible()
    page.locator('.discovery-conditions summary').click()
    labels=page.locator('#topics').inner_text()
    assert '캠핑·여행' in labels and '청소·세탁' in labels and '#' not in labels
    page.locator('#topics button').filter(has_text='캠핑·여행').click()
    assert page.locator('.card').count()==1
    assert page.locator('#result-count').inner_text()=='1'
    assert page.locator('#result-context').inner_text()=='캠핑·여행'
    page.locator('#topics button').filter(has_text='캠핑·여행').click()
    page.locator('#search-toggle').click();page.locator('#q').fill('곰팡이')
    page.wait_for_function("document.querySelectorAll('.card').length===1")
    page.locator('#q').press('Escape')
    assert not page.locator('#q').is_visible() and page.locator('.card').count()==2
    assert page.locator('#result-count').inner_text()=='2'
    page.locator('.card').first.click();assert page.locator('#modal').is_visible()


def test_settings_save_survives_navigation_and_reload(dashboard):
    page,state=dashboard
    page.goto('http://dashboard.test/settings.html')
    page.wait_for_function("!document.querySelector('#settings-save').disabled")
    page.locator('#period [data-v="72"]').click()
    page.locator('#kind [data-v="video"]').click()
    page.locator('#sort').select_option('views')
    page.locator('#presets [data-preset="views"]').click()
    page.locator('#settings-save').click()
    page.wait_for_function("document.querySelector('#settings-status').textContent.startsWith('저장했습니다')")
    assert state['display']['period']==72 and state['display']['sort']=='views'
    assert state['report']['criteria']['values']['wvViews']==70
    page.goto('http://dashboard.test/');page.wait_for_selector('.card')
    assert '3일' in page.locator('#current-settings').text_content() and '조회수순' in page.locator('#current-settings').text_content()
    page.goto('http://dashboard.test/settings.html');page.wait_for_function("!document.querySelector('#settings-save').disabled")
    assert page.locator('#period [data-v="72"]').get_attribute('aria-pressed')=='true'
    page.locator('#detection [data-v="today"]').click()
    assert page.locator('#period [data-v="72"]').is_disabled()
    page.locator('#display-reset').click()
    assert not page.locator('#period [data-v="72"]').is_disabled()


def test_removed_account_warning_is_hidden_but_current_failures_remain(dashboard):
    page,state=dashboard
    state['report']['notes']=['@retired_account: 이전 수집 실패']
    page.goto('http://dashboard.test/');page.wait_for_selector('.card')
    assert not page.locator('#banner').is_visible()
    state['report']['notes'].append('@creator: 현재 목록 계정의 수집 실패')
    page.reload();page.wait_for_selector('.card')
    assert '@creator' in page.locator('#collection-health').inner_text()
    assert '@retired_account' not in page.locator('#collection-health').inner_text()
    assert '수집 기록' in page.locator('#collection-health').inner_text()
    assert len(state['report']['notes'])==2  # No historical report data is erased.


def test_notice_dismissal_persists_and_new_issue_reappears(dashboard):
    page,state=dashboard
    page.goto('http://dashboard.test/');page.wait_for_selector('#collection-health .notice-close')
    page.locator('#collection-health .notice-close').click()
    assert not page.locator('#collection-health').is_visible()
    page.reload();page.wait_for_selector('.card')
    assert not page.locator('#collection-health').is_visible()
    state['health']['collection'].update(state='blocked',last_run=dict(id=99,started_at=10,finished_at=20,stop_reason='login_required',notes='세션 만료'))
    page.reload();page.wait_for_selector('#collection-health:not([hidden])')
    assert '해결 방법:' in page.locator('#collection-health').inner_text()
    assert '로그인 복구 방법' in page.locator('#collection-health').inner_text()
    page.locator('#collection-health a').first.click()
    assert page.locator('#collection-help').get_attribute('open') is not None
    assert page.locator('#help-login').is_visible()


def test_report_warning_can_be_closed_without_hiding_other_notices(dashboard):
    page,state=dashboard
    state['report']['is_sample']=True
    page.goto('http://dashboard.test/');page.wait_for_selector('#banner .notice-close')
    page.locator('#banner .notice-close').click()
    assert not page.locator('#banner').is_visible()
    assert page.locator('#collection-health').is_visible()
    page.reload();page.wait_for_selector('.card')
    assert not page.locator('#banner').is_visible()


def test_account_summary_candidates_and_notification_actions(dashboard):
    page,state=dashboard
    page.goto('http://dashboard.test/accounts.html');page.wait_for_selector('.account-row')
    assert page.locator('.account-row').count()==1
    assert '평소 조회수' in page.locator('.account-row').inner_text()
    assert page.locator('.account-candidates').count()==1
    assert not page.locator('#notification-panel').is_visible()
    assert page.locator('#notification-count').inner_text()=='1'
    page.locator('#notification-toggle').click()
    assert page.locator('#notification-panel').is_visible()
    page.locator('#notification-clear').click()
    page.wait_for_function("document.querySelectorAll('.notification-item').length===1")
    assert state['notifications'][0]['seen_at'] is None
    page.locator('[data-seen="1"]').click()
    page.wait_for_function("document.querySelector('#notification-count').hidden")
    page.locator('#notification-clear').click()
    page.wait_for_selector('.notification-empty')
    page.keyboard.press('Escape');assert not page.locator('#notification-panel').is_visible()


@pytest.mark.parametrize('path',['/','/settings.html','/accounts.html'])
def test_mobile_layout_fits_viewport(dashboard,path):
    page,state=dashboard
    page.set_viewport_size({'width':390,'height':844})
    page.goto('http://dashboard.test'+path)
    ready='#cards .card' if path=='/' else '#crit-summary' if 'settings' in path else '.account-row'
    page.wait_for_selector(ready)
    if 'accounts' in path:page.locator('#notification-toggle').click()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')

@pytest.mark.parametrize('width',[1440,390])
def test_detail_prioritizes_production_and_collapses_analysis(dashboard,width):
    page,state=dashboard
    page.set_viewport_size({'width':width,'height':1000})
    original=json.dumps(state['report'],sort_keys=True)
    page.goto('http://dashboard.test/');page.wait_for_selector('.card')
    card=page.locator('.card').first
    for label in ['핫 최초 감지일','신뢰도','잠정 후보','비교 게시물']:
        assert label not in card.inner_text()
    assert '조회수' in card.inner_text()
    card.locator('.card-open-production').click()
    page.wait_for_selector('#begin-auto')
    assert page.locator('.benchmark-performance').is_visible()
    assert page.locator('#production-flow').is_visible()
    info=page.locator('.video-info')
    assert not info.evaluate('(el)=>el.open')
    assert not info.locator('.kv').is_visible()
    assert not page.locator('#source-download').is_visible()
    assert '추가 확인 사항' not in page.locator('#modal-body').inner_text()
    info.locator('summary').click()
    assert info.locator('.kv').is_visible()
    for label in ['핫 최초 감지일','팔로워','비교 게시물','반응 성숙도','신뢰도','판정 상태']:
        assert label in info.inner_text()
    assert page.locator('#source-download').is_visible()
    assert page.locator('#transcript-extract').is_visible()
    assert page.locator('#production-flow').is_visible()
    assert page.locator('.modal-card').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
    info.locator('summary').click()
    page.keyboard.press('Escape')
    assert not page.locator('#modal').is_visible()
    assert json.dumps(state['report'],sort_keys=True)==original
