import json
import time
from types import SimpleNamespace

import pytest

from test_parallel_sources import task, finish


def test_waiting_days_in_queue_does_not_spend_actual_search_budget(tmp_path, monkeypatch):
    from hotpost import source_finder, studio_sources
    studio, tid, folder = task(tmp_path)
    studio.store.change(tid, lambda s, db:s['source_acquisition'].update(
        started_at=time.time()-3*86400, queued_at=time.time()-3*86400))
    job = studio.store.claim('sources')
    manifest = folder/'manifest.json'
    manifest.write_text(json.dumps({'candidates':[]}), encoding='utf-8')
    calls = []
    def search(*a, **k):
        calls.append(k)
        return {'zip_path':str(folder/'sources.zip'), 'candidates':[],
                'search_audit':[{'provider':'youtube', 'query':'garlic storage', 'status':'no_results'}]}
    monkeypatch.setattr(source_finder, 'find_sources', search)
    monkeypatch.setattr(source_finder, 'extract_frames', lambda *a, **k:[])
    clock = iter([100,145])
    monkeypatch.setattr(studio_sources, 'time', SimpleNamespace(time=time.time, monotonic=lambda:next(clock)))
    result = studio._collect_sources(studio.store.get(tid), job)
    assert len(calls) == 1 and not result.get('stopped')
    finish(studio, job, result)
    state = studio.store.get(tid)
    assert state['source_acquisition']['execution_seconds'] == 45
    assert not state['source_acquisition'].get('hold')


def test_failed_search_also_consumes_actual_execution_time(tmp_path, monkeypatch):
    from hotpost import source_finder, studio_sources
    studio, tid, folder = task(tmp_path)
    job = studio.store.claim('sources')
    def fail(*a, **k):
        raise TimeoutError('external search timed out')
    monkeypatch.setattr(source_finder, 'find_sources', fail)
    clock = iter([100,160])
    monkeypatch.setattr(studio_sources, 'time', SimpleNamespace(time=time.time, monotonic=lambda:next(clock)))
    with pytest.raises(TimeoutError):
        studio._collect_sources(studio.store.get(tid), job)
    assert studio.store.get(tid)['source_acquisition']['execution_seconds'] == 60
