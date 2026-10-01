"""Exercise the real studio UI with isolated API fixtures, never the user's queue."""
import copy
import json
import mimetypes
import io
import wave
from pathlib import Path
from urllib.parse import urlparse, parse_qs

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
                elif path=='/api/studio/intake':
                    result={'available':False}
                else:
                    parts=path.split('/')
                    t=next(t for t in tasks if t['id']==parts[3])
                    if request.request.method=='POST':
                        if parts[-1]=='upload-source':
                            name=parse_qs(urlparse(request.request.url).query)['name'][0]
                            t.setdefault('_upload_calls',[]).append(name)
                            if t.get('_fail_upload')==name:
                                t.pop('_fail_upload')
                                request.fulfill(status=400,content_type='application/json',body=json.dumps({'error':'영상 확인 실패 · 다시 시도하세요.'}));return
                            if not any(s.get('original_name')==name for s in t['sources']):
                                t['sources'].append(dict(id='upload-'+str(len(t['sources'])),original_name=name,url='/'+name,sha256=name))
                            body={}
                        else:body=request.request.post_data_json
                        t['revision']+=1
                        if parts[-1]=='save-script':
                            t['feedback']['script_text']=body['text'];t['feedback_revision']+=1
                        elif parts[-1]=='approve-script':
                            t['approved_script_id']=t['script_id'];t['status']='voice_generating'
                        elif parts[-1]=='use-sources':
                            t['_used_sources']=body['source_ids'];t['status']='preparing';t['error']='';t['message']='선택한 영상으로 제작을 이어갑니다'
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
    assert page.locator('.kanban-column').count()==3
    assert page.locator('[data-stage="attention"] [data-work-card="export"] .board-status').inner_text()=='외부 작업 대기'
    assert page.locator('.work-card.is-running').count()==1
    page.locator('[data-work-card="voice"] .card-progress-details summary').click()
    assert page.locator('[data-work-card="voice"] .milestone-progress').is_visible()
    assert not page.locator('#work-drawer').is_visible()
    page.locator('[data-work-card="voice"]').evaluate('(e)=>{window.keptCard=e;window.keptActivity=e.querySelector(".activity-dot")}')
    page.evaluate('refreshStudio()')
    assert page.evaluate('keptCard===document.querySelector("[data-work-card=voice]") && keptActivity===keptCard.querySelector(".activity-dot")')
    tasks[2].update(status='editing',revision=2)
    tasks[2]['jobs']=[dict(kind='edit',status='running')]
    page.evaluate('refreshStudio()')
    assert page.locator('[data-stage="working"] [data-work="voice"]').count()==1
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
    page.locator('#detail-tabs [data-detail-tab="script"]').click()
    page.locator('#detail-tabs [data-detail-tab="script"]').click()
    assert editor.input_value()=='저장하기 전 직접 고친 문장'
    page.locator('#close-work').click()
    page.locator('[data-work="source"]').click()
    page.locator('#close-work').click()
    page.locator('[data-work="voice"]').click()
    assert editor.input_value()=='저장하기 전 직접 고친 문장'
    page.locator('[data-pf="save-script"]').click()
    page.wait_for_function('document.querySelector(".pf-message").textContent.includes("보관했습니다")')
    assert tasks[2]['feedback']['script_text']=='저장하기 전 직접 고친 문장'
    assert page.evaluate('localStorage.getItem("production-feedback-voice")') is None


def test_results_version_and_keyboard_drawer(studio_page):
    page,_=studio_page
    page.locator('[data-work="voice"]').click()
    page.locator('#detail-tabs [data-detail-tab="edit"]').click()
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
    page.wait_for_function('document.querySelector("#detail-tabs [data-detail-tab=script]").getAttribute("aria-pressed")==="true"')
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
    assert page.locator('[data-stage="attention"] [data-work-card="voice"] [class="board-status"]').inner_text()=='확인 필요'
    page.locator('[data-work="voice"]').click()
    assert page.locator('#work-hero [data-action="retry"]').is_visible()
    page.locator('#close-work').click()
    tasks[2].update(status='voice_generating',error='',revision=3)
    tasks[2]['jobs'][0]['status']='running'
    page.evaluate('refreshStudio()')
    page.emulate_media(reduced_motion='reduce')
    assert page.locator('[data-work-card="voice"] .activity-dot').evaluate('(e)=>getComputedStyle(e).animationName')=='none'


def test_numbered_progress_and_six_stage_navigation(studio_page):
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
    page.locator('#detail-tabs [data-detail-tab=script]').click()
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
    assert page.locator('#work-list').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
    assert page.locator('.kanban-column').count()==3
    page.locator('[data-work="voice"]').click()
    assert page.locator('#journey-panel').get_attribute('open') is None
    assert page.locator('#detail-tabs button').count()==3
    assert page.locator('#detail-tabs [data-detail-tab=script]').get_attribute('aria-current')=='step'
    page.locator('#detail-tabs [data-detail-tab=script]').click()
    page.locator('.pf-original').evaluate('(e)=>e.open=true')
    assert page.locator('[data-field=original]').is_visible()
    assert page.locator('#work-drawer').bounding_box()['width']<=390


def test_multiple_uploads_partial_failure_retry_and_continue_preserve_draft(studio_page):
    page,tasks=studio_page
    t=tasks[0];t.update(status='attention',error='Source manifest contains no selected local videos.',revision=2)
    t['jobs'][0]['status']='failed';t['_fail_upload']='second.mp4'
    page.evaluate('refreshStudio()');page.locator('[data-work="source"]').click()
    assert '직접 영상 넣기' in page.locator('#work-hero').inner_text()
    assert 'Source manifest' not in page.locator('#work-drawer').inner_text()
    assert page.locator('[data-upload-open]').is_visible()
    assert page.locator('[data-upload-files]').get_attribute('multiple') is not None
    page.locator('#detail-tabs [data-detail-tab="script"]').click()
    page.locator('[data-field="script"]').fill('업로드 중에도 보존할 새 대본')
    page.locator('#detail-tabs [data-detail-tab="sources"]').click()
    with page.expect_file_chooser() as chooser:
        page.locator('[data-upload-open]').click()
    assert chooser.value.is_multiple()
    chooser.value.set_files([{'name':'first.mp4','mimeType':'video/mp4','buffer':b'first'},
        {'name':'second.mp4','mimeType':'video/mp4','buffer':b'second'},
        {'name':'notes.txt','mimeType':'text/plain','buffer':b'invalid'}])
    page.wait_for_function('!document.querySelector("#detail")._uploading')
    assert len(t['sources'])==1
    assert t['_upload_calls']==['first.mp4','second.mp4']
    assert page.locator('[data-upload-state="done"]').count()==1
    assert page.locator('[data-upload-state="failed"]').count()==2
    assert page.locator('[data-upload-retry]').count()==1
    page.locator('[data-upload-retry]').click()
    page.wait_for_function('document.querySelectorAll("[data-upload-state=done]").length===2')
    assert len(t['sources'])==2
    # Real DataTransfer follows the same multiple-file path as the picker.
    page.locator('[data-dropzone]').evaluate('''el=>{
        const dt=new DataTransfer();dt.items.add(new File(['third'],'third.webm',{type:'video/webm'}));
        dt.items.add(new File(['fourth'],'fourth.mov',{type:'video/quicktime'}));
        el.dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:dt}));
    }''')
    page.wait_for_function('document.querySelectorAll("[data-upload-state=done]").length===4')
    assert len(t['sources'])==4
    page.locator('[data-pf="clear-sources"]').click()
    assert page.locator('[data-pf="use-sources"]').is_disabled()
    page.locator('[data-field="source:upload-1"]').check()
    page.locator('[data-pf="use-sources"]').click()
    page.wait_for_function('document.querySelector(".pf-message").textContent.includes("선택한 영상")')
    assert t['_used_sources']==['upload-1']
    page.locator('#detail-tabs [data-detail-tab="script"]').click()
    assert page.locator('[data-field="script"]').input_value()=='업로드 중에도 보존할 새 대본'
    page.locator('#close-work').click()
    page.locator('[data-work="voice"]').click()
    page.locator('#detail-tabs [data-detail-tab="sources"]').click()
    assert page.locator('[data-upload-list] li').count()==0
    page.locator('#close-work').click();page.locator('[data-work="source"]').click()
    page.locator('#detail-tabs [data-detail-tab="sources"]').click()
    assert page.locator('[data-upload-state="done"]').count()==4


def test_mobile_source_hero_clear_actions_and_no_internal_identifiers(studio_page):
    page,tasks=studio_page
    t=tasks[0];t.update(shortcode='DdyQWlyKAv9',title='DdyQWlyKAv9',status='attention',error='Source manifest contains no selected local videos.',revision=2)
    t['jobs'][0]['status']='failed'
    page.set_viewport_size({'width':390,'height':844});page.evaluate('refreshStudio()')
    page.locator('[data-work="source"]').click()
    assert not page.locator('#journey-panel').evaluate('(e)=>e.open')
    text=page.locator('#work-drawer').inner_text()
    assert 'DdyQWlyKAv9' not in text and 'Source manifest' not in text
    assert '직접 영상 넣기' in text
    page.locator('[data-focus-current]').click()
    assert page.locator('[data-upload-open]').evaluate('(el)=>el===document.activeElement')
    box=page.locator('[data-upload-open]').bounding_box()
    assert box['y']+box['height']<=844
    assert page.locator('.pf-actionbar').is_hidden()
    assert page.locator('#work-drawer').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
    assert page.locator('[data-upload-open]').bounding_box()['height']>=44


def test_real_video_upload_http_and_resume_in_isolated_studio(tmp_path,monkeypatch):
    """Real browser + HTTP + ffprobe; no production data or external jobs."""
    import shutil
    import subprocess
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from hotpost.config import Settings
    from hotpost.studio import Studio
    from hotpost.studio_http import StudioHTTP
    pw=pytest.importorskip('playwright.sync_api')
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:pytest.skip('FFmpeg unavailable')
    studio=Studio(Settings(data_dir=tmp_path/'data'),workers=False)
    state,_=studio.store.create('isolated-upload','직접 넣은 영상으로 쇼츠 만들기',{'protocol':2,'active':True,'stage':'prepare'})
    clips=[]
    for color in ['red','blue']:
        path=tmp_path/(color+'.mp4')
        subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i',f'color=c={color}:s=160x284:r=10','-t','0.3','-c:v','libx264','-pix_fmt','yuv420p',str(path)],check=True,capture_output=True)
        clips.append(path)
    class Handler(StudioHTTP,SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
        def _json(self,data,status=200):
            body=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if not self.studio_get(studio):super().do_GET()
        def do_POST(self):self.studio_post(studio)
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(WEB)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with pw.sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page(viewport={'width':1440,'height':1000})
                page.goto(f'http://127.0.0.1:{server.server_port}/studio.html?work={state["id"]}')
                page.locator('[data-upload-files]').set_input_files([str(v) for v in clips])
                page.wait_for_function('document.querySelectorAll("[data-upload-state=done]").length===2')
                assert page.locator('.pf-source-card').count()==2
                page.locator('.pf-source-card video').first.evaluate('(v)=>v.load()')
                page.wait_for_function('document.querySelector(".pf-source-card video").readyState>=2')
                page.locator('[data-pf="use-sources"]').click()
                page.wait_for_function('document.querySelector(".pf-message").textContent.includes("선택한 영상")')
                stored=studio.store.get(state['id'])
                run=next(r for r in stored['runs'] if r['id']==stored['run_id'])
                assert len(run['inputs']['source_ids'])==2
                assert stored['status']=='preparing' and not stored['error']
                assert all(v['rights']=='user_supplied' for v in stored['sources'])
                assert [j['kind'] for j in studio.store.jobs(state['id']) if j['status']=='queued']==['prepare']
            finally:browser.close()
    finally:server.shutdown();server.server_close()


def test_original_and_script_are_separate_and_drafts_survive_navigation(studio_page):
    page,_=studio_page
    page.locator('[data-work="voice"]').click()
    page.locator('#detail-tabs [data-detail-tab=script]').click()
    page.locator('.pf-original').evaluate('(e)=>e.open=true')
    page.locator('[data-field=original]').fill('확인 중인 원본 발화')
    assert page.locator('.pf-actionbar').is_visible()
    page.locator('#detail-tabs [data-detail-tab=script]').click()
    page.locator('.pf-original > summary').click()
    assert not page.locator('[data-field=original]').is_visible()
    page.locator('[data-field=script]').fill('새로운 제작 대본 초안')
    page.locator('#detail-tabs [data-detail-tab=script]').click()
    page.locator('.pf-original').evaluate('(e)=>e.open=true')
    assert page.locator('[data-field=original]').input_value()=='확인 중인 원본 발화'
    page.evaluate('refreshStudio()')
    page.locator('#detail-tabs [data-detail-tab=script]').click()
    assert page.locator('[data-field=script]').input_value()=='새로운 제작 대본 초안'
    assert page.locator('#detail-tabs [aria-current=step]').get_attribute('data-detail-tab')=='script'
    assert page.locator('#detail-tabs [aria-pressed=true]').get_attribute('data-detail-tab')=='script'
