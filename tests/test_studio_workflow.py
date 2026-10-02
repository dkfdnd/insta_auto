import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.studio_store import Conflict
from hotpost.studio_workflow import snapshot, transient


@pytest.fixture
def prepared(tmp_path):
    studio = Studio(Settings(data_dir=tmp_path), workers=False)
    s,_ = studio.store.create('fixture','자동 제작',{'protocol':2,'active':True,'stage':'prepare'})
    folder=studio.folder(s['id']); source=folder/'source.mp4'; source.write_bytes(b'video')
    def prepare(s,db):
        s.update(sources=[{'id':'source1','path':str(source),'sha256':hashlib.sha256(b'video').hexdigest()}],original_text='원본 발화')
        studio._script(s,'이 도구의 모양을 살펴보세요.','automatic_script_auto')
        snapshot(s)
        db.execute("UPDATE jobs SET status='done'")
        studio._advance_auto(s,db)
    studio.store.change(s['id'],prepare)
    return studio,s['id']


def finish(studio,result):
    job=studio.store.claim(); assert job
    studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
    return job


def complete(studio,task):
    s=studio.store.get(task); folder=studio.folder(task)
    voice=folder/'test.wav';voice.write_bytes(b'audio')
    finish(studio,{'id':s['pending_voice_id'],'script_id':s['script_id'],'path':str(voice),'sha256':hashlib.sha256(b'audio').hexdigest(),'speed':1,'duration':3})
    job=studio.store.claim();s=studio.store.get(task)
    plan=folder/(job['id']+'.json');plan.write_text(json.dumps({'shots':[],'beats':[],'cues':[]}),encoding='utf-8')
    preview=folder/(job['id']+'.mp4');preview.write_bytes(b'preview')
    portable=folder/job['id'];portable.mkdir();(portable/'draft_content.json').write_text('{}')
    result={'id':job['id'],'script_id':s['script_id'],'voice_id':s['voice_id'],'plan_path':str(plan),
            'preview_path':str(preview),'portable_draft_path':str(portable),'duration':3,'review_count':0}
    studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
    finish(studio,{'draft_path':'external/CapCut','draft_name':'test'})
    assert studio.store.get(task)['status']=='exporting'
    final=folder/(job['id']+'-final.mp4');final.write_bytes(b'exported')
    finish(studio,{'export_path':str(final),'export_verified':True})


def test_export_is_completion_boundary_and_all_assets_download(prepared):
    studio,task=prepared;complete(studio,task)
    s=studio.store.get(task);assert s['status']=='completed'
    pipeline=studio.public(s)['pipeline'];assert len(pipeline)==1
    assert all(step['status']=='completed' for step in pipeline[0]['steps'])
    for step in pipeline[0]['steps']:
        path=studio.download(task,s['run_id'],step['key']);assert path.is_file()
    with zipfile.ZipFile(studio.download(task,s['run_id'],'sources')) as z: assert 'provenance.json' in z.namelist()
    with pytest.raises(ValueError): studio.download(task,'../../other','script')


def test_native_window_failure_recovers_same_plan_and_resumes_without_reopening(prepared, monkeypatch):
    from hotpost import editing_adapter
    studio,task=prepared;complete(studio,task)
    state=studio.store.get(task);edit=next(e for e in state['edits'] if e['id']==state['edit_id'])
    job={'id':'recovery-export','kind':'export','payload':{'edit_id':edit['id']},'checkpoint':{}}
    attempts=[];renders=[]
    def failed(*a,**k):
        attempts.append(k)
        raise editing_adapter.NativeExportUnavailable('CapCut MainWindow 창이 준비되지 않았습니다.')
    monkeypatch.setattr(editing_adapter.AutoCapcutAdapter,'export',failed)
    video=studio.folder(task)/'web-final.mp4';video.write_bytes(b'v'*2048)
    def render(s,j,action,payload):
        renders.append((action,payload))
        return {'export_path':str(video),'export_verified':True}
    monkeypatch.setattr(studio,'_process',render)
    result=studio._export(state,job)
    assert result['export_kind']=='web_render' and result['export_verified']
    assert renders[0]==('caption-export',{'plan':json.loads(Path(edit['plan_path']).read_text()),'changes':[]})
    assert studio._export(state,job)=={**result,'exported_at':pytest.approx(result['exported_at'],abs=1)}
    assert len(attempts)==1
    studio._accept(state,job,result)
    with studio.store.transaction() as db:studio.advance_workflow(state,db)
    assert state['status']=='completed' and '웹 렌더링' in state['message']
    assert next(e for e in state['edits'] if e['id']==edit['id'])['draft_path']=='external/CapCut'


def test_native_content_or_verification_errors_never_use_web_fallback(prepared,monkeypatch):
    from hotpost import editing_adapter
    studio,task=prepared;complete(studio,task);state=studio.store.get(task)
    job={'id':'failed-export','payload':{'edit_id':state['edit_id']},'checkpoint':{}}
    def fail(*a,**k):raise RuntimeError('편집 소스 재검토 필요')
    monkeypatch.setattr(editing_adapter.AutoCapcutAdapter,'export',fail)
    monkeypatch.setattr(studio,'_process',lambda *a,**k:pytest.fail('must not bypass validation'))
    with pytest.raises(RuntimeError,match='재검토'):studio._export(state,job)
    hold=studio.settings.editing_dir/job['id']/'export-hold.json';hold.parent.mkdir(parents=True)
    hold.write_text(json.dumps({'reason':'mismatched product'}))
    job['checkpoint']['native_export_unavailable']='previous window failure'
    with pytest.raises(RuntimeError,match='mismatched product'):studio._export(state,job)


def test_unverified_web_output_is_not_accepted(prepared,monkeypatch):
    studio,task=prepared;complete(studio,task);state=studio.store.get(task)
    job={'id':'bad-web-export','payload':{'edit_id':state['edit_id']},
         'checkpoint':{'native_export_unavailable':'window failure'}}
    monkeypatch.setattr(studio,'_process',lambda *a,**k:{'export_verified':False})
    with pytest.raises(ValueError,match='검증'):studio._export(state,job)


def test_make_video_atomically_saves_and_starts_once(prepared):
    studio,task=prepared;complete(studio,task)
    before=studio.store.get(task)
    result=studio.action(task,'make-video',{'text':'직접 고친 대본입니다.','speed':1.1,
        'pronunciations':[{'from':'USB','to':'유에스비'}],'source_ids':['source1'],'feedback_revision':0})
    state=studio.store.get(task)
    assert state['run_id']!=before['run_id']
    assert state['scripts'][-1]['text']=='직접 고친 대본입니다.'
    assert state['runs'][-1]['inputs']['speed']==1.1
    assert state['runs'][0]['status']=='completed'
    assert not result['feedback']
    assert len([j for j in result['jobs'] if j['status']=='queued'])==1
    with pytest.raises(Conflict):studio.action(task,'make-video',{'text':'중복 클릭','feedback_revision':0})


@pytest.mark.parametrize('invalid',[{'speed':2},{'source_ids':[]},{'pronunciations':[{'from':'','to':'말'}]}])
def test_make_video_invalid_setting_rolls_back_script_and_queue(prepared,invalid):
    studio,task=prepared;complete(studio,task);before=studio.store.get(task)
    with pytest.raises(ValueError):studio.action(task,'make-video',{'text':'저장되면 안 되는 대본',**invalid})
    after=studio.store.get(task)
    assert after==before
    assert not [j for j in studio.store.jobs(task) if j['status']=='queued']


def test_voice_choice_rebuilds_voice_and_can_return_to_default(prepared,monkeypatch):
    from hotpost.voicebench_adapter import VoiceBenchAdapter
    monkeypatch.setattr(VoiceBenchAdapter,'voices',lambda self:{'voices':[{'id':'qwen-sohee','available':True}]})
    studio,task=prepared;complete(studio,task)
    before=studio.store.get(task)
    with pytest.raises(ValueError):studio.action(task,'make-video',{'voice_profile_id':'not-approved'})
    assert studio.store.get(task)==before
    studio.action(task,'make-video',{'voice_profile_id':'qwen-sohee'})
    job=next(j for j in studio.store.jobs(task) if j['status']=='queued')
    with studio.store.connect() as db:
        payload=json.loads(db.execute('SELECT payload FROM jobs WHERE id=?',(job['id'],)).fetchone()[0])
    assert job['kind']=='voice' and payload['voice_profile_id']=='qwen-sohee'
    complete(studio,task)
    studio.action(task,'make-video',{'voice_profile_id':''})
    job=next(j for j in studio.store.jobs(task) if j['status']=='queued')
    with studio.store.connect() as db:
        payload=json.loads(db.execute('SELECT payload FROM jobs WHERE id=?',(job['id'],)).fetchone()[0])
    assert job['kind']=='voice' and not payload.get('voice_profile_id')
    assert studio.store.get(task)['runs'][-1]['inputs']['voice_profile_id']==''


def test_caption_export_is_atomic_reuses_voice_and_skips_native_registration(prepared):
    studio,task=prepared;complete(studio,task)
    before=studio.store.get(task);edit=next(e for e in before['edits'] if e['id']==before['edit_id'])
    plan={'duration':3,'cues':[{'id':'c','text':'자막','start':.2,'end':1.2}],
          'beats':[{'id':'b','cue_id':'c','options':[]}],'shots':[]}
    Path(edit['plan_path']).write_text(json.dumps(plan),encoding='utf-8')
    change={'beat_id':'b','text':'수정 자막','start':.3,'end':1.3}
    saved=studio.action(task,'save-captions',{'edit_id':edit['id'],'changes':[change],'feedback_revision':0})
    assert saved['edit_id']==edit['id'] and not [j for j in saved['jobs'] if j['status']=='queued']
    with pytest.raises(Conflict):
        studio.action(task,'export-edit',{'edit_id':edit['id'],'changes':[change],'feedback_revision':0})
    exported=studio.action(task,'export-edit',{'edit_id':edit['id'],'changes':[change],'feedback_revision':saved['feedback_revision']})
    job=studio.store.claim();assert job['kind']=='revision' and job['payload']['caption_only']
    assert job['payload']['changes']==[change]
    # Subsequent user input must never mutate the in-flight output snapshot.
    studio.action(task,'save-captions',{'edit_id':edit['id'],'changes':[{**change,'text':'다음 편집'}]})
    assert job['payload']['changes'][0]['text']=='수정 자막'
    with pytest.raises(Conflict):studio.action(task,'export-edit',{'edit_id':edit['id'],'changes':[change]})
    result={**edit,'id':job['id'],'export_kind':'web_captions','export_verified':True}
    result.pop('draft_path',None);result.pop('draft_name',None)
    studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
    after=studio.store.get(task)
    assert after['status']=='completed'
    assert after['voice_id']==before['voice_id'] and after['script_id']==before['script_id']
    assert after['feedback']['changes'][0]['text']=='다음 편집'
    assert not [j for j in studio.store.jobs(task) if j['status']=='queued']
    with pytest.raises(Conflict):studio.action(task,'save-captions',{'edit_id':edit['id'],'changes':[change]})
    with pytest.raises(Conflict):studio.action(task,'save-captions',{'edit_id':after['edit_id'],'changes':[change]})
    studio.action(task,'discard-edit-feedback',{})
    assert not studio.store.get(task)['feedback']


def test_caption_export_rejects_scene_changes_and_keeps_pending_script(prepared):
    studio,task=prepared;complete(studio,task);s=studio.store.get(task)
    studio.action(task,'save-script',{'text':'새 대본'})
    with pytest.raises(Conflict):studio.action(task,'export-edit',{'edit_id':s['edit_id'],'changes':[]})
    assert studio.store.get(task)['feedback']['script_text']=='새 대본'
    studio.action(task,'discard-feedback',{})
    with pytest.raises(ValueError):studio.action(task,'export-edit',{'edit_id':s['edit_id'],'changes':[{'beat_id':'b','shot_id':'new'}]})


def test_feedback_does_not_mutate_active_script_and_reproduction_waits(prepared):
    studio,task=prepared;job=studio.store.claim();before=studio.store.get(task)
    studio.action(task,'save-script',{'text':'사용자가 새로 고친 대본이에요.'})
    current=studio.store.get(task);assert current['script_id']==before['script_id'] and current['automation']['active']
    studio.action(task,'reproduce',{})
    assert studio.store.get(task)['pending_reproduction']['script_text']=='사용자가 새로 고친 대본이에요.'
    studio.action(task,'save-script',{'text':'다음 제작에 반영할 추가 수정이에요.'})
    folder=studio.folder(task);voice=folder/'v.wav';voice.write_bytes(b'audio')
    result={'id':before['pending_voice_id'],'script_id':before['script_id'],'path':str(voice),'sha256':hashlib.sha256(b'audio').hexdigest()}
    studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
    s=studio.store.get(task)
    assert len(s['runs'])==2 and s['runs'][0]['status']=='superseded'
    assert s['scripts'][-1]['text']=='사용자가 새로 고친 대본이에요.'
    assert s['feedback']['script_text']=='다음 제작에 반영할 추가 수정이에요.'
    assert studio.store.claim()['kind']=='voice'


def test_completed_version_survives_new_version_and_latest_updates(prepared):
    studio,task=prepared;complete(studio,task);old=studio.store.get(task)['run_id']
    studio.action(task,'save-script',{'text':'새로운 문장을 자연스럽게 읽어요.'})
    studio.action(task,'reproduce',{})
    s=studio.store.get(task)
    assert s['latest_completed_run_id']==old
    assert studio.download(task,old,'export').read_bytes()==b'exported'
    complete(studio,task)
    s=studio.store.get(task);assert len(s['runs'])==2 and all(r['status']=='completed' for r in s['runs'])
    assert s['latest_completed_run_id']!=old


def test_original_correction_preserves_evidence_and_proposal_uses_visible_text(prepared, monkeypatch):
    studio, task = prepared
    before = studio.store.get(task)
    studio.action(task, 'save-original', {'text':'사용자가 들으며 교정한 발화', 'base_text':'원본 발화'})
    after = studio.store.get(task)
    assert after['original_text'] == before['original_text']
    assert after['script_id'] == before['script_id']
    with pytest.raises(Conflict):
        studio.action(task, 'save-original', {'text':'다른 교정', 'base_text':'원본 발화'})
    studio.action(task, 'propose-script', {'request':'도입을 짧게', 'base_text':'아직 저장하지 않은 화면의 대본'})
    job = next(j for j in studio.store.jobs(task) if j['kind']=='proposal')
    with studio.store.connect() as db:
        job['payload'] = json.loads(db.execute('SELECT payload FROM jobs WHERE id=?',(job['id'],)).fetchone()[0])
    calls = []
    def propose(settings, state, text, request):
        calls.append((state['original_text'],text))
        return {'text':'짧게 고친 수정안', 'summary':'도입 축약'}
    monkeypatch.setattr('hotpost.studio_ai.propose_script', propose)
    proposal = studio._proposal(studio.store.get(task), job)
    assert calls == [('사용자가 들으며 교정한 발화','아직 저장하지 않은 화면의 대본')]
    studio.store.change(task, lambda s,db:s['proposals'].append(proposal))
    with pytest.raises(Conflict):
        studio.action(task, 'apply-proposal', {'proposal_id':proposal['id'], 'base_text':'요청 이후 더 고친 대본'})
    studio.action(task, 'apply-proposal', {'proposal_id':proposal['id'], 'base_text':proposal['base_text']})
    assert studio.store.get(task)['feedback']['script_text']=='짧게 고친 수정안'
    studio.action(task, 'save-original', {'text':'다시 확인한 발화'})
    with pytest.raises(Conflict, match='원본 발화'):
        studio.action(task, 'apply-proposal', {'proposal_id':proposal['id'], 'base_text':proposal['base_text']})


def test_mixed_upstream_and_scene_edits_are_recoverable_without_losing_completed_version(prepared):
    studio, task = prepared
    complete(studio, task)
    old = studio.store.get(task)['run_id']
    studio.action(task, 'save-script', {'text':'타이밍이 달라질 새 대본'})
    studio.store.change(task, lambda s,db:s['feedback'].update(changes=[{'beat_id':'old-beat','start':0,'end':2}],base_edit_id=s['edit_id']))
    with pytest.raises(Conflict, match='구간 수정만 초기화'):
        studio.action(task, 'reproduce', {})
    assert studio.store.get(task)['run_id']==old
    studio.action(task, 'discard-edit-feedback', {})
    assert studio.store.get(task)['feedback']=={'script_text':'타이밍이 달라질 새 대본'}
    studio.action(task, 'reproduce', {})
    assert studio.download(task,old,'export').read_bytes()==b'exported'
    job = studio.store.claim()
    assert job['kind']=='voice'


def test_user_result_review_is_version_specific(prepared):
    studio, task = prepared
    before = studio.store.get(task)['run_id']
    with pytest.raises(ValueError):
        studio.action(task,'review-result',{'run_id':before,'checks':['speech','captions','scenes']})
    complete(studio,task)
    with pytest.raises(ValueError):
        studio.action(task,'review-result',{'run_id':before,'checks':['speech']})
    studio.action(task,'review-result',{'run_id':before,'checks':['speech','captions','scenes']})
    studio.action(task,'save-script',{'text':'새로 검토할 제작 대본'})
    studio.action(task,'reproduce',{})
    state=studio.store.get(task)
    assert before in state['result_reviews']
    assert state['run_id'] not in state['result_reviews']


def test_original_evidence_media_is_scoped_and_ocr_stays_separate(prepared):
    studio, task=prepared
    folder=studio.settings.data_dir/'transcripts'/'reference';folder.mkdir(parents=True)
    ref=folder/'reference.mp4';ref.write_bytes(b'video')
    other=folder/'unrelated.mp4';other.write_bytes(b'other')
    transcript=folder/'transcript.json'
    transcript.write_text(json.dumps({'speech':[{'start':0,'text':'말한 내용'}], 'screen_text':[{'start':1,'text':'화면 문구'}]}),encoding='utf-8')
    studio.store.change(task,lambda s,db:s.update(reference_video=str(ref),transcript_path=str(transcript)))
    public=studio.public(studio.store.get(task))
    assert public['original_evidence']['speech'][0]['text']=='말한 내용'
    assert public['original_evidence']['screen_text'][0]['text']=='화면 문구'
    assert public['reference_url']
    assert studio.media(task,str(ref.relative_to(studio.settings.data_dir)))==ref
    with pytest.raises(ValueError): studio.media(task,str(other.relative_to(studio.settings.data_dir)))


def test_old_editor_cannot_apply_cues_to_new_edit(prepared):
    studio,task=prepared;complete(studio,task)
    state=studio.store.get(task);old=state['edit_id']
    studio.store.change(task,lambda s,db:s.update(edit_id='newer-edit'))
    with pytest.raises(Conflict,match='새 편집 영상'):
        studio.action(task,'revise-edit',{'edit_id':old,'changes':[{'beat_id':'old-beat','text':'보존할 입력'}]})


def test_capcut_wait_does_not_consume_retry_and_survives_recovery(prepared):
    studio,task=prepared;job=studio.store.claim()
    studio.store.defer(job,'CapCut 종료 대기',100,waiting=True)
    studio.store.recover();assert studio.store.claim() is None
    assert job['checkpoint'].get('auto_retries',0)==0
    studio.store.defer(job,'connection timeout',100)
    assert job['checkpoint']['auto_retries']==1
    assert studio.store.get(task)['status']=='retry_wait'


def test_claim_retry_restores_running_task_state(prepared):
    studio,task=prepared
    job=studio.store.claim()
    studio.store.defer(job,'connection timeout',0)
    assert studio.store.get(task)['status']=='retry_wait'
    reclaimed=studio.store.claim()
    assert reclaimed['id']==job['id']
    assert studio.store.get(task)['status']=='voice_generating'
    assert '다시 진행 중' in studio.store.get(task)['message']


def test_failed_transcription_keeps_reference_and_stops_before_source_search(tmp_path,monkeypatch):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('speech-failure','발화 추출 실패',{'protocol':2,'active':True,'stage':'prepare'})
    folder=studio.settings.transcript_dir/'speech-failure-cache';folder.mkdir(parents=True)
    transcript=folder/'transcript.json';reference=folder/'reference.mp4';reference.write_bytes(b'video')
    transcript.write_text(json.dumps({'speech':[],'screen_text':[{'text':'화면 글자'}],'methods':{'speech':'unavailable'}}),encoding='utf-8')
    monkeypatch.setattr('hotpost.transcript.extract_transcript',lambda *a:{'json_path':str(transcript)})
    def forbidden(*args,**kwargs):raise AssertionError('Do not search sources when speech extraction failed')
    monkeypatch.setattr('hotpost.source_finder.find_sources',forbidden)
    with pytest.raises(ValueError,match='전사 도구 설치'):
        studio._prepare(state,studio.store.claim())
    actual=studio.public(studio.store.get(state['id']))
    assert actual['original_text']==''
    assert actual['reference_url']
    assert actual['original_evidence']['speech_unavailable']
    assert actual['original_evidence']['screen_text']==[{'text':'화면 글자'}]


def test_error_classification():
    assert transient(TimeoutError()) and transient(RuntimeError('HTTP 503'))
    assert not transient(ValueError('대본 검증 실패'))
    assert not transient(RuntimeError('로그인 필요'))


@pytest.mark.parametrize('boundary', ['retry', 'capcut_wait', 'restart'])
def test_pause_during_running_step_survives_retry_and_restart(prepared, boundary):
    studio,task=prepared
    job=studio.store.claim()
    studio.action(task,'pause-auto',{})
    if boundary=='restart':
        studio.store.recover()
    else:
        studio.store.defer(job,'connection timeout',0,waiting=boundary=='capcut_wait')
    assert studio.store.claim() is None
    assert next(j for j in studio.store.jobs(task) if j['id']==job['id'])['status']=='paused'
    studio.action(task,'resume-auto',{})
    assert studio.store.claim()['id']==job['id']


def test_pause_after_requesting_next_version_still_requires_explicit_resume(prepared):
    studio,task=prepared
    job=studio.store.claim()
    studio.action(task,'save-script',{'text':'다음 버전을 위한 수정 대본이에요.'})
    studio.action(task,'reproduce',{})
    studio.action(task,'pause-auto',{})
    folder=studio.folder(task);voice=folder/'pending.wav';voice.write_bytes(b'audio')
    s=studio.store.get(task)
    result={'id':s['pending_voice_id'],'script_id':s['script_id'],'path':str(voice),'sha256':hashlib.sha256(b'audio').hexdigest()}
    studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
    assert studio.store.get(task)['automation']['active'] is False
    assert studio.store.claim() is None
    studio.action(task,'resume-auto',{})
    assert studio.store.claim()['kind']=='voice'


def test_paused_work_allows_explicit_reproduction_and_manual_tools(prepared):
    studio,task=prepared
    studio.action(task,'pause-auto',{})
    with studio.store.transaction() as db:
        studio.store.enqueue(db,task,'register',{'launch':True},'manual-open')
        studio.store.enqueue(db,task,'proposal',{},'manual-proposal')
    assert studio.store.claim()['payload']['launch'] is True
    assert studio.store.claim()['kind']=='proposal'
    # Complete the isolated manual jobs before starting a new production.
    with studio.store.transaction() as db:
        db.execute("UPDATE jobs SET status='done' WHERE task_id=? AND status='running'",(task,))
    studio.action(task,'save-script',{'text':'명시적으로 새 제작을 시작해요.'})
    studio.action(task,'reproduce',{})
    assert studio.store.get(task)['automation']['active']
    assert not any(j['status']=='paused' for j in studio.store.jobs(task))
    assert studio.store.claim()['kind']=='voice'


def test_invalid_feedback_preserves_saved_values(prepared):
    studio,task=prepared
    with pytest.raises(ValueError): studio.action(task,'save-feedback',{'source_ids':['foreign']})
    with pytest.raises(ValueError): studio.action(task,'save-feedback',{'speed':float('nan')})
    studio.action(task,'save-feedback',{'source_ids':[]})
    with pytest.raises(ValueError): studio.action(task,'reproduce',{})
    assert not studio.store.get(task).get('pending_reproduction')


def test_voice_feedback_sets_spoken_text_preserving_captions(prepared):
    studio,task=prepared
    studio.action(task,'save-feedback',{'speed':1.05,'pronunciations':[{'from':'도구','to':'도꾸'}]})
    studio.action(task,'reproduce',{})
    job=studio.store.claim()
    assert job['payload']['speed']==1.05 and '도꾸' in job['payload']['spoken_text']
    s=studio.store.get(task);assert '도구' in s['scripts'][0]['text']


def test_explicit_voice_regeneration_has_stable_key_for_retry(prepared):
    studio,task=prepared
    studio.action(task,'regenerate-voice',{})
    studio.action(task,'reproduce',{})
    job=studio.store.claim()
    assert job['kind']=='voice'
    assert job['payload']['generation_key']==studio.store.get(task)['run_id']


def test_upload_checks_video_and_deduplicates(prepared,monkeypatch):
    studio,task=prepared
    monkeypatch.setattr('hotpost.source_finder.probe_video',lambda p:{'duration':2,'width':100,'height':200})
    studio.upload_source(task,io.BytesIO(b'newvideo'),8,'../clip.mp4')
    studio.upload_source(task,io.BytesIO(b'newvideo'),8,'clip.mp4')
    s=studio.store.get(task);assert len(s['sources'])==2
    assert Path(s['sources'][-1]['path']).is_relative_to(studio.folder(task))
    assert s['sources'][-1]['rights']=='user_supplied'


def test_top_pick_compares_candidates_and_rejects_missing_scores(prepared,monkeypatch):
    from hotpost.studio_top_pick import choose
    studio,task=prepared;s=studio.store.get(task)
    monkeypatch.setattr('hotpost.source_finder.extract_frames',lambda *a,**k:[])
    rows=[{'index':i,'eligible':True,'scores':dict(hook=n,grounding=5,narration=n,footage=n),'reason':str(i),'issues':[]} for i,n in [(0,2),(1,5)]]
    monkeypatch.setattr('hotpost.studio_top_pick._generate',lambda *a,**k:{'evaluations':rows})
    index,evaluation=choose(studio.settings,s,[(0,{'text':'첫 후보'}),(1,{'text':'두 번째 후보'})])
    assert index==1 and len(evaluation['evaluations'])==2


def test_top_pick_uses_selected_sources_and_keeps_rejection_audit(prepared,monkeypatch):
    from hotpost.studio_top_pick import choose
    from hotpost.studio_workflow import current_run
    studio,task=prepared;s=studio.store.get(task)
    s['sources'].append({'id':'unused-game','path':'absent.mp4','sha256':'unused'})
    current_run(s)['inputs']['source_ids']=['source1']
    frames=[]; calls=[]
    monkeypatch.setattr('hotpost.source_finder.extract_frames',lambda path,*a,**k:frames.append(path.name) or [])
    def reject(*args,**kwargs):
        calls.append(args[2])
        return {'evaluations':[{'index':0,'eligible':False,'scores':dict(hook=3,grounding=1,narration=3,footage=1),
                               'reason':'캠핑 대본과 수납장 영상이 맞지 않습니다','issues':['상품 불일치']}]}
    monkeypatch.setattr('hotpost.studio_top_pick._generate',reject)
    for _ in range(2):
        with pytest.raises(ValueError,match='캠핑 대본과 수납장 영상'):
            choose(studio.settings,s,[(0,{'text':'캠핑 대본'})])
    assert len(calls)==2 and frames==['source.mp4','source.mp4']
    assert [v['id'] for v in calls[0]['sources']]==['source1']
    receipts=list((studio.folder(task)/'top-pick').glob('*.json'))
    assert len(receipts)==1 and receipts[0].name.endswith('.rejected.json')
    assert json.loads(receipts[0].read_text('utf-8'))['status']=='rejected'


def test_feedback_revision_ignores_worker_progress_but_rejects_other_editor(prepared):
    studio,task=prepared
    studio.action(task,'save-script',{'text':'첫 번째 편집자의 대본이에요.','feedback_revision':0})
    studio.store.change(task,lambda s,db:s.update(progress=50))
    with pytest.raises(Conflict): studio.action(task,'save-script',{'text':'오래된 화면에서 작성한 대본이에요.','feedback_revision':0})
    studio.action(task,'save-feedback',{'speed':1.05,'feedback_revision':1})
    assert studio.store.get(task)['feedback_revision']==2


@pytest.mark.parametrize('change', [
    {'start':9, 'end':2}, {'start':-1}, {'end':4}, {'end':float('nan')},
    {'text':''}, {'text':'first\nsecond'}, {'text':'x'*101},
    {'emphasis':3}, {'emphasis':True}, {'shot_id':'foreign'}, {'beat_id':'missing'},
])
def test_invalid_scene_feedback_is_rejected_before_reproduction(prepared, change):
    studio,task=prepared
    plan=studio.folder(task)/'feedback-plan.json'
    plan.write_text(json.dumps({'duration':3, 'beats':[
        {'id':'beat-1','cue_id':'cue-1','options':[{'shot_id':'shot-1'}]},
        {'id':'beat-2','cue_id':'cue-2','options':[{'shot_id':'shot-1'}]}],
        'cues':[{'id':'cue-1','start':0,'end':1},{'id':'cue-2','start':1.5,'end':3}]}))
    studio.store.change(task,lambda s,db:s['edits'].append({'id':'edit-1','plan_path':str(plan)}))
    studio.action(task,'revise-edit',{'edit_id':'edit-1','changes':[{'beat_id':'beat-1','emphasis':1}]})
    before=studio.store.get(task)
    with pytest.raises(ValueError):
        studio.action(task,'revise-edit',{'edit_id':'edit-1','changes':[{'beat_id':'beat-1',**change}]})
    after=studio.store.get(task)
    assert after['feedback']==before['feedback']
    assert after['feedback_revision']==before['feedback_revision']
    assert after['run_id']==before['run_id']


def test_frame_extraction_reuse_never_deletes_returned_scene_frame(tmp_path,monkeypatch):
    from hotpost import source_finder as f
    from types import SimpleNamespace
    monkeypatch.setattr(f.shutil,'which',lambda n:n)
    def run(args,**kwargs):
        if args[0]=='ffprobe': return SimpleNamespace(stdout='2',returncode=0)
        pattern=args[-1];Path(pattern.replace('%03d','001')).write_bytes(b'frame')
        return SimpleNamespace(stdout='',stderr='',returncode=0)
    monkeypatch.setattr(f,'_run',run)
    monkeypatch.setattr(f,'dhash',lambda p:255 if '_scene_' in p.name else 0)
    for _ in range(2):
        frames=f.extract_frames(tmp_path/'video.mp4',tmp_path/'frames',max_frames=2)
        assert len(frames)==2 and all(p.is_file() for p in frames)

@pytest.mark.parametrize('automatic',[True,False])
def test_uploaded_sources_resume_without_search_and_preserve_concurrent_upload(tmp_path,monkeypatch,automatic):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    auto={'protocol':2,'active':True,'stage':'prepare'} if automatic else None
    state,_=studio.store.create('upload-fixture','업로드로 이어가는 영상',auto)
    task=state['id'];failed=studio.store.claim();studio.store.fail(failed,'Source manifest contains no selected local videos.')
    monkeypatch.setattr('hotpost.source_finder.probe_video',lambda p:{'duration':2,'width':100,'height':200})
    for name in ['first','second']:
        studio.upload_source(task,io.BytesIO(name.encode()),len(name),name+'.mp4')
    sources=studio.store.get(task)['sources'];chosen=sources[1]['id']
    transcript=studio.settings.transcript_dir/'upload-fixture-cache';transcript.mkdir(parents=True)
    (transcript/'transcript.json').write_text(json.dumps({'speech':[{'text':'실제 원본 발화'}]}),encoding='utf-8')
    (transcript/'reference.mp4').write_bytes(b'reference')
    def forbidden(*args,**kwargs):raise AssertionError('An uploaded source must not trigger another search or extraction')
    monkeypatch.setattr('hotpost.source_finder.find_sources',forbidden)
    monkeypatch.setattr('hotpost.transcript.extract_transcript',forbidden)
    def rewrite(settings,transcript,manifest,*args):
        assert manifest.is_file()
        return {'variants':[{'text':'우리 규칙으로 가공한 대본'}]}
    monkeypatch.setattr('hotpost.script_rewriter.rewrite',rewrite)
    out=studio.action(task,'use-sources',{'source_ids':[chosen]})
    assert out['status']=='preparing' and not out['error']
    job=studio.store.claim();assert job['kind']=='prepare'
    result=studio._prepare(studio.store.get(task),job)
    assert [v['id'] for v in result['sources']]==[chosen]
    assert result['sources'][0]['rights']=='user_supplied'
    from hotpost.source_audit import summarize
    audit=summarize(result['manifest_path'])
    assert audit['selected']==audit['usable']==1
    assert audit['platforms']['직접 업로드']['received']==1
    studio.upload_source(task,io.BytesIO(b'third'),5,'third.mp4')
    studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
    finished=studio.store.get(task)
    assert len(finished['sources'])==3
    if automatic:
        assert finished['status']=='rewriting'
        public=studio.public(finished)
        active=next(r for r in public['pipeline'] if r['id']==public['run_id'])
        assert [v['id'] for v in active['artifacts']['sources']]==[chosen]
        assert active['status']=='running'
    else:
        assert finished['status']=='script_review'


def test_source_resume_rejects_missing_files_and_active_work(prepared):
    studio,task=prepared
    # Cannot jump backward into preparation from a later stage.
    with pytest.raises(Conflict):studio.action(task,'use-sources',{'source_ids':['source1']})
    def reset(s,db):
        db.execute("UPDATE jobs SET status='done'")
        s['automation']['stage']='prepare'
        studio.store.enqueue(db,task,'prepare',{},'new-prepare')
    studio.store.change(task,reset);studio.store.claim()
    with pytest.raises(Conflict):studio.action(task,'use-sources',{'source_ids':['source1']})
    with pytest.raises(ValueError):studio.action(task,'use-sources',{'source_ids':[]})
    with pytest.raises(ValueError):studio.action(task,'use-sources',{'source_ids':['missing']})
