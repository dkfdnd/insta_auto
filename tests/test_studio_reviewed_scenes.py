import pytest
from hotpost.studio_reviewed_scenes import apply_reviewed_scenes


def fixture():
    plan={'sources':[{'id':'s1','sha256':'hash','path':'source.mp4'}],
          'shots':[{'id':'old','sha256':'hash','start':0,'end':20}],
          'beats':[{'id':'beat-1','text':'내용을 적어요'},{'id':'beat-2','text':'댓글 남겨주세요'}]}
    rules=[{'reviewed':True,'source_sha256':'hash','pattern':'적어요','start':15,'end':17,
            'relation':'direct','reason':'펜으로 목록 칸에 쓰는 실제 장면','evidence_frames':['review.jpg']},
           {'reviewed':True,'source_sha256':'hash','pattern':'.','start':5,'end':9,
            'relation':'context','reason':'같은 제품의 전체 모습','evidence_frames':['review.jpg']}]
    return plan,rules


def test_reviewed_rules_match_actions_without_mutating_previous_plan():
    plan,rules=fixture();new=apply_reviewed_scenes(plan,rules)
    assert len(plan['shots'])==1 and len(new['shots'])==3
    assert new['shots'][-2]['start']==15
    assert new['beats'][0]['options'][0]['relation']=='direct'
    assert new['beats'][1]['options'][0]['relation']=='context'
    assert new['beats'][1]['options'][0]['reviewed'] is True


@pytest.mark.parametrize('change',[{'source_sha256':'other'},{'reviewed':False},{'end':21},
    {'start':float('nan')},{'evidence_frames':[]},{'relation':'invented'}])
def test_changed_or_unreviewed_sources_fail_before_render(change):
    plan,rules=fixture();rules[0].update(change)
    with pytest.raises(ValueError):apply_reviewed_scenes(plan,rules)


def test_missing_clause_mapping_is_not_replaced_with_default_cycle():
    plan,rules=fixture()
    with pytest.raises(ValueError):apply_reviewed_scenes(plan,rules[:1])
