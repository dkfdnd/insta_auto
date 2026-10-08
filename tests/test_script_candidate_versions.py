import copy
import pytest

from hotpost.script_candidate_versions import add_candidate, digest
from hotpost.studio_store import StudioStore, Conflict


@pytest.fixture
def ready(tmp_path):
    store = StudioStore(tmp_path)
    state, _ = store.create('fixture', '완성된 영상', {'protocol': 2, 'active': False, 'stage': 'completed'})
    def prepare(s, db):
        db.execute("UPDATE jobs SET status='done'")
        s.update(original_text='원본 발화', status='completed', script_id='s1', voice_id='v1', edit_id='e1',
                 approved_script_id='s1', selected_candidate=0, top_pick={'index': 0},
                 feedback={'script_text': '사용자가 수정 중인 대본'},
                 scripts=[{'id': 's1', 'text': '선택 대본'}], voices=[{'id': 'v1', 'script_id': 's1'}],
                 edits=[{'id': 'e1', 'script_id': 's1', 'voice_id': 'v1'}],
                 runs=[{'id': 'r1', 'status': 'completed'}],
                 script_candidates=[{'text': '이전 후보'}])
    return store, store.change(state['id'], prepare)


def payload(state):
    return {'text': '원본과 대조해 새로 쓴 후보예요.', 'reference_sha256': digest('원본 발화'),
            'writing_contract': {'version': 'test-policy', 'sha256': 'a'*64},
            'revision': state['revision'], 'review_notes': ['화자 경험을 시청자 상황으로 바꿈']}


def test_additive_candidate_preserves_all_production_state_and_queue(ready):
    store, before = ready
    jobs = store.jobs(before['id'])
    after = add_candidate(store, before['id'], payload(before))
    for key, value in before.items():
        if key not in {'revision', 'updated', 'script_candidates'}:
            assert after[key] == value, key
    assert after['script_candidates'][:-1] == before['script_candidates']
    assert after['script_candidates'][-1]['user_approved'] is False
    assert after['script_candidates'][-1]['editorial_review']['status'] == 'not_evaluated'
    assert after['script_candidate_revisions'] == [after['script_candidates'][-1]]
    assert store.jobs(before['id']) == jobs
    # Replaying a receipt is a no-op even though the caller's revision is old.
    assert add_candidate(store, before['id'], payload(before)) == after


def test_new_source_and_concurrent_feedback_cannot_be_overwritten(ready):
    store, before = ready
    request = payload(before)
    store.change(before['id'], lambda s, db: s.update(reviewed_original_text='다른 원본'))
    with pytest.raises(Conflict, match='원본'):
        add_candidate(store, before['id'], request)
    fresh = store.get(before['id']); request['reference_sha256'] = digest('다른 원본')
    with pytest.raises(Conflict, match='최신'):
        add_candidate(store, before['id'], request)
    assert store.get(before['id']) == fresh


def test_pending_rewrite_cannot_erase_a_new_candidate(ready):
    store, before = ready
    store.change(before['id'], lambda s, db: store.enqueue(db, s['id'], 'rewrite', {}, 'new-rewrite'))
    fresh = store.get(before['id']); request = payload(fresh)
    with pytest.raises(Conflict, match='생성'):
        add_candidate(store, before['id'], request)
    assert store.get(before['id']) == fresh


def test_archive_survives_regeneration_and_is_not_duplicated_on_restore(ready):
    store, before = ready
    saved = add_candidate(store, before['id'], payload(before))
    archived = copy.deepcopy(saved['script_candidate_revisions'])
    refreshed = store.change(before['id'], lambda s, db: s.update(script_candidates=[{'text': '새 생성 후보'}]))
    restored = add_candidate(store, before['id'], payload(refreshed))
    assert restored['script_candidate_revisions'] == archived
    assert restored['script_candidates'][-1] == archived[0]
