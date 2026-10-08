import copy
import hashlib
from types import SimpleNamespace

import pytest

from hotpost import studio_script_checks as checks, studio_top_pick as top


def diagnostics(text, reference, issues=()):
    hashes = {'script_sha256': hashlib.sha256(text.encode()).hexdigest(),
              'reference_sha256': hashlib.sha256(reference.encode()).hexdigest()}
    return {'text': text,
            'integrity_review': {**hashes, 'policy': 'current-test', 'issues': list(issues)},
            'rewrite_review': {**hashes, 'reasons': []}, 'naturalness_review': {'issues': []},
            'quality_summary': {**hashes, 'issues': [i['message'] for i in issues]}}


def test_refresh_preserves_text_selection_metadata_and_stored_objects(monkeypatch):
    original = [(2, {'text': '냉기를 덜 받아요.', 'origin': 'manual',
                     'editorial_review': {'scores': {'hook': 4}}})]
    before = copy.deepcopy(original)
    calls = []
    def review(self, text, reference, evidence_mode):
        calls.append((text, reference, evidence_mode))
        return diagnostics(text, reference)
    monkeypatch.setattr(checks.StudioAdapter, 'review', review)
    result = checks.refresh_local_reviews(None, '냉기가 덜해요.', original)
    assert original == before
    assert result[0][0] == 2
    assert result[0][1]['text'] == before[0][1]['text']
    assert result[0][1]['editorial_review'] == before[0][1]['editorial_review']
    assert result[0][1]['integrity_review']['policy'] == 'current-test'
    assert calls == [('냉기를 덜 받아요.', '냉기가 덜해요.', 'benchmark')]


@pytest.mark.parametrize('change', ['text', 'reference_hash', 'malformed'])
def test_mismatched_review_cannot_silently_replace_script(monkeypatch, change):
    def review(self, text, reference, evidence_mode):
        result = diagnostics(text, reference)
        if change == 'text': result['text'] = '몰래 바꾼 대본'
        elif change == 'malformed': result['integrity_review'] = None
        else: result['integrity_review']['reference_sha256'] = 'another-reference'
        return result
    monkeypatch.setattr(checks.StudioAdapter, 'review', review)
    with pytest.raises(ValueError):
        checks.refresh_local_reviews(None, '원본', [(0, {'text': '선택 대본'})])


def test_new_local_diagnosis_beats_stale_perfect_score_and_retains_refresh_on_ranking_failure(tmp_path, monkeypatch):
    ref = '습기랑 냉기가 덜해요.'
    drafts = [(0, {'text': '습기랑 냉기를 전혀 안 받아요.'}),
              (1, {'text': '바닥에서 올라오는 습기와 냉기가 줄어요.'})]
    def review(self, text, reference, evidence_mode):
        issues = [{'code': 'mitigation_strengthened', 'severity': 'critical',
                   'quote': text, 'message': '줄어드는 효과를 없어진다고 강화함'}] if '전혀' in text else []
        return diagnostics(text, reference, issues)
    monkeypatch.setattr(checks.StudioAdapter, 'review', review)
    def score(*args, **kwargs):
        return {'evaluations': [{'index': i, 'eligible': True,
                 'scores': dict(hook=5-i, grounding=5-i, narration=5-i),
                 'reason': '모델 점수', 'issues': []} for i in range(2)]}
    monkeypatch.setattr(top, '_generate', score)
    state = {'id': 'refresh-risk', 'original_text': ref}
    assert top.choose(SimpleNamespace(data_dir=tmp_path), state, drafts)[0] == 1
    def fail(*args, **kwargs): raise RuntimeError('model offline')
    monkeypatch.setattr(top, '_generate', fail)
    state['id'] = 'refresh-risk-offline'
    assert top.choose(SimpleNamespace(data_dir=tmp_path), state, drafts)[0] == 1
    assert all('integrity_review' not in item for _, item in drafts)


def test_refresh_outage_is_not_quality_success_or_an_approval_hold(tmp_path, monkeypatch):
    def fail(*args, **kwargs): raise RuntimeError('local checks unavailable')
    monkeypatch.setattr(checks.StudioAdapter, 'review', fail)
    monkeypatch.setattr(top, '_generate', lambda *a, **k: pytest.fail('Do not score unchecked stale candidates'))
    index, result = top.choose(SimpleNamespace(data_dir=tmp_path),
        {'id': 'unavailable', 'original_text': '원본'}, [(3, {'text': '저장된 원고예요.'})])
    assert index == 3 and result['advisory_only']
    assert result['quality_status'] == 'not_evaluated'
    assert 'local checks unavailable' in result['issues'][0]


def test_late_refresh_failure_keeps_the_earlier_confirmed_diagnosis(tmp_path, monkeypatch):
    def review(self, text, reference, evidence_mode):
        if text == '마지막 후보예요.': raise RuntimeError('service became unavailable')
        issues = [{'severity': 'critical', 'message': '의미 강화'}] if text == '강화된 후보예요.' else []
        return diagnostics(text, reference, issues)
    monkeypatch.setattr(checks.StudioAdapter, 'review', review)
    monkeypatch.setattr(top, '_generate', lambda *a, **k: pytest.fail('No scores after partial local failure'))
    drafts = list(enumerate([{'text': text} for text in
                            ['강화된 후보예요.', '다른 후보예요.', '마지막 후보예요.']]))
    index, result = top.choose(SimpleNamespace(data_dir=tmp_path),
                              {'id': 'partial', 'original_text': '원본'}, drafts)
    assert index == 1
    assert result['quality_status'] == 'not_evaluated'
    assert all('integrity_review' not in item for _, item in drafts)
