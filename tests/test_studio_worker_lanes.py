from concurrent.futures import ThreadPoolExecutor
import threading

from hotpost.config import Settings
from hotpost.studio import Studio


def enqueue(studio, task_id, kind):
    with studio.store.transaction() as db:
        return studio.store.enqueue(db, task_id, kind, {}, kind+':'+task_id)


def create(studio, code):
    return studio.store.create(code, code, prepare=False)[0]['id']


def test_same_task_script_and_media_claims_are_atomic_while_sources_can_overlap(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    tid=create(studio,'one-task')
    for kind in ('rewrite','voice','collect_sources'):
        enqueue(studio,tid,kind)
    barrier=threading.Barrier(2)

    def claim(lane):
        barrier.wait(timeout=3)
        return studio.store.claim(lane)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(claim,'scripts');b=pool.submit(claim,'media')
        jobs=[x for x in (a.result(timeout=4),b.result(timeout=4)) if x]
    assert len(jobs)==1
    source=studio.store.claim('sources')
    assert source and source['kind']=='collect_sources'
    studio.store.finish(jobs[0],{},lambda *_:None)
    next_job=studio.store.claim('media' if jobs[0]['kind']=='rewrite' else 'scripts')
    assert next_job and next_job['task_id']==tid


def test_script_lane_cannot_take_voice_edit_or_preparation_jobs(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    tid=create(studio,'media-only')
    for kind in ('prepare','voice','edit','register','export'):
        enqueue(studio,tid,kind)
    assert studio.store.claim('scripts') is None
    assert studio.store.claim('media')['kind']=='prepare'


def test_slow_media_job_does_not_stop_another_tasks_real_worker_script_completion(tmp_path):
    started=threading.Event();release=threading.Event();saved=threading.Event()

    class FixtureStudio(Studio):
        def _edit(self,state,job):
            started.set()
            assert release.wait(timeout=5)
            return {}

        def _rewrite(self,state,job):
            assert started.is_set() and not release.is_set()
            return {'text':'다른 게시물의 새 대본'}

        def _accept(self,state,job,result,db=None):
            state['lane_test_result']=result
            if job['kind']=='rewrite':
                saved.set()

    studio=FixtureStudio(Settings(data_dir=tmp_path),workers=False)
    media_tid=create(studio,'slow-edit');script_tid=create(studio,'parallel-script')
    media_id=enqueue(studio,media_tid,'edit');script_id=enqueue(studio,script_tid,'rewrite')
    with ThreadPoolExecutor(max_workers=2) as pool:
        media=pool.submit(studio._worker,'media')
        assert started.wait(timeout=3)
        writer=pool.submit(studio._worker,'scripts')
        try:
            assert saved.wait(timeout=3)
        finally:
            studio.stop.set();release.set()
        media.result(timeout=4);writer.result(timeout=4)
    assert studio.store.get(script_tid)['lane_test_result']['text']=='다른 게시물의 새 대본'
    assert next(j for j in studio.store.jobs(media_tid) if j['id']==media_id)['status']=='done'
    assert next(j for j in studio.store.jobs(script_tid) if j['id']==script_id)['status']=='done'


def test_legacy_production_claim_still_accepts_script_jobs(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    tid=create(studio,'legacy-entry')
    enqueue(studio,tid,'rewrite')
    assert studio.store.claim('production')['kind']=='rewrite'


def test_manual_proposal_is_independent_of_the_running_media_version(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    tid=create(studio,'manual-proposal')
    enqueue(studio,tid,'edit');enqueue(studio,tid,'proposal')
    assert studio.store.claim('media')['kind']=='edit'
    assert studio.store.claim('scripts')['kind']=='proposal'
