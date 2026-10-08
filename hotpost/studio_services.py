"""Start configured local services through their own entrypoints and environments."""
from __future__ import annotations

import os
import subprocess
import time
from urllib.parse import urlsplit

import requests


def ensure_local(settings, kind):
    if kind == 'script':
        from .writing.codex_writer import executable
        executable()
        return
    url = settings.voicebench_url
    parsed = urlsplit(url)
    # Remote deployments remain managed by their owner.
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.path not in ('', '/'):
        return
    root = settings.voicebench_root
    session = requests.Session()
    session.trust_env = False
    headers = {}
    environment = os.environ.copy()
    from .voicebench_adapter import VoiceBenchAdapter
    key = VoiceBenchAdapter(settings)._api_key()
    headers['Authorization'] = 'Bearer ' + key
    environment['VOICEBENCH_EXTERNAL_API_KEY'] = key
    path = '/v1/health'
    expected = 'VoiceBench External TTS API'

    def ready():
        try:
            response = session.get(url.rstrip('/') + path, headers=headers, timeout=3, allow_redirects=False)
        except requests.Timeout:
            # A cold service can accept the connection before its startup has
            # finished. Keep waiting without launching another process.
            return None
        except requests.ConnectionError:
            return False
        if response.status_code != 200 or response.json().get('service') != expected:
            raise RuntimeError(f'{kind} 연결 주소의 서비스 또는 인증 설정을 확인하세요.')
        return True

    initial = ready()
    if initial:
        return
    if initial is False:
        python = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        if not python.is_file():
            raise RuntimeError(f'{kind} 서비스 실행 환경이 없습니다. 해당 프로젝트의 설치 절차를 완료하세요.')
        port = str(parsed.port or 80)
        args = ['-m', 'voicebench', '--host', '127.0.0.1', '--port', port]
        with (settings.data_dir / f'{kind}-service.log').open('a', encoding='utf-8') as log:
            subprocess.Popen([str(python), '-X', 'utf8', *args], cwd=root, env=environment,
                             stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if ready():
            return
        time.sleep(1)
    raise RuntimeError(f'{kind} 서비스가 제한 시간 안에 준비되지 않았습니다. 서비스 실행 상태를 확인한 뒤 제작실에서 재시도하세요.')
