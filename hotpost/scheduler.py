"""Windows 작업 스케줄러 / macOS launchd로 매일 통계와 제작 자료를 수집한다."""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
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
        "ProgramArguments": [str(python), "-m", "hotpost", "run", "--acquire"],
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
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("올바른 시각을 입력하세요.")
    if sys.platform == 'win32':
        target = settings.data_dir / 'daily-task.xml'
        target.parent.mkdir(parents=True, exist_ok=True)
        if not (ROOT / '.venv' / 'Scripts' / 'python.exe').is_file():
            raise RuntimeError('먼저 Windows 실행 환경을 설치하세요.')
        target.write_text(windows_task_xml(hour, minute), encoding='utf-16')
        result = subprocess.run(['schtasks.exe', '/Create', '/TN', LABEL,
                                 '/XML', str(target), '/F'], capture_output=True,
                                text=True, errors='replace', check=False)
        if result.returncode:
            raise RuntimeError('Windows 예약 등록 실패: ' + result.stderr[:240])
        return schedule_status()
    if sys.platform != 'darwin':
        raise RuntimeError('이 OS의 예약 실행은 지원하지 않습니다.')
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
    if sys.platform == 'win32':
        subprocess.run(['schtasks.exe', '/Delete', '/TN', LABEL, '/F'],
                       capture_output=True, check=False)
        return schedule_status()
    if sys.platform != 'darwin':
        raise RuntimeError('이 OS의 예약 실행은 지원하지 않습니다.')
    target = launch_agent_path()
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(target)], capture_output=True, check=False)
    target.unlink(missing_ok=True)
    return schedule_status()


def schedule_status() -> dict:
    if sys.platform == 'win32':
        result = subprocess.run(['schtasks.exe', '/Query', '/TN', LABEL, '/XML'],
                                capture_output=True, text=True, errors='replace', check=False)
        base = {'installed': False, 'loaded': False, 'supported': True,
                'hour': DEFAULT_HOUR, 'minute': DEFAULT_MINUTE, 'label': LABEL, 'path': LABEL,
                'timezone': 'Asia/Seoul', 'requires_login': True}
        if result.returncode:
            return base
        root = ET.fromstring(result.stdout.lstrip('\ufeff'))
        boundary = root.findtext('.//{*}StartBoundary')
        moment = datetime.fromisoformat(boundary) if boundary else None
        enabled = root.findtext('.//{*}Settings/{*}Enabled', 'true') != 'false'
        return {**base, 'installed': True, 'loaded': enabled,
                'hour': moment.hour if moment else DEFAULT_HOUR,
                'minute': moment.minute if moment else DEFAULT_MINUTE}
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


def windows_task_xml(hour=DEFAULT_HOUR, minute=DEFAULT_MINUTE):
    """Interactive account keeps the owner's Instagram/browser sessions available."""
    namespace = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
    ET.register_namespace('', namespace)
    def child(parent, name, text=None, **attributes):
        node = ET.SubElement(parent, '{' + namespace + '}' + name, attributes)
        if text is not None:
            node.text = text
        return node
    root = ET.Element('{' + namespace + '}Task', {'version': '1.2'})
    triggers = child(root, 'Triggers')
    trigger = child(triggers, 'CalendarTrigger')
    now = datetime.now(timezone(timedelta(hours=9))).replace(hour=hour, minute=minute, second=0, microsecond=0)
    child(trigger, 'StartBoundary', now.isoformat())
    child(trigger, 'Enabled', 'true')
    child(child(trigger, 'ScheduleByDay'), 'DaysInterval', '1')
    principals = child(root, 'Principals')
    principal = child(principals, 'Principal', id='Author')
    user = os.environ.get('USERNAME', '')
    domain = os.environ.get('USERDOMAIN', '')
    child(principal, 'UserId', domain + '\\' + user if domain else user)
    child(principal, 'LogonType', 'InteractiveToken')
    child(principal, 'RunLevel', 'LeastPrivilege')
    options = child(root, 'Settings')
    child(options, 'MultipleInstancesPolicy', 'IgnoreNew')
    child(options, 'DisallowStartIfOnBatteries', 'false')
    child(options, 'StopIfGoingOnBatteries', 'false')
    child(options, 'StartWhenAvailable', 'true')
    child(options, 'Enabled', 'true')
    child(options, 'ExecutionTimeLimit', 'PT12H')
    action = child(child(root, 'Actions', Context='Author'), 'Exec')
    child(action, 'Command', str(ROOT / '.venv' / 'Scripts' / 'python.exe'))
    child(action, 'Arguments', '-X utf8 -m hotpost run --acquire')
    child(action, 'WorkingDirectory', str(ROOT))
    return '<?xml version="1.0" encoding="UTF-16"?>\n' + ET.tostring(root, encoding='unicode')
