"""Loose-coupled adapter from insta_auto assets to auto_capcut JSON jobs."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable

from .config import Settings

CONTRACT_VERSION = "1.0"
_JOB_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def script_from_transcript(transcript_path: Path, target: Path) -> Path:
    """Create spoken-text-only words.txt; OCR is never promoted to speech."""
    data = json.loads(transcript_path.read_text(encoding="utf-8"))
    speech = data.get("speech")
    if not isinstance(speech, list):
        raise ValueError("Transcript JSON has no speech array.")
    lines = [str(item.get("text") or "").strip() for item in speech
             if isinstance(item, dict) and str(item.get("text") or "").strip()]
    if not lines:
        raise ValueError("Transcript contains no verified speech for subtitles.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def selected_source_videos(manifest_path: Path) -> list[Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parent.resolve()
    selected: list[Path] = []
    for item in manifest.get("candidates") or []:
        if not isinstance(item, dict) or not item.get("selected_for_zip"):
            continue
        relative = item.get("downloaded_file")
        if not isinstance(relative, str) or not relative:
            continue
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Source manifest contains a path outside its job.")
        if path.is_file():
            selected.append(path)
    if not selected:
        raise ValueError("Source manifest contains no selected local videos.")
    return selected


class AutoCapcutAdapter:
    def __init__(self, settings: Settings,
                 runner: Callable[..., subprocess.CompletedProcess] | None = None):
        self.settings = settings
        self.runner = runner or subprocess.run

    def _asset(self, value: Path | str, label: str) -> Path:
        path = Path(value).expanduser().resolve(strict=True)
        data_root = self.settings.data_dir.resolve()
        if not path.is_file() or not path.is_relative_to(data_root):
            raise ValueError(f"{label} must be a file under {data_root}.")
        return path

    def build(self, *, job_id: str, video_paths: list[Path | str],
              draft_name: str, voice_path: Path | str | None = None,
              script_path: Path | str | None = None,
              whisper_model: str = "small") -> dict:
        if not _JOB_ID.fullmatch(job_id):
            raise ValueError("job_id contains unsupported characters.")
        if not video_paths:
            raise ValueError("At least one source video is required.")
        videos = [self._asset(path, "video") for path in video_paths]
        voice = self._asset(voice_path, "voice") if voice_path else None
        script = self._asset(script_path, "script") if script_path else None
        python = self.settings.auto_capcut_python.resolve()
        repo = self.settings.auto_capcut_root.resolve()
        if not python.is_file():
            raise RuntimeError(f"auto_capcut Python was not found: {python}")
        if not (repo / "auto_capcut" / "job_runner.py").is_file():
            raise RuntimeError(f"auto_capcut job runner was not found: {repo}")

        job_dir = self.settings.editing_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        request_path = job_dir / "request.json"
        result_path = job_dir / "result.json"
        log_path = job_dir / "runner.log"
        request = {
            "contract_version": CONTRACT_VERSION,
            "job_id": job_id,
            "video_paths": [str(path) for path in videos],
            "voice_path": str(voice) if voice else None,
            "script_path": str(script) if script else None,
            "draft_name": draft_name,
            "whisper_model": whisper_model,
        }
        _atomic_json(request_path, request)
        command = [str(python), "-m", "auto_capcut.job_runner",
                   "--request", str(request_path), "--result", str(result_path)]
        try:
            proc = self.runner(command, cwd=str(repo), capture_output=True,
                               text=True, timeout=self.settings.auto_capcut_timeout,
                               check=False)
        except subprocess.TimeoutExpired as exc:
            result = {
                "contract_version": CONTRACT_VERSION,
                "job_id": job_id,
                "status": "failed",
                "error_code": "timeout",
                "message": f"auto_capcut exceeded {self.settings.auto_capcut_timeout}s",
                "warnings": [],
            }
            _atomic_json(result_path, result)
            raise RuntimeError(result["message"]) from exc
        log_path.write_text(
            (proc.stdout or "") + ("\n[stderr]\n" + proc.stderr if proc.stderr else ""),
            encoding="utf-8",
        )
        if not result_path.is_file():
            raise RuntimeError(
                f"auto_capcut exited with {proc.returncode} without result.json."
            )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("contract_version") != CONTRACT_VERSION \
                or result.get("job_id") != job_id:
            raise RuntimeError("auto_capcut returned an incompatible result.")
        if result.get("status") not in {"completed", "blocked", "failed"}:
            raise RuntimeError("auto_capcut returned an unknown status.")
        return result


def build_with_voicebench(
    settings: Settings, *, job_id: str, manifest_path: Path,
    transcript_path: Path, draft_name: str,
    voicebench=None, auto_capcut: AutoCapcutAdapter | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> dict:
    """Orchestrate artifacts while keeping both subsystems behind adapters."""
    from .voicebench_adapter import VoiceBenchAdapter

    progress = progress or (lambda _message, _percent: None)
    job_dir = settings.editing_dir / job_id
    script_path = script_from_transcript(transcript_path, job_dir / "words.txt")
    videos = selected_source_videos(manifest_path)
    voice_path = job_dir / "voice.wav"
    tts = (voicebench or VoiceBenchAdapter(settings)).synthesize(
        script_path.read_text(encoding="utf-8"), voice_path,
        progress=lambda message, percent: progress(message, min(55, percent // 2)),
    )
    progress("CapCut 프로젝트를 생성하는 중", 60)
    result = (auto_capcut or AutoCapcutAdapter(settings)).build(
        job_id=job_id,
        video_paths=videos,
        voice_path=voice_path,
        script_path=script_path,
        draft_name=draft_name,
    )
    return {
        **result,
        "voicebench": tts,
        "artifacts": {
            "script_path": str(script_path),
            "voice_path": str(voice_path),
            "video_paths": [str(path) for path in videos],
        },
    }
