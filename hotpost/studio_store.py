"""Transactional studio state, immutable revision references, and a durable outbox."""
from __future__ import annotations

import copy
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class Conflict(ValueError):
    pass


def uid(prefix=""):
    return prefix + uuid.uuid4().hex[:16]


class StudioStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "studio.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks (
                  id TEXT PRIMARY KEY, shortcode TEXT UNIQUE NOT NULL,
                  revision INTEGER NOT NULL, state TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, task_id TEXT NOT NULL, kind TEXT NOT NULL,
                  key TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL,
                  checkpoint TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '',
                  created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY, task_id TEXT NOT NULL, kind TEXT NOT NULL,
                  detail TEXT NOT NULL, created REAL NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, code, title):
        with self.transaction() as db:
            row = db.execute("SELECT state FROM tasks WHERE shortcode=?", (code,)).fetchone()
            if row:
                return json.loads(row[0]), False
            state = dict(id=uid("work-"), shortcode=code, title=title, revision=0,
                         status="preparing", message="자료 준비 대기", error="",
                         scripts=[], voices=[], edits=[], proposals=[], sources=[],
                         script_id=None, approved_script_id=None, voice_id=None,
                         approved_voice_id=None, edit_id=None, original_text="",
                         created=time.time(), updated=time.time())
            db.execute("INSERT INTO tasks VALUES (?,?,?,?,?)", (
                state["id"], code, 0, json.dumps(state, ensure_ascii=False), state["updated"]))
            self.enqueue(db, state["id"], "prepare", {}, "prepare:" + state["id"])
            self.event(db, state["id"], "created", {})
            return state, True

    def get(self, task_id, db=None):
        if db is None:
            with self.connect() as conn:
                return self.get(task_id, conn)
        row = db.execute("SELECT state FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError("제작 작업을 찾을 수 없습니다.")
        return json.loads(row[0])

    def list(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT state FROM tasks ORDER BY updated DESC")]

    def change(self, task_id, fn, expected=None):
        with self.transaction() as db:
            state = self.get(task_id, db)
            if expected is not None and state["revision"] != expected:
                raise Conflict("다른 변경사항이 저장되었습니다. 새로고침 후 다시 적용하세요.")
            fn(state, db)
            self.save(db, state)
            return copy.deepcopy(state)

    def save(self, db, state):
        state["revision"] += 1
        state["updated"] = time.time()
        db.execute("UPDATE tasks SET state=?,revision=?,updated=? WHERE id=?", (
            json.dumps(state, ensure_ascii=False), state["revision"], state["updated"], state["id"]))

    def event(self, db, task_id, kind, detail):
        db.execute("INSERT INTO events(task_id,kind,detail,created) VALUES(?,?,?,?)", (
            task_id, kind, json.dumps(detail, ensure_ascii=False), time.time()))

    def enqueue(self, db, task_id, kind, payload, key):
        row = db.execute("SELECT id,status FROM jobs WHERE key=?", (key,)).fetchone()
        if row:
            if row["status"] == "failed":
                db.execute("UPDATE jobs SET status='queued',error='',updated=? WHERE id=?", (time.time(), row["id"]))
            return row["id"]
        job_id = uid("job-")
        db.execute("INSERT INTO jobs(id,task_id,kind,key,payload,status,created,updated) VALUES(?,?,?,?,?,'queued',?,?)",
                   (job_id, task_id, kind, key, json.dumps(payload, ensure_ascii=False), time.time(), time.time()))
        return job_id

    def claim(self):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET status='running',updated=? WHERE id=?", (time.time(), row["id"]))
            result = dict(row)
            result["payload"] = json.loads(result["payload"])
            result["checkpoint"] = json.loads(result["checkpoint"])
            return result

    def checkpoint(self, job_id, value):
        with self.transaction() as db:
            db.execute("UPDATE jobs SET checkpoint=?,updated=? WHERE id=?", (
                json.dumps(value, ensure_ascii=False), time.time(), job_id))

    def recover(self):
        # Called only after the process-exclusive studio worker lock is held.
        with self.transaction() as db:
            db.execute("UPDATE jobs SET status='queued' WHERE status='running'")

    def jobs(self, task_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT id,kind,status,error,updated FROM jobs WHERE task_id=? ORDER BY created DESC", (task_id,))]

    def finish(self, job, result, apply):
        with self.transaction() as db:
            state = self.get(job["task_id"], db)
            apply(state, db, result)
            self.save(db, state)
            db.execute("UPDATE jobs SET status='done',error='',updated=? WHERE id=?", (time.time(), job["id"]))
            self.event(db, state["id"], job["kind"] + "_finished", {"job_id": job["id"]})

    def fail(self, job, error):
        with self.transaction() as db:
            state = self.get(job["task_id"], db)
            payload = job.get("payload", {})
            current = payload.get("script_id", state["script_id"]) == state["script_id"]
            if job["kind"] == "voice":
                current &= payload.get("voice_id") == state.get("pending_voice_id")
            if job["kind"] in {"edit", "revision", "edit_request"}:
                current &= payload.get("voice_id") == state.get("approved_voice_id")
            if current:
                state.update(error=str(error)[:700], message="확인이 필요합니다")
                if job["kind"] not in {"proposal", "register"}:
                    state["status"] = "attention"
            self.save(db, state)
            db.execute("UPDATE jobs SET status='failed',error=?,updated=? WHERE id=?", (
                str(error)[:700], time.time(), job["id"]))
            self.event(db, state["id"], "failed", {"job_id": job["id"], "error": str(error)[:700]})
