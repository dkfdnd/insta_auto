"""Bound browser hangs in an owned subprocess and retain completed search results."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid


def _stop_owned_process(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == 'nt': process.kill()
        else: os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def run_bounded(command, payload, checkpoint, timeout, progress=None):
    checkpoint = Path(checkpoint)
    result = {'candidates': [], 'terms': [], 'notes': [], 'searches': []}
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
    with checkpoint.with_suffix('.stderr.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log,
                                   text=True, encoding='utf-8', cwd=Path(__file__).resolve().parents[1], **options)
        last_message = None
        expired = False
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False))
            process.stdin.close()
            deadline = time.monotonic() + timeout
            while True:
                try:
                    snapshot = json.loads(checkpoint.read_text(encoding='utf-8'))
                    result = {key: snapshot.get(key, []) for key in result}
                    message = snapshot.get('message')
                    if message and message != last_message and progress:
                        progress(message)
                    last_message = message
                except (OSError, ValueError):
                    pass
                if process.poll() is not None:
                    break
                if time.monotonic() >= deadline:
                    expired = True
                    break
                time.sleep(.25)
        finally:
            _stop_owned_process(process)
        try:
            snapshot = json.loads(checkpoint.read_text(encoding='utf-8'))
            result = {key: snapshot.get(key, []) for key in result}
        except (OSError, ValueError):
            pass
        if expired:
            result['notes'].append(f'브라우저 검색 {timeout}초 제한: 완료된 검색 결과를 보존하고 다운로드 단계로 계속')
            result['searches'].append({'provider': 'browser-worker', 'query': last_message or '',
                                      'language': '', 'status': 'timeout', 'candidates': 0})
        elif process.returncode:
            result['notes'].append(f'브라우저 검색 프로세스 종료({process.returncode}): 저장된 중간 결과 사용')
    return result


def isolated_search(settings, frames, queries, limit, debug_dir, previous_searches=None, progress=None):
    debug_dir = Path(debug_dir)
    debug_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = debug_dir / f'search-checkpoint-{uuid.uuid4().hex}.json'
    names = ('source_browser_search', 'source_browser_headless', 'source_browser_frames',
             'source_browser_captcha_wait', 'source_browser_search_interval',
             'source_browser_block_cooldown', 'source_queries_per_platform', 'source_candidates_per_platform',
             'source_tiktok_min_usable')
    public_settings = {name: getattr(settings, name) for name in names}
    public_settings['data_dir'] = str(settings.data_dir.resolve())
    payload = {'settings': public_settings, 'frames': [str(p.resolve()) for p in frames],
               'queries': queries, 'limit': limit, 'debug_dir': str(debug_dir.resolve()),
               'checkpoint': str(checkpoint.resolve()), 'previous_searches': previous_searches or []}
    timeout = max(15, settings.source_browser_timeout)
    if not frames: timeout = min(timeout, 180)
    python = Path(sys.executable)
    if os.name == 'nt' and python.with_name('python.exe').is_file():
        python = python.with_name('python.exe')
    return run_bounded([str(python), '-X', 'utf8', '-m', 'hotpost.source_browser_worker'],
                       payload, checkpoint, timeout, progress)


def main():
    from .browser_search import BrowserSearcher
    from .config import Settings
    from .editing_adapter import _atomic_json
    payload = json.load(sys.stdin)
    payload['settings']['data_dir'] = Path(payload['settings']['data_dir'])
    searcher = BrowserSearcher(Settings(**payload['settings']), Path(payload['debug_dir']))
    searcher.previous_searches = payload['previous_searches']
    target = Path(payload['checkpoint'])
    def checkpoint(message):
        _atomic_json(target, {'message': message, 'candidates': [*searcher.visual_candidates, *searcher.candidates],
                             'terms': searcher.terms, 'notes': searcher.notes, 'searches': searcher.searches})
    searcher.progress = checkpoint
    try:
        result = searcher.run([Path(p) for p in payload['frames']], payload['queries'], payload['limit'])
        _atomic_json(target, {**result, 'message': '브라우저 검색 완료'})
    except Exception as exc:
        searcher.notes.append(f'브라우저 검색 중단: {type(exc).__name__}')
        checkpoint('브라우저 중간 결과 저장')


if __name__ == '__main__':
    main()
