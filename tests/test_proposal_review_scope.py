from hotpost.config import Settings
from hotpost.studio_ai import propose_script


def test_revision_review_does_not_grade_deleted_claims_from_old_script(monkeypatch):
    revised = '피규어는 어디에 두고 계세요? 투명문 안에 좋아하는 수집품부터 한 칸씩 놓아보세요.'
    calls = []
    def generate(settings, instruction, evidence):
        calls.append(evidence)
        if len(calls) == 1:
            return {'text': revised, 'summary': '안전 보장 삭제'}
        assert evidence['proposal'] == revised
        assert 'current_script' not in evidence
        # Reference speech is evidence for hearsay and hook fidelity; deleted
        # claims in the old draft must still not be graded as the proposal.
        assert evidence['original_speech'] == '6만원이면 절대 안 넘어져요'
        assert 'request' not in evidence
        return {'passed': True, 'issues': []}
    monkeypatch.setattr('hotpost.studio_ai._generate', generate)
    result = propose_script(Settings(), {'original_text': '6만원이면 절대 안 넘어져요', 'research': {}},
                            '먼지를 닦을 필요가 없고 넘어질 걱정도 없어요', '보장 표현을 지우고 정리 제안으로 바꿔주세요')
    assert result['text'] == revised
    assert calls[0]['current_script'].startswith('먼지를')
