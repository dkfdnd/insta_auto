import hashlib
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.studio_http import StudioHTTP
from hotpost.studio_store import Conflict
from hotpost.studio_sources import source_goal
from hotpost.writing import pipeline
from hotpost.writing.contract import snapshot

TEXT='이거 접으면 가방 공간이 남는 거예요!\n댓글에 도시락 남겨주세요.'


def create(studio, **extra):
    return studio.create_self_shot({'creation_key':'a'*32, 'script_mode':'manual', 'text':TEXT, **extra})


def upload(studio, task, monkeypatch, content=b'video', name='my-video.mov'):
    monkeypatch.setattr('hotpost.source_finder.probe_video', lambda _: {'duration':2, 'width':1080})
    return studio.upload_source(task, io.BytesIO(content), len(content), name)


def finish(studio, result):
    job=studio.store.claim();assert job
    studio.store.finish(job, result, lambda s,db,r: studio._accept(s,job,r,db))
    return job


def test_independent_draft_is_idempotent_without_post_db_or_queued_work(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path), workers=False)
    t=create(studio)
    assert t['creation_mode']=='self_shot' and not studio.settings.db_path.exists()
    assert create(studio)['id']==t['id']
    assert not t['jobs'] and studio.store.claim() is None
    assert t['source_policy']['platform_minimums']=={} and t['source_goal']['target']==1
    reopened=Studio(studio.settings, workers=False)
    assert reopened.store.get(t['id'])['self_shot']['text']==TEXT
    assert reopened.store.claim() is None


def test_twenty_clip_limit_duplicate_and_failed_upload_cleanup(tmp_path, monkeypatch):
    studio=Studio(Settings(data_dir=tmp_path), workers=False);t=create(studio)
    for i in range(20): upload(studio,t['id'],monkeypatch,content=f'video-{i}'.encode())
    before=list((studio.folder(t['id'])/'uploads').iterdir())
    assert len(upload(studio,t['id'],monkeypatch,content=b'video-0')['sources'])==20
    with pytest.raises(ValueError,match='20개'): upload(studio,t['id'],monkeypatch,content=b'21st-video')
    assert len(list((studio.folder(t['id'])/'uploads').iterdir()))==len(before)==20
    assert studio.store.claim() is None


def test_manual_text_starts_at_personal_voice_with_one_clip_and_no_search(tmp_path, monkeypatch):
    studio=Studio(Settings(data_dir=tmp_path), workers=False);t=create(studio)
    t=upload(studio,t['id'],monkeypatch)
    t=studio.action(t['id'],'use-sources',{'source_ids':[t['sources'][0]['id']]})
    job=studio.store.claim();assert job['kind']=='prepare'
    result=studio._prepare(studio.store.get(t['id']),job)
    studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
    t=studio.public(studio.store.get(t['id']))
    assert t['scripts'][0]['text']==TEXT and t['scripts'][0]['origin']=='manual'
    assert not t.get('reference_video') and not t.get('transcript_path')
    assert t['source_goal']['ready'] and not t['source_goal']['platform_targets']
    job=studio.store.claim();assert job['kind']=='voice'
    assert job['payload']['voice_mode']=='personal_clone' and job['payload']['spoken_text']==TEXT
    assert not job['payload'].get('voice_profile_id')
    assert not any(j['kind'] in {'rewrite','collect_sources','refresh_sources'} for j in studio.store.jobs(t['id']))
    for command in ('refresh-sources','use-sources'):
        with pytest.raises((ValueError,Conflict)):studio.action(t['id'],command,{'source_ids':[]})
    studio.action(t['id'],'start-auto',{})
    assert not any(j['kind'] in {'collect_sources','refresh_sources'} for j in studio.store.jobs(t['id']))


def test_missing_selection_rejected_and_unselected_upload_stays_excluded(tmp_path, monkeypatch):
    studio=Studio(Settings(data_dir=tmp_path), workers=False);t=create(studio)
    with pytest.raises(ValueError):studio.action(t['id'],'use-sources',{'source_ids':[]})
    t=upload(studio,t['id'],monkeypatch,b'first');first=t['sources'][0]['id']
    t=upload(studio,t['id'],monkeypatch,b'second')
    t=studio.action(t['id'],'use-sources',{'source_ids':[first]})
    job=studio.store.claim();result=studio._prepare(studio.store.get(t['id']),job)
    studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
    s=studio.store.get(t['id'])
    assert len(s['sources'])==2 and source_goal(s)['source_ids']==[first]
    assert s['runs'][0]['artifacts']['sources'][0]['id']==first
    assert len(s['runs'][0]['artifacts']['sources'])==1


def test_manual_complete_and_reproduction_keep_owned_policy_and_old_version(tmp_path, monkeypatch):
    studio=Studio(Settings(data_dir=tmp_path), workers=False);t=create(studio)
    t=upload(studio,t['id'],monkeypatch);sid=t['sources'][0]['id']
    studio.action(t['id'],'use-sources',{'source_ids':[sid]})
    job=studio.store.claim();finish_result=studio._prepare(studio.store.get(t['id']),job)
    studio.store.finish(job,finish_result,lambda s,db,r:studio._accept(s,job,r,db))
    s=studio.store.get(t['id']);folder=studio.folder(t['id']);voice=folder/'voice.wav';voice.write_bytes(b'voice')
    finish(studio,{'id':s['pending_voice_id'],'script_id':s['script_id'],'path':str(voice),
                  'sha256':hashlib.sha256(b'voice').hexdigest(),'speed':1,'duration':3})
    job=studio.store.claim();assert job['kind']=='edit' and job['payload']['source_ids']==[sid]
    s=studio.store.get(t['id']);plan=folder/'plan.json';plan.write_text('{"shots":[],"beats":[],"cues":[]}')
    video=folder/'video.mp4';video.write_bytes(b'video');portable=folder/'portable';portable.mkdir()
    result={'id':job['id'],'script_id':s['script_id'],'voice_id':s['voice_id'],'plan_path':str(plan),
            'preview_path':str(video),'portable_draft_path':str(portable)}
    studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
    finish(studio,{'draft_path':'test-capcut','draft_name':'self-shot'})
    finish(studio,{'export_path':str(video),'export_verified':True})
    completed=studio.public(studio.store.get(t['id']))
    assert completed['status']=='completed'
    assert all(step['status']=='completed' for step in completed['pipeline'][0]['steps'])
    run=completed['run_id']
    changed=studio.action(t['id'],'make-video',{'text':TEXT+'\n직접 수정한 문장입니다.'})
    assert changed['run_id']!=run and changed['latest_completed_run_id']==run
    assert changed['source_policy']['owned_only'] and changed['source_goal']['ready']
    assert changed['pipeline'][0]['video_url'] and changed['pipeline'][0]['status']=='completed'
    assert studio.store.claim()['kind']=='voice'
    assert all(j['kind']!='collect_sources' for j in changed['jobs'])


def test_auto_research_and_writing_use_owned_contract_without_reference_video(tmp_path, monkeypatch):
    from hotpost.studio_adapter import StudioAdapter
    studio=Studio(Settings(data_dir=tmp_path), workers=False)
    t=create(studio,script_mode='automatic',product='접이식 도시락통',text='',details='다 먹은 뒤 접어 보관해요.')
    calls=[]
    def make(jobs,kind,payload,identity=''):
        calls.append((kind,payload,identity));return {'id':'codex'+str(len(calls)), 'state':'completed','result':{
            'facts':[{'text':'접어서 보관해요.','source_url':'https://example.com/product','source_title':'제품','same_product':True}],
            'warnings':[]} if kind=='product_research' else {'scripts':[{'text':TEXT}],'writing_contract':payload['writing_contract']}}
    monkeypatch.setattr('hotpost.writing.jobs.Jobs.create',make)
    monkeypatch.setattr('hotpost.writing.jobs.Jobs.start',lambda _:None)
    monkeypatch.setattr(StudioAdapter,'_wait',lambda _,job:job)
    monkeypatch.setattr('hotpost.local_compute.release_idle_voice',lambda *a,**k:{'status':'released'})
    t=upload(studio,t['id'],monkeypatch)
    studio.action(t['id'],'use-sources',{'source_ids':[t['sources'][0]['id']]})
    job=studio.store.claim();result=studio._prepare(studio.store.get(t['id']),job)
    assert result['research']['facts'] and result['reference_kind']=='provided_text'
    studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))
    job=studio.store.claim();assert job['kind']=='rewrite'
    result=studio._rewrite(studio.store.get(t['id']),job)
    assert result['text']==TEXT
    payload=calls[-1][1]
    assert payload['generation_mode']=='self_shot' and 'self-shot' in payload['writing_contract']['version']
    assert not any(k in payload for k in ['sources','reference_video_sha256'])
    assert '벤치마킹 원본이나 원본 후킹은 없다' in payload['writing_contract']['prompt']


def test_short_topic_can_generate_with_no_fake_reference_and_copy_flags(tmp_path, monkeypatch):
    calls=[]
    def chat(instruction,data,schema,check,state):
        calls.append((instruction,json.loads(data)))
        if len(calls)==1:return {'text':'접어서 보관해요! 댓글에 나도 남겨주세요.'}
        return {'issues':[]}
    monkeypatch.setattr(pipeline.codex_writer,'chat',chat)
    value=pipeline.generate({'reference_script':'도시락통','generation_mode':'self_shot','product':'도시락통',
        'writing_contract':snapshot('self_shot')},tmp_path,lambda:None,lambda *a:None)
    assert value['evidence']['mode']=='self_shot' and not value['benchmark']
    assert len(calls)==2 and calls[0][1]['reference_kind']=='product_information'
    assert 'sources' not in calls[0][1]


def test_create_http_route_origin_validation_and_independent_post(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    class Handler(StudioHTTP,BaseHTTPRequestHandler):
        def _json(self,data,status=200):
            raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)
        def do_POST(self):self.studio_post(studio)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:
        url=f'http://127.0.0.1:{server.server_port}/api/studio/self-shot'
        body={'creation_key':'b'*32,'script_mode':'manual','text':TEXT}
        assert requests.post(url,json=body,headers={'Origin':'https://unrelated.test'},timeout=5).status_code==403
        response=requests.post(url,json=body,timeout=5)
        assert response.status_code==202 and response.json()['creation_mode']=='self_shot'
        assert requests.post(url,json={**body,'script_mode':'automatic','product':''},timeout=5).status_code==400
        assert len(studio.store.list())==1 and not studio.settings.db_path.exists()
    finally:server.shutdown();server.server_close();worker.join(3)


def test_only_product_research_can_enable_web_and_filters_wrong_product(tmp_path,monkeypatch):
    from hotpost.writing import codex_writer, product_research
    assert 'web_search="disabled"' in codex_writer.command('codex','cwd','schema','output')
    assert 'web_search="live"' in codex_writer.command('codex','cwd','schema','output',allow_web=True)
    def chat(*args,**kwargs):
        assert kwargs['allow_web'] is True
        return {'facts':[{'text':'다른 모델','source_url':'https://example.com/other','source_title':'다른 모델','same_product':False},
                         {'text':'접어서 보관해요','source_url':'https://example.com/ours','source_title':'제품','same_product':True}],
                'warnings':['다른 모델은 제외했습니다.']}
    monkeypatch.setattr(product_research.codex_writer,'chat',chat)
    monkeypatch.setattr(product_research,'request_pause',lambda:None)
    result=product_research.research({'product':'도시락통'},tmp_path,lambda:None,lambda *a:None)
    assert len(result['facts'])==1 and result['facts'][0]['text']=='접어서 보관해요'
