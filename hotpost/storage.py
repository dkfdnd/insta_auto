"""SQLite 저장소.

- profiles : 계정 최신 정보
- posts    : 게시물 최신 지표 (upsert)
- snapshots: 수집 시점마다의 지표 기록 → 시간에 따른 증가 속도(velocity) 계산용
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .models import Post, Profile
from .config import Settings
from .criteria import defaults, validate

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
"""


class Storage:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

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

    def upsert_posts(self, posts: list[Post], collected_at: int | None = None) -> None:
        now = collected_at or int(time.time())
        for p in posts:
            self.conn.execute(
                """INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(shortcode) DO UPDATE SET
                     likes=excluded.likes, comments=excluded.comments, views=excluded.views,
                     caption=excluded.caption, hashtags=excluded.hashtags, thumbnail_url=excluded.thumbnail_url,
                     video_duration=excluded.video_duration, media_id=excluded.media_id, kind=excluded.kind,
                     updated_at=excluded.updated_at""",
                (p.shortcode, p.username, p.taken_at, p.kind, p.likes, p.comments, p.views,
                 p.caption, json.dumps(p.hashtags, ensure_ascii=False), p.thumbnail_url,
                 p.video_duration, p.media_id, now, now),
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?)",
                (p.shortcode, now, p.likes, p.comments, p.views),
            )
        self.conn.commit()

    def record_run(self, started: int, source: str, ok: int, failed: int, posts: int, notes: str = "") -> None:
        self.conn.execute(
            "INSERT INTO runs (started_at, finished_at, source, accounts_ok, accounts_failed, posts, notes) VALUES (?,?,?,?,?,?,?)",
            (started, int(time.time()), source, ok, failed, posts, notes),
        )
        self.conn.commit()

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
        return [dict(row) for row in rows]

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

    def last_run(self) -> dict | None:
        r = self.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else None

    def collection_status(self) -> dict:
        last = self.last_run()
        newest_update = self.conn.execute("SELECT MAX(updated_at) FROM posts").fetchone()[0]
        newest_post = self.conn.execute("SELECT MAX(taken_at) FROM posts").fetchone()[0]
        return {"last_run": last, "newest_post_update": newest_update, "newest_published_post": newest_post}

    def register_hot_view_tracking(self, posts: list[Post], days: int, detected_at: int | None = None) -> int:
        """한 번 터진 릴스는 게시일부터 정해진 기간까지 추적 대상으로 고정한다."""
        now = detected_at or int(time.time())
        rows = [(p.shortcode, p.username, p.taken_at, p.taken_at + days * 86400, now)
                for p in posts if p.is_video and p.media_id and p.taken_at + days * 86400 >= now]
        before = self.conn.total_changes
        self.conn.executemany(
            """INSERT OR IGNORE INTO hot_view_tracking
               (shortcode,username,posted_at,track_until,detected_at) VALUES (?,?,?,?,?)""", rows)
        self.conn.commit()
        return self.conn.total_changes - before

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
