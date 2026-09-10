"""브라우저에서 덤프한 JSON 을 읽어들이는 임포터.

tools/browser_dump.js 를 로그인된 인스타그램 탭 콘솔에서 실행하면
아래 형식의 JSON 이 다운로드된다. `python -m hotpost import <파일>` 로 넣는다.

{
  "generated_at": 1700000000,
  "accounts": [
    {"profile": {"username": "...", "user_id": "...", "followers": 123, ...},
     "posts": [{"shortcode": "...", "taken_at": 1700000000, "kind": "reel",
                "likes": 1, "comments": 2, "views": 3, "caption": "...", "thumbnail_url": "..."}]}
  ]
}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..models import Post, Profile

_HASHTAG_RE = re.compile(r"#([\w가-힣]+)")


def load_dump(path: Path) -> list[tuple[Profile, list[Post]]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for acc in data.get("accounts", []):
        pr = acc.get("profile", {})
        profile = Profile(
            username=pr["username"].lower(), user_id=str(pr.get("user_id", "")),
            full_name=pr.get("full_name", ""), followers=int(pr.get("followers", 0) or 0),
            following=int(pr.get("following", 0) or 0), media_count=int(pr.get("media_count", 0) or 0),
            biography=pr.get("biography", ""), profile_pic_url=pr.get("profile_pic_url", ""),
            is_private=bool(pr.get("is_private", False)),
        )
        posts = []
        for p in acc.get("posts", []):
            caption = p.get("caption") or ""
            posts.append(Post(
                shortcode=p["shortcode"], username=profile.username, taken_at=int(p["taken_at"]),
                kind=p.get("kind", "image"), likes=int(p.get("likes", 0) or 0),
                comments=int(p.get("comments", 0) or 0),
                views=(int(p["views"]) if p.get("views") is not None else None),
                caption=caption, hashtags=[h.lower() for h in _HASHTAG_RE.findall(caption)],
                thumbnail_url=p.get("thumbnail_url", ""), video_duration=p.get("video_duration"),
                media_id=str(p.get("media_id", "")),
            ))
        out.append((profile, posts))
    return out
