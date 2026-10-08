"""Serialize this process's local model work without crossing service ownership.

VoiceBench owns its workers and decides whether they are safe to release. This
lock coordinates Hotpost workers, not independent clients or remote services.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from functools import wraps
from urllib.parse import urlsplit

import requests

from .voicebench_adapter import VoiceBenchAdapter


_lock = threading.RLock()
_current = threading.local()
_log = logging.getLogger(__name__)


def _is_local(url: str) -> bool:
    parsed = urlsplit(url)
    return (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost')
            and parsed.path in ('', '/'))


def release_idle_voice(settings, *, best_effort=False) -> dict:
    """Use the optional authenticated API; never stop workers from this client."""
    if not _is_local(getattr(settings, 'voicebench_url', '')):
        return {'status': 'remote', 'released': False}
    try:
        return VoiceBenchAdapter(settings).release_idle()
    except (requests.ConnectionError, requests.Timeout):
        # Older/offline services remain usable through the existing TTS API.
        return {'status': 'unavailable', 'released': False}
    except (requests.RequestException, RuntimeError, ValueError):
        if not best_effort:
            raise
        # A failed cleanup must not turn an already saved voice into a failure.
        _log.warning('VoiceBench idle resource release failed after synthesis.')
        return {'status': 'unavailable', 'released': False}


@contextmanager
def compute_slot(settings, kind: str):
    url = getattr(settings, 'studio_url' if kind == 'script' else 'voicebench_url', '')
    if not _is_local(url):
        yield
        return
    timeout = float(getattr(settings, 'studio_timeout' if kind == 'script' else 'voicebench_timeout', 7200))
    deadline = time.monotonic() + timeout
    if not _lock.acquire(timeout=max(0, timeout)):
        raise RuntimeError('로컬 AI 작업 대기 시간이 초과됐습니다. 실행 중인 작업을 확인하세요.')
    try:
        depth = getattr(_current, 'depth', 0)
        if depth == 0 and kind == 'script':
            while release_idle_voice(settings).get('status') == 'busy':
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError('VoiceBench 음성 작업이 진행 중이어서 로컬 AI를 시작하지 못했습니다.')
                time.sleep(min(2, remaining))
        _current.depth = depth + 1
        try:
            yield
        finally:
            _current.depth = depth
    finally:
        _lock.release()


def serialized_compute(kind: str):
    def decorate(method):
        @wraps(method)
        def run(self, *args, **kwargs):
            with compute_slot(self.settings, kind):
                return method(self, *args, **kwargs)
        return run
    return decorate
