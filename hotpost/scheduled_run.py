"""Windows 예약 수집: 작업 디렉터리와 UTF-8 로그를 고정한다."""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime
from .config import ROOT, load_settings


def main() -> int:
    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with (settings.data_dir / 'daily_collect.log').open('a', encoding='utf-8') as log:
        log.write(f'\n[{datetime.now().astimezone().isoformat()}] scheduled collection started\n')
        log.flush()
        from .storage import Storage
        for attempt in range(2):
            started = int(time.time())
            result = subprocess.run([sys.executable, '-u', '-X', 'utf8', '-m', 'hotpost', 'run', '--acquire'], cwd=ROOT,
                                   stdout=log, stderr=subprocess.STDOUT, check=False,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            store = Storage(settings.db_path)
            try:
                last = store.last_run() or {}
            finally:
                store.close()
            retryable = (last.get('started_at', 0) >= started and
                         last.get('stop_reason') in {'network_timeout', 'server_error', 'profile_busy'})
            if result.returncode != 1 or not retryable or attempt == 1:
                break
            log.write(f'[{datetime.now().astimezone().isoformat()}] transient failure; retry once in 300s\n')
            log.flush()
            time.sleep(300)
        log.write(f'[{datetime.now().astimezone().isoformat()}] scheduled collection finished exit_code={result.returncode}\n')
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
