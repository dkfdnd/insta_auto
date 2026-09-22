from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.editing_adapter import (
    AutoCapcutAdapter, build_with_voicebench, script_from_transcript,
    selected_source_videos,
)


def _settings(tmp_path: Path) -> Settings:
    repo = tmp_path / "auto_capcut"
    runner = repo / "auto_capcut" / "job_runner.py"
    runner.parent.mkdir(parents=True)
    runner.touch()
    python = repo / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    return Settings(data_dir=tmp_path / "data", web_dir=tmp_path / "web",
                    auto_capcut_root=repo, auto_capcut_python=python)


def test_transcript_script_uses_speech_only(tmp_path):
    transcript = tmp_path / "transcript.json"
    transcript.write_text(json.dumps({
        "speech": [{"text": "실제 음성입니다"}, {"text": "두 번째 문장"}],
        "screen_text": [{"text": "화면 광고 문구"}],
    }, ensure_ascii=False), encoding="utf-8")
    target = script_from_transcript(transcript, tmp_path / "words.txt")
    assert target.read_text(encoding="utf-8") == "실제 음성입니다\n두 번째 문장\n"


def test_selected_sources_cannot_escape_job_directory(tmp_path):
    root = tmp_path / "source-job"
    root.mkdir()
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"candidates": [{
        "selected_for_zip": True, "downloaded_file": "../outside.mp4",
    }]}), encoding="utf-8")
    with pytest.raises(ValueError, match="outside"):
        selected_source_videos(manifest)


def test_adapter_passes_json_contract_and_accepts_blocked_result(tmp_path):
    settings = _settings(tmp_path)
    video = settings.data_dir / "source_jobs" / "clip.mp4"
    video.parent.mkdir(parents=True)
    video.touch()

    def fake_run(command, **kwargs):
        request_path = Path(command[command.index("--request") + 1])
        result_path = Path(command[command.index("--result") + 1])
        request = json.loads(request_path.read_text(encoding="utf-8"))
        result_path.write_text(json.dumps({
            "contract_version": "1.0", "job_id": request["job_id"],
            "status": "blocked", "error_code": "voice_required",
            "warnings": [],
        }), encoding="utf-8")
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="")

    result = AutoCapcutAdapter(settings, runner=fake_run).build(
        job_id="edit-001", video_paths=[video], draft_name="edit-001-v1")
    assert result["status"] == "blocked"
    assert result["error_code"] == "voice_required"


def test_adapter_rejects_assets_outside_data_root(tmp_path):
    settings = _settings(tmp_path)
    outside = tmp_path / "outside.mp4"
    outside.touch()
    with pytest.raises(ValueError, match="under"):
        AutoCapcutAdapter(settings).build(
            job_id="edit-001", video_paths=[outside], draft_name="edit-001-v1")


def test_workflow_synthesizes_spoken_script_before_capcut(tmp_path):
    settings = _settings(tmp_path)
    source_dir = settings.data_dir / "source_jobs" / "source-1"
    source_dir.mkdir(parents=True)
    video = source_dir / "clip.mp4"
    video.touch()
    manifest = source_dir / "manifest.json"
    manifest.write_text(json.dumps({"candidates": [{
        "selected_for_zip": True, "downloaded_file": "clip.mp4",
    }]}), encoding="utf-8")
    transcript_dir = settings.data_dir / "transcripts" / "transcript-1"
    transcript_dir.mkdir(parents=True)
    transcript = transcript_dir / "transcript.json"
    transcript.write_text(json.dumps({
        "speech": [{"text": "들리는 대사"}],
        "screen_text": [{"text": "읽기만 한 글자"}],
    }, ensure_ascii=False), encoding="utf-8")

    class Voice:
        def synthesize(self, text, output_path, progress=None):
            assert text == "들리는 대사\n"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"\0" * 32)
            return {"voicebench_request_id": 9, "status": "succeeded"}

    class CapCut:
        def build(self, **kwargs):
            assert kwargs["video_paths"] == [video]
            assert kwargs["voice_path"].is_file()
            assert kwargs["script_path"].read_text(encoding="utf-8") == "들리는 대사\n"
            return {"contract_version": "1.0", "job_id": kwargs["job_id"],
                    "status": "completed", "draft_path": "draft"}

    result = build_with_voicebench(
        settings, job_id="edit-001", manifest_path=manifest,
        transcript_path=transcript, draft_name="edit-001-v1",
        voicebench=Voice(), auto_capcut=CapCut(),
    )
    assert result["status"] == "completed"
    assert result["voicebench"]["voicebench_request_id"] == 9
