import json
import hashlib

import pytest

from hotpost.source_audit import summarize


def test_summary_counts_only_reviewed_masks_as_usable(tmp_path):
    path = tmp_path / 'manifest.json'
    common = {'url': 'https://www.youtube.com/watch?v=example',
              'downloaded_file': 'clip.mp4', 'selected_for_zip': True,
              'source_quality': 'edited-with-text', 'blur_required': True}
    path.write_text(json.dumps({'downloaded': 3, 'candidates': [
        {**common, 'watermark_masks': [{'reviewed': True}]},
        {**common, 'watermark_masks': [{'reviewed': False}]},
        {**common, 'watermark_masks': [{'reviewed': True}], 'editing_eligible': False},
    ]}))
    result = summarize(path)
    assert result['usable'] == 1
    assert result['needs_review'] == 2


def test_summary_exposes_the_chosen_strategy_and_prior_failure_reason(tmp_path):
    path = tmp_path/'manifest.json'
    strategy = {'phase':'clean_action','label':'원본 장면 검색','reasons':['이전 검증 탈락'],
                'skipped_routes':{'duckduckgo':'후보 없음'}}
    path.write_text(json.dumps({'search_strategy':strategy}))
    assert summarize(path)['strategy'] == strategy


def test_summary_preserves_inspection_order_evidence_and_allocated_time(tmp_path):
    path=tmp_path/'manifest.json'
    path.write_text(json.dumps({'candidates':[{'title':'Garlic storage','discovery_score':6,
        'discovery_reasons':['핵심 행동 일치'],'discovery_meta':{'duration':12},'download_budget_seconds':37.5}]}))
    inspection=summarize(path)['inspection'][0]
    assert inspection['duration']==12 and inspection['download_budget_seconds']==37.5
    assert inspection['reasons']==['핵심 행동 일치']


def reviewed_fixture(tmp_path):
    path = tmp_path / 'manifest.json'
    clip = tmp_path / 'clip.mp4'
    clip.write_bytes(b'actual acquired fixture')
    digest = hashlib.sha256(clip.read_bytes()).hexdigest()
    candidate = {'url': 'https://www.tiktok.com/@fixture/video/123',
        'file_sha256': digest, 'downloaded_file': 'clip.mp4', 'selected_for_zip': True,
        'source_quality': 'edited-with-text', 'blur_required': True,
        'watermark_masks': None, 'editing_eligible': None, 'rejection_reasons': [],
        'acquisition': 'local-cache', 'download_attempted': False}
    data = {'downloaded': 1, 'candidates': [candidate], 'platform_targets': {'tiktok': {'target': 1}},
        'search_audit': [{'provider': 'tiktok', 'status': 'readiness_blocked'}],
        'platform_outcomes': {'tiktok': {'usable': 0, 'reasons': {'quality_rejected': 1}}}}
    path.write_text(json.dumps(data))
    source = {'path': str(clip), 'sha256': digest, 'source_quality': 'edited-with-text',
        'blur_required': True, 'watermark_masks': [{'reviewed': True}], 'editing_eligible': True,
        'functional_review': {'reviewed': True, 'source_sha256': digest,
            'observed_actions': ['mincing garlic'], 'evidence_frames': ['observed.jpg']}}
    return path, source


def test_completed_review_updates_current_diagnostics_without_rewriting_acquisition(tmp_path):
    path, source = reviewed_fixture(tmp_path)
    original = path.read_bytes()
    result = summarize(path, [source])
    assert result['usable'] == 1 and result['needs_review'] == 0
    assert result['inspection_stage'] == 'studio_review'
    current = result['platform_outcomes']['tiktok']
    assert current['usable'] == 1 and current['status'] == 'met'
    assert current['local_reuses'] == 1 and current['network_received'] == 0
    assert current['search_attempts'] == current['download_attempts'] == 0
    assert 'quality_rejected' not in current['reasons']
    assert result['acquisition_platform_outcomes']['tiktok']['reasons'] == {'quality_rejected': 1}
    assert path.read_bytes() == original


@pytest.mark.parametrize('mismatch', ['hash', 'path', 'review_hash', 'mask', 'ineligible', 'unselected'])
def test_wrong_or_incomplete_review_cannot_promote_an_acquired_candidate(tmp_path, mismatch):
    path, source = reviewed_fixture(tmp_path)
    if mismatch == 'hash':
        source['sha256'] = '0' * 64
    elif mismatch == 'path':
        source['path'] = str(tmp_path / 'different.mp4')
    elif mismatch == 'review_hash':
        source['functional_review']['source_sha256'] = '0' * 64
    elif mismatch == 'mask':
        source['watermark_masks'] = [{'reviewed': False}]
    elif mismatch == 'ineligible':
        source['editing_eligible'] = False
    else:
        data = json.loads(path.read_text())
        data['candidates'][0]['selected_for_zip'] = False
        path.write_text(json.dumps(data))
    result = summarize(path, [source])
    assert result['usable'] == 0
    assert result['platform_outcomes']['tiktok']['usable'] == 0


def test_studio_review_does_not_hide_a_real_download_or_duplicate_rejection(tmp_path):
    path, source = reviewed_fixture(tmp_path)
    data = json.loads(path.read_text())
    data['candidates'][0]['rejection_reasons'] = ['duplicate_of:other']
    path.write_text(json.dumps(data))
    current = summarize(path, [source])['platform_outcomes']['tiktok']
    assert current['usable'] == 0 and current['reasons']['duplicate'] == 1


@pytest.mark.parametrize('contract', ['owned', 'legacy'])
def test_owned_and_legacy_footage_does_not_acquire_new_function_requirements(tmp_path, contract):
    path, source = reviewed_fixture(tmp_path)
    source.pop('functional_review')
    data = json.loads(path.read_text())
    data['candidates'][0].update(source_quality='clean-source', blur_required=False, editing_eligible=True)
    if contract == 'owned':
        data['user_supplied'] = True
    path.write_text(json.dumps(data))
    result = summarize(path, [source])
    assert result['usable'] == 1
    assert result['inspection_stage'] == 'acquisition'
