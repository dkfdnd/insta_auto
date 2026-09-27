from types import SimpleNamespace

import pytest
import requests

from hotpost.config import Settings
from hotpost.studio_services import ensure_local


def test_healthy_service_is_not_restarted(tmp_path, monkeypatch):
    from hotpost import studio_services as service
    monkeypatch.setattr(service.requests, 'Session', lambda: SimpleNamespace(
        get=lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {'service':'shortform-studio'})))
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: pytest.fail('must not restart'))
    ensure_local(Settings(data_dir=tmp_path, studio_url='http://127.0.0.1:18767'), 'script')


def test_wrong_service_never_launches_over_occupied_port(tmp_path, monkeypatch):
    from hotpost import studio_services as service
    monkeypatch.setattr(service.requests, 'Session', lambda: SimpleNamespace(
        get=lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {'service':'other-app'})))
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: pytest.fail('must not launch'))
    with pytest.raises(RuntimeError, match='설정'):
        ensure_local(Settings(data_dir=tmp_path), 'script')


def test_remote_deployment_is_not_started_locally(monkeypatch):
    from hotpost import studio_services as service
    monkeypatch.setattr(service.requests, 'Session', lambda: pytest.fail('not a local service'))
    ensure_local(Settings(studio_url='http://10.9.0.20:18765'), 'script')


def test_local_script_launch_uses_own_environment(tmp_path, monkeypatch):
    from hotpost import studio_services as service
    root=tmp_path/'script_auto'
    python=root/'.venv'/('Scripts/python.exe' if service.os.name=='nt' else 'bin/python')
    python.parent.mkdir(parents=True); python.touch()
    attempts=[]; launches=[]
    def get(*a, **k):
        attempts.append(1)
        if len(attempts)==1: raise requests.ConnectionError()
        return SimpleNamespace(status_code=200, json=lambda: {'service':'shortform-studio'})
    monkeypatch.setattr(service.requests, 'Session', lambda: SimpleNamespace(get=get))
    monkeypatch.setattr(service.subprocess, 'Popen', lambda args,**kwargs: launches.append((args,kwargs)))
    ensure_local(Settings(data_dir=tmp_path, studio_root=root, studio_url='http://127.0.0.1:18767'), 'script')
    args,kwargs=launches[0]
    assert args[0]==str(python) and args[-1]=='18767' and 'run.py' in args
    assert kwargs['cwd']==root
