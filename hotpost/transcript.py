"""실제 릴스 음성(Whisper)과 화면 글자(EasyOCR/Tesseract)를 시간별로 추출한다.

두 신호를 서로 다른 출처로 보존한다. 들리지 않는 내레이션이나 장면 설명은 만들지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from .config import Settings
from .source_finder import _download_reference, _post


def _run(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def _duration(video: Path) -> float:
    probe = shutil.which("ffprobe")
    if not probe:
        raise RuntimeError("ffprobe가 필요합니다.")
    result = _run([probe, "-v", "error", "-show_entries", "format=duration", "-of",
                   "default=nw=1:nk=1", str(video)], timeout=20)
    if result.returncode:
        raise RuntimeError("릴스 길이를 읽지 못했습니다.")
    return float(result.stdout.strip())


def _audio(video: Path, target: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg가 필요합니다.")
    result = _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
                   "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target)], timeout=120)
    return result.returncode == 0 and target.is_file() and target.stat().st_size > 32000


def _speech(settings: Settings, audio: Path,
            notes: list[str]) -> tuple[list[dict], str, str]:
    if sys.platform == "win32":
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            notes.append("faster-whisper가 설치되지 않아 음성 전사를 건너뛰었습니다.")
            return [], "", "unavailable"
        model_root = settings.source_model_dir / "faster-whisper"
        model_root.mkdir(parents=True, exist_ok=True)

        def transcribe(device: str, compute_type: str):
            model = WhisperModel(
                settings.transcript_faster_whisper_model,
                device=device,
                compute_type=compute_type,
                download_root=str(model_root),
            )
            return model.transcribe(
                str(audio), language=None, beam_size=5, vad_filter=True,
                condition_on_previous_text=False,
            )

        try:
            raw_segments, info = transcribe("cuda", "float16")
            engine = "faster-whisper-cuda"
            raw_segments = list(raw_segments)
        except Exception as exc:
            notes.append(
                f"faster-whisper GPU 전사를 사용할 수 없어 CPU로 전환했습니다: "
                f"{type(exc).__name__}"
            )
            raw_segments, info = transcribe("cpu", "int8")
            engine = "faster-whisper-cpu"
            raw_segments = list(raw_segments)
        segments = []
        for item in raw_segments:
            text = re.sub(r"\s+", " ", str(getattr(item, "text", "") or "")).strip()
            if text:
                segments.append({
                    "source": "speech",
                    "start": round(float(getattr(item, "start", 0) or 0), 2),
                    "end": round(float(getattr(item, "end", 0) or 0), 2),
                    "text": text,
                })
        return segments, str(getattr(info, "language", "") or ""), engine

    try:
        import mlx_whisper
        from huggingface_hub import snapshot_download
    except ImportError:
        notes.append("mlx-whisper가 설치되지 않아 음성 전사를 건너뛰었습니다.")
        return [], "", "unavailable"
    model_dir = settings.source_model_dir / "whisper-small-mlx-8bit"
    if not (model_dir / "weights.npz").is_file():
        snapshot_download(repo_id=settings.transcript_model, local_dir=str(model_dir),
                          allow_patterns=["config.json", "weights.npz"])
    result = mlx_whisper.transcribe(str(audio), path_or_hf_repo=str(model_dir),
                                    verbose=False, temperature=0.0,
                                    condition_on_previous_text=False)
    segments = []
    for item in result.get("segments", []):
        text = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
        if not text:
            continue
        no_speech = float(item.get("no_speech_prob") or 0)
        logprob = float(item.get("avg_logprob") or 0)
        if no_speech >= .6 and logprob < -1:
            continue
        segments.append({"source": "speech", "start": round(float(item.get("start") or 0), 2),
                         "end": round(float(item.get("end") or 0), 2), "text": text})
    return segments, str(result.get("language") or ""), "mlx-whisper"


def _ocr_text(frame: Path, tessdata: Path) -> str:
    tesseract = shutil.which("tesseract")
    if not tesseract:
        return ""
    languages = [name for name in ("eng", "kor", "chi_sim")
                 if (tessdata / f"{name}.traineddata").is_file()]
    if not languages:
        languages = ["eng"]
    args = [tesseract, str(frame), "stdout"]
    if all((tessdata / f"{name}.traineddata").is_file() for name in languages):
        args += ["--tessdata-dir", str(tessdata)]
    args += ["-l", "+".join(languages), "--psm", "11", "tsv"]
    try:
        result = _run(args, timeout=20)
    except subprocess.TimeoutExpired:
        return ""
    if result.returncode:
        return ""
    lines: dict[tuple[str, str, str], list[tuple[int, str]]] = {}
    for row in result.stdout.splitlines()[1:]:
        cols = row.split("\t", 11)
        if len(cols) < 12:
            continue
        try:
            confidence = float(cols[10]); top = int(cols[7])
        except ValueError:
            continue
        word = cols[11].strip()
        if confidence < 40 or not re.search(r"[0-9A-Za-z가-힣\u3400-\u9fff]", word):
            continue
        lines.setdefault((cols[2], cols[3], cols[4]), []).append((top, word))
    result_lines = []
    for words in lines.values():
        text = " ".join(word for _, word in words)
        if len(re.sub(r"\W", "", text, flags=re.UNICODE)) >= 3:
            result_lines.append((min(top for top, _ in words), text))
    usable = []
    for _, text in sorted(result_lines):
        hangul = len(re.findall(r"[가-힣]", text))
        han = len(re.findall(r"[\u3400-\u9fff]", text))
        latin = re.findall(r"[A-Za-z]{3,}", text)
        if hangul >= 4 or han >= 4 or (len(latin) >= 2 and sum(map(len, latin)) >= 10):
            usable.append(text)
    return " / ".join(usable)[:1000]


def _easyocr_text(frame: Path, reader) -> str:
    from PIL import Image
    with Image.open(frame) as image:
        height = image.height
    rows = []
    for box, raw, confidence in reader.readtext(frame.read_bytes(), detail=1):
        text = re.sub(r"\s+", " ", raw).strip()
        top = min(point[1] for point in box)
        center = sum(point[1] for point in box) / len(box)
        if not 0.15 <= center / height <= 0.85:
            continue  # 광고 라벨·제작자 워터마크 등 화면 가장자리 제외
        hangul = len(re.findall(r"[가-힣]", text))
        latin = re.findall(r"[A-Za-z]{3,}", text)
        if (hangul >= 3 and confidence >= .25) or (len(latin) >= 2 and confidence >= .6):
            rows.append((top, text))
    return " / ".join(text for _, text in sorted(rows))[:1000]


def collapse_screen_samples(samples: list[tuple[float, str]], interval: float, duration: float) -> list[dict]:
    """연속 프레임에서 동일한 화면 문구를 하나의 시간 구간으로 합친다."""
    out: list[dict] = []
    last_visible_start: float | None = None
    for start, raw in samples:
        text = re.sub(r"\s+", " ", raw).strip()
        if not text:
            last_visible_start = None
            continue
        normalized = re.sub(r"[^\w가-힣\u3400-\u9fff]", "", text).lower()
        if out and last_visible_start is not None and out[-1]["_key"] == normalized and start - last_visible_start <= interval * 1.5:
            out[-1]["end"] = round(min(duration, start + interval), 2)
        else:
            out.append({"source": "screen_text", "start": round(start, 2),
                        "end": round(min(duration, start + interval), 2), "text": text, "_key": normalized})
        last_visible_start = start
    for item in out:
        item.pop("_key")
    return out


def _screen_text(settings: Settings, video: Path, root: Path, duration: float,
                 notes: list[str]) -> list[dict]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        notes.append("ffmpeg가 없어 화면 글자를 건너뛰었습니다.")
        return []
    fps = max(.25, min(3.0, settings.transcript_ocr_fps))
    interval = 1 / fps
    frames_dir = root / "ocr_frames"
    frames_dir.mkdir(exist_ok=True)
    result = _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(video),
                   "-vf", f"fps={fps:.3f},scale=720:-2", "-q:v", "3",
                   str(frames_dir / "frame_%04d.jpg")], timeout=120)
    if result.returncode:
        notes.append("화면 프레임 추출에 실패했습니다.")
        return []
    reader = None
    try:
        import easyocr
        reader = easyocr.Reader(["ko", "en"], gpu=True,
                                model_storage_directory=str(settings.source_model_dir / "easyocr"))
    except Exception as exc:
        notes.append(f"EasyOCR를 사용할 수 없어 Tesseract로 전환했습니다: {type(exc).__name__}")
    if reader is None and not shutil.which("tesseract"):
        notes.append("OCR 도구가 없어 화면 글자를 건너뛰었습니다.")
        return []
    samples = []
    for index, frame in enumerate(sorted(frames_dir.glob("frame_*.jpg"))):
        text = _easyocr_text(frame, reader) if reader is not None else _ocr_text(frame, settings.source_tessdata_dir)
        samples.append((index * interval, text))
    return collapse_screen_samples(samples, interval, duration)


def _clock(seconds: float) -> str:
    value = int(max(0, seconds))
    return f"{value // 60:02d}:{value % 60:02d}"


def extract_transcript(settings: Settings, shortcode: str,
                       progress: Callable[[str, int], None] | None = None) -> dict:
    progress = progress or (lambda _message, _percent: None)
    post = _post(settings, shortcode)
    if not post.is_video:
        raise ValueError("릴스/동영상만 대본을 추출할 수 있습니다.")
    root = settings.transcript_dir / f"{shortcode}-{time.time_ns()}"
    root.mkdir(parents=True)
    notes = ["자동 전사와 OCR은 오류가 있을 수 있으므로 원본 영상과 대조하세요."]
    progress("기준 릴스를 가져오는 중", 10)
    video = _download_reference(settings, post, root / "reference.mp4")
    duration = _duration(video)
    progress("실제 음성을 전사하는 중", 35)
    speech: list[dict] = []; language = ""; speech_method = "unavailable"
    audio = root / "audio.wav"
    if _audio(video, audio):
        try:
            speech, language, speech_method = _speech(settings, audio, notes)
        except Exception as exc:  # OCR은 음성 모델 실패와 독립적으로 실행한다.
            notes.append(f"음성 전사 실패: {type(exc).__name__}: {str(exc)[:180]}")
    else:
        notes.append("분석 가능한 오디오 트랙이 없습니다.")
    progress("화면 자막·글자를 읽는 중", 70)
    screen = _screen_text(settings, video, root, duration, notes)
    lines = sorted([*speech, *screen], key=lambda row: (row["start"], row["source"] != "speech"))
    if not speech:
        notes.append("확인된 음성 대사가 없습니다. 화면 글자를 음성 대사로 간주하지 않습니다.")
    if not lines:
        notes.append("추출 가능한 음성·화면 글자가 없습니다.")
    result = {"shortcode": shortcode, "reference_url": post.url, "duration": round(duration, 2),
              "language": language, "speech": speech, "screen_text": screen, "lines": lines,
              "notes": notes, "created_at": int(time.time()),
              "methods": {"speech": speech_method, "screen_text": "easyocr-or-tesseract"}}
    json_path = root / "transcript.json"; text_path = root / "transcript.txt"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    text_lines = [f"Instagram 릴스 {shortcode} · {_clock(duration)}", f"원본: {post.url}",
                  "[음성] 실제 들리는 대사 / [화면 글자] OCR로 읽은 화면 문구", ""]
    text_lines.extend(f"{_clock(row['start'])}-{_clock(row['end'])} "
                      f"[{'음성' if row['source'] == 'speech' else '화면 글자'}] {row['text']}" for row in lines)
    text_lines += ["", "주의: 자동 추출 결과입니다. 원본과 대조하세요."]
    text_path.write_text("\n".join(text_lines) + "\n", encoding="utf-8")
    progress("대본 추출 완료", 100)
    return {**result, "json_path": str(json_path), "text_path": str(text_path)}


class TranscriptJobManager:
    def __init__(self, settings: Settings, job_queue=None):
        from .job_queue import JobQueue
        self.settings = settings
        self.queue = job_queue or JobQueue(settings)
        self.queue.register("transcript", lambda shortcode, progress: extract_transcript(settings, shortcode, progress))

    def start(self, shortcode: str) -> dict:
        return self.queue.start("transcript", shortcode)

    def get(self, job_id: str) -> dict | None:
        return self.queue.get(job_id)
