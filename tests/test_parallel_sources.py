import hashlib
import json
from pathlib import Path

from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.studio_sources import source_goal
from hotpost.studio_workflow import snapshot
from hotpost.source_queries import next_round_queries


def asset(folder, index, *, core=False, platform='youtube.com', quality='clean-source'):
    path=folder/f'source-{index}.mp4';path.write_bytes(f'actual distinct fixture {index}'.encode())
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    return {'id':f'source-{index}','path':str(path),'sha256':sha,'source_quality':quality,
            'origin_url':f'https://{platform}/@fixture/video/{index}' if platform=='tiktok.com' else f'https://{platform}/watch?v={index}',
            'source_role':'core' if core else 'context_only',
            'functional_review':{'reviewed':True,'same_core_function':core,'context_usable':not core,
                'context_usage_limits':[] if core else ['general cooking'], 'observed_actions':['scooping garlic' if core else 'mixing salad'],
                'evidence_frames':['observed.jpg'],'source_sha256':sha}}


def task(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('parallel-test','마늘 준비',{'protocol':2,'active':True,'stage':'prepare'})
    folder=studio.folder(state['id']);ref=folder/'reference.mp4';ref.write_bytes(b'reference')
    def prepared(s,db):
        db.execute("UPDATE jobs SET status='done'")
        s.update(original_text='마늘을 준비해 한 스푼 떠서 요리에 넣어요.',reference_video=str(ref))
        studio.advance_workflow(s,db)
    studio.store.change(state['id'],prepared)
    return studio,state['id'],folder


def finish(studio,job,result):
    studio.store.finish(job,result,lambda s,db,r:studio._accept(s,job,r,db))


def test_source_and_script_lanes_run_together_without_duplicate_jobs(tmp_path):
    studio,tid,folder=task(tmp_path)
    source=studio.store.claim('sources');script=studio.store.claim('production')
    assert source['kind']=='collect_sources' and script['kind']=='rewrite'
    finish(studio,script,{'text':'요리를 시작할 때 마늘 한 스푼이면 편하겠죠?'})
    voice=studio.store.claim('production')
    assert voice['kind']=='voice' and voice['payload']['voice_mode']=='personal_clone'
    assert 'voice_profile_id' not in voice['payload']
    public=studio.public(studio.store.get(tid))
    steps={s['key']:s['status'] for s in public['pipeline'][0]['steps']}
    assert steps['sources']=='running' and steps['voice']=='running' and steps['script']=='completed'
    studio.store.change(tid,lambda s,db:studio.advance_workflow(s,db))
    jobs=studio.store.jobs(tid)
    assert sum(j['kind']=='collect_sources' for j in jobs)==1
    assert sum(j['kind']=='voice' for j in jobs)==1


def test_collection_returns_post_review_outcomes_and_preserves_search_history(tmp_path, monkeypatch):
    from hotpost import source_finder, source_overlay_review, source_functional
    studio, tid, folder = task(tmp_path)
    job = studio.store.claim('sources')
    source = asset(folder, 0, core=True, platform='tiktok.com')
    manifest = folder / 'manifest.json'
    raw = {'zip_path': str(folder / 'sources.zip'), 'downloaded': 1,
        'candidates': [{'url': source['origin_url'], 'downloaded_file': Path(source['path']).name,
            'file_sha256': source['sha256'], 'selected_for_zip': True,
            'source_quality': 'clean-source', 'editing_eligible': None,
            'functional_review': source['functional_review'], 'acquisition': 'local-cache',
            'download_attempted': False, 'rejection_reasons': []}],
        'platform_targets': {'tiktok': 5},
        'search_audit': [{'provider': 'tiktok', 'status': 'readiness_blocked'}],
        'platform_outcomes': {'tiktok': {'usable': 0, 'reasons': {'quality_rejected': 1}}}}
    manifest.write_text(json.dumps(raw))
    monkeypatch.setattr(source_finder, 'find_sources', lambda *a, **kw: raw)
    monkeypatch.setattr(source_finder, 'extract_frames', lambda *a, **kw: [Path('reference.jpg')])
    monkeypatch.setattr(source_overlay_review, 'needs_overlay_review', lambda s: False)
    monkeypatch.setattr(source_functional, 'needs_function_review', lambda s: False)
    result = studio._collect_source_attempt(studio.store.get(tid), job)
    current = result['platform_outcomes']['tiktok']
    assert current['usable'] == 1 and current['local_reuses'] == 1
    assert current['search_attempts'] == current['download_attempts'] == 0
    assert 'quality_rejected' not in current['reasons']
    assert result['searches'] == raw['search_audit']
    assert json.loads(manifest.read_text()) == raw


def automatic_review_fixture(tmp_path, monkeypatch, *, mode='ready', active=True, kind='collect_sources'):
    from hotpost import source_finder, source_overlay_review, source_functional
    studio, tid, folder = task(tmp_path)
    job = studio.store.claim('sources')
    job['kind'] = kind
    rows = [asset(folder, i, core=i == (12 if mode == 'missing_core' else 5),
                  platform='tiktok.com' if i < (4 if mode == 'missing_tiktok' else 5) or i == 12 else 'youtube.com')
            for i in range(14)]
    if mode == 'duplicate':
        rows[1] = {**rows[0], 'id': 'duplicate'}
    if mode == 'unprepared_blur':
        rows[0]['source_quality'] = 'edited-with-text'
        rows[0]['blur_required'] = True
    raw = {'zip_path': str(folder / 'sources.zip'), 'downloaded': len(rows),
           'candidates': [{'url': s['origin_url'], 'downloaded_file': Path(s['path']).name,
                           'file_sha256': s['sha256'], 'selected_for_zip': True,
                           'source_quality': s['source_quality'], 'blur_required': s.get('blur_required', False),
                           'editing_eligible': None, 'acquisition': 'local-cache',
                           'download_attempted': False, 'rejection_reasons': []} for s in rows],
           'platform_targets': {'tiktok': 5}, 'search_audit': []}
    manifest = folder / 'manifest.json'
    manifest.write_text(json.dumps(raw))
    reviews = {s['sha256']: s['functional_review'] for s in rows}
    calls = []
    def review_function(settings, candidate, reference, evidence):
        calls.append(candidate.file_sha256)
        return reviews[candidate.file_sha256]
    monkeypatch.setattr(source_finder, 'find_sources', lambda *a, **kw: raw)
    monkeypatch.setattr(source_finder, 'extract_frames', lambda *a, **kw: [Path('reference.jpg')])
    monkeypatch.setattr(source_overlay_review, 'needs_overlay_review', lambda s: False)
    monkeypatch.setattr(source_functional, 'review_function', review_function)
    state = studio.store.change(tid, lambda s, db: s['automation'].update(active=active))
    result = studio._collect_source_attempt(state, job)
    return studio, tid, job, result, calls, raw, manifest


def test_automatic_review_finishes_at_verified_quota_and_preserves_extra_downloads(tmp_path, monkeypatch):
    studio, tid, job, result, calls, raw, manifest = automatic_review_fixture(tmp_path, monkeypatch)
    assert len(calls) == len(result['sources']) == 10
    completion = result['review_completion']
    assert completion['reason'] == 'quota_met' and completion['deferred_sources'] == 4
    assert completion['goal']['ready'] and completion['goal']['platform_targets']['tiktok']['usable'] == 5
    assert json.loads(manifest.read_text()) == raw
    assert all((manifest.parent / c['downloaded_file']).is_file() for c in raw['candidates'])
    assert result['platform_outcomes']['tiktok']['reasons']['review_pending'] == 1  # retained extra TikTok
    finish(studio, job, result)
    saved = studio.store.get(tid)
    assert saved['source_goal']['ready'] and len(saved['sources']) == 10
    assert saved['source_acquisition']['rounds'][-1]['review_completion'] == completion
    assert not any(j['kind'] == 'collect_sources' and j['status'] == 'queued' for j in studio.store.jobs(tid))


def test_automatic_review_does_not_stop_on_ten_without_tiktok_coverage(tmp_path, monkeypatch):
    _, _, _, result, calls, _, _ = automatic_review_fixture(tmp_path, monkeypatch, mode='missing_tiktok')
    assert len(calls) == 13
    assert result['review_completion']['goal']['ready']
    assert result['review_completion']['goal']['platform_targets']['tiktok']['usable'] == 5


def test_automatic_review_does_not_stop_without_actual_core_action(tmp_path, monkeypatch):
    _, _, _, result, calls, _, _ = automatic_review_fixture(tmp_path, monkeypatch, mode='missing_core')
    assert len(calls) == 13 and result['review_completion']['goal']['core_ready']


def test_automatic_review_deduplicates_before_finishing(tmp_path, monkeypatch):
    _, _, _, result, calls, _, _ = automatic_review_fixture(tmp_path, monkeypatch, mode='duplicate')
    assert len(calls) == 12  # repeated URL/hash is removed before any review
    assert result['review_completion']['goal']['platform_targets']['tiktok']['usable'] == 5


def test_automatic_review_does_not_count_unprepared_blur(tmp_path, monkeypatch):
    _, _, _, result, calls, _, _ = automatic_review_fixture(tmp_path, monkeypatch, mode='unprepared_blur')
    assert len(calls) == 13
    assert result['review_completion']['goal']['platform_targets']['tiktok']['usable'] == 5
    assert result['sources'][0]['id'] not in result['review_completion']['goal']['source_ids']


def test_inactive_collection_still_reviews_requested_candidates(tmp_path, monkeypatch):
    _, _, _, result, calls, _, _ = automatic_review_fixture(tmp_path, monkeypatch, active=False)
    assert len(calls) == 14 and result['review_completion'] is None


def test_explicit_refresh_still_reviews_requested_candidates(tmp_path, monkeypatch):
    _, _, _, result, calls, _, _ = automatic_review_fixture(tmp_path, monkeypatch, kind='refresh_sources')
    assert len(calls) == 14 and result['review_completion'] is None


def test_voice_finishes_before_sources_but_edit_waits_until_ten_and_core(tmp_path):
    studio,tid,folder=task(tmp_path)
    source=studio.store.claim('sources');rewrite=studio.store.claim('production')
    finish(studio,rewrite,{'text':'마늘을 떠서 사용하는 방법이 궁금하죠?'})
    voice_job=studio.store.claim('production');p=folder/'voice.wav';p.write_bytes(b'voice')
    finish(studio,voice_job,{'id':voice_job['payload']['voice_id'],'script_id':voice_job['payload']['script_id'],
        'path':str(p),'sha256':hashlib.sha256(b'voice').hexdigest(),'speed':1,'duration':3})
    assert studio.store.get(tid)['status']=='source_wait'
    assert studio.store.claim('production') is None
    sources=[asset(folder,i,core=i==0,platform='tiktok.com' if i<5 else 'youtube.com') for i in range(10)]
    finish(studio,source,{'sources':sources,'source_search_manifest_path':'fixture.json','round':0})
    edit=studio.store.claim('production')
    assert edit['kind']=='edit' and len(edit['payload']['source_ids'])==10
    assert studio.store.claim('sources') is None
    assert source_goal(studio.store.get(tid))['ready']


def test_insufficient_or_context_only_round_is_queued_automatically(tmp_path):
    studio,tid,folder=task(tmp_path);job=studio.store.claim('sources')
    sources=[asset(folder,i) for i in range(10)]
    finish(studio,job,{'sources':sources,'source_search_manifest_path':'fixture.json','round':0})
    state=studio.store.get(tid)
    assert state['source_goal']['count']==10 and not state['source_goal']['ready']
    assert state['source_search']['status']=='queued'
    jobs=studio.store.jobs(tid)
    assert sum(j['kind']=='collect_sources' and j['status']=='queued' for j in jobs)==1
    assert studio.store.claim('sources') is None  # request pacing, not a running spinner
    studio.store.recover()
    assert studio.store.claim('sources') is None


def test_download_duplicates_and_unprepared_blur_do_not_inflate_count(tmp_path):
    s=asset(tmp_path,1,core=True)
    duplicate={**s,'id':'duplicate'}
    text=asset(tmp_path,2,quality='edited-with-text')
    state={'sources':[s,duplicate,text]}
    assert source_goal(state)['count']==1
    text['watermark_masks']=[{'reviewed':True,'source_start':0,'source_end':3}]
    assert source_goal(state)['count']==2
    Path(text['path']).unlink()
    assert source_goal(state)['count']==1


def test_collection_does_not_reset_failed_voice_or_repeat_its_request(tmp_path):
    studio,tid,folder=task(tmp_path);source=studio.store.claim('sources')
    rewrite=studio.store.claim('production');finish(studio,rewrite,{'text':'새 대본'})
    voice=studio.store.claim('production');studio.store.fail(voice,'personal clone unavailable')
    finish(studio,source,{'sources':[asset(folder,0,core=True)],'source_search_manifest_path':'fixture.json','round':0})
    assert studio.store.get(tid)['error']=='personal clone unavailable'
    assert next(j for j in studio.store.jobs(tid) if j['id']==voice['id'])['status']=='failed'
    assert studio.store.claim('production') is None
    assert any(j['kind']=='collect_sources' and j['status']=='queued' for j in studio.store.jobs(tid))


def test_user_pause_stops_future_round_without_losing_acquired_sources(tmp_path):
    studio,tid,folder=task(tmp_path);job=studio.store.claim('sources')
    studio.store.change(tid,lambda s,db:s['automation'].update(active=False,paused_by_user=True))
    finish(studio,job,{'sources':[asset(folder,0,core=True)],'source_search_manifest_path':'fixture.json','round':0})
    assert len(studio.store.get(tid)['sources'])==1
    assert studio.store.claim('sources') is None


def test_new_search_round_changes_language_and_intent_without_repeating_completed_query():
    plan={'products':[{'en':'minced garlic','ko':'다진 마늘','zh':'蒜末','sources':['speech']}],
          'query_details':[{'query':'minced garlic','language':'en'}]}
    result=next_round_queries(plan,1,[{'query':'minced garlic','status':'results'}])
    assert all(r['query']!='minced garlic' for r in result)
    assert {r['language'] for r in result}=={'en','ko','zh'}
    assert {r['query'] for r in result}!={r['query'] for r in next_round_queries(plan,2,[])}


def test_daily_consumed_running_source_job_does_not_restart_after_error_or_recovery(tmp_path):
    studio,tid,folder=task(tmp_path);job=studio.store.claim('sources')
    studio.store.change(tid,lambda s,db:s['automation'].update(active=False,consumed_by_daily_policy=True))
    studio.store.defer(job,'connection timeout',0)
    assert next(j for j in studio.store.jobs(tid) if j['id']==job['id'])['status']=='paused'
    studio.store.recover()
    assert studio.store.claim('sources') is None


def test_source_authentication_error_stops_identical_retries_without_stopping_script(tmp_path):
    studio,tid,folder=task(tmp_path);job=studio.store.claim('sources')
    studio.handle_source_error(job,RuntimeError('HTTP 401: invalid credential'))
    state=studio.store.get(tid)
    assert state['source_search']['status']=='failed' and not state.get('error')
    studio.store.change(tid,lambda s,db:studio.advance_workflow(s,db))
    assert studio.store.claim('sources') is None
    assert studio.store.claim('production')['kind']=='rewrite'


def test_transient_source_retry_has_a_limit(tmp_path):
    studio,tid,folder=task(tmp_path);job=studio.store.claim('sources')
    studio.handle_source_error(job,TimeoutError('timeout'))
    assert job['checkpoint']['auto_retries']==1
    studio.handle_source_error(job,TimeoutError('timeout'))
    assert job['checkpoint']['auto_retries']==2
    studio.handle_source_error(job,TimeoutError('timeout'))
    assert next(j for j in studio.store.jobs(tid) if j['id']==job['id'])['status']=='failed'


def test_explicit_source_retry_does_not_erase_independent_voice_failure(tmp_path):
    studio,tid,folder=task(tmp_path);job=studio.store.claim('sources')
    studio.handle_source_error(job,RuntimeError('HTTP 401'))
    studio.store.change(tid,lambda s,db:s.update(error='personal clone unavailable',status='attention'))
    state=studio.store.get(tid)
    studio.action(tid,'retry',{'revision':state['revision'],'job_id':job['id']})
    assert studio.store.get(tid)['error']=='personal clone unavailable'
    assert studio.store.claim('sources')['id']==job['id']


def test_manual_edit_selection_is_preserved_with_ten_in_acquisition_pool(tmp_path):
    studio,tid,folder=task(tmp_path);source=studio.store.claim('sources');rewrite=studio.store.claim('production')
    finish(studio,rewrite,{'text':'선택한 장면으로 제작합니다.'})
    voice=studio.store.claim('production');p=folder/'voice.wav';p.write_bytes(b'voice')
    finish(studio,source,{'sources':[asset(folder,i,core=i==0,platform='tiktok.com' if i<5 else 'youtube.com') for i in range(10)],'source_search_manifest_path':'fixture.json','round':0})
    chosen=source_goal(studio.store.get(tid))['source_ids'][:3]
    studio.store.change(tid,lambda s,db:snapshot(s)['inputs'].update(source_ids=chosen))
    finish(studio,voice,{'id':voice['payload']['voice_id'],'script_id':voice['payload']['script_id'],
        'path':str(p),'sha256':hashlib.sha256(b'voice').hexdigest(),'speed':1,'duration':3})
    edit=studio.store.claim('production')
    assert edit['kind']=='edit' and edit['payload']['source_ids']==chosen
