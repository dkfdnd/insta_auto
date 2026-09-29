"""Exercise the real studio UI with isolated API fixtures, never the user's queue."""
import copy
import json
import mimetypes
import io
import wave
from pathlib import Path
from urllib.parse import urlparse

import pytest

WEB = Path(__file__).parents[1] / 'web'


def task(key, status, stage, automatic=True, job_status='queued'):
    t = dict(id=key, shortcode=key, title={'source':'작은 주방을 바꾸는 정리 아이디어',
        'script':'출근 가방 속 공간 활용', 'voice':'책상 위 케이블 정리',
        'edit':'작은 방의 조명 바꾸기', 'export':'간편한 아침 준비', 'done':'여행 가방 수납법'}[key],
        status=status, message='현재 작업 상태를 확인하세요', revision=1, created=1, updated=1,
        scripts=[dict(id='s1',text='실제 입력 보존 테스트 대본',created=1,origin='recommended')],
        voices=[],edits=[],proposals=[],sources=[],script_id='s1',approved_script_id=None,
        voice_id=None,approved_voice_id=None,edit_id=None,original_text='원본 발화',events=[],
        jobs=[dict(id='j1',kind=stage,status=job_status,updated=1)] if job_status else [],
        feedback={},feedback_revision=0,script_candidates=[],run_id='v2',latest_completed_run_id='v1',
        pipeline=[dict(id='v1',number=1,status='completed',steps=[],artifacts={},video_url='/old.mp4'),
                  dict(id='v2',number=2,status='running',steps=[],artifacts={})])
    keys=['sources','transcript','script','voice','project','export']
    index={'prepare':0,'rewrite':2,'voice':3,'edit':4,'export':5,'completed':6}[stage]
    t['pipeline'][1]['steps']=[dict(key=k,label=k,status='completed' if i<index else 'running' if i==index else 'pending') for i,k in enumerate(keys)]
    if status=='completed':
        t['latest_completed_run_id']='v2';t['pipeline'][1]['status']='completed';t['pipeline'][1]['video_url']='/final.mp4'
    if automatic:
        t['automation'] = dict(protocol=2,stage=stage,active=True)
    return t


@pytest.fixture
def studio_page():
    pw = pytest.importorskip('playwright.sync_api')
    tasks = [task('source','preparing','prepare'), task('script','script_review','rewrite',False,None),
             task('voice','voice_generating','voice',job_status='running'),
             task('edit','draft_review','edit',False,None),
             task('export','waiting_capcut','export'), task('done','completed','completed',job_status=None)]
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel='chrome', headless=True)
        except pw.Error as exc:
            pytest.skip(f'Chrome unavailable: {exc}')
        page = browser.new_page(viewport={'width':1600,'height':1000})
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.add_init_script("""const interval=window.setInterval;window.setInterval=(fn,ms,...args)=>{
            if(ms===3000){window.refreshStudio=fn;return 1;}return interval(fn,ms,...args);
        };""")
        def route(request):
            path=urlparse(request.request.url).path
            if path.startswith('/api/studio'):
                if path=='/api/studio':
                    result={'tasks':copy.deepcopy(tasks)}
                else:
                    parts=path.split('/')
                    t=next(t for t in tasks if t['id']==parts[3])
                    if request.request.method=='POST':
                        body=request.request.post_data_json
                        t['revision']+=1
                        if parts[-1]=='save-script':
                            t['feedback']['script_text']=body['text'];t['feedback_revision']+=1
                        elif parts[-1]=='approve-script':
                            t['approved_script_id']=t['script_id'];t['status']='voice_generating'
                    result=copy.deepcopy(t)
                request.fulfill(content_type='application/json',body=json.dumps(result))
            elif path.endswith('.mp4'):
                request.fulfill(status=404)
            else:
                file=WEB/path.lstrip('/')
                if file.is_file():request.fulfill(content_type=mimetypes.guess_type(str(file))[0] or 'text/plain',body=file.read_bytes())
                else:request.fulfill(status=404)
        page.route('http://studio.test/**',route)
        page.goto('http://studio.test/studio.html')
        page.wait_for_selector('[data-work="voice"]')
        yield page,tasks
        browser.close()
        assert not errors,errors


def test_columns_filters_and_stable_polling(studio_page):
    page,tasks=studio_page
    assert page.locator('.kanban-column').count()==6
    assert page.locator('[data-stage="export"] [data-work-card="export"] .board-status').inner_text()=='외부 작업 대기'
    assert page.locator('.work-card.is-running').count()==1
    page.locator('[data-work-card="voice"]').evaluate('(e)=>{window.keptCard=e;window.keptActivity=e.querySelector(".activity-dot")}')
    page.evaluate('refreshStudio()')
    assert page.evaluate('keptCard===document.querySelector("[data-work-card=voice]") && keptActivity===keptCard.querySelector(".activity-dot")')
    tasks[2].update(status='editing',revision=2)
    tasks[2]['jobs']=[dict(kind='edit',status='running')]
    page.evaluate('refreshStudio()')
    assert page.locator('[data-stage="edit"] [data-work="voice"]').count()==1
    assert page.evaluate('keptCard===document.querySelector("[data-work-card=voice]")')
    page.locator('[data-filter="review"]').click()
    assert page.locator('.work-card').count()==2
    page.locator('#search').fill('없는 작업')
    assert page.locator('.work-card').count()==0
    assert page.locator('#board-empty').is_visible()


def test_feedback_survives_poll_tab_close_switch_and_save(studio_page):
    page,tasks=studio_page
    page.locator('[data-work="voice"]').click()
    page.locator('#detail-tabs [data-detail-tab="script"]').click()
    editor=page.locator('[data-field="script"]')
    editor.fill('저장하기 전 직접 고친 문장')
    editor.evaluate('(e)=>window.keptEditor=e')
    tasks[2].update(revision=2,status='editing')
    page.evaluate('refreshStudio()')
    assert page.evaluate('keptEditor===document.querySelector("[data-field=script]")')
    assert editor.input_value()=='저장하기 전 직접 고친 문장'
    assert page.locator('#detail-tabs [data-detail-tab="script"]').get_attribute('aria-pressed')=='true'
    page.locator('#detail-tabs [data-detail-tab="voice"]').click()
    page.locator('#detail-tabs [data-detail-tab="script"]').click()
    assert editor.input_value()=='저장하기 전 직접 고친 문장'
    page.locator('#close-work').click()
    page.locator('[data-work="source"]').click()
    page.locator('#close-work').click()
    page.locator('[data-work="voice"]').click()
    assert editor.input_value()=='저장하기 전 직접 고친 문장'
    page.locator('[data-pf="save-script"]').click()
    page.wait_for_function('document.querySelector(".pf-message").textContent.includes("저장했습니다")')
    assert tasks[2]['feedback']['script_text']=='저장하기 전 직접 고친 문장'
    assert page.evaluate('localStorage.getItem("production-feedback-voice")') is None


def test_results_version_and_keyboard_drawer(studio_page):
    page,_=studio_page
    page.locator('[data-work="voice"]').click()
    page.locator('#detail-tabs [data-detail-tab="results"]').click()
    assert page.locator('.pf-summary > video').get_attribute('src')=='/old.mp4'
    page.locator('[data-pf-version]').select_option('v2')
    assert page.locator('.pf-summary > video').count()==0
    page.locator('#expand-work').click()
    assert page.locator('main').evaluate('(e)=>e.inert')
    page.keyboard.press('Escape')
    assert page.locator('#work-drawer').is_hidden()
    assert not page.locator('main').evaluate('(e)=>e.inert')
    page.locator('[data-work="voice"]').click()
    assert page.locator('[data-pf-version]').input_value()=='v2'
    page.locator('#close-work').click()
    page.set_viewport_size({'width':390,'height':844})
    page.locator('[data-work="source"]').click()
    assert page.locator('#work-drawer').get_attribute('aria-modal')=='true'
    assert page.locator('#work-drawer').bounding_box()['width']<=390
    page.locator('#close-work').click()
    assert not page.locator('main').evaluate('(e)=>e.inert')


def test_manual_approval_and_tab_input_preservation(studio_page):
    page,tasks=studio_page
    page.locator('[data-work="script"]').click()
    page.locator('#script-request').fill('도입부를 더 짧게')
    page.locator('#detail-tabs [data-detail-tab="sources"]').click()
    page.locator('#detail-tabs [data-detail-tab="script"]').click()
    assert page.locator('#script-request').input_value()=='도입부를 더 짧게'
    page.locator('[data-action="approve-script"]').click()
    page.wait_for_function('document.querySelector("#detail-tabs [data-detail-tab=voice]").getAttribute("aria-pressed")==="true"')
    assert tasks[1]['approved_script_id']=='s1'


def test_scroll_media_position_and_paused_refresh(studio_page):
    page,tasks=studio_page
    audio=io.BytesIO()
    with wave.open(audio,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000)
        wav.writeframes(b'\0\0'*8000*5)
    def audio_route(route):
        data=audio.getvalue()
        requested=route.request.headers.get('range')
        headers={'Accept-Ranges':'bytes'}
        status=200
        if requested:
            start,end=requested.removeprefix('bytes=').split('-')
            start=int(start or 0);end=int(end) if end else len(data)-1
            headers['Content-Range']=f'bytes {start}-{end}/{len(data)}'
            data=data[start:end+1];status=206
        route.fulfill(status=status,content_type='audio/wav',headers=headers,body=data)
    page.route('**/tone.wav',audio_route)
    tasks[2]['voices']=[dict(id='audio',path_url='/tone.wav',duration=5,speed=1,script_id='s1')]
    tasks[2]['voice_id']='audio';tasks[2]['revision']+=1
    page.evaluate('refreshStudio()')
    page.locator('[data-work="voice"]').click()
    player=page.locator('[data-pf-section="voice"] audio')
    player.evaluate('(e)=>e.load()')
    page.wait_for_function('document.querySelector("[data-pf-section=voice] audio").readyState>=2')
    player.evaluate('(e)=>e.currentTime=2')
    page.wait_for_function('document.querySelector("[data-pf-section=voice] audio").currentTime>=1.9')
    tasks[2]['revision']+=1
    page.evaluate('refreshStudio()')
    page.wait_for_function('document.querySelector("[data-pf-section=voice] audio").currentTime>=1.9')
    page.locator('#close-work').click()
    page.locator('[data-work="source"]').click()
    page.locator('#close-work').click()
    page.locator('[data-work="voice"]').click()
    page.wait_for_function('document.querySelector("[data-pf-section=voice] audio").currentTime>=1.9')
    page.locator('#detail-tabs [data-detail-tab="script"]').click()
    page.locator('#drawer-scroll').evaluate('(e)=>e.scrollTop=200')
    top=page.locator('#drawer-scroll').evaluate('(e)=>e.scrollTop')
    assert top>0
    page.locator('#close-work').click()
    page.locator('[data-work="voice"]').click()
    assert page.locator('#drawer-scroll').evaluate('(e)=>e.scrollTop')==top


def test_dirty_manual_request_survives_poll_and_reopen(studio_page):
    page,tasks=studio_page
    page.locator('[data-work="script"]').click()
    page.locator('#script-request').fill('보존할 AI 수정 요청')
    page.locator('#drawer-title').click()
    tasks[1]['revision']+=1
    page.evaluate('refreshStudio()')
    assert page.locator('#script-request').input_value()=='보존할 AI 수정 요청'
    page.locator('#close-work').click()
    page.locator('[data-work="script"]').click()
    assert page.locator('#script-request').input_value()=='보존할 AI 수정 요청'


def test_attention_actions_and_reduced_motion(studio_page):
    page,tasks=studio_page
    tasks[2].update(status='attention',error='음성 연결 실패',revision=2)
    tasks[2]['jobs'][0]['status']='failed'
    page.evaluate('refreshStudio()')
    assert page.locator('[data-stage="voice"] [data-work-card="voice"] [class="board-status"]').inner_text()=='확인 필요'
    page.locator('[data-work="voice"]').click()
    assert page.locator('.pf-runtime [data-pf="retry"]').is_visible()
    page.locator('#close-work').click()
    tasks[2].update(status='voice_generating',error='',revision=3)
    tasks[2]['jobs'][0]['status']='running'
    page.evaluate('refreshStudio()')
    page.emulate_media(reduced_motion='reduce')
    assert page.locator('[data-work-card="voice"] .activity-dot').evaluate('(e)=>getComputedStyle(e).animationName')=='none'


def test_numbered_progress_and_vertical_journey(studio_page):
    page,tasks=studio_page
    card=page.locator('[data-work-card="voice"]')
    assert card.locator('.card-phase').inner_text()=='4 / 6 단계'
    assert card.locator('.milestone-progress').get_attribute('aria-valuenow')=='3'
    assert card.locator('[data-step-state="done"]').count()==3
    assert card.locator('[data-step="voice"]').get_attribute('data-step-state')=='current'
    assert card.locator('.card-open').inner_text()=='음성 제작 작업 열기 →'
    card.locator('h3').click()
    assert page.locator('#journey-current').inner_text()=='4 / 6 단계'
    assert page.locator('[data-journey="voice"]').get_attribute('aria-current')=='step'
    page.locator('[data-journey="script"] button').click()
    assert page.locator('[data-field="script"]').is_visible()
    tasks[2].update(status='editing',revision=2)
    page.evaluate('refreshStudio()')
    assert page.locator('#journey-current').inner_text()=='5 / 6 단계'
    assert page.locator('[data-field="script"]').is_visible()
    page.locator('#close-work').click()
    assert page.locator('[data-work-card="done"] .milestone-progress').get_attribute('aria-valuenow')=='6'


def test_mobile_progress_expansion_and_stage_navigation(studio_page):
    page,_=studio_page
    page.set_viewport_size({'width':390,'height':844})
    page.locator('[data-jump-stage="export"]').click()
    page.wait_for_function('document.querySelector("#work-list").scrollLeft>0')
    page.locator('[data-work="voice"]').click()
    assert page.locator('#journey-panel').get_attribute('open') is None
    page.locator('#journey-panel > summary').click()
    assert page.locator('[data-journey="voice"]').is_visible()
    assert page.locator('#work-drawer').bounding_box()['width']<=390
