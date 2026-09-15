"""소스·대본 작업을 하나의 SQLite 큐에서 실행한다."""
from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from typing import Callable

from .config import Settings
from .storage import Storage

Worker = Callable[[str, Callable[[str, int], None]], dict]


class JobQueue:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.pending: queue.Queue[str] = queue.Queue()
        self.workers: dict[str, Worker] = {}
        self.submitted: set[str] = set()
        self.lock = threading.Lock()
        store = Storage(settings.db_path)
        try:
            store.interrupt_running_jobs()
        finally:
            store.close()
        for _ in range(max(1, settings.job_concurrency)):
            threading.Thread(target=self._run, daemon=True).start()

    def register(self, kind: str, worker: Worker) -> None:
        self.workers[kind] = worker

    def resume_queued(self) -> None:
        store = Storage(self.settings.db_path)
        try:
            items = store.queued_jobs()
        finally:
            store.close()
        for item in items:
            self._enqueue(item["id"])

    def _enqueue(self, job_id: str) -> None:
        with self.lock:
            if job_id in self.submitted:
                return
            self.submitted.add(job_id)
        self.pending.put(job_id)

    def start(self, kind: str, shortcode: str) -> dict:
        if kind not in self.workers:
            raise ValueError("작업 종류가 등록되지 않았습니다")
        job_id = hashlib.sha1(f"{kind}-{shortcode}-{time.time_ns()}".encode()).hexdigest()[:12]
        store = Storage(self.settings.db_path)
        try:
            job, created = store.create_job(job_id, kind, shortcode)
        finally:
            store.close()
        if created:
            self._enqueue(job["id"])
        return job

    def get(self, job_id: str) -> dict | None:
        store = Storage(self.settings.db_path)
        try:
            return store.job_for(job_id)
        finally:
            store.close()

    def _run(self) -> None:
        while True:
            job_id = self.pending.get()
            store = Storage(self.settings.db_path)
            try:
                job = store.job_for(job_id)
                if not job or job["status"] != "queued":
                    continue
                worker = self.workers.get(job["kind"])
                if worker is None:
                    store.update_job(job_id, status="interrupted", message="작업 실행기 없음",
                                     finished_at=int(time.time()))
                    continue
                store.update_job(job_id, status="running", started_at=int(time.time()), message="실행 중")
                def progress(message: str, percent: int) -> None:
                    store.update_job(job_id, message=message, progress=max(0, min(100, int(percent))))
                try:
                    result = worker(job["shortcode"], progress)
                    path = result.get("zip_path") or result.get("json_path") or ""
                    store.update_job(job_id, status="done", progress=100,
                                     message=(f"소스 영상 {result.get('downloaded', 0)}개 준비 완료"
                                              if job["kind"] == "source" else "대본 추출 완료"),
                                     result_json=json.dumps(result, ensure_ascii=False),
                                     result_path=path, finished_at=int(time.time()))
                    if job["kind"] == "source" and any("429" in note for note in
                                                           result.get("browser_notes", [])):
                        store.notify("source_429", f"source-429-{job_id}",
                                     f"소스 탐색 {job['shortcode']} 중 플랫폼 429 제한이 발생했습니다")
                except Exception as exc:  # 개별 실패가 큐를 중단하지 않는다.
                    store.update_job(job_id, status="error", error=str(exc)[:600],
                                     message="작업 실패", finished_at=int(time.time()))
                    if "429" in str(exc):
                        store.notify("source_429", f"source-429-{job_id}",
                                     f"소스 탐색 {job['shortcode']} 중 플랫폼 429 제한이 발생했습니다")
            finally:
                store.close()
                with self.lock:
                    self.submitted.discard(job_id)
                self.pending.task_done()
