"""미보관 임시 분석 파일의 정리 예고와 명시적 실행."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from .config import Settings
from .storage import Storage


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def disk_usage(settings: Settings) -> dict:
    total = _size(settings.data_dir)
    return {"total_bytes": total, "source_jobs_bytes": _size(settings.source_dir),
            "transcripts_bytes": _size(settings.transcript_dir),
            "models_bytes": _size(settings.source_model_dir),
            "max_bytes": int(settings.cleanup_max_gb * 1024 ** 3),
            "over_limit": total > settings.cleanup_max_gb * 1024 ** 3}


def cleanup_dry_run(settings: Settings, now: int | None = None) -> dict:
    now = now or int(time.time())
    cutoff = now - settings.cleanup_retention_days * 86400
    store = Storage(settings.db_path)
    try:
        archived_roots = {Path(row[0]).resolve().parent for row in store.conn.execute(
            "SELECT result_path FROM jobs WHERE archived=1 AND result_path IS NOT NULL")}
    finally:
        store.close()
    candidates = []
    for root, names in ((settings.source_dir, ("compare", "browser_debug")),
                        (settings.transcript_dir, ("ocr_frames", "audio.wav"))):
        for job_dir in root.iterdir() if root.is_dir() else []:
            if not job_dir.is_dir() or job_dir.resolve() in archived_roots:
                continue
            if job_dir.stat().st_mtime > cutoff:
                continue
            for name in names:
                target = job_dir / name
                if target.exists():
                    candidates.append(target)
            if root == settings.source_dir:
                candidates.extend(job_dir.glob("videos/*.part"))
    entries = [{"path": str(path.relative_to(settings.data_dir)), "bytes": _size(path)}
               for path in candidates]
    return {"retention_days": settings.cleanup_retention_days,
            "disk": disk_usage(settings), "items": entries,
            "expected_freed_bytes": sum(item["bytes"] for item in entries)}


def cleanup_execute(settings: Settings) -> dict:
    preview = cleanup_dry_run(settings)
    deleted = []
    freed = 0
    allowed = {settings.source_dir.resolve(), settings.transcript_dir.resolve()}
    for item in preview["items"]:
        path = (settings.data_dir / item["path"]).resolve()
        if not any(root in path.parents for root in allowed):
            raise ValueError("정리 경로가 데이터 작업 디렉터리 밖입니다.")
        if path.name not in {"compare", "browser_debug", "ocr_frames", "audio.wav"} and path.suffix != ".part":
            raise ValueError("정리 대상이 아닌 경로입니다.")
        measured = _size(path)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()
        freed += measured
        deleted.append(item["path"])
    return {"deleted": deleted, "freed_bytes": freed,
            "expected_freed_bytes": preview["expected_freed_bytes"]}
