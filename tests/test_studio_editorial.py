from types import SimpleNamespace
import pytest
from hotpost.config import Settings
from hotpost.studio_adapter import StudioAdapter


def test_editorial_reconnects_then_retries_failed_request_at_most_once(tmp_path,monkeypatch):
    adapter=StudioAdapter(Settings(data_dir=tmp_path));calls=[]
    monkeypatch.setattr(adapter.jobs,'start',lambda:None)
    monkeypatch.setattr(adapter,'_wait',lambda job:calls.append(job) or {'result':{'value':{}}})
    adapter.editorial('Revise',{})
    adapter.editorial('Revise',{})
    assert calls[0]['id']==calls[1]['id']
    adapter.jobs.update(calls[0]['id'],state='failed')
    adapter.editorial('Revise',{})
    assert calls[-1]['id']!=calls[0]['id']
    retry_id=calls[-1]['id']
    adapter.jobs.update(retry_id,state='failed')
    adapter.editorial('Revise',{})
    assert calls[-1]['id']==retry_id


def test_editorial_surfaces_worker_error_without_retry_loop(monkeypatch):
    adapter=StudioAdapter(SimpleNamespace(studio_timeout=30))
    responses=iter([{'id':'job','state':'running'}, {'id':'job','state':'failed','error':'로그인 필요'}])
    monkeypatch.setattr(adapter,'get',lambda _:next(responses))
    monkeypatch.setattr('hotpost.studio_adapter.time.sleep',lambda _:None)
    with pytest.raises(RuntimeError,match='로그인 필요'):adapter._wait({'id':'job'})


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
    with pytest.raises(RuntimeError, match='웹 검색'):
        _generate(SimpleNamespace(), 'Research', {}, research=True)
