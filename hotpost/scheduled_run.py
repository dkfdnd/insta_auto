"""Windows 예약 수집: 작업 디렉터리와 UTF-8 로그를 고정한다."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from .config import ROOT, load_settings


def main() -> int:
    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with (settings.data_dir / 'daily_collect.log').open('a', encoding='utf-8') as log:
        log.write(f'\n[{datetime.now().astimezone().isoformat()}] scheduled collection started\n')
        log.flush()
        result = subprocess.run([sys.executable, '-u', '-X', 'utf8', '-m', 'hotpost', 'run'], cwd=ROOT,
                              stdout=log, stderr=subprocess.STDOUT, check=False,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        log.write(f'[{datetime.now().astimezone().isoformat()}] scheduled collection finished exit_code={result.returncode}\n')
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
