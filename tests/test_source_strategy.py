"""Regressions for exhausted queries, cross-provider searches and bounded acquisition."""
import json
import time
from types import SimpleNamespace

import pytest

from hotpost.browser_search import BrowserSearcher
from hotpost.config import Settings
from hotpost.source_queries import next_round_queries, product_query_plan
from hotpost.source_search.discovery import discover
from hotpost.source_search.strategy import fresh_queries, image_sha256, merge_history, restore_history
from test_parallel_sources import task, asset, finish


def test_used_youtube_query_remains_available_on_tiktok_and_all_intents_survive_rotation():
    plan = product_query_plan('다진마늘 보관 준비', [], [], {}, [])
    initial = next_round_queries(plan, 1, [])
    history = [{'provider':'youtube', 'query':q['query'], 'status':'no_results'} for q in initial]
    later = next_round_queries(plan, 239, history)
    queries = [q['query'] for q in later]
    assert queries and {'en', 'ko', 'zh'} <= {q['language'] for q in later}
    assert fresh_queries(queries, 'tiktok', history)
    assert not fresh_queries(queries, 'youtube', history)
    assert not any('unboxing' in q or 'product demonstration' in q for q in queries)


def test_history_does_not_forget_old_searches_after_500_new_entries():
    history = merge_history([{'provider':'youtube', 'query':f'garlic {i}', 'status':'no_results'} for i in range(700)])
    assert not fresh_queries(['  GARLIC   0  ', 'garlic 699'], 'youtube', history)
    assert fresh_queries(['garlic 0'], 'bing', history) == ['garlic 0']


def test_migration_restores_attempts_from_manifests_not_skipped_authentication(tmp_path):
    manifest = tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'search_audit':[
        {'provider':'youtube','query':'old garlic','status':'no_results'},
        {'provider':'tiktok','query':'garlic','status':'verification_required'}]}))
    record = {'queries':[], 'rounds':[{'manifest_path':str(manifest)}]}
    history = restore_history(record)
    assert fresh_queries(['old garlic'], 'youtube', history) == []
    assert fresh_queries(['garlic'], 'tiktok', history) == ['garlic']
    manifest.unlink()
    assert restore_history(record) == history


def test_images_advance_and_same_bytes_under_new_name_are_not_reuploaded(tmp_path):
    frames = []
    for index in range(5):
        p = tmp_path/f'frame_{index}.jpg'; p.write_bytes(str(index).encode()); frames.append(p)
    searcher = BrowserSearcher(Settings(data_dir=tmp_path, source_browser_frames=2), tmp_path)
    first = searcher._fresh_images(frames, 'yandex-images')
    searcher.previous_searches = [{'provider':'yandex-images','query':p.name,'language':'image',
        'image_sha256':image_sha256(p),'status':'no_results'} for p in first]
    second = searcher._fresh_images(frames, 'yandex-images')
    assert not set(first) & set(second)
    duplicate = tmp_path/'renamed.jpg'; duplicate.write_bytes(first[0].read_bytes())
    assert not searcher._fresh_images([duplicate], 'yandex-images')
    assert searcher.searches[-1]['status'] == 'image_exhausted'
    assert searcher._fresh_images([duplicate], 'google-lens') == [duplicate]


def test_provider_filters_before_query_limit_and_never_reuses_image_labels(tmp_path):
    calls = []
    def search(provider):
        def invoke(queries, limit, audit, *args):
            calls.extend((provider, q) for q in queries)
            audit.extend({'provider':provider,'query':q,'status':'no_results'} for q in queries)
            return []
        return invoke
    services = SimpleNamespace(search_local_hints=lambda *_: [], search_local_cache=lambda *_: [],
        _clean_visual_terms=lambda x:x, Candidate=lambda **x:x,
        search_web=search('duckduckgo'), search_bing=search('bing'),
        search_youtube=lambda qs,n,cookies,audit,runtime:search('youtube')(qs,n,audit),
        search_pexels=lambda settings,qs,n,audit:search('pexels')(qs,n,audit))
    history = [{'provider':'youtube', 'query':'garlic preparation', 'status':'no_results'}]
    candidates, queries, *_ = discover(Settings(source_browser_search=False, source_queries_per_platform=1),
        'post', [], ['garlic preparation', 'garlic portioning'], {'products':[]}, [], tmp_path,
        history, [], lambda *_:None, services)
    assert ('youtube', 'garlic preparation') not in calls
    assert ('youtube', 'garlic portioning') in calls
    _, _, _, audit, _ = discover(Settings(source_browser_search=False), 'post', [], [],
        {'products':[]}, [], tmp_path, [], [], lambda *_:None, services)
    assert any(r['status']=='no_supported_queries' for r in audit)
    assert all(q.strip() for _, q in calls)


def round_result(number, sources=None, searches=None):
    return {'sources':sources or [], 'source_search_manifest_path':'fixture.json', 'round':number,
            'searches':searches if searches is not None else [
                {'provider':'youtube', 'query':f'garlic shot {number}', 'status':'no_results'}]}


def claim_next(studio, tid):
    with studio.store.transaction() as db:
        db.execute("UPDATE jobs SET checkpoint='{}' WHERE task_id=? AND status='queued' AND kind='collect_sources'", (tid,))
    return studio.store.claim('sources')


def test_three_no_gain_rounds_stop_persistently_and_leave_script_lane_alive(tmp_path):
    studio, tid, folder = task(tmp_path)
    for i in range(3):
        job = claim_next(studio, tid)
        assert job
        finish(studio, job, round_result(i))
    state = studio.store.get(tid)
    assert state['source_acquisition']['hold']['reason'] == 'no_progress'
    assert state['source_search']['status'] == 'blocked'
    assert '증가 없음' in state['message'] or '증가 없음' in state['source_search']['message']
    assert not state.get('error')
    studio.store.recover()
    studio.store.change(tid, lambda s, db:studio.advance_workflow(s, db))
    assert studio.store.claim('sources') is None
    assert studio.store.claim('production')['kind'] == 'rewrite'
    public = studio.public(studio.store.get(tid))
    assert public['pipeline'][0]['steps'][0]['status'] == 'blocked'


def test_skipped_authentication_and_exhaustion_stop_without_new_failed_requests(tmp_path):
    studio, tid, folder = task(tmp_path)
    job = studio.store.claim('sources')
    finish(studio, job, round_result(0, searches=[
        {'provider':'tiktok','query':'','status':'verification_required'},
        {'provider':'yandex-images','query':'','status':'image_exhausted'},
        {'provider':'youtube','query':'','status':'query_exhausted'}]))
    state = studio.store.get(tid)
    assert state['source_acquisition']['hold']['reason'] == 'strategy_exhausted'
    assert 'tiktok' in state['source_search']['message']
    assert '장면 이미지 소진' in state['source_search']['message']
    assert not state['source_acquisition']['queries']
    assert studio.store.claim('sources') is None


@pytest.mark.parametrize('provider',['local-cache','source-library'])
def test_cache_only_round_can_continue_to_external_search_without_false_exhaustion(tmp_path,provider):
    studio, tid, folder = task(tmp_path)
    job = studio.store.claim('sources')
    finish(studio, job, round_result(0, searches=[
        {'provider':provider, 'query':'', 'status':'results', 'candidates':2}]))
    state = studio.store.get(tid)
    assert not state['source_acquisition'].get('hold')
    assert not state['source_acquisition']['queries']  # Local inspection is not an external request.
    assert claim_next(studio, tid)['kind'] == 'collect_sources'


def test_library_candidates_do_not_disable_the_bounded_no_gain_stop(tmp_path):
    studio,tid,folder=task(tmp_path)
    for i in range(3):
        job=claim_next(studio,tid)
        finish(studio,job,round_result(i,searches=[
            {'provider':'source-library','query':'','status':'results','candidates':2}]))
    state=studio.store.get(tid)
    assert state['source_acquisition']['hold']['reason']=='no_progress'
    assert not state['source_acquisition']['queries']
    assert studio.store.claim('sources') is None


def test_verified_gain_resets_stagnation_but_not_total_round_limit(tmp_path):
    studio, tid, folder = task(tmp_path)
    studio.settings.source_collection_max_rounds = 3
    for i in range(3):
        job = claim_next(studio, tid)
        finish(studio, job, round_result(i, [asset(folder,i,core=i==0)]))
    state = studio.store.get(tid)
    assert state['source_acquisition']['no_progress_rounds'] == 0
    assert state['source_acquisition']['hold']['reason'] == 'round_limit'
    assert len(state['sources']) == 3


def test_elapsed_budget_blocks_rescheduling_and_explicit_resume_preserves_search_ledger(tmp_path):
    studio, tid, folder = task(tmp_path)
    job = studio.store.claim('sources')
    studio.store.change(tid, lambda s, db:s['source_acquisition'].update(started_at=time.time()-7200, execution_seconds=7200))
    finish(studio, job, round_result(0))
    state = studio.store.get(tid)
    assert state['source_acquisition']['hold']['reason'] == 'time_limit'
    ledger = state['source_acquisition']['queries']
    studio.action(tid, 'resume-auto', {'revision':state['revision']})
    state = studio.store.get(tid)
    assert not state['source_acquisition'].get('hold')
    assert state['source_acquisition']['queries'] == ledger
    assert claim_next(studio, tid)['kind'] == 'collect_sources'


def test_fresh_budget_record_without_round_can_start_acquisition(tmp_path):
    studio, tid, folder = task(tmp_path)
    def reset(s, db):
        # Remove the fixture's pre-created round so this exercises a fresh
        # acquisition record rather than an already completed idempotency key.
        db.execute("DELETE FROM jobs WHERE kind='collect_sources'")
        s['source_acquisition'] = {}
        studio.release_source_hold(s)
        studio.ensure_source_collection(s, db)
    studio.store.change(tid, reset)
    assert studio.store.claim('sources')['payload']['round'] == 0


def test_expired_queued_round_does_not_invoke_external_search(tmp_path, monkeypatch):
    from hotpost import source_finder
    studio, tid, folder = task(tmp_path)
    studio.store.change(tid, lambda s, db:s['source_acquisition'].update(started_at=time.time()-7200, execution_seconds=7200))
    job = studio.store.claim('sources')
    monkeypatch.setattr(source_finder, 'find_sources', lambda *a, **k: (_ for _ in ()).throw(AssertionError('unexpected external search')))
    result = studio._collect_sources(studio.store.get(tid), job)
    finish(studio, job, result)
    state = studio.store.get(tid)
    assert state['source_acquisition']['hold']['reason'] == 'time_limit'
    assert studio.store.claim('sources') is None


def test_blank_web_queries_never_issue_network_requests(monkeypatch):
    from hotpost import source_finder
    monkeypatch.setattr(source_finder.requests, 'get', lambda *a, **k: (_ for _ in ()).throw(AssertionError('blank query request')))
    assert source_finder.search_web(['', '   '], 10) == []
    assert source_finder.search_bing(['', '   '], 10) == []
