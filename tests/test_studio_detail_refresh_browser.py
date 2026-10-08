"""Independent interaction QA for the refreshed detail, with no user queue writes."""
import copy
import io
import json
import mimetypes
import os
import shutil
import wave
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from test_studio_board_browser import WEB, task


@pytest.fixture
def detail_page():
    pw = pytest.importorskip('playwright.sync_api')
    t = task('done', 'completed', 'completed', job_status=None)
    t['title'] = '다진 마늘을 보관하는 방법'
    t['sources'] = [dict(id=f'clip-{i}', url=f'/clip-{i}.mp4', original_name=f'마늘-{i}.mp4', rights='user_supplied') for i in range(7)]
    t['scripts'][0]['text'] = '마늘 보관이 불편했다면 이렇게 해보세요.\n' * 25
    t['script_candidates'] = [dict(text='첫 번째 마늘 대본 후보'), dict(text='두 번째 마늘 대본 후보')]
    t['selected_candidate'] = 0
    t['voice_id'] = 'current-audio'
    t['voices'] = [dict(id='current-audio', path_url='/tone.wav', speed=1, script_id='s1')]
    t['pipeline'][1]['inputs'] = dict(source_ids=[v['id'] for v in t['sources']], speed=1, voice_profile_id='')
    t['pipeline'][1]['artifacts'] = dict(sources=copy.deepcopy(t['sources']))
    t['source_acquisition'] = dict(hold=True)
    t['source_search'] = dict(hold=True, message='검색 인증을 확인하세요')
    calls = []
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as w:
        w.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        w.writeframes(b'\0\0' * 8000)
    with pw.sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport=dict(width=1600, height=1000))
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("const interval=window.setInterval;window.setInterval=(fn,ms,...args)=>{if(ms===3000){window.refreshStudio=fn;return 1;}return interval(fn,ms,...args);};")
        def route(r):
            path = urlparse(r.request.url).path
            if path == '/api/studio/voices':
                result = dict(personal_default=dict(available=True), voices=[dict(id='qwen-sohee', name='소희', gender='female', model='Qwen', available=True, preview_url='/tone.wav'), dict(id='qwen-aiden', name='에이든', gender='male', model='Qwen', available=True, preview_url='/tone.wav')])
            elif path == '/api/studio/intake':
                result = dict(available=False)
            elif path.startswith('/api/studio'):
                if path == '/api/studio':
                    result = dict(tasks=[copy.deepcopy(t)])
                else:
                    if r.request.method == 'POST':
                        action = path.split('/')[-1]
                        if action == 'upload-source':
                            name = parse_qs(urlparse(r.request.url).query)['name'][0]
                            calls.append((action, dict(name=name, bytes=len(r.request.post_data_buffer or b''))))
                            if t.get('_fail_upload') == name:
                                t.pop('_fail_upload')
                                r.fulfill(status=400, content_type='application/json', body=json.dumps(dict(error='영상 확인 실패 · 다시 시도하세요.')))
                                return
                            t['sources'].append(dict(id=f'upload-{len(t["sources"])}', original_name=name, url='/'+name, rights='user_supplied'))
                        else:
                            body = r.request.post_data_json
                            calls.append((action, copy.deepcopy(body)))
                            if t.get('_fail_action') == action:
                                t.pop('_fail_action')
                                r.fulfill(status=409, content_type='application/json', body=json.dumps(dict(error='다른 수정 내용과 충돌했습니다. 다시 확인하세요.')))
                                return
                            if action == 'make-video':
                                t['feedback'].update({{'text':'script_text'}.get(k,k):v for k,v in body.items() if k not in ['revision','feedback_revision']})
                                t['pending_reproduction'] = True
                            elif action == 'select-candidate':
                                t['selected_candidate'] = body['index']
                                t['feedback']['script_text'] = t['script_candidates'][body['index']]['text']
                            elif action == 'discard-feedback':
                                t['feedback'] = {}
                            elif action == 'propose-script':
                                t['proposals'].append(dict(id='proposal-1', base_text=body['base_text'], text='AI가 고친 마늘 보관 대본'))
                            elif action == 'apply-proposal':
                                t['feedback']['script_text'] = next(v['text'] for v in t['proposals'] if v['id']==body['proposal_id'])
                            t['feedback_revision'] += 1
                        t['revision'] += 1
                    result = copy.deepcopy(t)
            elif path.endswith('.wav'):
                r.fulfill(content_type='audio/wav', body=audio.getvalue())
                return
            else:
                f = WEB / path.lstrip('/')
                if f.is_file():
                    r.fulfill(content_type=mimetypes.guess_type(str(f))[0] or 'text/plain', body=f.read_bytes())
                else:
                    r.fulfill(status=404)
                return
            r.fulfill(content_type='application/json', body=json.dumps(result))
        page.route('http://detail.test/**', route)
        page.goto('http://detail.test/studio.html?work=done&tab=script')
        page.wait_for_selector('[data-pf-section=script] textarea[data-field=script]')
        yield page, t, calls
        browser.close()
        assert not errors, errors


def tab(page, name):
    page.locator(f'#detail-tabs [data-detail-tab={name}]').click()


def script(page, section='script'):
    return page.locator(f'[data-pf-section={section}] textarea[data-field=script]')


def disclosure(page, suffix):
    page.locator(f'[data-detail-toggle$="-{suffix}"]').click()


def test_script_voice_edit_mirror_poll_backdrop_reopen_and_exact_production_request(detail_page):
    page, t, calls = detail_page
    original_artifacts = copy.deepcopy(t['pipeline'])
    long_text = '직접 고친 마늘 대본입니다.\n' * 70
    script(page).fill(long_text)
    assert script(page).evaluate('(e)=>e.scrollHeight<=e.clientHeight+2')
    tab(page, 'voice')
    disclosure(page, 'voice-script-edit')
    assert script(page, 'voice').input_value() == long_text
    assert script(page, 'voice').evaluate('(e)=>e.scrollHeight<=e.clientHeight+2'), 'Opening the voice script editor must resize the long mirrored script immediately'
    script(page, 'voice').fill('목소리 화면에서 최종 수정한 대본')
    tab(page, 'script')
    assert script(page).input_value() == '목소리 화면에서 최종 수정한 대본'
    t['revision'] += 1
    page.evaluate('refreshStudio()')
    assert script(page).input_value() == '목소리 화면에서 최종 수정한 대본'
    tab(page, 'voice')
    disclosure(page, 'voice-options')
    page.locator('[data-choose-voice]').click()
    page.locator('[data-select-voice=qwen-sohee]').click()
    page.locator('[data-field=speed]').fill('1.15')
    tab(page, 'sources')
    page.locator('[data-field="source:clip-0"]').uncheck()
    page.locator('#work-backdrop').click(position=dict(x=5, y=5))
    assert page.locator('#work-drawer').is_hidden()
    page.locator('[data-work=done]').click()
    tab(page, 'script')
    assert script(page).input_value() == '목소리 화면에서 최종 수정한 대본'
    page.locator('[data-pf=make-video]').click()
    page.wait_for_function('document.querySelector("#detail")._task.pending_reproduction===true')
    body = next(body for action, body in calls if action == 'make-video')
    assert body['text'] == '목소리 화면에서 최종 수정한 대본'
    assert body['voice_profile_id'] == 'qwen-sohee'
    assert body['speed'] == 1.15
    assert body['source_ids'] == [f'clip-{i}' for i in range(1,7)]
    assert t['pipeline'] == original_artifacts
    assert page.evaluate('localStorage.getItem("production-feedback-done")') is None


def test_source_selection_clear_recheck_all_and_notice_dismiss(detail_page):
    page, _, _ = detail_page
    tab(page, 'sources')
    page.locator('[data-pf=clear-sources]').click()
    assert page.locator('[data-field^="source:"]:checked').count() == 0
    assert page.locator('[data-selected-count]').inner_text() == '0'
    page.locator('[data-field="source:clip-2"]').check()
    assert page.locator('[data-selected-count]').inner_text() == '1'
    page.locator('[data-pf=select-all-sources]').click()
    assert page.locator('[data-field^="source:"]:checked').count() == 7
    page.get_by_role('button', name='영상 준비 알림', exact=True).click()
    assert page.locator('.sd-notice-popover').is_visible()
    page.locator('.sd-source-stage h3').click()
    assert page.locator('.sd-notice-popover').is_hidden()
    page.get_by_role('button', name='영상 준비 알림', exact=True).click()
    page.get_by_role('button', name='영상 준비 알림', exact=True).click()
    assert page.locator('.sd-notice-popover').is_hidden()


def test_voice_preview_filter_select_restore_default_and_dialog_backdrop(detail_page):
    page, _, _ = detail_page
    tab(page, 'voice')
    disclosure(page, 'voice-options')
    page.locator('[data-choose-voice]').click()
    page.locator('[data-gender=female]').click()
    assert page.locator('.voice-choice').count() == 1
    page.locator('[data-listen=qwen-sohee]').click()
    page.wait_for_function('document.querySelector("[data-voice-audio]").currentTime>0')
    page.locator('[data-select-voice=qwen-sohee]').click()
    assert page.locator('[data-field=voice-profile]').input_value() == 'qwen-sohee'
    page.locator('[data-choose-voice]').click()
    page.locator('[data-select-voice=""]').click()
    assert page.locator('[data-field=voice-profile]').input_value() == ''
    page.locator('[data-choose-voice]').click()
    page.mouse.click(3, 3)
    assert page.locator('.voice-dialog').count() == 0
    assert page.locator('#work-drawer').is_visible()


def test_candidates_apply_and_still_work_after_manual_script_edit(detail_page):
    page, _, calls = detail_page
    page.locator('[data-pf=candidate][data-index="1"]').click()
    page.wait_for_function('document.querySelector("#detail")._task.selected_candidate===1')
    assert script(page).input_value() == '두 번째 마늘 대본 후보'
    script(page).fill('후보를 고르기 전에 직접 고친 대본')
    page.locator('[data-pf=candidate][data-index="0"]').click()
    page.wait_for_function('document.querySelector("#detail")._task.selected_candidate===0')
    assert script(page).input_value() == '첫 번째 마늘 대본 후보'
    assert len([c for c in calls if c[0]=='select-candidate']) == 2


def test_partial_upload_retry_preserves_voice_script_draft(detail_page):
    page, t, calls = detail_page
    script(page).fill('업로드를 해도 보존할 대본')
    tab(page, 'sources')
    t['_fail_upload'] = 'second.mp4'
    page.locator('[data-upload-files]').set_input_files([dict(name='first.mp4',mimeType='video/mp4',buffer=b'first'),dict(name='second.mp4',mimeType='video/mp4',buffer=b'second'),dict(name='invalid.txt',mimeType='text/plain',buffer=b'no')])
    page.wait_for_function('!document.querySelector("#detail")._uploading')
    assert page.locator('[data-upload-state=done]').count() == 1
    assert page.locator('[data-upload-state=failed]').count() == 2
    page.locator('[data-upload-retry]').click()
    page.wait_for_function('document.querySelectorAll("[data-upload-state=done]").length===2')
    assert len(t['sources']) == 9
    assert [v['name'] for a,v in calls if a=='upload-source'] == ['first.mp4','second.mp4','second.mp4']
    tab(page, 'voice')
    disclosure(page, 'voice-script-edit')
    assert script(page, 'voice').input_value() == '업로드를 해도 보존할 대본'


def test_real_mp4_upload_preview_and_resume_through_isolated_http(tmp_path, monkeypatch):
    from test_studio_board_browser import test_real_video_upload_http_and_resume_in_isolated_studio
    ffmpeg = shutil.which('ffmpeg') or 'C:/Codex/tools/ffmpeg/ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe'
    assert Path(ffmpeg).is_file(), 'An actual FFmpeg binary is required for this integration check'
    monkeypatch.setenv('PATH', str(Path(ffmpeg).parent)+os.pathsep+os.environ['PATH'])
    test_real_video_upload_http_and_resume_in_isolated_studio(tmp_path, monkeypatch)


def test_discard_returns_all_inputs_to_current_settings_and_preserves_result(detail_page):
    page, t, calls = detail_page
    old_script = t['scripts'][0]['text']
    old_pipeline = copy.deepcopy(t['pipeline'])
    script(page).fill('취소할 수정 대본')
    tab(page, 'voice')
    disclosure(page, 'voice-options')
    page.locator('[data-field=speed]').fill('1.2')
    page.locator('[data-choose-voice]').click()
    page.locator('[data-select-voice=qwen-aiden]').click()
    tab(page, 'sources')
    page.locator('[data-pf=clear-sources]').click()
    page.locator('[data-pf=discard-feedback]').click()
    page.wait_for_function('localStorage.getItem("production-feedback-done")===null')
    assert page.locator('[data-field^="source:"]:checked').count() == 7
    assert page.locator('[data-pf=make-video]').is_disabled()
    tab(page, 'script')
    assert script(page).input_value() == old_script
    tab(page, 'voice')
    assert page.locator('[data-field=speed]').input_value() == '1'
    assert page.locator('[data-field=voice-profile]').input_value() == ''
    tab(page, 'results')
    assert page.locator('[data-result-preview]').get_attribute('src') == '/final.mp4'
    assert t['pipeline'] == old_pipeline
    assert len([c for c in calls if c[0]=='discard-feedback']) == 1


def test_ai_rewrite_uses_visible_draft_and_applying_preserves_other_changes(detail_page):
    page, _, calls = detail_page
    script(page).fill('AI에게 보낼 현재 수정 중인 대본')
    tab(page, 'voice')
    disclosure(page, 'voice-options')
    page.locator('[data-field=speed]').fill('1.1')
    tab(page, 'script')
    disclosure(page, 'ai-rewrite')
    page.locator('[data-field=script-request]').fill('첫 문장을 더 짧게 바꿔주세요')
    page.locator('[data-pf=propose-script]').click()
    page.wait_for_function('document.querySelector("#detail")._task.proposals.length===1')
    body = next(body for action, body in calls if action == 'propose-script')
    assert body['base_text'] == 'AI에게 보낼 현재 수정 중인 대본'
    assert body['request'] == '첫 문장을 더 짧게 바꿔주세요'
    assert script(page).input_value() == 'AI에게 보낼 현재 수정 중인 대본'
    page.locator('[data-proposals] summary').click()
    page.locator('[data-pf=proposal]').click()
    page.wait_for_function('document.querySelector("#detail")._task.feedback.script_text==="AI가 고친 마늘 보관 대본"')
    assert script(page).input_value() == 'AI가 고친 마늘 보관 대본'
    tab(page, 'voice')
    assert page.locator('[data-field=speed]').input_value() == '1.1'


def test_failed_production_request_keeps_draft_and_can_retry(detail_page):
    page, t, calls = detail_page
    script(page).fill('실패해도 보존할 마늘 대본')
    t['_fail_action'] = 'make-video'
    page.locator('[data-pf=make-video]').click()
    page.wait_for_function('document.querySelector("[data-action-notice]").textContent.includes("충돌")')
    assert script(page).input_value() == '실패해도 보존할 마늘 대본'
    assert page.locator('[data-pf=make-video]').is_enabled()
    page.locator('[data-pf=make-video]').click()
    page.wait_for_function('document.querySelector("#detail")._task.pending_reproduction===true')
    assert len([v for a,v in calls if a=='make-video']) == 2
    assert t['feedback']['script_text'] == '실패해도 보존할 마늘 대본'


def test_actual_http_script_source_voice_changes_create_one_run_preserve_completed_assets(tmp_path, monkeypatch):
    """Click real controls against an isolated durable store; enqueue without workers."""
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from hotpost.studio_http import StudioHTTP
    from hotpost.voicebench_adapter import VoiceBenchAdapter
    from test_studio_workflow import prepared, complete

    monkeypatch.setattr('hotpost.source_policy.current_policy', lambda settings=None: dict(version=2, minimum_total=1, platform_minimums={}))
    monkeypatch.setattr(VoiceBenchAdapter, 'voices', lambda self: dict(personal_default=dict(available=True), voices=[dict(id='qwen-sohee',name='소희',gender='female',model='Qwen',available=True)]))
    studio, task_id = prepared.__wrapped__(tmp_path)
    def add_source(s, db):
        second = copy.deepcopy(s['sources'][0])
        second['id'] = 'source2'
        s['sources'].append(second)
        s['runs'][-1]['inputs']['source_ids'] = ['source1','source2']
    studio.store.change(task_id, add_source)
    complete(studio, task_id)
    before = studio.store.get(task_id)
    completed_id = before['run_id']
    completed_run = copy.deepcopy(before['runs'][-1])
    old_downloads = {key:studio.download(task_id,completed_id,key).read_bytes() for key in ['script','voice','export']}
    class Handler(StudioHTTP, SimpleHTTPRequestHandler):
        def log_message(self,*args): pass
        def _json(self,data,status=200):
            body=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if not self.studio_get(studio):super().do_GET()
        def do_POST(self):self.studio_post(studio)
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(WEB)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    pw=pytest.importorskip('playwright.sync_api')
    try:
        with pw.sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page(viewport=dict(width=1600,height=1000))
                page.goto(f'http://127.0.0.1:{server.server_port}/studio.html?work={task_id}&tab=script')
                script(page).fill('실제 HTTP로 저장한 마늘 보관 대본입니다.')
                tab(page,'sources')
                page.locator('[data-field="source:source1"]').uncheck()
                page.locator('[data-field="source:source1"]').check()
                page.locator('[data-field="source:source2"]').uncheck()
                tab(page,'voice')
                disclosure(page,'voice-options')
                page.locator('[data-choose-voice]').click()
                page.locator('[data-select-voice=qwen-sohee]').click()
                page.locator('[data-field=speed]').fill('1.15')
                page.locator('[data-pf=make-video]').click()
                page.wait_for_function('document.querySelector("[data-action-notice]").textContent.includes("새 영상 제작")')
                after=studio.store.get(task_id)
                assert after['run_id'] != completed_id
                assert after['latest_completed_run_id'] == completed_id
                assert next(r for r in after['runs'] if r['id']==completed_id) == completed_run
                assert not after['feedback']
                assert not after.get('pending_reproduction')
                assert after['scripts'][-1]['text'] == '실제 HTTP로 저장한 마늘 보관 대본입니다.'
                inputs=after['runs'][-1]['inputs']
                assert inputs['source_ids'] == ['source1']
                assert inputs['voice_profile_id'] == 'qwen-sohee'
                assert inputs['speed'] == 1.15
                jobs=[j for j in studio.store.jobs(task_id) if j['status']=='queued']
                assert len(jobs)==1 and jobs[0]['kind']=='voice'
                with studio.store.connect() as db:
                    payload=json.loads(db.execute('SELECT payload FROM jobs WHERE id=?',(jobs[0]['id'],)).fetchone()[0])
                assert payload['voice_profile_id']=='qwen-sohee' and payload['speed']==1.15
                for key, content in old_downloads.items():
                    assert studio.download(task_id,completed_id,key).read_bytes()==content
            finally:browser.close()
    finally:server.shutdown();server.server_close()


def test_caption_edit_scene_navigation_undo_save_and_export_controls(detail_page):
    page, t, calls = detail_page
    t.update(caption_editor_supported=True,edit_id='edit-1',revision=t['revision']+1)
    t['edits']=[dict(id='edit-1',duration=5,clean_preview_url='/clean.mp4',export_url='/exported.mp4',plan=dict(
        cues=[dict(id='cue-1',text='마늘을 준비해요',start=.2,end=1.2),dict(id='cue-2',text='보관통에 담아요',start=2,end=3)],
        shots=[dict(id='shot-1',video_url='/source.mp4',start=0,end=5)],
        beats=[dict(id='beat-1',cue_id='cue-1',start=0,end=2,text='마늘을 준비해요',selected_shot_id='shot-1'),dict(id='beat-2',cue_id='cue-2',start=2,end=5,text='보관통에 담아요',selected_shot_id='shot-1')]))]
    page.evaluate('refreshStudio()')
    tab(page,'edit')
    page.locator('[data-edit-preview]').evaluate("v=>{Object.defineProperty(v,'duration',{get:()=>5});Object.defineProperty(v,'readyState',{get:()=>4});v.dispatchEvent(new Event('loadedmetadata'));v.dispatchEvent(new Event('loadeddata'));}")
    page.locator('[data-field="caption:beat-1"]').fill('고친 마늘 자막')
    assert page.locator('[data-caption-undo]').is_enabled()
    page.locator('[data-caption-undo]').click()
    assert page.locator('[data-field="caption:beat-1"]').input_value()=='마늘을 준비해요'
    page.locator('.ce-cue.ce-selected details summary').click()
    page.locator('[data-caption-step="0.5"]').first.click()
    page.locator('[data-sync=later]').first.click()
    assert float(page.locator('[data-field="start:beat-1"]').input_value())==.7
    page.locator('[data-field="caption:beat-1"]').fill('최종 마늘 자막')
    page.locator('[data-cue-next]').click()
    assert page.locator('.ce-cue.ce-selected').get_attribute('data-caption-card')=='beat-2'
    page.locator('[data-cue-prev]').click()
    assert page.locator('[data-field="caption:beat-1"]').input_value()=='최종 마늘 자막'
    page.locator('.ce-timeline-disclosure > summary').click()
    page.locator('.ce-scene-library > summary').click()
    page.locator('[data-timeline-scene="1"]').last.click()
    assert page.locator('[data-edit-preview]').evaluate('(v)=>v.currentTime')==2
    page.locator('.ce-advanced-tools > summary').click()
    page.locator('[data-pf=save-captions]').click()
    page.wait_for_function('!document.querySelector("#detail")._saving')
    body=next(v for a,v in calls if a=='save-captions')
    assert body['edit_id']=='edit-1'
    assert body['changes'][0]==dict(beat_id='beat-1',text='최종 마늘 자막',start=.7,end=1.7)
    page.locator('[data-field="caption:beat-1"]').fill('내보낼 마늘 자막')
    page.locator('[data-pf=export-edit]').click()
    page.wait_for_function('!document.querySelector("#detail")._saving')
    body=next(v for a,v in calls if a=='export-edit')
    assert body['changes'][0]['text']=='내보낼 마늘 자막'
    assert body['changes'][0]['start']==.2


def test_extra_source_search_validates_query_and_preserves_inventory_and_script(detail_page):
    page, t, calls = detail_page
    inventory=copy.deepcopy(t['sources'])
    script(page).fill('소스 검색 중 보존할 내 대본')
    tab(page,'sources')
    disclosure(page,'source-search')
    page.locator('[data-search-options] > summary').click()
    page.locator('[data-pf=search]').click()
    assert not calls
    assert '검색 조건을 입력' in page.locator('[data-search-validation]').inner_text()
    page.locator('[data-field=search]').fill('다진 마늘을 한 스푼 떠 쓰는 장면')
    page.locator('[data-pf=search]').click()
    page.wait_for_function('!document.querySelector("#detail")._saving')
    body=next(v for a,v in calls if a=='refresh-sources')
    assert body['request']=='다진 마늘을 한 스푼 떠 쓰는 장면'
    assert t['sources']==inventory
    tab(page,'script')
    assert script(page).input_value()=='소스 검색 중 보존할 내 대본'


def test_results_version_switch_and_review_checks_target_displayed_run(detail_page):
    page, _, calls = detail_page
    tab(page,'results')
    page.locator('[data-pf-version]').select_option('v1')
    assert page.locator('[data-result-preview]').get_attribute('src')=='/old.mp4'
    page.locator('[data-pf-version]').select_option('v2')
    assert page.locator('[data-result-preview]').get_attribute('src')=='/final.mp4'
    disclosure(page,'result-review-v2')
    for name in ['speech','captions','scenes']:
        page.locator(f'[data-review-check={name}]').check()
    page.locator('[data-pf=review-result]').click()
    page.wait_for_function('!document.querySelector("#detail")._saving')
    body=next(v for a,v in calls if a=='review-result')
    assert body['run_id']=='v2' and body['checks']==['speech','captions','scenes']
