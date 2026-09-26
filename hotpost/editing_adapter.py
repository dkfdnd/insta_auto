"""Loose-coupled adapter from insta_auto assets to auto_capcut JSON jobs."""
from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
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


def selected_source_videos(
    manifest_path: Path, *, allow_unclassified: bool = False,
) -> list[Path]:
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
        quality = str(item.get("source_quality") or "unknown")
        if quality == "edited-with-text":
            raise ValueError("Selected source contains a detected text overlay.")
        if quality == "unknown" and not allow_unclassified:
            raise ValueError(
                "Selected source overlay quality is unclassified; manual review "
                "is required before final editing."
            )
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

    def export(self, *, job_id: str, draft_name: str, draft_path: Path) -> dict:
        if not _JOB_ID.fullmatch(job_id):
            raise ValueError("Invalid export job ID")
        job_dir = self.settings.editing_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        request_path, result_path = job_dir / "export-request.json", job_dir / "export-result.json"
        output = job_dir / "shorts.mp4"
        request = {"job_id": job_id, "draft_name": draft_name, "draft_path": str(draft_path.resolve()),
                   "output_path": str(output.resolve())}
        _atomic_json(request_path, request)
        command = [str(self.settings.auto_capcut_python.resolve()), "-X", "utf8", "-m", "auto_capcut.export_runner",
                   "--request", str(request_path), "--result", str(result_path)]
        proc = self.runner(command, cwd=str(self.settings.auto_capcut_root), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=1500, check=False)
        (job_dir / "export.log").write_text((proc.stdout or "") + (proc.stderr or ""), encoding="utf-8")
        if not result_path.is_file():
            raise RuntimeError("CapCut 내보내기 결과 응답이 없습니다.")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("job_id") != job_id or result.get("status") != "completed":
            raise RuntimeError(result.get("message") or "CapCut 내보내기가 완료되지 않았습니다.")
        if not output.is_file() or output.stat().st_size < 1024 or not result.get("verified"):
            raise RuntimeError("내보낸 영상 파일이 검증되지 않았습니다.")
        return {**result, "video_path": str(output)}

    def _asset(self, value: Path | str, label: str) -> Path:
        path = Path(value).expanduser().resolve(strict=True)
        data_root = self.settings.data_dir.resolve()
        if not path.is_file() or not path.is_relative_to(data_root):
            raise ValueError(f"{label} must be a file under {data_root}.")
        return path

    def build(self, *, job_id: str, video_paths: list[Path | str],
              draft_name: str, voice_path: Path | str | None = None,
              script_path: Path | str | None = None,
              whisper_model: str = "small",
              video_labels: list[str] | None = None,
              audio_profile: str = "recorded_voice",
              narration_speed: float = 1.0, edit_style: str = "house",
              source_ranges: list | None = None,
              export_profile: str = "standard",
              thumbnail: dict | None = None,
              watermark_masks: list[dict] | None = None,
              editorial_plan: dict | None = None) -> dict:
        if not _JOB_ID.fullmatch(job_id):
            raise ValueError("job_id contains unsupported characters.")
        if not video_paths:
            raise ValueError("At least one source video is required.")
        videos = [self._asset(path, "video") for path in video_paths]
        labels = video_labels or [path.stem for path in videos]
        if len(labels) != len(videos) or not all(
                isinstance(label, str) and label.strip() for label in labels):
            raise ValueError("video_labels must match video_paths.")
        voice = self._asset(voice_path, "voice") if voice_path else None
        script = self._asset(script_path, "script") if script_path else None
        if thumbnail is not None:
            if not isinstance(thumbnail, dict):
                raise ValueError("thumbnail must be an object")
            thumbnail = {**thumbnail, "image_path": str(self._asset(
                thumbnail.get("image_path", ""), "thumbnail"))}
        version = "1.1" if thumbnail is not None or watermark_masks is not None else CONTRACT_VERSION
        if editorial_plan is not None:
            version = "1.2"
        if export_profile not in {"standard", "free"}:
            raise ValueError("Unsupported export profile")
        if export_profile == "free":
            version = "1.3"
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
            "contract_version": version,
            "job_id": job_id,
            "video_paths": [str(path) for path in videos],
            "video_labels": labels,
            "voice_path": str(voice) if voice else None,
            "script_path": str(script) if script else None,
            "draft_name": draft_name,
            "whisper_model": whisper_model,
            "audio_profile": audio_profile,
            "narration_speed": narration_speed,
            'edit_style': edit_style,
            'source_ranges': source_ranges if source_ranges is not None else [None] * len(videos),
            'script_sha256': hashlib.sha256(script.read_bytes()).hexdigest() if script else None,
        }
        if version in {"1.1", "1.2", "1.3"}:
            request.update(thumbnail=thumbnail, watermark_masks=watermark_masks or [])
        if export_profile == "free":
            request["export_profile"] = "free"
        if editorial_plan is not None:
            request["editorial_plan"] = editorial_plan
        _atomic_json(request_path, request)
        command = [str(python), "-m", "auto_capcut.job_runner",
                   "--request", str(request_path), "--result", str(result_path)]
        child_env = os.environ.copy()
        child_env.setdefault("PYTHONUTF8", "1")
        child_env.setdefault("PYTHONIOENCODING", "utf-8")
        try:
            proc = self.runner(command, cwd=str(repo), capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               env=child_env,
                               timeout=self.settings.auto_capcut_timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            result = {
                "contract_version": version,
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
        if result.get("contract_version") != version \
                or result.get("job_id") != job_id:
            raise RuntimeError("auto_capcut returned an incompatible result.")
        if result.get("status") not in {"completed", "blocked", "failed"}:
            raise RuntimeError("auto_capcut returned an unknown status.")
        return result


def build_with_voicebench(
    settings: Settings, *, job_id: str, manifest_path: Path,
    transcript_path: Path, draft_name: str,
    approved_script_path: Path | None = None,
    video_labels: list[str] | None = None,
    allow_unclassified_sources: bool = False,
    narration_speed: float = 1.12,
    thumbnail: dict | None = None,
    watermark_masks: list[dict] | None = None,
    editorial_plan: dict | None = None,
    voicebench=None, auto_capcut: AutoCapcutAdapter | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> dict:
    """Orchestrate artifacts while keeping both subsystems behind adapters."""
    from .voicebench_adapter import VoiceBenchAdapter

    progress = progress or (lambda _message, _percent: None)
    job_dir = settings.editing_dir / job_id
    script_path = job_dir / "words.txt"
    if approved_script_path is None:
        raise ValueError("rewritten_script_required: PersonalProject1에서 재가공한 대본을 선택하세요.")
    else:
        approved = approved_script_path.expanduser().resolve(strict=True)
        data_root = settings.data_dir.resolve()
        if not approved.is_file() or not approved.is_relative_to(data_root):
            raise ValueError(f"approved script must be a file under {data_root}.")
        if not approved.read_text(encoding="utf-8").strip():
            raise ValueError("approved script is empty.")
        script_path.parent.mkdir(parents=True, exist_ok=True)
        if approved != script_path.resolve():
            shutil.copy2(approved, script_path)
    videos = selected_source_videos(
        manifest_path, allow_unclassified=allow_unclassified_sources)
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
        video_labels=video_labels,
        audio_profile="clean_tts",
        narration_speed=narration_speed,
        thumbnail=thumbnail,
        watermark_masks=watermark_masks,
        editorial_plan=editorial_plan,
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
