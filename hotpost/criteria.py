"""서버와 화면이 공유하는 판정 기준 및 입력 검증."""
from __future__ import annotations

import math

from .config import Settings


def defaults(settings: Settings) -> dict:
    return {
        "t1": settings.hot_multiplier, "t2": settings.tier2_multiplier,
        "t3": settings.tier3_multiplier,
        "wvViews": 50, "wvComments": 30, "wvLikes": 20,
        "wiLikes": 60, "wiComments": 40,
        "minRatioViews": 0, "minRatioComments": 0, "minRatioLikes": 0,
        "minViews": 0, "minComments": 0, "minLikes": 0,
        "minEng": settings.min_engagement,
        "followersMin": 0, "followersMax": 0,
        "confidence": "all", "maturity": True,
    }


def validate(raw: dict, settings: Settings) -> dict:
    if not isinstance(raw, dict) or set(raw) != set(defaults(settings)):
        raise ValueError("판정 기준 필드가 누락되었거나 알 수 없는 필드가 있습니다.")
    result = {}
    for key, value in raw.items():
        if key == "confidence":
            if value not in ("all", "medium", "high"):
                raise ValueError("잘못된 신뢰도 기준")
        elif key == "maturity":
            if not isinstance(value, bool):
                raise ValueError("maturity는 boolean이어야 합니다.")
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"잘못된 숫자 기준: {key}")
            if key.startswith("w") and value > 100:
                raise ValueError(f"가중치는 100 이하이어야 합니다: {key}")
        result[key] = value
    if not (1 <= result["t1"] <= result["t2"] <= result["t3"]):
        raise ValueError("등급 배수는 1 이상이며 오름차순이어야 합니다.")
    if sum(result[k] for k in ("wvViews", "wvComments", "wvLikes")) <= 0 or sum(result[k] for k in ("wiLikes", "wiComments")) <= 0:
        raise ValueError("가중치 합은 0보다 커야 합니다.")
    if result["followersMin"] and result["followersMax"] and result["followersMin"] > result["followersMax"]:
        raise ValueError("팔로워 범위가 잘못되었습니다.")
    return result
