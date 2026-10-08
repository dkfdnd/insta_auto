from datetime import datetime, timezone

from hotpost.daily_hot import daily_state, priority
from hotpost.config import Settings
from hotpost.studio_automation import top_two


def test_midnight_consumes_previous_detection_without_changing_history():
    now = datetime(2026, 10, 4, 15, tzinfo=timezone.utc).timestamp()
    old = {'tier': 3, 'hot_detected_at': now-1, 'rank_score': 100}
    new = {'tier': 1, 'hot_detected_at': now, 'rank_score': 2}
    assert daily_state(old, now)['benchmark_consumed']
    assert daily_state(new, now)['hot_today']
    assert sorted([old, new], key=lambda p: priority(p, now), reverse=True) == [new, old]
    assert old['hot_detected_at'] == now-1
    assert daily_state({'tier': 3}, now)['benchmark_consumed']
    assert not daily_state({'tier': 0}, now)['benchmark_consumed']


def test_daily_selection_has_no_previous_day_fallback():
    now = datetime(2026, 10, 4, 15, tzinfo=timezone.utc).timestamp()
    old = {'shortcode': 'old', 'kind': 'reel', 'tier': 3, 'taken_at': now-86400,
           'hot_detected_at': now-1, 'rank_score': 100}
    new = {**old, 'shortcode': 'new', 'taken_at': now-20*86400,
           'hot_detected_at': now, 'rank_score': 1,
           'metric_status': {'views': 'observed'}, 'views': 5000,
           'assessment': {'last_observed_at': now}}
    assert top_two({'generated_at': now, 'posts': [old, new]}, Settings(), now)[0]['shortcode'] == 'new'
    assert top_two({'generated_at': now, 'posts': [old]}, Settings(), now) == []


def test_rollover_pauses_automatic_but_explicit_batch_has_priority(tmp_path):
    import time
    from hotpost.studio_store import StudioStore
    store = StudioStore(tmp_path)
    old, _ = store.create('old', 'old', {'active':True, 'protocol':2,
        'selection_mode':'automatic', 'selected_at':time.time()-86400})
    manual, _ = store.create('manual', 'manual')
    requested, _ = store.create('requested', 'requested', {'active':True, 'protocol':2,
        'selection_mode':'user_batch', 'selected_at':time.time()-86400, 'priority':100})
    assert store.claim()['task_id'] == requested['id']
    assert store.jobs(old['id'])[0]['status'] == 'paused'
    assert store.get(old['id'])['automation']['consumed_by_daily_policy']
    assert store.claim()['task_id'] == manual['id']
    assert store.claim() is None


def test_current_automatic_and_completed_history_do_not_break_claim(tmp_path):
    import time
    from hotpost.studio_store import StudioStore
    store = StudioStore(tmp_path)
    done, _ = store.create('done', 'done', {'active':True, 'protocol':2,
        'selection_mode':'automatic', 'selected_at':time.time()-86400})
    store.change(done['id'], lambda s, db: s.update(status='completed'))
    with store.transaction() as db:
        db.execute("UPDATE jobs SET status='done' WHERE task_id=?", (done['id'],))
    current, _ = store.create('current', 'current', {'active':True, 'protocol':2,
        'selection_mode':'automatic', 'selected_at':time.time()})
    assert store.claim()['task_id'] == current['id']
    assert store.get(current['id'])['message'] == '자료 준비 진행 중'
    assert store.get(done['id'])['status'] == 'completed'
    assert store.claim() is None


def test_all_selected_daily_batch_keeps_working_after_midnight(tmp_path):
    import time
    from hotpost.studio_store import StudioStore
    store = StudioStore(tmp_path)
    state, _ = store.create('all-batch', 'all-batch', {'active':True, 'protocol':2,
        'selection_mode':'automatic', 'selected_at':time.time()-86400, 'finish_selected_batch':True})
    assert store.claim()['task_id'] == state['id']
    assert store.get(state['id'])['automation']['active']
    assert not store.get(state['id'])['automation'].get('consumed_by_daily_policy')
