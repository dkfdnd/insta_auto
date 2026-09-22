"""macOS launchd로 등록 계정 전체를 매일 수집한다."""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from .config import ROOT, Settings

LABEL = "com.dkfdnd.hotpost.daily"
DEFAULT_HOUR = 7
DEFAULT_MINUTE = 0


def launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def launch_agent_config(settings: Settings, hour: int = DEFAULT_HOUR, minute: int = DEFAULT_MINUTE) -> dict:
    python = ROOT / ".venv" / "bin" / "python"
    log = settings.data_dir / "daily_collect.log"
    return {
        "Label": LABEL,
        "ProgramArguments": [str(python), "-m", "hotpost", "run"],
        "WorkingDirectory": str(ROOT),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            "PYTHONUNBUFFERED": "1",
        },
    }


def install_schedule(settings: Settings, hour: int = DEFAULT_HOUR, minute: int = DEFAULT_MINUTE) -> dict:
    if not (ROOT / ".venv" / "bin" / "python").is_file():
        raise RuntimeError(".venv Python을 찾지 못했습니다. 먼저 의존성을 설치하세요.")
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("올바른 시각을 입력하세요.")
    target = launch_agent_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".plist.tmp")
    temp.write_bytes(plistlib.dumps(launch_agent_config(settings, hour, minute), sort_keys=False))
    temp.replace(target)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(target)], capture_output=True, check=False)
    result = subprocess.run(["launchctl", "bootstrap", domain, str(target)], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"LaunchAgent 등록 실패: {(result.stderr or result.stdout).strip()[:240]}")
    subprocess.run(["launchctl", "enable", f"{domain}/{LABEL}"], capture_output=True, check=False)
    return schedule_status()


def uninstall_schedule() -> dict:
    target = launch_agent_path()
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(target)], capture_output=True, check=False)
    target.unlink(missing_ok=True)
    return schedule_status()


def schedule_status() -> dict:
    if sys.platform != "darwin":
        return {"installed": False, "loaded": False, "supported": False,
                "hour": DEFAULT_HOUR, "minute": DEFAULT_MINUTE,
                "label": LABEL, "path": ""}
    target = launch_agent_path()
    domain = f"gui/{os.getuid()}"
    loaded = subprocess.run(["launchctl", "print", f"{domain}/{LABEL}"],
                            capture_output=True, check=False).returncode == 0
    hour, minute = DEFAULT_HOUR, DEFAULT_MINUTE
    if target.is_file():
        try:
            interval = plistlib.loads(target.read_bytes()).get("StartCalendarInterval", {})
            hour, minute = int(interval.get("Hour", hour)), int(interval.get("Minute", minute))
        except (OSError, ValueError, plistlib.InvalidFileException):
            pass
    return {"installed": target.is_file(), "loaded": loaded, "hour": hour, "minute": minute,
            "label": LABEL, "path": str(target)}
