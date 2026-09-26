"""분석 결과를 report.json + web/data.js 로 내보낸다."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta

from . import __version__
from .analyze import Scored, extract_topics, score_account, post_terms, assessment
from .config import Settings
from .storage import Storage
from .criteria import defaults
from .growth import growth_signal
from .thumbs import ensure_thumbnail

KST = timezone(timedelta(hours=9))


def build_report(settings: Settings, store: Storage, source: str, notes: list[str] | None = None,
                 usernames: list[str] | None = None) -> dict:
    now = int(time.time())
    store.finalize_hot_tracking(now)
    profiles = store.profiles()
    active_criteria = store.criteria(settings)
    all_scored: list[Scored] = []
    growth_by_code: dict[str, dict] = {}
    observations_by_code: dict[str, list[dict]] = {}
    post_updated = {row['shortcode']: row['updated_at'] for row in
                    store.conn.execute('SELECT shortcode,updated_at FROM posts')}
    accounts_out = []
    allowed = set(usernames) if usernames is not None else None
    for username, prof in sorted(profiles.items()):
        if allowed is not None and username not in allowed:
            continue
        posts = store.posts_for(username, limit=None)
        if not posts:
            continue
        snaps = {p.shortcode: store.snapshots_for(p.shortcode) if not p.is_video else [] for p in posts}
        histories = {p.shortcode: store.observations_for(p.shortcode) for p in posts if p.is_video}
        video_by_code = {p.shortcode: p for p in posts if p.is_video}
        observations_by_code.update(histories)
        scored = score_account(posts, settings, now=now, snapshots=snaps,
                               criteria=active_criteria["values"], followers=prof.followers)
        recent = [s for s in scored if s.age_hours <= settings.recent_days * 24]
        for s in recent:
            if s.post.is_video:
                peers = [history for code, history in histories.items()
                         if code != s.post.shortcode and video_by_code[code].taken_at < s.post.taken_at]
                growth_by_code[s.post.shortcode] = growth_signal(
                    histories[s.post.shortcode], now, s.age_hours, peers, s.multiplier)
        all_scored.extend(recent)
        videos = [p for p in posts if p.is_video and p.views]
        best = max(recent, key=lambda s: s.multiplier) if recent else None
        accounts_out.append({
            **prof.to_dict(),
            **store.account_observation_health(username, now),
            "posts_analyzed": len(posts),
            "posts_recent": len(recent),
            "hot_recent": sum(1 for s in recent if s.tier >= 1),
            "hot_7d": sum(1 for s in recent if s.tier >= 1 and s.age_hours <= 24 * 7),
            "median_likes": _median([p.likes for p in posts]),
            "median_comments": _median([p.comments for p in posts]),
            "median_views": _median([p.views for p in videos]) if videos else None,
            "reel_share": round(sum(1 for p in posts if p.is_video) / len(posts), 2),
            "best_recent": best.post.shortcode if best else None,
            "last_post_at": max(p.taken_at for p in posts),
        })

    all_scored.sort(key=lambda s: (s.rank_score, s.post.taken_at), reverse=True)
    terms_by_code = post_terms([s.post for s in all_scored])
    posts_out = []
    for s in all_scored:
        thumb = ensure_thumbnail(settings, s.post)
        d = s.post.to_dict()
        d.update({
            "metric_status": {"likes": "missing" if s.post.likes is None else "observed",
                              "comments": "missing" if s.post.comments is None else "observed",
                              "views": ("not_applicable" if not s.post.is_video else
                                        "missing" if s.post.views is None else
                                        "legacy_unverified" if not observations_by_code.get(s.post.shortcode) else
                                        "observed" if observations_by_code[s.post.shortcode][-1]["success"] else
                                        "stale")},
            "thumb": thumb,
            "baseline": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in s.baseline.items()},
            "ratios": {k: (round(v, 2) if v is not None else None) for k, v in s.ratios.items()},
            "multiplier": round(s.multiplier, 2),
            "tier": s.tier,
            "rank_score": round(s.rank_score, 3),
            "age_hours": round(s.age_hours, 1),
            "maturity": round(s.maturity, 2),
            "flags": s.flags,
            "confidence": s.confidence,
            "velocity": s.velocity,
            "growth": growth_by_code.get(s.post.shortcode),
            "tracking": store.tracking_for(s.post.shortcode, now) if s.post.is_video else None,
            "assessment": assessment(s, observations_by_code.get(s.post.shortcode, []), now,
                                     settings, active_criteria['values'], post_updated.get(s.post.shortcode)),
            "terms": terms_by_code.get(s.post.shortcode, []),
        })
        posts_out.append(d)

    topics = extract_topics(all_scored, settings)
    hot = [p for p in posts_out if p["tier"] >= 1]
    store.register_hot_view_tracking(
        [scored.post for scored in all_scored if scored.tier >= 1], settings.hot_view_tracking_days, now
    )
    if source != "demo":
        last_run = store.last_run()
        if last_run:
            for scored in all_scored:
                if scored.tier < 1 or scored.post.is_video:
                    continue
                first_seen = store.conn.execute(
                    "SELECT first_seen FROM posts WHERE shortcode=?", (scored.post.shortcode,)
                ).fetchone()
                if first_seen and first_seen[0] >= last_run["started_at"]:
                    store.notify("new_hot_post", f"new-hot-{scored.post.shortcode}",
                                 f"@{scored.post.username} 신규 터진 게시물 {scored.post.shortcode} 최초 감지")
    report = {
        "version": __version__,
        "generated_at": now,
        "generated_at_kst": datetime.fromtimestamp(now, KST).strftime("%Y-%m-%d %H:%M"),
        "source": source,
        "is_sample": source == "demo",
        "notes": notes or [],
        "criteria": active_criteria,
        "criteria_defaults": defaults(settings),
        "last_data_update_at": max(post_updated.values(), default=None),
        "settings": {
            "recent_days": settings.recent_days,
            "collect_posts_per_account": settings.collect_posts_per_account,
            "hot_multiplier": active_criteria["values"]["t1"],
            "tier2_multiplier": active_criteria["values"]["t2"],
            "tier3_multiplier": active_criteria["values"]["t3"],
            "posts_per_account": settings.posts_per_account,
            "maturity_hours": settings.maturity_hours,
            "min_engagement": active_criteria["values"]["minEng"],
        },
        "weights": {"video": {"views": 0.5, "comments": 0.3, "likes": 0.2}, "image": {"likes": 0.6, "comments": 0.4}},
        "summary": {
            "accounts": len(accounts_out),
            "posts": len(posts_out),
            "hot": len(hot),
            "confirmed_hot": sum(p['assessment']['status'] == 'confirmed' for p in hot),
            "provisional_hot": sum(p['assessment']['status'] == 'provisional' for p in hot),
            "hot_24h": sum(1 for p in hot if p["age_hours"] <= 24),
            "hot_7d": sum(1 for p in hot if p["age_hours"] <= 24 * 7),
            "reels": sum(1 for p in posts_out if p["kind"] in ("reel", "video")),
        },
        "topics": topics,
        "accounts": accounts_out,
        "posts": posts_out,
    }
    from .acquisition import candidates
    report['acquisition_candidates'] = candidates(report, settings)
    report['acquisition_policy'] = {
        'min_views_per_follower': settings.acquisition_min_views_per_follower,
        'min_views': settings.acquisition_min_views,
        'daily_limit': settings.acquisition_daily_limit,
    }
    return report


def write_report(settings: Settings, report: dict) -> None:
    report_tmp = settings.report_path.with_suffix(".json.tmp")
    report_tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    report_tmp.replace(settings.report_path)
    js = "window.HOTPOST_REPORT = " + json.dumps(report, ensure_ascii=False) + ";\n"
    data_path = settings.web_dir / "data.js"
    data_tmp = data_path.with_suffix(".js.tmp")
    data_tmp.write_text(js, encoding="utf-8")
    data_tmp.replace(data_path)


def _median(xs):
    import statistics
    xs = [x for x in xs if x is not None]
    return round(float(statistics.median(xs)), 1) if xs else 0
