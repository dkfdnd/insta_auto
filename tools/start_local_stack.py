"""Start this checkout's local services without collecting Instagram posts."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse
import webbrowser

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hotpost.config import load_settings
from hotpost.voicebench_adapter import VoiceBenchAdapter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--open-browser', action='store_true')
    args = parser.parse_args()
    # A long-running desktop app can retain PATH from before FFmpeg/Node setup.
    if os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
                user_path, _ = winreg.QueryValueEx(key, 'Path')
            os.environ['PATH'] += os.pathsep + os.path.expandvars(user_path)
        except FileNotFoundError:
            pass
    settings = load_settings()
    session = requests.Session()
    session.trust_env = False
    logs = settings.data_dir / 'local-services'
    logs.mkdir(exist_ok=True)

    def start(name, base, health, root, command, expected, headers=None, environment=None):
        address = urlparse(base)
        if address.scheme != 'http' or address.hostname not in {'127.0.0.1', 'localhost'}:
            raise ValueError(f'{name}: local startup requires a loopback HTTP URL')
        port = address.port or 80
        def running():
            try:
                response = session.get(base + health, headers=headers, timeout=2)
                return response.status_code == 200 and expected(response.json())
            except (requests.RequestException, ValueError):
                return False
        if running():
            print(f'{name}: {base} (already running)', flush=True)
            return
        with socket.socket() as probe:
            if probe.connect_ex((address.hostname, port)) == 0:
                raise RuntimeError(f'{name}: port {port} is occupied; existing process was preserved')
        if not Path(command[0]).is_file():
            raise FileNotFoundError(f'{name}: Python not found: {command[0]}')
        with (logs / f'{name}.log').open('ab') as log:
            process = subprocess.Popen(command, cwd=root, env=environment,
                stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f'{name}: exited; inspect {logs / (name + ".log")}')
            if running():
                print(f'{name}: {base}', flush=True)
                return
            time.sleep(.5)
        raise TimeoutError(f'{name}: startup not confirmed; process {process.pid} retained')

    python_name = 'Scripts/python.exe' if os.name == 'nt' else 'bin/python'
    script_url = settings.studio_url.rstrip('/')
    start('scripts', script_url, '/api/health', settings.studio_root,
          [str(settings.studio_root / '.venv' / python_name), '-X', 'utf8', '-u', 'run.py',
           '--port', str(urlparse(script_url).port or 80)],
          lambda value: value.get('service') == 'shortform-studio')
    voice_url = settings.voicebench_url.rstrip('/')
    voice = VoiceBenchAdapter(settings)
    headers = voice._headers()
    environment = os.environ.copy()
    environment['VOICEBENCH_EXTERNAL_API_KEY'] = voice._api_key()
    start('voice', voice_url, '/v1/health', settings.voicebench_root,
          [str(settings.voicebench_root / '.venv' / python_name), '-X', 'utf8', '-u',
           '-m', 'voicebench', '--host', '127.0.0.1', '--port', str(urlparse(voice_url).port or 80)],
          lambda value: value.get('service') == 'VoiceBench External TTS API', headers, environment)
    start('hotpost', 'http://127.0.0.1:8775', '/api/studio', ROOT,
          [sys.executable, '-X', 'utf8', '-u', '-m', 'hotpost', 'serve', '--no-browser'],
          lambda value: 'tasks' in value)
    response = session.get('http://127.0.0.1:8775/api/production-health', timeout=35)
    response.raise_for_status()
    health = response.json()
    print(json.dumps(health, ensure_ascii=False), flush=True)
    if args.open_browser:
        webbrowser.open('http://127.0.0.1:8775/')
    if not health.get('ready'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
