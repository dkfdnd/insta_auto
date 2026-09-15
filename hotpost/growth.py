"""실제로 성공한 조회수 관측으로 최근 성장·가속도를 계산한다."""
from __future__ import annotations

import statistics


def _success(rows: list[dict]) -> list[dict]:
    return sorted((row for row in rows if row.get("success") and row.get("views") is not None
                   and row.get("observed_at") is not None), key=lambda row: row["observed_at"])


def _rate(first: dict, last: dict) -> float | None:
    hours = (last["observed_at"] - first["observed_at"]) / 3600
    if not 3 <= hours <= 30:
        return None
    return max(0.0, (last["views"] - first["views"]) / hours)


def growth_signal(rows: list[dict], now: int, age_hours: float,
                  peer_histories: list[list[dict]] | None = None,
                  fallback_multiplier: float = 1.0) -> dict:
    good = _success(rows)
    current = previous = None
    if (len(good) >= 2 and now - good[-1]["observed_at"] <= 24 * 3600
            and good[-2]["observed_at"] >= now - 30 * 3600):
        current = _rate(good[-2], good[-1])
    if current is not None and len(good) >= 3:
        previous = _rate(good[-3], good[-2])
    acceleration = current - previous if current is not None and previous is not None else None
    if current is None:
        state = "조회 데이터 부족"
    elif acceleration is not None and previous is not None and acceleration > max(1, previous * .1):
        state = "상승 가속"
    elif acceleration is not None and previous is not None and acceleration < -max(1, previous * .1):
        state = "상승 둔화"
    elif current > 0:
        state = "현재 상승 중"
    else:
        state = "조회 데이터 부족"

    peer_rates = []
    for history in peer_histories or []:
        matching = [row for row in _success(history)
                    if abs(row.get("age_hours", -1000) - age_hours) <= 30]
        if len(matching) >= 2:
            rate = _rate(matching[-2], matching[-1])
            if rate is not None:
                peer_rates.append(rate)
    if current is not None and len(peer_rates) >= 3:
        median_rate = statistics.median(peer_rates)
        comparison = {"mode": "age_matched", "peers": len(peer_rates),
                      "ratio": round(current / median_rate, 2) if median_rate > 0 else None,
                      "confidence": "high"}
    else:
        comparison = {"mode": "median_fallback", "peers": len(peer_rates),
                      "ratio": round(fallback_multiplier, 2), "confidence": "low"}
    return {"state": state, "views_per_hour": round(current, 2) if current is not None else None,
            "acceleration": round(acceleration, 2) if acceleration is not None else None,
            "previous_views_per_hour": round(previous, 2) if previous is not None else None,
            "successful_observations": len(good), "last_success_at": good[-1]["observed_at"] if good else None,
            "comparison": comparison}
