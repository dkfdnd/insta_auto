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
        for name in ['studio-board.js', 'caption-editor.js', 'production-flow.js']:
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
        task.source_search_retry_supported=true;
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


def test_additional_search_requires_new_condition_and_keeps_existing_success_quiet(flow_page):
    page=flow_page;setup_editor(page)
    page.evaluate('''()=>{task.jobs=[];task.sources=[{id:'src1',url:'/source.mp4'}];
        task.source_search={status:'done',message:'추가 수집 완료 · 신규 0개 / 보유 1개'};
        task.revision++;draw();}''')
    assert not page.locator('[data-search-options]').evaluate('(e)=>e.open')
    assert page.locator('[data-pf=retry-source-search]').count()==0
    page.locator('[data-search-options] > summary').click()
    page.locator('[data-pf=search]').click()
    assert page.evaluate('requests.length')==0
    assert '검색 조건을 입력' in page.locator('[data-search-validation]').inner_text()
    page.locator('[data-field=search]').fill('가방 내부 칸막이를 보여주는 장면')
    page.locator('[data-pf=search]').click()
    page.wait_for_function('requests.length===1 && !document.querySelector("#root")._saving')
    assert page.evaluate('requests[0].body.request')=='가방 내부 칸막이를 보여주는 장면'
    assert page.evaluate('requests[0].url.endsWith("/refresh-sources")')


def test_search_retry_targets_failed_search_and_polling_preserves_new_query(flow_page):
    page=flow_page;setup_editor(page)
    page.evaluate('''()=>{task.jobs=[{id:'search-failed',kind:'refresh_sources',status:'failed'},
        {id:'voice-failed',kind:'voice',status:'failed'}];
        task.source_search={status:'failed',message:'CAPTCHA'};task.revision++;draw();}''')
    page.locator('[data-search-options] > summary').click()
    page.locator('[data-field=search]').fill('나중에 검색할 새로운 조건')
    page.locator('[data-pf=retry-source-search]').click()
    page.wait_for_function('requests.length===1 && !document.querySelector("#root")._saving')
    assert page.evaluate('requests[0].body.retry_job_id')=='search-failed'
    assert page.locator('[data-field=search]').input_value()=='나중에 검색할 새로운 조건'
    page.evaluate('''()=>{window.searchInput=document.querySelector('[data-field=search]');
        task.jobs.unshift({kind:'refresh_sources',status:'running'});
        task.source_search={status:'running',message:'후보 영상 확인 중'};task.revision++;draw();}''')
    assert page.locator('[data-pf=search]').is_disabled()
    assert '소스 검색 진행 중' in page.locator('[data-search-status]').inner_text()
    assert page.locator('[data-pf=retry-source-search]').count()==0
    assert page.evaluate('searchInput===document.querySelector("[data-field=search]")')
    page.evaluate('''()=>{task.jobs=[];task.source_search={status:'done',message:'추가 수집 완료 · 신규 0개'};task.revision++;draw();}''')
    assert page.locator('[data-pf=search]').is_enabled()
    assert '신규 0개' in page.locator('[data-search-status]').inner_text()


def test_prepare_transcription_failure_is_not_presented_as_source_search_failure(flow_page):
    page=flow_page
    page.evaluate('''()=>{task.jobs=[{kind:'prepare',status:'failed'}];task.status='attention';
        task.error='원본 발화를 추출하지 못했습니다.';task.revision++;draw();}''')
    assert page.locator('[data-pf=retry-source-search]').count()==0
    page.evaluate('''()=>{task.error='제작에 사용할 소스 영상이 없습니다.';task.revision++;draw();}''')
    assert page.locator('[data-pf=retry-source-search]').count()==1


def test_old_server_cannot_silently_drop_retry_conditions(flow_page):
    page=flow_page
    page.evaluate('''()=>{task.jobs=[{id:'failed-search',kind:'refresh_sources',status:'failed'}];
        task.source_search={status:'failed',message:'연결 실패'};task.revision++;draw();}''')
    assert page.locator('[data-pf=retry-source-search]').is_disabled()
    assert '서버를 재시작' in page.locator('[data-search-status]').inner_text()


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
    assert not page.locator('.pf-original').evaluate('(e)=>e.open')
    page.locator('.pf-original > summary').click()
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

def test_used_sources_stay_separate_from_uploads_and_pending_selection(flow_page):
    page=flow_page;setup_editor(page)
    page.evaluate('''()=>{
      task.status='completed';task.automation.stage='completed';task.latest_completed_run_id='v2';task.jobs=[];
      task.sources=[{id:'used',url:'/used.mp4',original_name:'used.mp4'},
        {id:'new',url:'/new.mp4',original_name:'new.mp4',rights:'user_supplied'},
        {id:'found',url:'/found.mp4',title:'검색 영상'}];
      task.pipeline[1].inputs={source_ids:['used']};task.pipeline[1].artifacts.sources=[{id:'used'}];
      task.revision++;draw();
    }''')
    assert page.locator('[data-source-group=used] [data-field="source:used"]').is_checked()
    assert not page.locator('[data-source-group=added] [data-field="source:new"]').is_checked()
    assert page.locator('[data-source-group=other] [data-field="source:found"]').count()==1
    page.locator('[data-field="source:used"]').uncheck()
    page.locator('[data-field="source:new"]').check()
    page.evaluate('task.revision++;draw()')
    assert not page.locator('[data-source-group=used] [data-field="source:used"]').is_checked()
    assert page.locator('[data-source-group=added] [data-field="source:new"]').is_checked()
    assert page.locator('[data-field="source:new"]').evaluate('(e)=>e===document.activeElement')
    page.locator('[data-pf=save-sources]').click()
    page.wait_for_function('requests.length===1')
    assert page.evaluate('requests[0].body.source_ids')==['new']
    assert page.locator('[data-source-group=used] [data-field="source:used"]').count()==1


def test_caption_sync_controls_validate_bounds_preserve_draft_and_loop(flow_page):
    page=flow_page;setup_editor(page)
    page.evaluate('''()=>{
      task.jobs=[];task.caption_editor_supported=true;task.edit_id='e1';task.edits=[{id:'e1',duration:10,preview_url:'/preview.mp4',clean_preview_url:'/clean.mp4',plan:{
        cues:[{id:'c1',text:'한 문장',start:.2,end:1.2}],shots:[{id:'s1',video_url:'/s.mp4',start:0,end:2}],
        beats:[{id:'b1',cue_id:'c1',start:0,end:2,text:'한 문장',selected_shot_id:'s1',options:[{shot_id:'s1',reason:'대응 장면'}]}]}}];
      task.revision++;draw();
      const v=document.querySelector('[data-edit-preview]');
      Object.defineProperty(v,'duration',{get:()=>10});Object.defineProperty(v,'readyState',{get:()=>4});
      Object.defineProperty(v,'paused',{get:()=>false});v.play=()=>Promise.resolve();
    }''')
    page.locator('[data-sync=earlier]').click()
    assert float(page.locator('[data-field="start:b1"]').input_value())==.1
    assert float(page.locator('[data-field="end:b1"]').input_value())==1.1
    page.locator('[data-sync=loop]').click()
    assert page.locator('[data-sync=loop]').get_attribute('aria-pressed')=='true'
    page.evaluate("const v=document.querySelector('[data-edit-preview]');v.currentTime=1.5;v.dispatchEvent(new Event('timeupdate'))")
    assert page.locator('[data-edit-preview]').evaluate('(v)=>v.currentTime')==0
    page.locator('[data-sync=loop]').click()
    assert page.locator('[data-sync=loop]').get_attribute('aria-pressed')=='false'
    page.locator('[data-edit-preview]').evaluate('(v)=>v.currentTime=.6')
    page.locator('.ce-cue details > summary').click()
    page.locator('[data-sync=start]').click()
    assert float(page.locator('[data-field="start:b1"]').input_value())==.6
    assert '0.60–1.10초' in page.locator('[data-sync-range]').inner_text()
    page.locator('[data-edit-preview]').evaluate('(v)=>v.currentTime=.4')
    page.locator('[data-sync=end]').click()
    assert float(page.locator('[data-field="end:b1"]').input_value())==1.1
    assert '끝은 시작보다 뒤' in page.locator('.pf-sync-feedback').inner_text()
    page.locator('[data-pf=save-captions]').click()
    page.wait_for_function('requests.length===1')
    change=page.evaluate('requests[0].body.changes[0]')
    assert change['start']==.6 and change['end']==1.1 and change['text']=='한 문장'
    page.evaluate('''()=>{
      localStorage.setItem('production-feedback-work-test',JSON.stringify({'start:b1':'.4','end:b1':'1.5'}));
      const root=document.querySelector('#root');root.innerHTML='';root._dirty=false;root._renderedRevision=null;draw();
    }''')
    assert page.locator('[data-sync-times]').inner_text()=='0.40–1.50초'


def test_live_caption_shift_paints_without_render_and_exports_last_input(flow_page):
    page=flow_page;setup_editor(page)
    page.evaluate('''()=>{
      task.jobs=[];task.caption_editor_supported=true;task.edit_id='e1';
      task.edits=[{id:'e1',duration:3,clean_preview_url:'/base.mp4',plan:{
        cues:[{id:'c1',text:'실시간 자막',start:.2,end:1.2}],
        beats:[{id:'b1',cue_id:'c1',emphasis:0}]}}];task.revision++;draw();
      const v=document.querySelector('[data-edit-preview]');
      Object.defineProperty(v,'duration',{get:()=>3});Object.defineProperty(v,'readyState',{get:()=>4});
      v.currentTime=.25;v.dispatchEvent(new Event('seeked'));
    }''')
    canvas=page.locator('[data-caption-canvas]')
    assert canvas.get_attribute('data-active-cue')=='b1'
    assert canvas.evaluate('(c)=>c.getContext("2d").getImageData(0,0,1080,1920).data.some(v=>v>0)')
    page.locator('[data-sync=later]').click()
    assert canvas.get_attribute('data-active-cue')==''
    assert page.evaluate('requests.length')==0
    page.locator('[data-caption-undo]').click()
    assert canvas.get_attribute('data-active-cue')=='b1'
    page.locator('[data-field="caption:b1"]').fill('내보낼 최종 문구')
    page.locator('[data-sync=later]').click()
    page.evaluate('window.hold=true')
    page.locator('[data-pf=export-edit]').click()
    page.wait_for_function('requests.length===1')
    assert page.evaluate('requests[0].url.endsWith("/export-edit")')
    assert page.evaluate('requests[0].body.changes[0]')=={'beat_id':'b1','text':'내보낼 최종 문구','start':.3,'end':1.3}
    page.locator('[data-field="caption:b1"]').fill('다음 내보내기에 쓸 문구')
    page.evaluate('release()')
    page.wait_for_function('!document.querySelector("#root")._saving')
    assert page.locator('[data-field="caption:b1"]').input_value()=='다음 내보내기에 쓸 문구'
