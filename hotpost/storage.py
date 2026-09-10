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

    def posts_for(self, username: str, limit: int = 60) -> list[Post]:
        rows = self.conn.execute(
            "SELECT * FROM posts WHERE username=? ORDER BY taken_at DESC LIMIT ?", (username, limit)
        ).fetchall()
        return [self._row_to_post(r) for r in rows]

    def snapshots_for(self, shortcode: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT collected_at, likes, comments, views FROM snapshots WHERE shortcode=? ORDER BY collected_at",
            (shortcode,),
        ).fetchall()
        return [dict(r) for r in rows]

    def last_run(self) -> dict | None:
        r = self.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else None

    @staticmethod
    def _row_to_post(r: sqlite3.Row) -> Post:
        return Post(
            shortcode=r["shortcode"], username=r["username"], taken_at=r["taken_at"], kind=r["kind"],
            likes=r["likes"] or 0, comments=r["comments"] or 0, views=r["views"],
            caption=r["caption"] or "", hashtags=json.loads(r["hashtags"] or "[]"),
            thumbnail_url=r["thumbnail_url"] or "", video_duration=r["video_duration"], media_id=r["media_id"] or "",
        )

    def close(self) -> None:
        self.conn.close()
