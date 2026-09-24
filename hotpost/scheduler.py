"""Windows 작업 스케줄러 / macOS launchd로 등록 계정 전체를 매일 수집한다."""
from __future__ import annotations

import os
import json
import plistlib
import subprocess
import sys
from pathlib import Path

from .config import ROOT, Settings

LABEL = "com.dkfdnd.hotpost.daily"
DEFAULT_HOUR = 7
DEFAULT_MINUTE = 0
WINDOWS_TASK = "HotpostDailyCollect"


def _windows_schedule(action: str, hour: int = DEFAULT_HOUR, minute: int = DEFAULT_MINUTE) -> dict:
    """현재 사용자의 일반 권한 작업. 경로와 입력은 코드에 삽입하지 않고 JSON으로 전달한다."""
    python = ROOT / '.venv' / 'Scripts' / 'pythonw.exe'
    if not python.is_file():
        python = ROOT / '.venv' / 'Scripts' / 'python.exe'
    if action == 'install' and not python.is_file():
        raise RuntimeError('.venv Python을 찾지 못했습니다.')
    script = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$c = [Console]::In.ReadToEnd() | ConvertFrom-Json
if ($c.action -eq 'install') {
    $a = New-ScheduledTaskAction -Execute $c.python -Argument '-X utf8 -m hotpost.scheduled_run' -WorkingDirectory $c.root
    $t = New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours($c.hour).AddMinutes($c.minute))
    $p = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
    $s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName $c.name -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null
} elseif ($c.action -eq 'uninstall') {
    Get-ScheduledTask -TaskName $c.name -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false
}
$task = Get-ScheduledTask -TaskName $c.name -ErrorAction SilentlyContinue
$h = $c.hour; $m = $c.minute
$last = $null; $next = $null; $result = $null
if ($task) {
    $at = [datetime]($task.Triggers | Select-Object -First 1).StartBoundary
    $h = $at.Hour; $m = $at.Minute
    $info = Get-ScheduledTaskInfo -TaskName $c.name
    if ($info.LastRunTime.Year -gt 2000) { $last = $info.LastRunTime.ToString('o') }
    if ($info.NextRunTime.Year -gt 2000) { $next = $info.NextRunTime.ToString('o') }
    $result = $info.LastTaskResult
}
@{installed=[bool]$task; loaded=([bool]$task -and $task.State -ne 'Disabled'); supported=$true;
  hour=$h; minute=$m; label=$c.name; path=$c.name; requires_login=$true;
  last_run=$last; next_run=$next; last_result=$result; timezone=(Get-TimeZone).Id} | ConvertTo-Json -Compress
'''
    import base64
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            input=json.dumps({'action': action, 'name': WINDOWS_TASK, 'python': str(python),
                                              'root': str(ROOT), 'hour': hour, 'minute': minute}),
                            capture_output=True, encoding='utf-8', errors='replace', timeout=30, check=False,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError(f'Windows 작업 스케줄러 {action} 실패: {result.stderr[-500:]}')
    return json.loads(result.stdout.lstrip('\ufeff'))


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
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("올바른 시각을 입력하세요.")
    if sys.platform == 'win32':
        return _windows_schedule('install', hour, minute)
    if sys.platform != 'darwin':
        raise RuntimeError('Windows와 macOS에서 일정을 지원합니다.')
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
        return _windows_schedule('uninstall')
    if sys.platform != 'darwin':
        raise RuntimeError('Windows와 macOS에서 일정을 지원합니다.')
    target = launch_agent_path()
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(target)], capture_output=True, check=False)
    target.unlink(missing_ok=True)
    return schedule_status()


def schedule_status() -> dict:
    if sys.platform == 'win32':
        return _windows_schedule('status')
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
