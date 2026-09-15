import sqlite3
import time

from hotpost.growth import growth_signal
from hotpost.models import Post
from hotpost.observations import MetricObservation
from hotpost.storage import Storage
from hotpost.config import Settings
from hotpost.collectors.web_graphql import WebGraphQLCollector


def _row(at, views, age=24, success=True):
    return {"observed_at": at if success else None, "requested_at": at,
            "success": int(success), "views": views if success else None, "age_hours": age}


def test_recent_successful_intervals_acceleration_and_failure():
    now = 1_800_000_000
    rows = [_row(now - 48 * 3600, 100), _row(now - 24 * 3600, 300), _row(now, 700)]
    result = growth_signal(rows, now, 48)
    assert result["state"] == "상승 가속"
    assert result["views_per_hour"] == round(400 / 24, 2)
    assert result["acceleration"] == round(200 / 24, 2)
    assert result["comparison"]["confidence"] == "low"

    rows[-1] = _row(now, None, success=False)
    failed = growth_signal(rows, now, 48)
    assert failed["state"] == "조회 데이터 부족"
    assert failed["views_per_hour"] is None
    assert failed["successful_observations"] == 2

    slowing = growth_signal([_row(now - 48 * 3600, 100), _row(now - 24 * 3600, 500),
                             _row(now, 600)], now, 48)
    assert slowing["state"] == "상승 둔화"


def test_age_matched_curves_and_median_fallback():
    now = 1_800_000_000
    rows = [_row(now - 24 * 3600, 100, age=24), _row(now, 340, age=48)]
    histories = [[_row(now - (i + 5) * 86400, 100, age=24),
                  _row(now - (i + 4) * 86400, 220, age=48)] for i in range(3)]
    matched = growth_signal(rows, now, 48, histories, fallback_multiplier=4)
    assert matched["comparison"] == {"mode": "age_matched", "peers": 3,
                                      "ratio": 2.0, "confidence": "high"}
    fallback = growth_signal(rows, now, 48, histories[:1], fallback_multiplier=4)
    assert fallback["comparison"]["mode"] == "median_fallback"
    assert fallback["comparison"]["ratio"] == 4
    assert fallback["comparison"]["confidence"] == "low"


def test_observations_preserve_snapshots_and_tracking_through_migration(tmp_path):
    path = tmp_path / "hotpost.db"
    legacy = sqlite3.connect(path)
    legacy.execute("""CREATE TABLE hot_view_tracking (
        shortcode TEXT PRIMARY KEY, username TEXT, posted_at INTEGER, track_until INTEGER,
        detected_at INTEGER)""")
    legacy.execute("INSERT INTO hot_view_tracking VALUES ('old','u',100,200,110)")
    legacy.execute("""CREATE TABLE snapshots (
        shortcode TEXT, collected_at INTEGER, likes INTEGER, comments INTEGER, views INTEGER,
        PRIMARY KEY(shortcode,collected_at))""")
    legacy.execute("INSERT INTO snapshots VALUES ('old',120,10,1,100)")
    legacy.commit(); legacy.close()

    store = Storage(path)
    assert store.hot_tracking_status(now=150) == {"active": 1, "total": 1}
    assert store.snapshots_for("old")[0]["views"] == 100
    assert store.observations_for("old") == []
    now = int(time.time())
    post = Post("old", "u", now - 10 * 86400, "reel", 20, 2, 100, media_id="m")
    store.upsert_posts([post], collected_at=now)
    success = MetricObservation("old", now + 10, now + 10, True, 150, 20, 2,
                                "test", age_hours=240, scope="tracking")
    failure = MetricObservation("old", now + 20, None, False, None, None, None,
                                "test", http_status=429, reason="rate_limited",
                                age_hours=240, scope="tracking")
    store.upsert_posts([post], collected_at=now + 10, observations=[success])
    store.upsert_posts([post], collected_at=now + 20, observations=[failure])
    rows = store.observations_for("old")
    assert len(rows) == 2 and rows[0]["views"] == 150
    assert rows[1]["success"] == 0 and rows[1]["views"] is None
    assert store.snapshots_for("old")[-1]["views"] is None
    assert store.posts_for("u")[0].views == 150
    assert store.hot_tracking_status(now=150)["total"] == 1
    store.close()


def test_tracking_finishes_after_fourteen_days_without_new_requests(tmp_path):
    store = Storage(tmp_path / "db.sqlite")
    now = int(time.time())
    posted = now - 15 * 86400
    post = Post("finished", "u", posted, "reel", 100, 10, 5000, media_id="m")
    store.upsert_posts([post], collected_at=now)
    store.conn.execute("INSERT INTO hot_view_tracking (shortcode,username,posted_at,track_until,detected_at) VALUES (?,?,?,?,?)",
                       ("finished", "u", posted, posted + 14 * 86400, posted + 86400))
    store.conn.commit()
    assert store.tracked_hot_posts("u", now=now) == []
    assert store.finalize_hot_tracking(now=now) == 1
    result = store.tracking_for("finished", now=now)
    assert result["finalized_at"] == now and result["final_views"] == 5000
    assert store.finalize_hot_tracking(now=now + 1) == 0
    store.close()


def test_collector_records_429_and_observed_zero_without_reusing_failure(tmp_path):
    class Response:
        def __init__(self, status, item=None):
            self.status_code = status
            self.ok = status == 200
            self.item = item
        def json(self):
            return {"items": [self.item]} if self.item is not None else {}
    class Session:
        def __init__(self, response):
            self.response = response
            self.calls = 0
        def get(self, *_args, **_kwargs):
            self.calls += 1
            return self.response

    collector = WebGraphQLCollector.__new__(WebGraphQLCollector)
    collector.settings = Settings(data_dir=tmp_path)
    collector._api_headers = lambda _url: {}
    collector._sleep = lambda *_args: None
    now = int(time.time())
    post = Post("fresh", "u", now - 86400, "reel", 10, 1, None, media_id="m")
    collector.s = Session(Response(429))
    failed = collector._fill_video_views({post.shortcode: post}, {})
    assert len(failed) == 1 and not failed[0].success
    assert failed[0].http_status == 429 and failed[0].reason == "rate_limited"
    assert post.views is None

    collector.s = Session(Response(200, {"play_count": 0}))
    observed = collector._fill_video_views({post.shortcode: post}, {})
    assert observed[0].success and observed[0].views == 0
    expired = Post("expired", "u", now - 15 * 86400, "reel", 10, 1, 100, media_id="old")
    assert collector.refresh_video_views([expired]) == []
    assert collector.s.calls == 1
