from __future__ import annotations

from typing import Protocol

from ..models import Post, Profile
from ..observations import MetricObservation


class CollectError(Exception):
    """한 계정 수집 실패. 전체 파이프라인은 계속 진행한다."""


class Collector(Protocol):
    name: str

    def fetch(self, username: str, limit: int, existing: dict[str, Post] | None = None) -> tuple[Profile, list[Post], list[MetricObservation]]:
        """프로필, 게시물, 실제 지표 조회 결과를 돌려준다."""
        ...
