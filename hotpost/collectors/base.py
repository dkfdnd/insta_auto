from __future__ import annotations

from typing import Protocol

from ..models import Post, Profile


class CollectError(Exception):
    """한 계정 수집 실패. 전체 파이프라인은 계속 진행한다."""


class Collector(Protocol):
    name: str

    def fetch(self, username: str, limit: int, existing: dict[str, Post] | None = None) -> tuple[Profile, list[Post]]:
        """프로필과 최근 게시물 `limit` 개를 돌려준다. `existing` 은 DB 에 이미 있는 같은 계정 게시물."""
        ...
