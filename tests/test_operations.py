import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen, Request

from hotpost.config import Settings
from hotpost.job_queue import JobQueue
from hotpost.models import Post
from hotpost.retention import cleanup_dry_run, cleanup_execute
from hotpost.server import schedule_health, serve
from hotpost.storage import Storage
from hotpost.cli import _operational_event


def _settings(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", web_dir=tmp_path / "web",
                        influencer_file=tmp_path / "missing.txt")
    settings.web_dir.mkdir()
    settings.source_dir.mkdir(parents=True)
    settings.transcript_dir.mkdir(parents=True)
    return settings


def test_single_heavy_worker_duplicate_suppression_and_restart_recovery(tmp_path):
    settings = _settings(tmp_path)
    settings.job_concurrency = 1
    queue = JobQueue(settings)
    active = 0
    maximum = 0
    lock = threading.Lock()
    entered = threading.Event()
    release = threading.Event()

    def worker(shortcode, progress):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        progress("검사 중", 50)
        entered.set()
        release.wait(3)
        with lock:
            active -= 1
        return {"shortcode": shortcode, "downloaded": 0, "zip_path": ""}

    queue.register("source", worker)
    queue.register("transcript", worker)
    first = queue.start("source", "reel-a")
    assert entered.wait(2)
    duplicate = queue.start("source", "reel-a")
    second = queue.start("transcript", "reel-b")
    assert duplicate["id"] == first["id"]
    assert queue.get(second["id"])["status"] == "queued"
    release.set()
    queue.pending.join()
    assert maximum == 1
    assert queue.get(first["id"])["status"] == "done"
    assert queue.get(second["id"])["status"] == "done"

    restarted = JobQueue(settings)
    assert restarted.get(first["id"])["result"]["shortcode"] == "reel-a"
    store = Storage(settings.db_path)
    running, _ = store.create_job("running-old", "source", "reel-old")
    store.update_job(running["id"], status="running")
    store.close()
    second_restart = JobQueue(settings)
    assert second_restart.get("running-old")["status"] == "interrupted"


def test_cleanup_dry_run_matches_actual_and_preserves_archived_results(tmp_path):
    settings = _settings(tmp_path)
    settings.cleanup_retention_days = 1
    root = settings.source_dir / "reel-100"
    compare = root / "compare"
    compare.mkdir(parents=True)
    (compare / "frame.jpg").write_bytes(b"frame" * 100)
    (root / "reference.mp4").write_bytes(b"reference")
    video = root / "videos" / "candidate.mp4"
    video.parent.mkdir()
    video.write_bytes(b"candidate")
    result = root / "sources_reel.zip"
    result.write_bytes(b"zip")
    old = time.time() - 3 * 86400
    os.utime(root, (old, old))
    store = Storage(settings.db_path)
    job, _ = store.create_job("archived-job", "source", "reel")
    store.update_job(job["id"], status="done", result_path=str(result))
    store.archive_job(job["id"], True)
    store.close()
    assert cleanup_dry_run(settings)["items"] == []

    store = Storage(settings.db_path)
    assert store.archive_job("archived-job", False)
    store.close()
    preview = cleanup_dry_run(settings)
    assert [item["path"] for item in preview["items"]] == ["source_jobs/reel-100/compare"]
    result = cleanup_execute(settings)
    assert result["freed_bytes"] == preview["expected_freed_bytes"]
    assert not compare.exists()
    assert video.read_bytes() == b"candidate"
    assert (root / "reference.mp4").read_bytes() == b"reference"
    assert (root / "sources_reel.zip").read_bytes() == b"zip"


def test_collection_alerts_schedule_miss_and_schema_version(tmp_path):
    settings = _settings(tmp_path)
    store = Storage(settings.db_path)
    assert store.conn.execute("SELECT version FROM schema_version").fetchone()[0] == 4
    assert store.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    health = store.record_account_collection("creator", False)
    assert health["consecutive_failures"] == 1
    store.record_account_collection("creator", False)
    health = store.record_account_collection("creator", False)
    assert health["consecutive_failures"] == 3
    assert store.notify("fail", "creator-third", "연속 실패")
    assert not store.notify("fail", "creator-third", "중복")
    assert len(store.notifications()) == 1
    store.record_account_collection("creator", True)
    assert store.managed_accounts() == []
    run_id = store.start_run(int(time.time()), "web")
    assert store.collection_status()["state"] == "running"
    store.finish_run(run_id, 1, 0, 5)
    assert store.collection_status()["state"] == "success"
    now = int(datetime(2026, 9, 16, 8, 0, tzinfo=timezone(timedelta(hours=9))).timestamp())
    status = schedule_health({"installed": True, "loaded": True, "hour": 7, "minute": 0}, None, now)
    assert status["missed_today"]
    assert schedule_health({"installed": True, "loaded": False, "hour": 7, "minute": 0}, None, now)["missed_today"]
    assert not schedule_health({"installed": False, "loaded": False, "hour": 7, "minute": 0}, None, now)["missed_today"]
    store.close()


def test_operational_log_rotates_without_touching_daily_collect_log(tmp_path):
    settings = _settings(tmp_path)
    settings.operational_log_max_mb = 1
    (settings.data_dir / "daily_collect.log").write_text("기존 로그", encoding="utf-8")
    _operational_event(settings, "수집 상태 " + "a" * 600_000)
    _operational_event(settings, "수집 상태 " + "b" * 600_000)
    assert (settings.data_dir / "operational.log.1").is_file()
    assert (settings.data_dir / "daily_collect.log").read_text(encoding="utf-8") == "기존 로그"


def test_sqlite_parallel_collection_accounts_and_jobs_do_not_lock(tmp_path):
    settings = _settings(tmp_path)
    errors = []
    barrier = threading.Barrier(4)

    def run(index):
        try:
            barrier.wait()
            for number in range(10):
                store = Storage(settings.db_path)
                name = f"account-{index}"
                store.upsert_managed_account(name)
                post = Post(f"post-{index}-{number}", name, int(time.time()) - 86400,
                            "reel", 10, 1, 100)
                store.upsert_posts([post])
                store.create_job(f"job-{index}-{number}", "source", f"reel-{index}-{number}")
                store.close()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(4)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(10)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors
    store = Storage(settings.db_path)
    assert len(store.managed_accounts()) == 4
    assert store.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 40
    store.close()


def test_completed_jobs_remain_downloadable_after_server_restart(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    source_root = settings.source_dir / "result"
    source_root.mkdir()
    zip_path = source_root / "sources_reel.zip"
    zip_path.write_bytes(b"zip-result")
    transcript_root = settings.transcript_dir / "result"
    transcript_root.mkdir()
    txt = transcript_root / "transcript.txt"
    txt.write_text("실제 확인된 음성", encoding="utf-8")
    raw = transcript_root / "transcript.json"
    raw.write_text('{}', encoding="utf-8")
    store = Storage(settings.db_path)
    source, _ = store.create_job("source-done", "source", "reel")
    store.update_job(source["id"], status="done", result_path=str(zip_path),
                     result_json=json.dumps({"zip_path": str(zip_path), "downloaded": 1,
                                             "candidates": [], "quality_counts": {}}))
    transcript, _ = store.create_job("transcript-done", "transcript", "reel")
    store.update_job(transcript["id"], status="done", result_path=str(raw),
                     result_json=json.dumps({"json_path": str(raw), "text_path": str(txt),
                                             "speech": [], "screen_text": [], "lines": [], "notes": []}))
    store.close()
    monkeypatch.setattr("hotpost.server.schedule_status", lambda: {"installed": False, "loaded": False,
                                                                      "hour": 7, "minute": 0})
    for _ in range(2):
        httpd = serve(settings, port=0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_port}"
        try:
            with urlopen(base + "/api/jobs") as response:
                assert len(json.load(response)["jobs"]) == 2
            with urlopen(base + "/api/storage/dry-run") as response:
                assert json.load(response)["expected_freed_bytes"] == 0
            with urlopen(base + "/api/notifications") as response:
                assert "notifications" in json.load(response)
            with urlopen(base + "/api/collection-status") as response:
                assert json.load(response)["schedule"]["next_run_at"] is None
            with urlopen(base + "/api/source-jobs/source-done") as response:
                assert json.load(response)["status"] == "done"
            with urlopen(base + "/api/source-jobs/source-done/download") as response:
                assert response.read() == b"zip-result"
            with urlopen(base + "/api/transcript-jobs/transcript-done/download?format=txt") as response:
                assert response.read().decode() == "실제 확인된 음성"
            archive = Request(base + "/api/jobs/source-done/archive",
                              data=b'{"archived":true}', method="POST",
                              headers={"Content-Type": "application/json"})
            with urlopen(archive) as response:
                assert json.load(response)["archived"]
        finally:
            httpd.shutdown(); httpd.server_close(); thread.join(2)
