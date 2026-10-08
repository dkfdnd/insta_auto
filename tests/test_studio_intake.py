import json
import time

from hotpost.config import Settings
from hotpost.models import Post, Profile
from hotpost.storage import Storage
from hotpost.studio import Studio
from hotpost.studio_automation import enqueue_top, intake_log
from hotpost.studio_intake import intake_status


def setup_run(tmp_path):
    settings = Settings(data_dir=tmp_path, studio_auto_top_enabled=True)
    store = Storage(settings.db_path)
    now = int(time.time())
    store.upsert_profile(Profile('account'))
    store.upsert_posts([Post('old','account',now-3600,'reel')], collected_at=now-100)
    run = store.start_run(now, 'browser')
    store.upsert_posts([Post(code,'account',now-3600,'reel') for code in ('new','third')], collected_at=now)
    store.finish_run(run, 1, 0, 3)
    report = {'generated_at':time.time()+1, 'posts':[
        {'shortcode':code,'username':'account','caption':'테스트 영상','kind':'reel','tier':1,
         'rank_score':score,'taken_at':now-3600,'hot_detected_at':now,'views':12000,
         'metric_status':{'views':'observed'},'assessment':{'last_observed_at':now}}
        for code,score in [('old',3),('new',2),('third',1)]]}
    settings.report_path.write_text(json.dumps(report), encoding='utf-8')
    store.close()
    return settings, Studio(settings,workers=False), report, run


def test_registration_execution_and_new_candidates_are_separate(tmp_path):
    settings, studio, report, run = setup_run(tmp_path)
    old = studio.create('old')
    studio.store.change(old['id'], lambda s,db:s.update(status='attention', error='GEMINI_API_KEY가 설정되지 않았습니다.'))
    rows = enqueue_top(settings, report, run)
    assert [r['created'] for r in rows] == [False,True,True]
    assert rows[0]['state']=='blocked'
    assert '신규 등록 2개 · 기존 작업 1개' in intake_log(rows)
    before = sum(len(studio.store.jobs(t['id'])) for t in studio.store.list())
    for _ in range(2):
        receipt = intake_status(studio)
        assert (receipt['new_posts'],receipt['new_hot_videos'])==(2,3)
        assert (receipt['created'],receipt['existing'],receipt['blocked'])==(2,1,1)
        assert '키 없이 로컬 모델' in receipt['rows'][0]['solution']
        assert [r['shortcode'] for r in receipt['candidates']]==['old','new','third']
        assert receipt['candidates'][1]['task_id'] and receipt['candidates'][2]['task_id']
    again = enqueue_top(settings, report, run)
    assert '신규 등록 0개 · 기존 작업 3개' in intake_log(again)
    assert sum(len(studio.store.jobs(t['id'])) for t in studio.store.list())==before
    assert 'automation' not in studio.store.get(old['id'])
    studio.store.change(old['id'], lambda s,db:s.update(status='completed',error=''))
    assert intake_status(studio)['blocked']==0


def test_new_collection_does_not_show_previous_receipt(tmp_path):
    settings, studio, report, run = setup_run(tmp_path)
    enqueue_top(settings,report,run)
    store=Storage(settings.db_path)
    store.start_run(int(time.time())+10,'browser');store.close()
    receipt=intake_status(studio)
    assert not receipt['ready'] and not receipt['selection_ready']
    assert receipt['rows']==[] and receipt['candidates']==[]


def test_all_hot_videos_are_registered_even_with_a_metric_warning(tmp_path):
    settings, studio, report, run = setup_run(tmp_path)
    report['posts'][0]['metric_status']['views']='missing'
    result=enqueue_top(settings,report,run)
    assert result[0]['outcome']=='created' and result[0]['metric_warning']
    receipt=intake_status(studio)
    assert receipt['skipped']==0 and receipt['created']==3
    assert len(studio.store.list())==3


def test_new_candidate_post_never_restarts_existing_task(tmp_path):
    import io
    from hotpost.studio_http import StudioHTTP
    _, studio, _, _ = setup_run(tmp_path)
    old = studio.create('old')
    studio.store.change(old['id'], lambda s,db:s.update(status='attention',error='기존 오류'))
    before = studio.store.get(old['id'])
    class Handler(StudioHTTP):
        path='/api/studio'
        def _json(self, data, status=200):
            self.result,self.code=data,status
    h=Handler()
    body=json.dumps({'shortcodes':['old','new'],'automatic':True,'only_new':True}).encode()
    h.headers={'Content-Length':str(len(body))}
    h.rfile=io.BytesIO(body)
    assert h.studio_post(studio) and h.code==202
    assert studio.store.get(old['id'])==before
    assert h.result['tasks'][1]['automation']['active']
