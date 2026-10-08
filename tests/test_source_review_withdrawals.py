import copy
import json
from types import SimpleNamespace

import pytest

from hotpost.source_review_withdrawals import apply_withdrawals, validate_plan


@pytest.fixture
def withdrawn(tmp_path):
    digest = 'a'*64
    root = tmp_path/'source_review_withdrawals'
    root.mkdir()
    path = root/f'{digest}.json'
    path.write_text(json.dumps({'source_sha256': digest, 'intervals': [{
        'source_start': 4., 'source_end': 8., 'evidence': 'actual-export-frame.png',
        'reason': 'Trailing original subtitle outside the blur'}]}))
    spans = [{'source_start': 0., 'source_end': 4.}, {'source_start': 4., 'source_end': 8.}]
    source = {'id': 'source-a', 'sha256': digest, 'reviewed_intervals': copy.deepcopy(spans),
              'editing_eligible': True, 'functional_review': {'reviewed': True}, 'source_role': 'core',
              'watermark_masks': copy.deepcopy(spans), 'mask_review': {
                  'intervals': copy.deepcopy(spans), 'evidence_frames': [{'source_timestamp': 1.}, {'source_timestamp': 5.}]}}
    return SimpleNamespace(data_dir=tmp_path), source, path


def test_same_bytes_withdrawal_survives_review_policy_upgrade_and_keeps_exact_other_window(withdrawn):
    settings, source, _ = withdrawn
    for policy in ('old-policy', 'new-policy'):
        result = apply_withdrawals(settings, {**source, 'overlay_review_policy': policy})
        assert result['reviewed_intervals'] == [{'source_start': 0., 'source_end': 4.}]
        assert result['watermark_masks'] == [{'source_start': 0., 'source_end': 4.}]
        assert result['mask_review']['evidence_frames'] == [{'source_timestamp': 1.}]
        assert 'functional_review' not in result and not result['editing_eligible']
        assert apply_withdrawals(settings, result) == result
    assert len(source['reviewed_intervals']) == 2 and source['editing_eligible']


def test_all_withdrawn_and_unbounded_sources_cannot_count_as_clean(withdrawn):
    settings, source, _ = withdrawn
    for windows in (None, [source['reviewed_intervals'][1]]):
        result = apply_withdrawals(settings, {**source, 'reviewed_intervals': windows})
        assert result['reviewed_intervals'] == []
        assert result['manual_usage_review']['editing_eligible'] is False
        assert not result['editing_eligible']


def test_different_hash_is_not_denied_and_corrupt_same_hash_receipt_fails_closed(withdrawn):
    settings, source, path = withdrawn
    different = {**source, 'sha256': 'b'*64}
    assert apply_withdrawals(settings, different) == different
    for value in ({'source_sha256': 'b'*64, 'intervals': []},
                  {'source_sha256': source['sha256'], 'intervals': [{'source_start': -1, 'source_end': 2}]}):
        path.write_text(json.dumps(value))
        with pytest.raises(ValueError):
            apply_withdrawals(settings, source)


def test_cached_plan_cannot_reselect_bad_span_but_boundary_touch_is_allowed(withdrawn):
    settings, source, _ = withdrawn
    plan = {'sources': [source], 'shots': [{'id': 'shot-a', 'source_id': source['id'], 'start': 0., 'end': 8.}],
            'beats': [{'selected_shot_id': 'shot-a', 'source_start': 5., 'source_end': 6.}]}
    with pytest.raises(ValueError, match='제외한'):
        validate_plan(settings, plan)
    plan['beats'][0].update(source_start=1., source_end=4.)
    validate_plan(settings, plan)


def test_revision_validates_replacement_instead_of_original_selection(withdrawn):
    settings, source, _ = withdrawn
    plan = {'sources': [source], 'shots': [
        {'id': 'good', 'source_id': source['id'], 'start': 0., 'end': 4.},
        {'id': 'bad', 'source_id': source['id'], 'start': 4., 'end': 8.}],
        'beats': [{'id': 'beat', 'selected_shot_id': 'bad', 'source_start': 5., 'source_end': 6.}]}
    validate_plan(settings, plan, [{'beat_id': 'beat', 'shot_id': 'good'}])
    plan['beats'][0].update(selected_shot_id='good', source_start=1., source_end=2.)
    with pytest.raises(ValueError, match='제외한'):
        validate_plan(settings, plan, [{'beat_id': 'beat', 'shot_id': 'bad'}])
