"""Browser regression coverage; skips on machines without Playwright/Chrome."""
from pathlib import Path

import pytest


def test_focused_version_selector_switches_preview():
    browser_api = pytest.importorskip('playwright.sync_api')
    with browser_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel='chrome', headless=True)
        except browser_api.Error as exc:
            pytest.skip(f'Chrome unavailable: {exc}')
        try:
            page = browser.new_page()
            page.route('http://studio.test/**', lambda route: route.fulfill(
                content_type='text/html', body='<div id="root"></div>'))
            page.goto('http://studio.test/')
            page.add_script_tag(path=str(Path(__file__).parents[1]/'web'/'studio-board.js'))
            page.add_script_tag(path=str(Path(__file__).parents[1]/'web'/'production-flow.js'))
            page.evaluate("""() => ProductionFlow.mount(document.querySelector('#root'), {
                id:'work-test', run_id:'v2', latest_completed_run_id:'v2',
                automation:{protocol:2,active:true}, status:'completed', message:'Ready',
                pipeline:[1,2].map(n=>({id:'v'+n,number:n,status:'completed',
                    steps:[],artifacts:{},video_url:'/video-'+n+'.mp4'}))
            })""")
            selector = page.locator('[data-pf-version]')
            selector.focus()
            selector.select_option('v1')
            assert page.locator('.pf-summary > video').get_attribute('src') == '/video-1.mp4'
            selector.focus()
            selector.select_option('v2')
            assert page.locator('.pf-summary > video').get_attribute('src') == '/video-2.mp4'
        finally:
            browser.close()

@pytest.fixture
def flow_page():
    browser_api = pytest.importorskip('playwright.sync_api')
    with browser_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel='chrome', headless=True)
        except browser_api.Error as exc:
            pytest.skip(f'Chrome unavailable: {exc}')
        page = browser.new_page(viewport={'width': 1280, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('http://studio.test/**', lambda route: route.fulfill(
            content_type='text/html', body='<div id="root"></div>'))
        page.goto('http://studio.test/')
        web = Path(__file__).parents[1]/'web'
        page.add_style_tag(path=str(web/'production-flow.css'))
        for name in ['studio-board.js', 'production-flow.js']:
            page.add_script_tag(path=str(web/name))
        page.evaluate('''() => {
            window.task = {id:'work-test', revision:1, run_id:'v2', latest_completed_run_id:'v1',
                automation:{protocol:2, active:true, stage:'prepare'}, status:'preparing',
                message:'후보 다운로드/검증 3/20', error:'', progress:100,
                jobs:[{kind:'prepare',status:'running'}], sources:[], scripts:[], voices:[], edits:[], proposals:[],
                pipeline:[1,2].map(n=>({id:'v'+n,number:n,status:n===1?'completed':'running',artifacts:{},
                    steps:['sources','transcript','script','voice','project','export'].map((key,i)=>({
                        key,label:['소스 확보','원본 대본 추출','제작 대본','TTS','CapCut 프로젝트','MP4 내보내기'][i],
                        status:n===1?'completed':i===0?'running':'pending'
                    }))}))};
            window.draw = () => ProductionFlow.mount(document.querySelector('#root'),task,{editor:true});
            draw();
        }''')
        try:
            yield page
            assert not errors
        finally:
            browser.close()


def test_current_step_order_real_activity_and_responsive_layout(flow_page):
    page = flow_page
    assert page.locator('.pf-steps li').count() == 6
    assert page.locator('.pf-connector').count() == 5
    assert page.locator('[aria-current="step"] b').inner_text() == '1. 소스 확보'
    assert page.locator('.pf-current-message').inner_text() == '후보 다운로드/검증 3/20'
    assert page.locator('.pf-next').inner_text() == '다음 단계 · 2. 원본 대본 추출'
    assert page.locator('.pf-spinner').count() == 2
    # A previous completed video and task-local 100% must not fill the new run.
    assert page.locator('[role=progressbar]').get_attribute('aria-valuenow') == '0'
    boxes = page.locator('.pf-steps li').all()
    assert boxes[0].bounding_box()['y'] == boxes[5].bounding_box()['y']
    page.set_viewport_size({'width': 390, 'height': 844})
    assert boxes[0].bounding_box()['y'] < boxes[5].bounding_box()['y']
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.emulate_media(reduced_motion='reduce')
    assert page.locator('.pf-spinner').first.evaluate('(el)=>getComputedStyle(el).animationName') == 'none'


@pytest.mark.parametrize('status,job,label', [
    ('preparing','queued','실행 대기'), ('waiting_capcut','queued','외부 작업 대기'),
    ('retry_wait','queued','재시도 대기'), ('paused','paused','일시중지'),
    ('attention','failed','확인 필요'), ('script_review','done','검토 필요'),
])
def test_waiting_error_and_review_do_not_spin(flow_page,status,job,label):
    page = flow_page
    page.evaluate('''([status,job])=>{
        task.status=status; task.jobs[0].status=job; task.revision++;
        task.error=status==='attention'?'연결을 확인하고 재시도하세요.':''; draw();
    }''', [status,job])
    assert label in page.locator('.pf-phase').inner_text()
    assert page.locator('.pf-spinner').count() == 0
    if status == 'attention':
        assert page.locator('.pf-recovery [data-pf=retry]').count() == 1


def test_polling_preserves_draft_and_updates_stage_and_recovery(flow_page):
    page = flow_page
    page.locator('[data-field=script]').fill('저장하지 않은 새 대본')
    page.evaluate('''()=>{
        window.inputBefore=document.querySelector('[data-field=script]');
        task.status='voice_generating';task.automation.stage='voice';task.jobs=[{kind:'voice',status:'running'}];
        task.pipeline[1].steps.forEach((s,i)=>s.status=i<3?'completed':i===3?'running':'pending');
        task.message='음성 합성 중';task.revision++;draw();
    }''')
    assert page.locator('[data-field=script]').input_value() == '저장하지 않은 새 대본'
    assert page.evaluate('inputBefore === document.querySelector("[data-field=script]")')
    assert page.locator('[aria-current=step] b').inner_text() == '4. TTS'
    assert page.locator('[role=progressbar]').get_attribute('aria-valuenow') == '3'
    assert '5. CapCut 프로젝트' in page.locator('.pf-next').inner_text()
    page.evaluate('''()=>{window.spinner=document.querySelector('.pf-steps .pf-spinner'); draw();}''')
    assert page.evaluate('spinner===document.querySelector(".pf-steps .pf-spinner")')
    page.evaluate('''()=>{task.error='음성 서비스 연결 필요';task.status='attention';task.jobs=[];task.revision++;draw();}''')
    assert page.locator('.pf-spinner').count() == 0
    assert page.locator('.pf-recovery [data-pf=retry]').count() == 1
    assert page.locator('.pf-current-message').inner_text() == '음성 서비스 연결 필요'
    page.evaluate('''()=>{task.error='';task.status='completed';task.pipeline[1].steps.forEach(s=>s.status='completed');task.message='내보내기 완료';task.revision++;draw();}''')
    assert page.locator('.pf-recovery [data-pf=retry]').count() == 0
    assert page.locator('[role=progressbar]').get_attribute('aria-valuenow') == '6'
    assert page.locator('[aria-current=step]').count() == 0
    assert '완성 영상' in page.locator('.pf-next').inner_text()


def setup_editor(page):
    page.evaluate('''()=>{
        task.scripts=[{id:'s1',text:'현재 제작 대본'}];task.script_id='s1';task.feedback={};task.feedback_revision=0;
        task.original_text='자동 인식 원문';task.reviewed_original_text='교정한 원본 발화';
        task.original_evidence={speech:[{start:1,text:'실제 발화'}],screen_text:[{text:'화면 광고 문구'}]};
        task.revision++;draw();window.requests=[];
        window.fetch=async(url,options={})=>{
            if(options.method!=='POST')return {ok:true,json:async()=>structuredClone(task)};
            const body=JSON.parse(options.body);requests.push({url,body});
            if(window.hold)await new Promise(resolve=>window.release=resolve);
            if(url.endsWith('/save-script'))task.feedback.script_text=body.text;
            if(url.endsWith('/save-original'))task.reviewed_original_text=body.text;
            if(url.endsWith('/apply-proposal'))task.feedback.script_text='AI가 고친 대본';
            task.revision++;task.feedback_revision++;
            return {ok:true,json:async()=>structuredClone(task)};
        };
    }''')


def test_ai_uses_visible_unsaved_script_and_proposal_arrives_without_losing_it(flow_page):
    page=flow_page;setup_editor(page)
    page.locator('[data-field=script]').fill('저장 전 사용자 수정 대본')
    page.locator('[data-field=script-request]').fill('도입을 간결하게')
    page.locator('[data-pf=propose-script]').click()
    page.wait_for_function('requests.length===1 && !document.querySelector("#root")._saving')
    assert page.evaluate('requests[0].body.base_text')=='저장 전 사용자 수정 대본'
    assert page.locator('[data-field=script]').input_value()=='저장 전 사용자 수정 대본'
    page.evaluate('''()=>{
        task.proposals.push({id:'p1',base_text:'저장 전 사용자 수정 대본',text:'AI가 고친 대본',summary:'도입 수정'});
        task.revision++;draw();
    }''')
    page.locator('[data-proposals] summary').click()
    assert '저장 전 사용자 수정 대본' in page.locator('.pf-compare').inner_text()
    page.locator('[data-pf=proposal]').click()
    page.wait_for_function('requests.length===2 && !document.querySelector("#root")._saving')
    assert page.locator('[data-field=script]').input_value()=='AI가 고친 대본'


def test_ai_status_updates_while_unsaved_input_survives(flow_page):
    page=flow_page;setup_editor(page)
    page.locator('[data-field=script]').fill('보존해야 할 사용자 입력')
    page.evaluate("""()=>{task.jobs.unshift({id:'ai1',kind:'proposal',status:'running'});task.revision++;draw();}""")
    status=page.locator('[data-ai-status=proposal]')
    assert '준비하고 있어요' in status.inner_text()
    assert page.locator('[data-pf=propose-script]').is_disabled()
    page.evaluate("""()=>{task.jobs[0].status='failed';task.jobs[0].error='요청을 구체화하세요';task.revision++;draw();}""")
    assert '요청을 구체화하세요' in status.inner_text()
    assert not page.locator('[data-pf=propose-script]').is_disabled()
    assert page.locator('[data-field=script]').input_value()=='보존해야 할 사용자 입력'


def test_typing_during_save_keeps_new_input_and_other_sections(flow_page):
    page=flow_page;setup_editor(page)
    page.locator('[data-field=script]').fill('첫 번째 저장 요청')
    page.locator('[data-field=speed]').fill('1.15')
    page.evaluate('window.hold=true')
    page.locator('[data-pf=save-script]').click()
    page.wait_for_function('typeof release === "function"')
    page.locator('[data-field=script]').fill('저장 응답 전에 더 쓴 대본')
    page.evaluate('release()')
    page.wait_for_function('!document.querySelector("#root")._saving')
    assert page.locator('[data-field=script]').input_value()=='저장 응답 전에 더 쓴 대본'
    assert page.locator('[data-field=speed]').input_value()=='1.15'
    assert page.evaluate('task.feedback.script_text')=='첫 번째 저장 요청'
    assert '저장하지 않은' in page.locator('[data-change-status]').inner_text()


def test_evidence_separation_stale_voice_and_result_review_survive_poll(flow_page):
    page=flow_page;setup_editor(page)
    page.evaluate('''()=>{
        task.feedback={script_text:'새 대본'};task.voices=[{id:'voice1',script_id:'s1',speed:1.05,duration:4,spoken_text:'실제 읽은 발음',path_url:'/voice.wav'}];task.voice_id='voice1';
        task.pipeline[0].video_url='/completed.mp4';task.revision++;draw();
    }''')
    assert '수정사항 반영 전 음성' in page.locator('.pf-audio-card').inner_text()
    assert page.locator('[data-pf-section=original]').is_visible()
    assert page.locator('.pf-original').evaluate('(e)=>e.open')
    assert page.locator('[data-field=original]').input_value()=='교정한 원본 발화'
    assert '화면 속 글자 · 발화와 별도 자료' in page.locator('.pf-original').inner_text()
    page.locator('[data-review-check=speech]').check()
    page.evaluate('document.activeElement.blur();task.revision++;draw()')
    assert page.locator('[data-review-check=speech]').is_checked()
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_reload_keeps_old_scene_draft_separate_from_new_edit(flow_page):
    page=flow_page;setup_editor(page)
    page.evaluate('''()=>{
        localStorage.setItem('production-feedback-work-test',JSON.stringify({'caption:old':'보관할 자막',script:'보관할 대본'}));
        localStorage.setItem('production-feedback-work-test-edit','old-edit');
        task.edit_id='new-edit';task.revision++;draw();
    }''')
    assert '이전 구간 입력' in page.locator('[data-change-status]').inner_text()
    page.locator('[data-change-status] summary').click()
    assert '보관할 자막' in page.locator('[data-change-status]').inner_text()
    page.locator('[data-pf=discard-local-edit]').click()
    assert page.locator('[data-field=script]').input_value()=='보관할 대본'
    assert page.evaluate("JSON.parse(localStorage.getItem('production-feedback-work-test'))") == {'script':'보관할 대본'}
