"""Local-only regression checks for the Windows CLI and dashboard API."""
import subprocess
import sys

import pytest

import hotpost.source_finder as source_finder

from hotpost.config import ROOT, Settings


@pytest.mark.parametrize("fail", [False, True])
def test_collection_lock_excludes_other_process_and_releases(tmp_path, monkeypatch, fail):
    from hotpost import cli

    settings = Settings(data_dir=tmp_path)
    child = """
import sys
from pathlib import Path
from hotpost import cli
from hotpost.config import Settings
cli._cmd_run_locked = lambda *_: 42
sys.exit(cli.cmd_run(Settings(data_dir=Path(sys.argv[1])), None))
"""

    def probe():
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-c", child, str(tmp_path)],
            cwd=ROOT, capture_output=True, timeout=15,
        ).returncode

    def collect_stub(*_):
        assert probe() == 3
        if fail:
            raise RuntimeError("test collection failure")
        return 0

    monkeypatch.setattr(cli, "_cmd_run_locked", collect_stub)
    if fail:
        with pytest.raises(RuntimeError, match="test collection failure"):
            cli.cmd_run(settings, None)
    else:
        assert cli.cmd_run(settings, None) == 0
    assert probe() == 42


def test_non_macos_schedule_status_does_not_launch_programs(monkeypatch):
    from hotpost import scheduler

    monkeypatch.setattr(sys, "platform", "linux")

    def unexpected(*args, **kwargs):
        pytest.fail("Non-macOS status must not launch launchctl")

    monkeypatch.setattr(scheduler.subprocess, "run", unexpected)
    status = scheduler.schedule_status()
    assert status["installed"] is False
    assert status["loaded"] is False
    assert status["supported"] is False


def test_server_can_bind_multiple_explicit_interfaces(tmp_path):
    from hotpost.server import serve_many

    settings = Settings(data_dir=tmp_path / "data", web_dir=ROOT / "web",
                        influencer_file=tmp_path / "missing.txt")
    servers = serve_many(settings, ["127.0.0.1", "127.0.0.2", "127.0.0.1"], 0)
    try:
        assert [server.server_address[0] for server in servers] == ["127.0.0.1", "127.0.0.2"]
    finally:
        for server in servers:
            server.server_close()


def test_virtualenv_tool_is_found_beside_python(tmp_path, monkeypatch):
    python = tmp_path / "python.exe"
    tool = tmp_path / "yt-dlp.exe"
    python.touch()
    tool.touch()
    monkeypatch.setattr(source_finder.shutil, "which", lambda _name: None)
    monkeypatch.setattr(source_finder.sys, "executable", str(python))
    assert source_finder._executable("yt-dlp") == str(tool)


def test_bilibili_download_uses_short_timeout(tmp_path, monkeypatch):
    candidate = source_finder.Candidate(
        url="https://www.bilibili.com/video/BV1example",
        provider="browser-search",
        original_url="https://www.bilibili.com/video/BV1example",
    )
    monkeypatch.setattr(source_finder, "_executable", lambda _name: "yt-dlp.exe")

    def timeout_stub(_command, *, timeout):
        assert timeout == 35
        raise subprocess.TimeoutExpired("yt-dlp", timeout)

    monkeypatch.setattr(source_finder, "_run", timeout_stub)
    assert source_finder.download_candidate(candidate, tmp_path, 1, 100, None) is None
    assert "35" in candidate.error
