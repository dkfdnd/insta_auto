from datetime import datetime, timezone

from hotpost.config import Settings
from hotpost.models import Post, Profile
from hotpost.report import build_report
from hotpost.storage import Storage


def test_migration_keeps_earliest_tracking_and_photo_notification(tmp_path):
    path = tmp_path / 'test.db'
    store = Storage(path)
    store.conn.execute('DROP TABLE hot_detections')
    store.conn.execute('UPDATE schema_version SET version=4')
    store.conn.execute("INSERT INTO hot_view_tracking(shortcode,username,posted_at,track_until,detected_at) VALUES ('video','u',1,99999,300)")
    store.conn.executemany('INSERT INTO notifications(kind,key,message,created_at) VALUES (?,?,?,?)', [
        ('new_hot_reel', 'new-hot-video', '', 200),
        ('new_hot_post', 'new-hot-photo', '', 100),
        ('schedule_missed', 'other', '', 50),
    ])
    store.conn.commit()
    store.close()
    store = Storage(path)
    assert store.record_hot_detections([], 999) == {'video': 200, 'photo': 100}
    store.close()


def test_first_hot_date_is_stable_and_independent_of_post_date(tmp_path, monkeypatch):
    now = int(datetime(2026, 9, 27, 1, tzinfo=timezone.utc).timestamp())
    monkeypatch.setattr('hotpost.report.time.time', lambda: now)
    settings = Settings(data_dir=tmp_path, download_thumbs=False)
    store = Storage(settings.db_path)
    store.upsert_profile(Profile('u', followers=1000))
    normal = [Post(f'base{i}', 'u', now - (i + 5) * 86400, 'image', 10, 1) for i in range(10)]
    hot = Post('hot', 'u', now - 2 * 86400, 'image', 1000, 100)
    store.upsert_posts(normal + [hot])
    report = build_report(settings, store, 'browser', usernames=['u'])
    row = next(p for p in report['posts'] if p['shortcode'] == 'hot')
    assert row['tier'] > 0
    assert row['hot_detected_at'] == now
    assert row['hot_detected_date_kst'] == '2026-09-27'
    assert next(p for p in report['posts'] if p['shortcode'] == 'base0')['hot_detected_at'] is None
    now += 86400
    report = build_report(settings, store, 'browser', usernames=['u'])
    assert next(p for p in report['posts'] if p['shortcode'] == 'hot')['hot_detected_date_kst'] == '2026-09-27'
    # Reopening and rescanning must not turn yesterday's hot item into today's.
    store.close()
    store = Storage(settings.db_path)
    assert store.record_hot_detections([hot], now)['hot'] == now - 86400
    store.close()


def test_old_hot_without_history_is_not_backdated_to_today(tmp_path):
    store = Storage(tmp_path / 'test.db')
    old = Post('old', 'u', 1, 'image')
    new = Post('new', 'u', 1, 'reel')
    dates = store.record_hot_detections([old, new], 1000, legacy_hot_codes=['old'])
    assert dates == {'new': 1000}
    assert store.record_hot_detections([old, new], 2000) == {'new': 1000}
    store.close()
