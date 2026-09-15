"""정적 대시보드와 소스 영상 탐색 API를 함께 제공한다."""
from __future__ import annotations

import json
import mimetypes
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .config import Settings
from .source_finder import SourceJobManager
from .transcript import TranscriptJobManager
from .platform_session import PlatformSessionManager
from .accounts import AccountRegistry
from .scheduler import schedule_status
from .storage import Storage
from .report import build_report, write_report
from .criteria import defaults
from .job_queue import JobQueue
from .retention import cleanup_dry_run, cleanup_execute, disk_usage


KST = timezone(timedelta(hours=9))


def schedule_health(schedule: dict, last_attempt_at: int | None, now: int | None = None) -> dict:
    now = now or int(time.time())
    local = datetime.fromtimestamp(now, KST)
    scheduled = local.replace(hour=int(schedule.get("hour", 7)), minute=int(schedule.get("minute", 0)),
                              second=0, microsecond=0)
    missed = bool(schedule.get("installed")
                  and local >= scheduled + timedelta(minutes=30)
                  and (last_attempt_at is None or last_attempt_at < int(scheduled.timestamp())))
    next_run = scheduled if local < scheduled else scheduled + timedelta(days=1)
    return {"missed_today": missed,
            "next_run_at": int(next_run.timestamp()) if schedule.get("installed") else None}


def make_handler(settings: Settings):
    job_queue = JobQueue(settings)
    manager = SourceJobManager(settings, job_queue)
    transcripts = TranscriptJobManager(settings, job_queue)
    job_queue.resume_queued()
    sessions = PlatformSessionManager(settings)
    accounts = AccountRegistry(settings)
    criteria_lock = threading.Lock()

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            return

        def _json(self, value: dict, status: int = 200) -> None:
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)

        def do_PUT(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/criteria":
                self.send_error(HTTPStatus.NOT_FOUND); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 8192:
                    raise ValueError("잘못된 요청 크기")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict) or set(payload) != {"values"}:
                    raise ValueError("values 객체가 필요합니다.")
                with criteria_lock:
                    store = Storage(settings.db_path)
                    try:
                        active = store.update_criteria(payload["values"], settings)
                        previous = {}
                        if settings.report_path.is_file():
                            previous = json.loads(settings.report_path.read_text(encoding="utf-8"))
                        report = build_report(settings, store, previous.get("source", "reanalysis"),
                                              previous.get("notes", []), accounts.usernames())
                        write_report(settings, report)
                    finally:
                        store.close()
                self._json({"criteria": active, "report": report})
            except (ValueError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/storage/cleanup":
                try:
                    self._json(cleanup_execute(settings))
                except ValueError as exc:
                    self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            if path.startswith("/api/notifications/") and path.endswith("/seen"):
                try:
                    notification_id = int(path.split("/")[3])
                except ValueError:
                    self._json({"error": "잘못된 알림 ID"}, HTTPStatus.BAD_REQUEST); return
                store = Storage(settings.db_path)
                try:
                    changed = store.mark_notification_seen(notification_id)
                finally:
                    store.close()
                self._json({"seen": changed}, HTTPStatus.OK if changed else HTTPStatus.NOT_FOUND); return
            if path.startswith("/api/jobs/") and path.endswith("/archive"):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 4096:
                        raise ValueError("잘못된 요청 크기")
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict) or not isinstance(payload.get("archived"), bool):
                        raise ValueError("archived boolean이 필요합니다")
                    job_id = path.split("/")[3]
                    store = Storage(settings.db_path)
                    try:
                        changed = store.archive_job(job_id, payload["archived"])
                    finally:
                        store.close()
                    self._json({"archived": payload["archived"]}, HTTPStatus.OK if changed else HTTPStatus.NOT_FOUND)
                except (ValueError, json.JSONDecodeError) as exc:
                    self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            if path == "/api/accounts":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 4096:
                        raise ValueError("잘못된 요청 크기")
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict):
                        raise ValueError("JSON 객체로 요청하세요.")
                    item, created = accounts.add(str(data.get("account") or ""), str(data.get("note") or ""))
                    self._json({"account": item, "created": created},
                               HTTPStatus.CREATED if created else HTTPStatus.OK)
                except (ValueError, json.JSONDecodeError) as exc:
                    self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            if path == "/api/platform-session":
                self._json(sessions.start(), HTTPStatus.ACCEPTED); return
            if path == "/api/platform-session/finish":
                self._json(sessions.finish(), HTTPStatus.ACCEPTED); return
            if path not in ("/api/source-jobs", "/api/transcript-jobs"):
                self.send_error(HTTPStatus.NOT_FOUND); return
            try:
                if sessions.status()["active"]:
                    self._json({"error": "플랫폼 로그인 창에서 확인 완료를 누른 뒤 다시 시도하세요."},
                               HTTPStatus.CONFLICT); return
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 4096:
                    raise ValueError("잘못된 요청 크기")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("JSON 객체로 요청하세요.")
                shortcode = str(data.get("shortcode", ""))
                if not shortcode or len(shortcode) > 40 or not all(c.isalnum() or c in "-_" for c in shortcode):
                    raise ValueError("올바르지 않은 shortcode")
                job_manager = transcripts if path == "/api/transcript-jobs" else manager
                self._json(job_manager.start(shortcode), HTTPStatus.ACCEPTED)
            except (ValueError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/accounts":
                items = accounts.list()
                self._json({"accounts": items, "count": len(items)}); return
            if path == "/api/criteria":
                store = Storage(settings.db_path)
                try:
                    active = store.criteria(settings)
                finally:
                    store.close()
                self._json({**active, "defaults": defaults(settings)}); return
            if path == "/api/notifications":
                store = Storage(settings.db_path)
                try:
                    items = store.notifications()
                finally:
                    store.close()
                self._json({"notifications": items, "unseen": sum(item["seen_at"] is None for item in items)}); return
            if path == "/api/jobs":
                store = Storage(settings.db_path)
                try:
                    items = store.list_jobs()
                finally:
                    store.close()
                self._json({"jobs": items}); return
            if path == "/api/storage":
                self._json(disk_usage(settings)); return
            if path == "/api/storage/dry-run":
                self._json(cleanup_dry_run(settings)); return
            if path == "/api/collection-status":
                store = Storage(settings.db_path)
                try:
                    collection = store.collection_status()
                    hot_tracking = store.hot_tracking_status()
                    schedule = schedule_status()
                    health = schedule_health(schedule, collection["last_attempt_at"])
                    if health["missed_today"]:
                        store.notify("schedule_missed", f"missed-{datetime.now(KST).date()}",
                                     "오늘 예정된 자동 수집이 실행되지 않았습니다")
                finally:
                    store.close()
                self._json({"collection": collection, "schedule": {**schedule, **health},
                            "hot_tracking": hot_tracking,
                            "registered_accounts": len(accounts.usernames())}); return
            if path == "/api/platform-session":
                self._json(sessions.status()); return
            if path.startswith("/api/transcript-jobs/"):
                parts = path.strip("/").split("/")
                if len(parts) not in (3, 4):
                    self.send_error(HTTPStatus.NOT_FOUND); return
                job = transcripts.get(parts[2])
                if not job:
                    self._json({"error": "작업을 찾지 못했습니다."}, HTTPStatus.NOT_FOUND); return
                if len(parts) == 4:
                    if parts[3] != "download":
                        self.send_error(HTTPStatus.NOT_FOUND); return
                    if job["status"] != "done":
                        self._json({"error": "대본이 아직 준비되지 않았습니다."}, HTTPStatus.CONFLICT); return
                    format_name = parse_qs(urlparse(self.path).query).get("format", ["txt"])[0]
                    if format_name not in ("txt", "json"):
                        self._json({"error": "지원하지 않는 형식입니다."}, HTTPStatus.BAD_REQUEST); return
                    target = Path(job["result"][f"{'text' if format_name == 'txt' else 'json'}_path"])
                    if not target.is_file() or settings.transcript_dir.resolve() not in target.resolve().parents:
                        self._json({"error": "결과 파일이 없습니다."}, HTTPStatus.NOT_FOUND); return
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/plain; charset=utf-8" if format_name == "txt" else "application/json; charset=utf-8")
                    self.send_header("Content-Disposition", f'attachment; filename="{job["shortcode"]}-transcript.{format_name}"')
                    self.send_header("Content-Length", str(target.stat().st_size)); self.end_headers()
                    with target.open("rb") as f:
                        while chunk := f.read(1024 * 256): self.wfile.write(chunk)
                    return
                public = {k: v for k, v in job.items() if k != "result"}
                if job["status"] == "done":
                    public["result"] = {k: v for k, v in job["result"].items() if not k.endswith("_path")}
                    public["download_txt_url"] = f"/api/transcript-jobs/{job['id']}/download?format=txt"
                    public["download_json_url"] = f"/api/transcript-jobs/{job['id']}/download?format=json"
                self._json(public); return
            if path.startswith("/api/source-jobs/"):
                parts = path.strip("/").split("/")
                job = manager.get(parts[2]) if len(parts) >= 3 else None
                if not job:
                    self._json({"error": "작업을 찾지 못했습니다."}, HTTPStatus.NOT_FOUND); return
                if len(parts) == 4 and parts[3] == "download":
                    if job["status"] != "done":
                        self._json({"error": "아직 다운로드가 준비되지 않았습니다."}, HTTPStatus.CONFLICT); return
                    target = Path(job["result"]["zip_path"])
                    if not target.is_file() or settings.source_dir.resolve() not in target.resolve().parents:
                        self._json({"error": "결과 파일이 없습니다."}, HTTPStatus.NOT_FOUND); return
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/zip")
                    self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
                    self.send_header("Content-Length", str(target.stat().st_size)); self.end_headers()
                    with target.open("rb") as f:
                        while chunk := f.read(1024 * 256): self.wfile.write(chunk)
                    return
                public = {k: v for k, v in job.items() if k != "result"}
                if job["status"] == "done":
                    public["downloaded"] = job["result"]["downloaded"]
                    public["probed_downloads"] = job["result"].get("probed_downloads", job["result"]["downloaded"])
                    public["quality_counts"] = job["result"].get("quality_counts", {})
                    public["candidates"] = [{k: c.get(k) for k in ("provider", "title", "uploader", "url", "original_url", "platform", "hash_similarity",
                                                                        "semantic_similarity", "similarity", "match_quality",
                                                                        "source_quality", "text_overlay_score", "source_score",
                                                                        "selected_for_zip", "selection_reason", "rejection_reasons",
                                                                        "rights", "downloaded_file", "error")}
                                            for c in job["result"]["candidates"]]
                    public["notes"] = [*job["result"].get("browser_notes", []), *job["result"].get("verification_notes", [])]
                    public["download_url"] = f"/api/source-jobs/{job['id']}/download"
                self._json(public); return
            super().do_GET()

        def do_DELETE(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if not path.startswith("/api/accounts/"):
                self.send_error(HTTPStatus.NOT_FOUND); return
            try:
                username = unquote(path.removeprefix("/api/accounts/"))
                if not accounts.delete(username):
                    self._json({"error": "관리 목록에서 계정을 찾지 못했습니다."}, HTTPStatus.NOT_FOUND); return
                self._json({"deleted": username})
            except ValueError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    return partial(Handler, directory=str(settings.web_dir))


def serve(settings: Settings, port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(settings))
