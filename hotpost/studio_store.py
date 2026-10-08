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
                CREATE TABLE IF NOT EXISTS automatic_runs (
                  run_key TEXT PRIMARY KEY, selection TEXT NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS jobs_task_activity ON jobs(task_id,status,kind);
            """)
        # Existing daily automatic tasks adopt the shared workflow without
        # launching new work or changing manually selected studio tasks.
        with self.transaction() as db:
            for row in db.execute('SELECT state FROM tasks').fetchall():
                state = json.loads(row[0])
                auto = state.get('automation', {})
                if auto.get('selection_mode') == 'automatic' and auto.get('protocol') != 2:
                    from .studio_workflow import snapshot
                    auto['protocol'] = 2
                    auto['needs_top_pick'] = bool(state.get('script_candidates'))
                    snapshot(state)
                    self.save(db, state)

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

    def create(self, code, title, automation=None, *, initial=None, prepare=True):
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
            from .source_policy import current_policy
            state['source_policy'] = current_policy()
            if initial:
                state.update(copy.deepcopy(initial))
            if automation:
                state['automation'] = automation
                if automation.get('protocol') == 2:
                    from .studio_workflow import init_run
                    init_run(state)
            db.execute("INSERT INTO tasks VALUES (?,?,?,?,?)", (
                state["id"], code, 0, json.dumps(state, ensure_ascii=False), state["updated"]))
            if prepare:
                self.enqueue(db, state["id"], "prepare", {}, "prepare:" + state["id"])
            self.event(db, state["id"], "created", {})
            return state, True

    def freeze_selection(self, run_key, selection):
        with self.transaction() as db:
            db.execute('INSERT OR IGNORE INTO automatic_runs VALUES(?,?,?)',
                       (str(run_key), json.dumps(selection, ensure_ascii=False), time.time()))
            return json.loads(db.execute('SELECT selection FROM automatic_runs WHERE run_key=?',
                                         (str(run_key),)).fetchone()[0])

    def events(self, task_id):
        with self.connect() as db:
            return [{**dict(r), 'detail':json.loads(r['detail'])} for r in db.execute(
                'SELECT kind,detail,created FROM events WHERE task_id=? ORDER BY id DESC LIMIT 60', (task_id,))]

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
        row = db.execute("SELECT id,status,checkpoint FROM jobs WHERE key=?", (key,)).fetchone()
        if row:
            if row["status"] == "failed":
                db.execute("UPDATE jobs SET status='queued',error='',updated=? WHERE id=?", (time.time(), row["id"]))
                if kind in {'rewrite', 'voice'}:
                    checkpoint = json.loads(row['checkpoint'])
                    checkpoint['retry_requested'] = True
                    db.execute('UPDATE jobs SET checkpoint=? WHERE id=?', (json.dumps(checkpoint), row['id']))
            return row["id"]
        job_id = uid("job-")
        db.execute("INSERT INTO jobs(id,task_id,kind,key,payload,status,created,updated) VALUES(?,?,?,?,?,'queued',?,?)",
                   (job_id, task_id, kind, key, json.dumps(payload, ensure_ascii=False), time.time(), time.time()))
        return job_id

    def claim(self, lane=None, *, task_id=None):
        with self.transaction() as db:
            self.consume_previous_daily(db)
            self.pause_queued(db)
            # Finish an already-prepared video's downstream stages before the
            # next slow source search, so the first review becomes ready sooner.
            lane_filter = (" AND kind IN ('collect_sources','refresh_sources')" if lane == 'sources' else
                           " AND kind IN ('rewrite','proposal')" if lane == 'scripts' else
                           " AND kind NOT IN ('collect_sources','refresh_sources','rewrite','proposal')" if lane == 'media' else
                           " AND kind NOT IN ('collect_sources','refresh_sources')" if lane == 'production' else '')
            parameters = [time.time()]
            if task_id is not None:
                lane_filter += ' AND task_id=?'
                parameters.append(task_id)
            row = db.execute("""SELECT * FROM jobs WHERE status='queued'
                AND COALESCE(json_extract(checkpoint,'$.not_before'),0)<=?
                AND (jobs.kind IN ('collect_sources','refresh_sources','proposal') OR NOT EXISTS (
                  SELECT 1 FROM jobs AS running WHERE running.task_id=jobs.task_id
                  AND running.status='running'
                  AND running.kind NOT IN ('collect_sources','refresh_sources','proposal')
                ))
                """ + lane_filter + """
                ORDER BY COALESCE((SELECT json_extract(tasks.state,'$.automation.priority')
                  FROM tasks WHERE tasks.id=jobs.task_id),0) DESC,
                CASE WHEN kind<>'prepare' AND EXISTS (
                  SELECT 1 FROM tasks WHERE tasks.id=jobs.task_id
                  AND json_extract(tasks.state,'$.automation.active')=1
                ) THEN 0 ELSE 1 END,created LIMIT 1""", parameters).fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET status='running',updated=? WHERE id=?", (time.time(), row["id"]))
            state = self.get(row['task_id'], db)
            if row['kind'] == 'collect_sources':
                state['source_search'] = {'status':'running','message':'소스 영상을 자동으로 확보하는 중','progress':0}
                self.save(db,state)
            stages = {'prepare':('preparing','자료 준비'), 'rewrite':('rewriting','대본 재가공'),
                      'voice':('voice_generating','음성 제작'), 'edit':('editing','장면·자막 편집'),
                      'revision':('editing','구간 수정'), 'register':('registering','프로젝트 등록'),
                      'export':('exporting','최종 영상 내보내기')}
            if state['status'] in {'retry_wait','waiting_capcut'} and row['kind'] in stages:
                status, label = stages[row['kind']]
                state.update(status=status, error='', message=label+' 다시 진행 중')
                self.save(db, state)
            elif state.get('automation', {}).get('active') and row['kind'] in stages:
                status, label = stages[row['kind']]
                state.update(status=status, message=label+' 진행 중')
                self.save(db, state)
            result = dict(row)
            result["payload"] = json.loads(result["payload"])
            result["checkpoint"] = json.loads(result["checkpoint"])
            return result

    def consume_previous_daily(self, db):
        """Consume legacy daily picks; full batches keep processing after midnight."""
        from .daily_hot import date_key
        today = date_key(time.time())
        rows = db.execute("SELECT state FROM tasks WHERE json_extract(state,'$.automation.selection_mode')='automatic' AND json_extract(state,'$.automation.active')=1 AND COALESCE(json_extract(state,'$.automation.finish_selected_batch'),0)<>1").fetchall()
        for row in rows:
            state = json.loads(row[0])
            auto = state['automation']
            day = auto.get('selection_date_kst') or date_key(auto.get('selected_at', state['created']))
            if day and day < today and state['status'] != 'completed':
                auto.update(active=False, consumed_by_daily_policy=True)
                db.execute("UPDATE jobs SET status='paused' WHERE task_id=? AND status='queued' AND kind NOT IN ('proposal','refresh_sources','suggest_edit') AND COALESCE(json_extract(payload,'$.launch'),0)<>1", (state['id'],))
                state.update(status='paused', message='이전 감지일 · 소모 처리 · 명시적 재개 시 이어집니다')
                self.save(db, state)
                self.event(db, state['id'], 'daily_policy_consumed', {'selection_date_kst':day, 'today_kst':today})

    def checkpoint(self, job_id, value):
        with self.transaction() as db:
            db.execute("UPDATE jobs SET checkpoint=?,updated=? WHERE id=?", (
                json.dumps(value, ensure_ascii=False), time.time(), job_id))

    @staticmethod
    def pause_queued(db):
        db.execute("""UPDATE jobs SET status='paused' WHERE status='queued' AND kind='collect_sources'
            AND EXISTS (SELECT 1 FROM tasks WHERE tasks.id=jobs.task_id
                AND json_extract(tasks.state,'$.source_acquisition.hold') IS NOT NULL)""")
        db.execute("""UPDATE jobs SET status='paused' WHERE status='queued'
            AND kind NOT IN ('proposal','refresh_sources','suggest_edit')
            AND COALESCE(json_extract(payload,'$.launch'),0)<>1
            AND EXISTS (SELECT 1 FROM tasks WHERE tasks.id=jobs.task_id
                AND json_extract(tasks.state,'$.automation.protocol')=2
                AND (json_extract(tasks.state,'$.automation.paused_by_user')=1
                     OR json_extract(tasks.state,'$.automation.consumed_by_daily_policy')=1))""")

    def defer(self, job, message, seconds, waiting=False, waiting_status=None):
        with self.transaction() as db:
            state = self.get(job['task_id'], db)
            checkpoint = job['checkpoint']
            checkpoint['not_before'] = time.time()+seconds
            if not waiting:
                checkpoint['auto_retries'] = checkpoint.get('auto_retries',0)+1
                checkpoint['retry_requested'] = True
            if job['kind'] == 'collect_sources':
                state['source_search'] = {'status':'queued','message':'소스 자동 수집 재시도 대기','error':str(message)[:500], 'progress':0}
            else:
                state.update(status=(waiting_status or 'waiting_capcut') if waiting else 'retry_wait', error='',
                             message=message if waiting else f"일시적 오류 · 자동 재시도 {checkpoint['auto_retries']}/2 대기: {message}")
            if state.get('pending_reproduction') and job['kind'] != 'collect_sources':
                # The deferred job is no longer running; let the worker consume it
                # once and transition at its boundary without losing the request.
                checkpoint['not_before'] = 0
            db.execute("UPDATE jobs SET status='queued',checkpoint=?,updated=? WHERE id=?",
                       (json.dumps(checkpoint),time.time(),job['id']))
            if (state.get('automation', {}).get('paused_by_user') or state.get('automation', {}).get('consumed_by_daily_policy')) and job['kind'] not in {'proposal','refresh_sources','suggest_edit'} and not job['payload'].get('launch'):
                db.execute("UPDATE jobs SET status='paused' WHERE id=?", (job['id'],))
                state.update(status='paused', message='자동 진행 중지 · 재개하면 중단 단계부터 이어집니다')
                if job['kind'] == 'collect_sources': state['source_search']['status'] = 'paused'
            self.save(db,state)

    def recover(self):
        # Called only after the process-exclusive studio worker lock is held.
        with self.transaction() as db:
            db.execute("UPDATE jobs SET status='queued' WHERE status='running'")
            self.pause_queued(db)

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
            if job['kind'] in {'refresh_sources','collect_sources'}:
                state['source_search'] = {'status': 'failed', 'message': str(error)[:500], 'progress': 0}
            current = payload.get("script_id", state["script_id"]) == state["script_id"]
            current &= job['kind'] not in {'refresh_sources','collect_sources'}
            if job['kind'] in {'proposal','suggest_edit'} and state.get('automation', {}).get('protocol')==2:
                current = False
                state['feedback_message'] = '수정안 생성 실패: '+str(error)[:500]
            if job["kind"] == "voice":
                current &= payload.get("voice_id") == state.get("pending_voice_id")
            if job["kind"] in {"edit", "revision", "edit_request"}:
                current &= payload.get("voice_id") == state.get("approved_voice_id")
            if current:
                state.update(error=str(error)[:700], message="확인이 필요합니다")
                if job["kind"] not in {"proposal", "register"} or (job['kind'] == 'register' and state.get('automation')):
                    state["status"] = "attention"
            self.save(db, state)
            db.execute("UPDATE jobs SET status='failed',error=?,updated=? WHERE id=?", (
                str(error)[:700], time.time(), job["id"]))
            self.event(db, state["id"], "failed", {"job_id": job["id"], "error": str(error)[:700]})
