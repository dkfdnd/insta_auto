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


def test_capcut_wait_does_not_consume_retry_and_survives_recovery(prepared):
    studio,task=prepared;job=studio.store.claim()
    studio.store.defer(job,'CapCut 종료 대기',100,waiting=True)
    studio.store.recover();assert studio.store.claim() is None
    assert job['checkpoint'].get('auto_retries',0)==0
    studio.store.defer(job,'connection timeout',100)
    assert job['checkpoint']['auto_retries']==1
    assert studio.store.get(task)['status']=='retry_wait'


def test_error_classification():
    assert transient(TimeoutError()) and transient(RuntimeError('HTTP 503'))
    assert not transient(ValueError('대본 검증 실패'))
    assert not transient(RuntimeError('로그인 필요'))


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


def test_feedback_revision_ignores_worker_progress_but_rejects_other_editor(prepared):
    studio,task=prepared
    studio.action(task,'save-script',{'text':'첫 번째 편집자의 대본이에요.','feedback_revision':0})
    studio.store.change(task,lambda s,db:s.update(progress=50))
    with pytest.raises(Conflict): studio.action(task,'save-script',{'text':'오래된 화면에서 작성한 대본이에요.','feedback_revision':0})
    studio.action(task,'save-feedback',{'speed':1.05,'feedback_revision':1})
    assert studio.store.get(task)['feedback_revision']==2


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
