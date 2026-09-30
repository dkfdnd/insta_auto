from types import SimpleNamespace

import pytest

from hotpost.studio_adapter import StudioAdapter


def test_editorial_reconnects_to_existing_job_and_follows_failed_retries(monkeypatch):
    adapter = StudioAdapter(SimpleNamespace(studio_timeout=30))
    calls = []
    responses = iter([
        {'id': 'first', 'state': 'failed'},
        {'id': 'second', 'state': 'failed'},
        {'id': 'third', 'state': 'running'},
        {'id': 'third', 'state': 'completed', 'result': {'value': {'text': '수정 대본'}}},
    ])
    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return next(responses)
    monkeypatch.setattr(adapter, 'request', request)
    monkeypatch.setattr('hotpost.studio_adapter.time.sleep', lambda _: None)
    assert adapter.editorial('Revise', {'script': '원문'}) == {'text': '수정 대본'}
    assert [c[1] for c in calls] == ['/api/editorial/jobs', '/api/jobs/first/retry',
                                    '/api/jobs/second/retry', '/api/jobs/third']
    assert calls[1][2]['headers']['Idempotency-Key'] != calls[2][2]['headers']['Idempotency-Key']


def test_editorial_surfaces_worker_error_without_retry_loop(monkeypatch):
    adapter = StudioAdapter(SimpleNamespace(studio_timeout=30))
    responses = iter([{'id': 'job', 'state': 'running'},
                      {'id': 'job', 'state': 'failed', 'error': '모델 준비 필요'}])
    monkeypatch.setattr(adapter, 'request', lambda *a, **kw: next(responses))
    monkeypatch.setattr('hotpost.studio_adapter.time.sleep', lambda _: None)
    with pytest.raises(RuntimeError, match='모델 준비 필요'):
        adapter.editorial('Revise', {})


def test_missing_cloud_key_uses_local_editorial_but_does_not_invent_research(monkeypatch):
    from hotpost.script_rewriter import _generate
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setattr('hotpost.studio_services.ensure_local', lambda *a: None)
    received = []
    def editorial(self, instruction, evidence, media):
        received.append((instruction, evidence, media))
        return {'passed': True}
    monkeypatch.setattr(StudioAdapter, 'editorial', editorial)
    assert _generate(SimpleNamespace(), 'Review', {'text': '대본'}) == {'passed': True}
    assert received == [('Review', {'text': '대본'}, None)]
    with pytest.raises(RuntimeError, match='웹 근거 조사'):
        _generate(SimpleNamespace(), 'Research', {}, research=True)
