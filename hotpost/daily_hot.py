"""Daily production eligibility follows the first hot detection in Korea."""
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def date_key(seconds):
    return datetime.fromtimestamp(seconds, KST).strftime('%Y-%m-%d') if seconds is not None and seconds > 0 else None


def daily_state(post, now):
    detected = post.get('hot_detected_at')
    day = date_key(detected)
    today = date_key(now)
    hot = post.get('tier', 0) >= 1
    return {'hot_today': hot and day == today,
            'benchmark_consumed': hot and (day is None or day < today),
            'benchmark_day_kst': day}


def priority(post, now):
    return (daily_state(post, now)['hot_today'], post.get('rank_score', 0), post.get('taken_at', 0))
