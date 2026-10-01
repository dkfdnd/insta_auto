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
         'taken_at':now-3600, 'views':12000, 'metric_status':{'views':'observed'},
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


def test_frozen_top_two_never_backfills_or_overwrites_manual_task(setup):
    settings,studio=setup
    manual=studio.create('first')
    r=report(time.time())
    rows=enqueue_top(settings,r,'run-1')
    assert [x['shortcode'] for x in rows]==['first','second']
    assert 'automation' not in studio.store.get(manual['id'])
    r['posts'][0]['rank_score']=99
    assert [x['created'] for x in rows] == [False, True]
    repeated = enqueue_top(settings,r,'run-1')
    assert [x['task_id'] for x in repeated] == [x['task_id'] for x in rows]
    assert all(x['outcome']=='existing' and not x['created'] for x in repeated)
    assert len(studio.store.list())==2
    assert sum(len(studio.store.jobs(t['id'])) for t in studio.store.list())==2


def test_stale_top_rank_does_not_turn_third_into_second():
    now=time.time(); r=report(now)
    r['posts'][1]['assessment']['last_observed_at']=now-40*3600
    result=top_two(r,Settings(),now)
    assert [(x['shortcode'],x['eligible']) for x in result]==[('first',False),('second',True)]
    assert top_two({**r,'is_sample':True},Settings(),now)==[]


def test_subject_uses_observed_context_instead_of_comment_bait():
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
    review['script_sha256']='wrong'
    with pytest.raises(ValueError,match='검증'): rewrite(studio,state,job)


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
