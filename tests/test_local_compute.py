from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
import requests

from hotpost import local_compute
from hotpost.studio_adapter import StudioAdapter
from hotpost.studio_runtime.generation import GenerationMixin


@pytest.fixture
def settings():
    return SimpleNamespace(studio_url='http://127.0.0.1:18765',
                           voicebench_url='http://127.0.0.1:8765',
                           studio_timeout=2, voicebench_timeout=2)


def test_codex_rewrite_does_not_release_or_wait_for_voice_gpu(settings, monkeypatch):
    released = []
    monkeypatch.setattr(local_compute, 'release_idle_voice',
                        lambda s: released.append(s) or {'status': 'released'})
    monkeypatch.setattr('hotpost.studio_services.ensure_local', lambda *a: None)
    adapter = StudioAdapter(settings)
    monkeypatch.setattr(adapter, 'editorial', lambda *a, **kw: {'text':'Result'})
    monkeypatch.setattr('hotpost.studio_automation.rewrite',
                        lambda *a: adapter.editorial('Choose', {}))
    worker = GenerationMixin()
    worker.settings = settings
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(worker._rewrite, {}, {}).result(timeout=3) == {'text': 'Result'}
    assert released == []


def test_voice_and_script_work_are_serialized(settings, monkeypatch):
    entered, finish_voice, script_started = Event(), Event(), Event()
    releases = []
    monkeypatch.setattr(local_compute, 'release_idle_voice',
                        lambda s: releases.append('release') or {'status': 'released'})
    def voice():
        with local_compute.compute_slot(settings, 'voice'):
            entered.set()
            assert finish_voice.wait(timeout=2)
    def script():
        with local_compute.compute_slot(settings, 'script'):
            script_started.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        voice_future = pool.submit(voice)
        assert entered.wait(timeout=1)
        script_future = pool.submit(script)
        try:
            assert not script_started.wait(timeout=.05)
            assert releases == []
        finally:
            finish_voice.set()
        voice_future.result(timeout=2)
        script_future.result(timeout=2)
    assert script_started.is_set()
    assert releases == ['release']


def test_script_waits_for_server_queue_without_loading_a_model(settings, monkeypatch):
    clock = [0.0]
    outcomes = iter([{'status': 'busy'}, {'status': 'released'}])
    monkeypatch.setattr(local_compute, 'release_idle_voice', lambda s: next(outcomes))
    monkeypatch.setattr(local_compute.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(local_compute.time, 'sleep', lambda duration: clock.__setitem__(0, clock[0] + duration))
    with local_compute.compute_slot(settings, 'script'):
        assert clock[0] == 2


def test_busy_timeout_does_not_enter_model_work_and_lock_is_reusable(settings, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(local_compute, 'release_idle_voice', lambda s: {'status': 'busy'})
    monkeypatch.setattr(local_compute.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(local_compute.time, 'sleep', lambda duration: clock.__setitem__(0, clock[0] + duration))
    with pytest.raises(RuntimeError, match='음성 작업'):
        with local_compute.compute_slot(settings, 'script'):
            pytest.fail('A busy VoiceBench must not start a competing model')
    assert clock[0] == settings.studio_timeout
    monkeypatch.setattr(local_compute, 'release_idle_voice', lambda s: {'status': 'released'})
    with local_compute.compute_slot(settings, 'script'):
        pass


@pytest.mark.parametrize('error', [requests.ConnectionError(), requests.Timeout()])
def test_unavailable_optional_api_is_compatible(settings, monkeypatch, error):
    def fail(self):
        raise error
    monkeypatch.setattr(local_compute.VoiceBenchAdapter, 'release_idle', fail)
    with local_compute.compute_slot(settings, 'script'):
        pass


def test_cleanup_failure_does_not_invalidate_completed_audio(settings, monkeypatch):
    def fail(self):
        raise requests.HTTPError('Fixture unauthorized')
    monkeypatch.setattr(local_compute.VoiceBenchAdapter, 'release_idle', fail)
    assert local_compute.release_idle_voice(settings, best_effort=True)['status'] == 'unavailable'
    with pytest.raises(requests.HTTPError):
        local_compute.release_idle_voice(settings)


def test_remote_services_are_not_resource_managed(settings, monkeypatch):
    settings.studio_url = 'https://studio.example.test'
    monkeypatch.setattr(local_compute, 'release_idle_voice', lambda s: pytest.fail('Remote compute'))
    with local_compute.compute_slot(settings, 'script'):
        pass


def test_remote_voice_is_not_released(settings, monkeypatch):
    settings.voicebench_url = 'https://voice.example.test'
    monkeypatch.setattr(local_compute.VoiceBenchAdapter, 'release_idle', lambda s: pytest.fail('Remote voice'))
    assert local_compute.release_idle_voice(settings)['status'] == 'remote'
