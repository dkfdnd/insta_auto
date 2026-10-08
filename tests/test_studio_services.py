from types import SimpleNamespace

import pytest
import requests

from hotpost.config import Settings
from hotpost.studio_services import ensure_local

@pytest.fixture(autouse=True)
def fake_voice_key(monkeypatch):
    from hotpost.voicebench_adapter import VoiceBenchAdapter
    monkeypatch.setattr(VoiceBenchAdapter, '_api_key', lambda self: 'fixture-key')


def test_healthy_service_is_not_restarted(tmp_path, monkeypatch):
    from hotpost import studio_services as service
    monkeypatch.setattr(service.requests, 'Session', lambda: SimpleNamespace(
        get=lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {'service':'VoiceBench External TTS API'})))
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: pytest.fail('must not restart'))
    ensure_local(Settings(data_dir=tmp_path, voicebench_url='http://127.0.0.1:18767'), 'voice')


def test_wrong_service_never_launches_over_occupied_port(tmp_path, monkeypatch):
    from hotpost import studio_services as service
    monkeypatch.setattr(service.requests, 'Session', lambda: SimpleNamespace(
        get=lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {'service':'other-app'})))
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: pytest.fail('must not launch'))
    with pytest.raises(RuntimeError, match='설정'):
        ensure_local(Settings(data_dir=tmp_path), 'voice')


def test_remote_deployment_is_not_started_locally(monkeypatch):
    from hotpost import studio_services as service
    monkeypatch.setattr(service.requests, 'Session', lambda: pytest.fail('not a local service'))
    ensure_local(Settings(voicebench_url='http://10.9.0.20:18765'), 'voice')


def test_local_voice_launch_uses_own_environment(tmp_path, monkeypatch):
    from hotpost import studio_services as service
    root=tmp_path/'VoiceBench'
    python=root/'.venv'/('Scripts/python.exe' if service.os.name=='nt' else 'bin/python')
    python.parent.mkdir(parents=True); python.touch()
    attempts=[]; launches=[]
    def get(*a, **k):
        attempts.append(1)
        if len(attempts)==1: raise requests.ConnectionError()
        if len(attempts)==2: raise requests.ReadTimeout()
        return SimpleNamespace(status_code=200, json=lambda: {'service':'VoiceBench External TTS API'})
    monkeypatch.setattr(service.requests, 'Session', lambda: SimpleNamespace(get=get))
    monkeypatch.setattr(service.subprocess, 'Popen', lambda args,**kwargs: launches.append((args,kwargs)))
    monkeypatch.setattr(service.time, 'sleep', lambda _: None)
    ensure_local(Settings(data_dir=tmp_path, voicebench_root=root, voicebench_url='http://127.0.0.1:18767'), 'voice')
    args,kwargs=launches[0]
    assert args[0]==str(python) and args[-1]=='18767' and 'voicebench' in args
    assert kwargs['cwd']==root
    assert len(launches)==1 and len(attempts)==3


def test_slow_existing_service_is_awaited_without_duplicate_launch(tmp_path, monkeypatch):
    from hotpost import studio_services as service
    attempts=[]
    def get(*a, **k):
        attempts.append(1)
        if len(attempts)==1: raise requests.ReadTimeout()
        return SimpleNamespace(status_code=200, json=lambda: {'service':'VoiceBench External TTS API'})
    monkeypatch.setattr(service.requests, 'Session', lambda: SimpleNamespace(get=get))
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: pytest.fail('must not launch a duplicate'))
    ensure_local(Settings(data_dir=tmp_path), 'voice')
    assert len(attempts)==2


def test_unresponsive_service_stops_after_bounded_wait(tmp_path, monkeypatch):
    from hotpost import studio_services as service
    def get(*a, **k): raise requests.ReadTimeout()
    ticks=iter([0, 1, 61])
    monkeypatch.setattr(service.requests, 'Session', lambda: SimpleNamespace(get=get))
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: pytest.fail('must not launch a duplicate'))
    monkeypatch.setattr(service.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(service.time, 'sleep', lambda _: None)
    with pytest.raises(RuntimeError, match='제한 시간'):
        ensure_local(Settings(data_dir=tmp_path), 'voice')


def test_script_checks_cli_without_external_service(tmp_path,monkeypatch):
    from hotpost import studio_services as service
    from hotpost.writing import codex_writer
    monkeypatch.setattr(codex_writer, 'executable', lambda: 'codex.exe')
    monkeypatch.setattr(service.requests, 'Session', lambda: pytest.fail('external service'))
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: pytest.fail('legacy service'))
    ensure_local(Settings(data_dir=tmp_path), 'script')
