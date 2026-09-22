"""SQLite 저장소.

- profiles : 계정 최신 정보
- posts    : 게시물 최신 지표 (upsert)
- snapshots: 수집 시점마다의 지표 기록 → 시간에 따른 증가 속도(velocity) 계산용
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .models import Post, Profile
from .config import Settings
from .criteria import defaults, validate
from .observations import MetricObservation

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    username TEXT PRIMARY KEY,
    user_id TEXT, full_name TEXT, followers INTEGER, following INTEGER,
    media_count INTEGER, biography TEXT, profile_pic_url TEXT, is_private INTEGER,
    updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS posts (
    shortcode TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    taken_at INTEGER NOT NULL,
    kind TEXT NOT NULL,
    likes INTEGER, comments INTEGER, views INTEGER,
    caption TEXT, hashtags TEXT, thumbnail_url TEXT, video_duration REAL, media_id TEXT,
    first_seen INTEGER, updated_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_posts_user_time ON posts(username, taken_at DESC);
CREATE TABLE IF NOT EXISTS snapshots (
    shortcode TEXT NOT NULL,
    collected_at INTEGER NOT NULL,
    likes INTEGER, comments INTEGER, views INTEGER,
    PRIMARY KEY (shortcode, collected_at)
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at INTEGER, finished_at INTEGER, source TEXT,
    accounts_ok INTEGER, accounts_failed INTEGER, posts INTEGER, notes TEXT
);
CREATE TABLE IF NOT EXISTS managed_accounts (
    username TEXT PRIMARY KEY,
    note TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hot_view_tracking (
    shortcode TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    posted_at INTEGER NOT NULL,
    track_until INTEGER NOT NULL,
    detected_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hot_tracking_user_until ON hot_view_tracking(username, track_until);
CREATE TABLE IF NOT EXISTS scoring_criteria (
    id INTEGER PRIMARY KEY CHECK (id=1),
    version INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    values_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS metric_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shortcode TEXT NOT NULL,
    requested_at INTEGER NOT NULL,
    observed_at INTEGER,
    success INTEGER NOT NULL,
    views INTEGER, likes INTEGER, comments INTEGER,
    source TEXT NOT NULL,
    http_status INTEGER,
    reason TEXT NOT NULL DEFAULT '',
    age_hours REAL NOT NULL,
    scope TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observations_post_time ON metric_observations(shortcode, observed_at);
CREATE INDEX IF NOT EXISTS idx_observations_request ON metric_observations(requested_at);
"""


# Schema creation and PRAGMA journal_mode both take an exclusive database
# lock.  SQLite's busy timeout does not reliably serialize simultaneous
# first-use connections on Windows, so initialization is guarded inside the
# process.  Normal reads/writes remain concurrent under WAL.
_INITIALIZE_LOCK = threading.Lock()


class Storage:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=10000")
        with _INITIALIZE_LOCK:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        self.conn.execute("CREATE TABLE IF NOT EXISTS schema_version (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL)")
        self.conn.execute("INSERT OR IGNORE INTO schema_version VALUES (1,0)")
        self.conn.commit()
        for version in range(1, 4):
            self.conn.execute("BEGIN IMMEDIATE")
            current = self.conn.execute("SELECT version FROM schema_version WHERE id=1").fetchone()[0]
            if current >= version:
                self.conn.commit(); continue
            if version == 1:
                columns = {row[1] for row in self.conn.execute("PRAGMA table_info(hot_view_tracking)")}
                for column, definition in {
                    "finalized_at": "INTEGER", "final_views": "INTEGER",
                    "max_views_per_hour": "REAL", "max_acceleration": "REAL",
                }.items():
                    if column not in columns:
                        self.conn.execute(f"ALTER TABLE hot_view_tracking ADD COLUMN {column} {definition}")
            elif version == 2:
                self.conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, shortcode TEXT NOT NULL,
                    status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
                    result_json TEXT, result_path TEXT, archived INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL, started_at INTEGER, finished_at INTEGER)""")
                self.conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_active_reel
                    ON jobs(kind,shortcode) WHERE status IN ('queued','running')""")
            elif version == 3:
                self.conn.execute("""CREATE TABLE IF NOT EXISTS account_collection_health (
                    username TEXT PRIMARY KEY, last_attempt INTEGER, last_success INTEGER,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '')""")
                self.conn.execute("""CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, key TEXT NOT NULL UNIQUE,
                    message TEXT NOT NULL, created_at INTEGER NOT NULL, seen_at INTEGER)""")
            self.conn.execute("UPDATE schema_version SET version=? WHERE id=1", (version,))
            self.conn.commit()

    # ---- write ----
    def upsert_profile(self, p: Profile) -> None:
        self.conn.execute(
            """INSERT INTO profiles VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(username) DO UPDATE SET
                 user_id=excluded.user_id, full_name=excluded.full_name, followers=excluded.followers,
                 following=excluded.following, media_count=excluded.media_count, biography=excluded.biography,
                 profile_pic_url=excluded.profile_pic_url, is_private=excluded.is_private, updated_at=excluded.updated_at""",
            (p.username, p.user_id, p.full_name, p.followers, p.following, p.media_count,
             p.biography, p.profile_pic_url, int(p.is_private), int(time.time())),
        )

    def upsert_posts(self, posts: list[Post], collected_at: int | None = None,
                     observations: list[MetricObservation] | None = None) -> None:
        now = collected_at or int(time.time())
        latest = {o.shortcode: o for o in (observations or [])}
        successful = {code: o for code, o in latest.items() if o.success and o.views is not None}
        for p in posts:
            view_value = (p.views if observations is None or not p.is_video else
                          successful[p.shortcode].views if p.shortcode in successful else None)
            self.conn.execute(
                """INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(shortcode) DO UPDATE SET
                     likes=excluded.likes, comments=excluded.comments,
                     views=COALESCE(excluded.views,posts.views),
                     caption=excluded.caption, hashtags=excluded.hashtags, thumbnail_url=excluded.thumbnail_url,
                     video_duration=excluded.video_duration, media_id=excluded.media_id, kind=excluded.kind,
                     updated_at=excluded.updated_at""",
                (p.shortcode, p.username, p.taken_at, p.kind, p.likes, p.comments, view_value,
                 p.caption, json.dumps(p.hashtags, ensure_ascii=False), p.thumbnail_url,
                 p.video_duration, p.media_id, now, now),
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?)",
                (p.shortcode, now, p.likes, p.comments, view_value),
            )
        if observations:
            self.conn.executemany(
                """INSERT INTO metric_observations
                   (shortcode,requested_at,observed_at,success,views,likes,comments,
                    source,http_status,reason,age_hours,scope) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(o.shortcode, o.requested_at, o.observed_at, int(o.success),
                  o.views if o.success else None, o.likes if o.success else None,
                  o.comments if o.success else None, o.source, o.http_status, o.reason,
                  o.age_hours, o.scope) for o in observations],
            )
        self.conn.commit()

    def record_run(self, started: int, source: str, ok: int, failed: int, posts: int, notes: str = "") -> None:
        self.conn.execute(
            "INSERT INTO runs (started_at, finished_at, source, accounts_ok, accounts_failed, posts, notes) VALUES (?,?,?,?,?,?,?)",
            (started, int(time.time()), source, ok, failed, posts, notes),
        )
        self.conn.commit()

    def start_run(self, started: int, source: str) -> int:
        cursor = self.conn.execute("INSERT INTO runs (started_at,source,accounts_ok,accounts_failed,posts) VALUES (?,?,0,0,0)",
                                   (started, source))
        self.conn.commit()
        return cursor.lastrowid

    def finish_run(self, run_id: int, ok: int, failed: int, posts: int, notes: str = "") -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?,accounts_ok=?,accounts_failed=?,posts=?,notes=? WHERE id=?",
            (int(time.time()), ok, failed, posts, notes, run_id),
        )
        self.conn.commit()

    def record_account_collection(self, username: str, success: bool, error: str = "") -> dict:
        now = int(time.time())
        if success:
            self.conn.execute("""INSERT INTO account_collection_health
                (username,last_attempt,last_success,consecutive_failures,last_error) VALUES (?,?,?,?,?)
                ON CONFLICT(username) DO UPDATE SET last_attempt=excluded.last_attempt,
                last_success=excluded.last_success,consecutive_failures=0,last_error=''""",
                (username, now, now, 0, ""))
        else:
            self.conn.execute("""INSERT INTO account_collection_health
                (username,last_attempt,last_success,consecutive_failures,last_error) VALUES (?,?,?,?,?)
                ON CONFLICT(username) DO UPDATE SET last_attempt=excluded.last_attempt,
                consecutive_failures=account_collection_health.consecutive_failures+1,
                last_error=excluded.last_error""",
                (username, now, None, 1, error[:300]))
        self.conn.commit()
        return dict(self.conn.execute(
            "SELECT * FROM account_collection_health WHERE username=?", (username,)).fetchone())

    def notify(self, kind: str, key: str, message: str) -> bool:
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO notifications (kind,key,message,created_at) VALUES (?,?,?,?)",
            (kind, key, message[:500], int(time.time())),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def notifications(self, limit: int = 50) -> list[dict]:
        return [dict(row) for row in self.conn.execute(
            "SELECT id,kind,message,created_at,seen_at FROM notifications ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()]

    def mark_notification_seen(self, notification_id: int) -> bool:
        cursor = self.conn.execute("UPDATE notifications SET seen_at=? WHERE id=?",
                                   (int(time.time()), notification_id))
        self.conn.commit()
        return cursor.rowcount > 0

    def create_job(self, job_id: str, kind: str, shortcode: str) -> tuple[dict, bool]:
        self.conn.execute("BEGIN IMMEDIATE")
        active = self.conn.execute(
            "SELECT * FROM jobs WHERE kind=? AND shortcode=? AND status IN ('queued','running') LIMIT 1",
            (kind, shortcode),
        ).fetchone()
        if active:
            self.conn.commit()
            return self._job_dict(active), False
        now = int(time.time())
        self.conn.execute("INSERT INTO jobs (id,kind,shortcode,status,message,created_at) VALUES (?,?,?,?,?,?)",
                          (job_id, kind, shortcode, "queued", "대기 중", now))
        self.conn.commit()
        return self.job_for(job_id), True

    @staticmethod
    def _job_dict(row: sqlite3.Row) -> dict:
        result = dict(row)
        payload = result.pop("result_json")
        result["result"] = json.loads(payload) if payload else None
        return result

    def job_for(self, job_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._job_dict(row) if row else None

    def list_jobs(self, limit: int = 50) -> list[dict]:
        return [dict(row) for row in self.conn.execute(
            """SELECT id,kind,shortcode,status,progress,message,error,archived,
                      created_at,started_at,finished_at FROM jobs ORDER BY created_at DESC,id DESC LIMIT ?""",
            (limit,),
        ).fetchall()]

    def queued_jobs(self) -> list[dict]:
        return [self._job_dict(row) for row in self.conn.execute(
            "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at,id").fetchall()]

    def interrupt_running_jobs(self) -> int:
        cursor = self.conn.execute(
            "UPDATE jobs SET status='interrupted',message='서버 재시작으로 중단',finished_at=? WHERE status='running'",
            (int(time.time()),),
        )
        self.conn.commit()
        return cursor.rowcount

    def update_job(self, job_id: str, **values) -> None:
        allowed = {"status", "progress", "message", "error", "result_json", "result_path",
                   "started_at", "finished_at", "archived"}
        if not values or set(values) - allowed:
            raise ValueError("잘못된 작업 업데이트")
        self.conn.execute("UPDATE jobs SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?",
                          (*values.values(), job_id))
        self.conn.commit()

    def archive_job(self, job_id: str, archived: bool) -> bool:
        cursor = self.conn.execute("UPDATE jobs SET archived=? WHERE id=? AND status='done'",
                                   (int(archived), job_id))
        self.conn.commit()
        return cursor.rowcount > 0

    def initialize_managed_accounts(self, accounts: list[tuple[str, str]]) -> bool:
        """최초 한 번만 레거시 텍스트 목록을 가져온다. 빈 목록도 초기화 상태로 기록한다."""
        done = self.conn.execute("SELECT 1 FROM app_meta WHERE key='managed_accounts_initialized'").fetchone()
        if done:
            return False
        now = int(time.time())
        self.conn.executemany(
            "INSERT OR IGNORE INTO managed_accounts (username,note,created_at,updated_at) VALUES (?,?,?,?)",
            [(username, note, now + index, now + index) for index, (username, note) in enumerate(accounts)],
        )
        self.conn.execute("INSERT INTO app_meta (key,value) VALUES ('managed_accounts_initialized',?)", (str(now),))
        self.conn.commit()
        return True

    def managed_accounts(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT m.username,m.note,m.created_at,m.updated_at,
                      COALESCE(p.full_name,'') full_name,COALESCE(p.followers,0) followers,
                      COALESCE(p.profile_pic_url,'') profile_pic_url,p.updated_at profile_updated_at,
                      COUNT(posts.shortcode) posts_count,MAX(posts.taken_at) last_post_at
               FROM managed_accounts m
               LEFT JOIN profiles p ON p.username=m.username
               LEFT JOIN posts ON posts.username=m.username
               GROUP BY m.username
               ORDER BY m.created_at,m.username"""
        ).fetchall()
        output = []
        for row in rows:
            health = self.conn.execute(
                "SELECT * FROM account_collection_health WHERE username=?", (row["username"],)
            ).fetchone()
            output.append({**dict(row), **self.account_observation_health(row["username"]),
                           "consecutive_failures": health["consecutive_failures"] if health else 0,
                           "last_collection_success": health["last_success"] if health else None})
        return output

    def upsert_managed_account(self, username: str, note: str = "") -> bool:
        exists = self.conn.execute("SELECT 1 FROM managed_accounts WHERE username=?", (username,)).fetchone()
        now = int(time.time())
        next_order = self.conn.execute("SELECT COALESCE(MAX(created_at),0)+1 FROM managed_accounts").fetchone()[0]
        self.conn.execute(
            """INSERT INTO managed_accounts (username,note,created_at,updated_at) VALUES (?,?,?,?)
               ON CONFLICT(username) DO UPDATE SET note=excluded.note,updated_at=excluded.updated_at""",
            (username, note, next_order, now),
        )
        self.conn.commit()
        return not bool(exists)

    def delete_managed_account(self, username: str) -> bool:
        cursor = self.conn.execute("DELETE FROM managed_accounts WHERE username=?", (username,))
        self.conn.commit()
        return cursor.rowcount > 0

    # ---- read ----
    def profiles(self) -> dict[str, Profile]:
        rows = self.conn.execute("SELECT * FROM profiles").fetchall()
        out = {}
        for r in rows:
            out[r["username"]] = Profile(
                username=r["username"], user_id=r["user_id"] or "", full_name=r["full_name"] or "",
                followers=r["followers"] or 0, following=r["following"] or 0, media_count=r["media_count"] or 0,
                biography=r["biography"] or "", profile_pic_url=r["profile_pic_url"] or "",
                is_private=bool(r["is_private"]),
            )
        return out

    def posts_for(self, username: str, limit: int | None = 60) -> list[Post]:
        sql = "SELECT * FROM posts WHERE username=? ORDER BY taken_at DESC, shortcode DESC"
        rows = self.conn.execute(sql + (" LIMIT ?" if limit is not None else ""),
                                 (username, limit) if limit is not None else (username,)).fetchall()
        return [self._row_to_post(r) for r in rows]

    def criteria(self, settings: Settings) -> dict:
        row = self.conn.execute("SELECT version,updated_at,values_json FROM scoring_criteria WHERE id=1").fetchone()
        if row:
            return {"version": row["version"], "updated_at": row["updated_at"],
                    "values": json.loads(row["values_json"])}
        values = defaults(settings)
        now = int(time.time())
        self.conn.execute("INSERT OR IGNORE INTO scoring_criteria VALUES (1,1,?,?)",
                          (now, json.dumps(values, ensure_ascii=False)))
        self.conn.commit()
        return self.criteria(settings)

    def update_criteria(self, values: dict, settings: Settings) -> dict:
        values = validate(values, settings)
        current = self.criteria(settings)
        if values == current["values"]:
            return current
        now = int(time.time())
        self.conn.execute("UPDATE scoring_criteria SET version=version+1,updated_at=?,values_json=? WHERE id=1",
                          (now, json.dumps(values, ensure_ascii=False)))
        self.conn.commit()
        return self.criteria(settings)

    def snapshots_for(self, shortcode: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT collected_at, likes, comments, views FROM snapshots WHERE shortcode=? ORDER BY collected_at",
            (shortcode,),
        ).fetchall()
        return [dict(r) for r in rows]

    def observations_for(self, shortcode: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM metric_observations WHERE shortcode=? ORDER BY requested_at,id",
            (shortcode,),
        ).fetchall()
        return [dict(row) for row in rows]

    def account_observation_health(self, username: str, now: int | None = None) -> dict:
        now = now or int(time.time())
        rows = self.conn.execute(
            """SELECT COUNT(*) requests, SUM(o.success) successes
               FROM metric_observations o JOIN posts p ON p.shortcode=o.shortcode
               WHERE p.username=? AND o.requested_at>=?""",
            (username, now - 7 * 86400),
        ).fetchone()
        last_success = self.conn.execute(
            """SELECT MAX(o.observed_at) FROM metric_observations o
               JOIN posts p ON p.shortcode=o.shortcode WHERE p.username=? AND o.success=1""",
            (username,),
        ).fetchone()[0]
        videos = self.conn.execute(
            "SELECT COUNT(*) total, SUM(views IS NULL) missing FROM posts WHERE username=? AND kind IN ('reel','video')",
            (username,),
        ).fetchone()
        return {"views_missing_rate": round((videos["missing"] or 0) / max(1, videos["total"]), 3),
                "recent_success_rate": (round((rows["successes"] or 0) / rows["requests"], 3)
                                        if rows["requests"] else None),
                "last_success_observed_at": last_success}

    def last_run(self) -> dict | None:
        r = self.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else None

    def collection_status(self) -> dict:
        last = self.last_run()
        last_success = self.conn.execute(
            "SELECT * FROM runs WHERE accounts_ok>0 ORDER BY id DESC LIMIT 1").fetchone()
        newest_update = self.conn.execute("SELECT MAX(updated_at) FROM posts").fetchone()[0]
        newest_post = self.conn.execute("SELECT MAX(taken_at) FROM posts").fetchone()[0]
        state = ("none" if not last else "running" if last["finished_at"] is None else
                 "success" if last["accounts_failed"] == 0 else
                 "partial_failure" if last["accounts_ok"] else "failure")
        return {"last_run": last, "last_attempt_at": (last["finished_at"] or last["started_at"]) if last else None,
                "last_success_at": last_success["finished_at"] if last_success else None,
                "state": state, "newest_post_update": newest_update,
                "newest_published_post": newest_post}

    def register_hot_view_tracking(self, posts: list[Post], days: int, detected_at: int | None = None) -> int:
        """한 번 터진 릴스는 게시일부터 정해진 기간까지 추적 대상으로 고정한다."""
        now = detected_at or int(time.time())
        rows = [(p.shortcode, p.username, p.taken_at, p.taken_at + days * 86400, now)
                for p in posts if p.is_video and p.media_id and p.taken_at + days * 86400 >= now]
        inserted = 0
        for row in rows:
            cursor = self.conn.execute(
                """INSERT OR IGNORE INTO hot_view_tracking
                   (shortcode,username,posted_at,track_until,detected_at) VALUES (?,?,?,?,?)""", row)
            if cursor.rowcount:
                inserted += 1
                self.conn.execute(
                    "INSERT OR IGNORE INTO notifications (kind,key,message,created_at) VALUES (?,?,?,?)",
                    ("new_hot_reel", f"new-hot-{row[0]}", f"@{row[1]} 신규 터진 릴스 {row[0]} 최초 감지", now),
                )
        self.conn.commit()
        return inserted

    def tracked_hot_posts(self, username: str, now: int | None = None, limit: int = 50) -> list[Post]:
        now = now or int(time.time())
        rows = self.conn.execute(
            """SELECT posts.* FROM hot_view_tracking tracking
               JOIN posts ON posts.shortcode=tracking.shortcode
               WHERE tracking.username=? AND tracking.track_until>=?
               ORDER BY tracking.posted_at DESC LIMIT ?""",
            (username, now, limit),
        ).fetchall()
        return [self._row_to_post(row) for row in rows]

    def hot_tracking_status(self, now: int | None = None) -> dict:
        now = now or int(time.time())
        active = self.conn.execute("SELECT COUNT(*) FROM hot_view_tracking WHERE track_until>=?", (now,)).fetchone()[0]
        total = self.conn.execute("SELECT COUNT(*) FROM hot_view_tracking").fetchone()[0]
        return {"active": active, "total": total}

    def tracking_for(self, shortcode: str, now: int | None = None) -> dict | None:
        row = self.conn.execute("SELECT * FROM hot_view_tracking WHERE shortcode=?", (shortcode,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["day"] = min(14, max(0, ((now or int(time.time())) - result["posted_at"]) // 86400))
        result["successful_observations"] = self.conn.execute(
            "SELECT COUNT(*) FROM metric_observations WHERE shortcode=? AND success=1 AND views IS NOT NULL",
            (shortcode,),
        ).fetchone()[0]
        return result

    def finalize_hot_tracking(self, now: int | None = None) -> int:
        """14일 이후 추가 요청 없이 마지막 관측값과 최고 성장 지표를 고정한다."""
        from .growth import _rate, _success
        now = now or int(time.time())
        rows = self.conn.execute(
            "SELECT shortcode FROM hot_view_tracking WHERE track_until<? AND finalized_at IS NULL", (now,)
        ).fetchall()
        for row in rows:
            code = row["shortcode"]
            good = _success(self.observations_for(code))
            rates = [rate for first, last in zip(good, good[1:])
                     if (rate := _rate(first, last)) is not None]
            accelerations = [b - a for a, b in zip(rates, rates[1:])]
            fallback = self.conn.execute("SELECT views FROM posts WHERE shortcode=?", (code,)).fetchone()
            final_views = good[-1]["views"] if good else (fallback["views"] if fallback else None)
            self.conn.execute(
                """UPDATE hot_view_tracking SET finalized_at=?,final_views=?,
                   max_views_per_hour=?,max_acceleration=? WHERE shortcode=?""",
                (now, final_views, max(rates) if rates else None,
                 max(accelerations) if accelerations else None, code),
            )
        self.conn.commit()
        return len(rows)

    @staticmethod
    def _row_to_post(r: sqlite3.Row) -> Post:
        return Post(
            shortcode=r["shortcode"], username=r["username"], taken_at=r["taken_at"], kind=r["kind"],
            likes=r["likes"], comments=r["comments"], views=r["views"],
            caption=r["caption"] or "", hashtags=json.loads(r["hashtags"] or "[]"),
            thumbnail_url=r["thumbnail_url"] or "", video_duration=r["video_duration"], media_id=r["media_id"] or "",
        )

    def close(self) -> None:
        self.conn.close()
