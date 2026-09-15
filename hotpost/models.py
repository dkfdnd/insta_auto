from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Profile:
    username: str
    user_id: str = ""
    full_name: str = ""
    followers: int = 0
    following: int = 0
    media_count: int = 0
    biography: str = ""
    profile_pic_url: str = ""
    is_private: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Post:
    shortcode: str
    username: str
    taken_at: int                    # unix epoch (UTC)
    kind: str                        # 'reel' | 'video' | 'image' | 'carousel'
    likes: Optional[int] = 0       # None: 숨김/조회 불가, 0: 실제 관측된 0
    comments: Optional[int] = 0
    views: Optional[int] = None      # 릴스/동영상 조회수 (사진은 None)
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    thumbnail_url: str = ""
    video_duration: Optional[float] = None
    media_id: str = ""

    @property
    def url(self) -> str:
        seg = "reel" if self.kind in ("reel", "video") else "p"
        return f"https://www.instagram.com/{seg}/{self.shortcode}/"

    @property
    def is_video(self) -> bool:
        return self.kind in ("reel", "video")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["url"] = self.url
        return d
