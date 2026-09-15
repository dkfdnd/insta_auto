"""Instagram 지표 조회 요청의 성공과 실패를 구분하는 계약."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MetricObservation:
    shortcode: str
    requested_at: int
    observed_at: int | None
    success: bool
    views: int | None
    likes: int | None
    comments: int | None
    source: str
    http_status: int | None = None
    reason: str = ""
    age_hours: float = 0.0
    scope: str = "latest"
