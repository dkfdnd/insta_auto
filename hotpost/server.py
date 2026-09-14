"""정적 대시보드와 소스 영상 탐색 API를 함께 제공한다."""
from __future__ import annotations

import json
import mimetypes
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .config import Settings
from .source_finder import SourceJobManager
from .platform_session import PlatformSessionManager


def make_handler(settings: Settings):
    manager = SourceJobManager(settings)
    sessions = PlatformSessionManager(settings)

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

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/platform-session":
                self._json(sessions.start(), HTTPStatus.ACCEPTED); return
            if path == "/api/platform-session/finish":
                self._json(sessions.finish(), HTTPStatus.ACCEPTED); return
            if path != "/api/source-jobs":
                self.send_error(HTTPStatus.NOT_FOUND); return
            try:
                if sessions.status()["active"]:
                    self._json({"error": "플랫폼 로그인 창에서 확인 완료를 누른 뒤 다시 시도하세요."},
                               HTTPStatus.CONFLICT); return
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 4096:
                    raise ValueError("잘못된 요청 크기")
                data = json.loads(self.rfile.read(length))
                shortcode = str(data.get("shortcode", ""))
                if not shortcode or len(shortcode) > 40 or not all(c.isalnum() or c in "-_" for c in shortcode):
                    raise ValueError("올바르지 않은 shortcode")
                self._json(manager.start(shortcode), HTTPStatus.ACCEPTED)
            except (ValueError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/platform-session":
                self._json(sessions.status()); return
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
                    public["candidates"] = [{k: c[k] for k in ("provider", "title", "uploader", "url", "hash_similarity",
                                                                        "semantic_similarity", "similarity", "match_quality",
                                                                        "source_quality", "text_overlay_score", "source_score",
                                                                        "selected_for_zip", "rights", "downloaded_file", "error")}
                                            for c in job["result"]["candidates"]]
                    public["notes"] = [*job["result"].get("browser_notes", []), *job["result"].get("verification_notes", [])]
                    public["download_url"] = f"/api/source-jobs/{job['id']}/download"
                self._json(public); return
            super().do_GET()

    return partial(Handler, directory=str(settings.web_dir))


def serve(settings: Settings, port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(settings))
