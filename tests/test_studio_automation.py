import hashlib
import json
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost.models import Post, Profile
from hotpost.storage import Storage
from hotpost.studio import Studio
from hotpost.studio_automation import top_two, enqueue_top, rewrite, identify_subject


def report(now):
    return {'generated_at':now, 'posts':[
        {'shortcode':code, 'kind':'reel', 'tier':1, 'rank_score':score,
         'taken_at':now-3600, 'hot_detected_at':now, 'views':12000, 'metric_status':{'views':'observed'},
         'assessment':{'last_observed_at':now, 'status':'provisional'}}
        for code,score in [('third',1),('first',3),('second',2)]]}


@pytest.fixture
def setup(tmp_path):
    s=Settings(data_dir=tmp_path, studio_auto_top_enabled=True)
    store=Storage(s.db_path)
    store.upsert_profile(Profile('account'))
    store.upsert_posts([Post(code,'account',int(time.time())-3600,'reel') for code in ('first','second','third')])
    store.close()
    return s,Studio(s,workers=False)


def test_all_new_hot_videos_are_frozen_without_overwriting_manual_task(setup):
    settings,studio=setup
    manual=studio.create('first')
    r=report(time.time())
    rows=enqueue_top(settings,r,'run-1')
    assert [x['shortcode'] for x in rows]==['first','second','third']
    assert 'automation' not in studio.store.get(manual['id'])
    assert studio.store.get(rows[1]['task_id'])['automation']['finish_selected_batch']
    r['posts'][0]['rank_score']=99
    assert [x['created'] for x in rows] == [False, True, True]
    repeated = enqueue_top(settings,r,'run-1')
    assert [x['task_id'] for x in repeated] == [x['task_id'] for x in rows]
    assert all(x['outcome']=='existing' and not x['created'] for x in repeated)
    assert len(studio.store.list())==3
    assert sum(len(studio.store.jobs(t['id'])) for t in studio.store.list())==3


def test_metric_warning_does_not_remove_a_discovered_hot_video():
    now=time.time(); r=report(now)
    r['posts'][1]['assessment']['last_observed_at']=now-40*3600
    result=top_two(r,Settings(),now)
    assert [(x['shortcode'],x['eligible']) for x in result]==[('first',True),('second',True),('third',True)]
    assert result[0]['metric_warning'] and not result[1]['metric_warning']
    assert top_two({**r,'is_sample':True},Settings(),now)==[]


def test_subject_uses_observed_context_instead_of_comment_bait():
    assert identify_subject({}, '피규어 장난감을 투명창 안에 싹 진열하고 문만 닫아요. 대나무 원목이에요.', '피규어')=='원목 진열장'
    assert identify_subject({}, '책을 진열장에 넣어요.', '책')=='진열장'
    assert identify_subject({}, '피규어를 조립해요. 원목 책상에서 작업해요.', '피규어')!='원목 진열장'
    assert identify_subject({'caption':'생선 남겨주세요!\n오늘 저녁 생선구이 이렇게 해보세요'}, '', '생선 남겨주세요')=='생선구이'
    assert identify_subject({'caption':'타일 남겨주세요!\n타일 보수 비법을 소개합니다'}, '', '타일 남겨주세요')=='타일 보수'
    assert identify_subject({'caption':'댓글 남겨주세요\n관측한 새로운 도구의 실제 설명입니다'}, '', '댓글 남겨주세요')=='관측한 새로운 도구의 실제 설명입니다'


def finish(studio, result):
    job=studio.store.claim()
    assert job
    studio.store.finish(job,result,lambda state,db,value:studio._accept(state,job,value,db))
    return job


def test_automatic_chain_survives_recovery_and_ends_in_same_studio(setup):
    settings,studio=setup
    task=studio.create('first',automation={'active':True,'stage':'prepare','rank':1,'reviewed_by_user':False})
    finish(studio,{'sources':[{'path':'source.mp4'}],'original_text':'원본 발화'})
    assert studio.store.get(task['id'])['status']=='rewriting'
    finish(studio,{'text':'새로운 관점의 대본입니다.','rewrite_review':{'status':'needs_editorial_review'}})
    # Simulate a restart after claiming voice: the same voice/job ID is reused.
    claimed=studio.store.claim(); studio.store.recover()
    state=studio.store.get(task['id'])
    voice=studio.folder(task['id'])/'voice.wav'; voice.write_bytes(b'checked audio')
    v={'id':claimed['payload']['voice_id'],'script_id':state['script_id'],
       'path':str(voice),'sha256':hashlib.sha256(voice.read_bytes()).hexdigest()}
    assert finish(studio,v)['id']==claimed['id']
    state=studio.store.get(task['id']); editjob=studio.store.claim()
    edit={'id':editjob['id'],'script_id':state['script_id'],'voice_id':v['id'],
          'preview_path':'preview.mp4','plan_path':'timeline.json'}
    studio.store.finish(editjob,edit,lambda s,db,r:studio._accept(s,editjob,r,db))
    register=studio.store.claim()
    assert register['kind']=='register' and register['payload']['launch'] is False
    studio.store.finish(register,{'draft_path':'CapCut/Studio-job','draft_name':'Studio-job'},
                        lambda s,db,r:studio._accept(s,register,r,db))
    state=studio.store.get(task['id'])
    assert state['status']=='draft_review' and state['automation']['stage']=='completed'
    assert state['automation']['reviewed_by_user'] is False
    assert len(state['scripts'])==len(state['voices'])==len(state['edits'])==1
    assert [j['kind'] for j in reversed(studio.store.jobs(task['id']))]==['prepare','rewrite','voice','edit','register']
    assert studio.store.claim() is None


def test_ready_video_continues_before_next_source_search(setup):
    _,studio=setup
    first=studio.create('first',automation={'active':True,'stage':'prepare'})
    second=studio.create('second',automation={'active':True,'stage':'prepare'})
    finish(studio,{'sources':[{'path':'source.mp4'}],'original_text':'원본 발화'})
    next_job=studio.store.claim()
    assert next_job['task_id']==first['id'] and next_job['kind']=='rewrite'
    assert studio.store.jobs(second['id'])[0]['status']=='queued'


def test_pause_stops_advancement_and_failure_keeps_stage_for_retry(setup):
    _,studio=setup
    t=studio.create('first',automation={'active':True,'stage':'prepare','rank':1})
    studio.action(t['id'],'pause-auto',{})
    finish(studio,{'sources':[{'path':str(studio.folder(t['id'])/'source.mp4')}],'original_text':'발화'})
    assert studio.store.claim() is None
    studio.action(t['id'],'resume-auto',{})
    job=studio.store.claim(); studio.store.fail(job,'서비스에 연결하지 못했습니다')
    state=studio.store.get(t['id'])
    assert state['status']=='attention' and state['automation']['stage']=='rewrite'
    studio.action(t['id'],'retry',{})
    assert studio.store.claim()['id']==job['id']


def test_resume_with_uploaded_sources_finishes_prepare_before_rewrite(setup):
    _, studio = setup
    task = studio.create('first', automation={'active':True,'protocol':2,'stage':'prepare'})
    studio.action(task['id'], 'pause-auto', {})
    source = str(studio.folder(task['id'])/'source.mp4')
    studio.store.change(task['id'], lambda s,db:s.update(sources=[{'id':'upload','path':source}]))
    studio.action(task['id'], 'resume-auto', {})
    assert [j['kind'] for j in studio.store.jobs(task['id'])] == ['prepare']
    assert studio.store.claim()['kind'] == 'prepare'


def test_rewrite_reuses_external_id_and_requires_verified_candidate(setup,monkeypatch):
    _,studio=setup
    state=studio.create('first',automation={'active':True})
    state['original_text']='원본 발화'
    job={'id':studio.store.jobs(state['id'])[0]['id'],'checkpoint':{'studio_job_id':'existing'}}
    text='새로운 대본'
    review={'status':'needs_editorial_review','script_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'reference_sha256':hashlib.sha256(state['original_text'].encode()).hexdigest()}
    from hotpost import studio_adapter
    monkeypatch.setattr(studio_adapter,'StudioAdapter',lambda s:SimpleNamespace(
        get=lambda job_id:{'state':'completed','result':{'scripts':[{'text':text,'rewrite_review':review}]}}))
    assert rewrite(studio,state,job)['text']==text
    # Old cached rejections and new advisory reviews both continue production.
    for status in ('blocked', 'advisory'):
        review.update(status=status, reasons=['후킹 평가 미흡'])
        assert rewrite(studio,state,job)['text']==text
    review['script_sha256']='wrong'
    with pytest.raises(ValueError,match='버전'): rewrite(studio,state,job)


def test_partial_collection_does_not_trigger_watcher(setup):
    from hotpost.studio_automation import enqueue_latest
    settings,studio=setup
    store=Storage(settings.db_path)
    store.initialize_managed_accounts([('account',''),('other','')])
    store.record_run(int(time.time()),'browser',1,0,3,'partial')
    store.close()
    settings.report_path.write_text(json.dumps(report(time.time())),encoding='utf-8')
    assert enqueue_latest(settings)==[]
    assert studio.store.list()==[]


@pytest.mark.parametrize('skipped,failed', [(1,0), (0,1)])
def test_interrupted_collection_never_freezes_top_two(setup, skipped, failed):
    from hotpost.studio_automation import enqueue_latest
    settings,studio=setup
    store=Storage(settings.db_path)
    store.initialize_managed_accounts([('account',''),('other','')])
    run_id=store.start_run(int(time.time()),'browser')
    store.finish_run(run_id,1,failed,3,skipped=skipped,stop_reason='browser_navigation')
    store.close()
    settings.report_path.write_text(json.dumps(report(time.time())),encoding='utf-8')
    assert enqueue_latest(settings)==[]
    with studio.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM automatic_runs').fetchone()[0]==0


def test_cli_interrupted_collection_does_not_start_production(setup, monkeypatch):
    from hotpost import cli, report as reports, studio_automation, acquisition
    settings,_=setup
    monkeypatch.setattr(cli.AccountRegistry,'usernames',lambda _: ['account','other'])
    def stopped(settings, store, source, usernames):
        rid=store.start_run(int(time.time()),source)
        store.finish_run(rid,1,0,3,skipped=1,stop_reason='browser_navigation')
        return 1,0,3,[]
    monkeypatch.setattr(cli,'collect',stopped)
    monkeypatch.setattr(reports,'build_report',lambda *a,**k:{'summary':{'hot':2,'posts':3}})
    monkeypatch.setattr(reports,'write_report',lambda *a: None)
    def forbidden(*a,**k): pytest.fail('interrupted collection must not start production')
    monkeypatch.setattr(studio_automation,'enqueue_top',forbidden)
    monkeypatch.setattr(studio_automation,'ensure_worker',forbidden)
    monkeypatch.setattr(acquisition,'acquire',forbidden)
    args=SimpleNamespace(source='browser',only=None,acquire=True,serve=False)
    assert cli._cmd_run_locked(settings,args)==1


def test_explicit_retry_replaces_failed_remote_id_once(setup,monkeypatch):
    from hotpost import studio_adapter
    _,studio=setup
    state=studio.create('first',automation={'active':True})
    state['original_text']='원본'
    job={'id':studio.store.jobs(state['id'])[0]['id'],'checkpoint':{'studio_job_id':'old','retry_requested':True}}
    text='새 대본'
    review={'status':'needs_editorial_review','script_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'reference_sha256':hashlib.sha256(state['original_text'].encode()).hexdigest()}
    calls=[]
    monkeypatch.setattr(studio_adapter,'StudioAdapter',lambda s:SimpleNamespace(
        get=lambda jid:{'state':'failed'},
        retry=lambda task,jid:calls.append(jid) or {'id':'new','state':'completed','result':{'scripts':[{'text':text,'rewrite_review':review}]}}))
    assert rewrite(studio,state,job)['studio_job_id']=='new'
    assert calls==['old'] and not job['checkpoint'].get('retry_requested')


def test_retry_of_completed_but_rejected_generation_creates_new_identity(setup):
    _,studio=setup
    task=studio.create('first',automation={'protocol':2,'active':True})
    def failed(s,db):
        db.execute("UPDATE jobs SET status='done' WHERE task_id=?",(s['id'],))
        jid=studio.store.enqueue(db,s['id'],'rewrite',{},'rejected-generation')
        db.execute("UPDATE jobs SET status='failed',checkpoint=? WHERE id=?",
                   (json.dumps({'studio_job_id':'completed-but-blocked','generation_key':'old-key'}),jid))
        s.update(status='attention',error='All candidates rejected')
    studio.store.change(task['id'],failed)
    job=next(j for j in studio.store.jobs(task['id']) if j['kind']=='rewrite')
    studio.action(task['id'],'retry',{'job_id':job['id']})
    with studio.store.connect() as db:
        row=db.execute('SELECT status,checkpoint FROM jobs WHERE id=?',(job['id'],)).fetchone()
    checkpoint=json.loads(row['checkpoint'])
    assert row['status']=='queued' and 'studio_job_id' not in checkpoint
    assert checkpoint['generation_key'].startswith('rewrite-retry-')
    assert checkpoint['previous_studio_job_ids']==['completed-but-blocked']
    assert len([j for j in studio.store.jobs(task['id']) if j['kind']=='rewrite'])==1


def test_open_registered_automatic_project_requests_launch(setup):
    _,studio=setup
    task=studio.create('first')
    def registered(s,db):
        s['edits']=[{'id':'edit1'}]
        studio.store.enqueue(db,s['id'],'register',{'edit_id':'edit1','launch':False},'register:edit1')
        db.execute("UPDATE jobs SET status='done' WHERE key='register:edit1'")
    studio.store.change(task['id'],registered)
    studio.action(task['id'],'open-capcut',{'edit_id':'edit1'})
    with studio.store.connect() as db:
        row=db.execute("SELECT payload,status FROM jobs WHERE key='register:edit1'").fetchone()
    assert row['status']=='queued' and json.loads(row['payload'])['launch'] is True


def test_explicit_rewrite_correction_preserves_old_result_and_queues_new_attempt(setup):
    _,studio=setup
    task=studio.create('first',automation={'protocol':2,'active':True})
    def ready(s,db):
        db.execute("UPDATE jobs SET status='failed' WHERE task_id=?",(s['id'],))
        s.update(original_text='관찰한 원본 발화',reference_video=str(studio.folder(s['id'])/'reference.mp4'),sources=[{'id':'source','path':str(studio.folder(s['id'])/'source.mp4')}],
                 studio_job_id='old-result',product='피규어',error='대본 검증 실패',status='attention',script_candidates=[{'text':'오래된 후보'}])
        s['automation']['needs_top_pick']=True
        studio.store.enqueue(db,s['id'],'rewrite',{},'old-rewrite')
        db.execute("UPDATE jobs SET status='failed' WHERE key='old-rewrite'")
    studio.store.change(task['id'],ready)
    result=studio.action(task['id'],'regenerate-script',{'product':'원목 진열장','instructions':'원목 키워드를 유지하세요.','product_url':'https://example.com/cabinet'})
    state=studio.store.get(task['id'])
    assert state['rewrite_history'][-1]['studio_job_id']=='old-result'
    assert state['product_override']=='원목 진열장' and state['studio_job_id'] is None
    assert state['product_url_override']=='https://example.com/cabinet'
    assert not state['automation']['needs_top_pick'] and state['script_candidates']==[]
    assert state['rewrite_history'][-1]['script_candidates']==[{'text':'오래된 후보'}]
    with studio.store.connect() as db:
        assert db.execute("SELECT status FROM jobs WHERE key='old-rewrite'").fetchone()[0]=='superseded'
    with pytest.raises(Exception,match='진행 중'):studio.action(task['id'],'regenerate-script',{'product':'원목 진열장'})
    job=studio.store.claim()
    assert job['kind']=='rewrite' and job['checkpoint']['generation_key'].startswith('rewrite-')


def test_corrected_script_input_gets_new_idempotency_key(setup,tmp_path,monkeypatch):
    from hotpost.studio_adapter import StudioAdapter
    settings,_=setup;api=StudioAdapter(settings);video=tmp_path/'reference.mp4';video.write_bytes(b'video')
    monkeypatch.setattr(api,'writing_contract',lambda:{'sha256':'rules'})
    keys=[]
    monkeypatch.setattr(api.jobs,'start',lambda:None)
    for product,generation in [('피규어',''),('원목 진열장',''),('원목 진열장',''),('원목 진열장','attempt-2')]:
        keys.append(api.submit('task',video,'원본',{'product':product,'generation_key':generation})['id'])
    assert keys[0]!=keys[1] and keys[1]==keys[2] and keys[2]!=keys[3]
