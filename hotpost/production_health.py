"""Read-only connection/runtime checks. Never starts a model or a service."""
import json
import subprocess

import requests

from .studio_adapter import StudioAdapter
from .voicebench_adapter import VoiceBenchAdapter


def check(settings):
    checks = {}
    endpoints = [
        ('studio', settings.studio_url.rstrip('/') + '/api/status',
         lambda: StudioAdapter(settings).headers()),
        ('voicebench', settings.voicebench_url.rstrip('/') + '/v1/health',
         lambda: VoiceBenchAdapter(settings)._headers()),
    ]
    with requests.Session() as session:
        session.trust_env = False
        for name, url, headers in endpoints:
            try:
                response = session.get(url, headers=headers(), timeout=3, allow_redirects=False)
                checks[name] = {'ready': response.status_code == 200,
                                'message': '연결됨' if response.status_code == 200 else f'HTTP {response.status_code}'}
            except (OSError, RuntimeError, requests.RequestException):
                checks[name] = {'ready': False, 'message': '서비스 주소·실행 상태·연결 키를 확인하세요.'}
    try:
        result = subprocess.run([str(settings.auto_capcut_python), '-X', 'utf8',
                                 '-m', 'auto_capcut.doctor'], cwd=str(settings.auto_capcut_root),
                                capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=20, check=False)
        doctor = json.loads(result.stdout)
        checks['editor'] = {'ready': bool(doctor['ready']),
                            'message': '편집 준비됨' if doctor['ready'] else
                            ('CapCut을 종료하세요.' if doctor.get('capcut_running') else '\n'.join(doctor.get('errors', [])))}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        checks['editor'] = {'ready': False, 'message': 'auto_capcut의 Python·패키지·실행 경로를 확인하세요.'}
    return {'ready': all(item['ready'] for item in checks.values()), 'checks': checks}
