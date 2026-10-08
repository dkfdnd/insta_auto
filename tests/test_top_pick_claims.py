from hotpost.studio_top_pick import unsupported_claims
import pytest


@pytest.fixture(autouse=True)
def local_diagnostics_boundary(monkeypatch):
    # Ranking unit tests provide their own diagnostic fixtures. The HTTP
    # refresh boundary is exercised in test_studio_script_checks.py.
    monkeypatch.setattr('hotpost.studio_top_pick.refresh_local_reviews',
                        lambda settings, reference, valid: valid)


def test_footage_inventory_cannot_change_script_rank_or_trigger_frame_access(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from hotpost.studio_top_pick import choose
    calls=[]
    def evaluate(settings, instruction, evidence, **kw):
        assert 'sources' not in evidence and not kw.get('media')
        calls.append(evidence)
        return {'evaluations':[
            {'index':0,'eligible':True,'scores':dict(hook=5,grounding=4,narration=5,footage=0),'reason':'좋은 대본','issues':[]},
            {'index':1,'eligible':True,'scores':dict(hook=4,grounding=4,narration=3,footage=5),'reason':'쉬운 편집','issues':[]}]}
    monkeypatch.setattr('hotpost.studio_top_pick._generate',evaluate)
    monkeypatch.setattr('hotpost.source_finder.extract_frames',lambda *a,**k:(_ for _ in ()).throw(AssertionError('frames used')))
    candidates=[(0,{'text':'마늘, 또 얼리려고요? 잠깐만요!'}),(1,{'text':'마늘 넣는 방법이 소개됐어요.'})]
    state={'id':'inventory-independent','original_text':'마늘을 얼리지 마세요!','sources':[]}
    assert choose(SimpleNamespace(data_dir=tmp_path),state,candidates)[0] == 0
    state['sources']=[{'id':'new','sha256':'new','path':'missing.mp4','source_role':'context_only'}]
    assert choose(SimpleNamespace(data_dir=tmp_path),state,candidates)[0] == 0
    assert len(calls) == 1  # same script evidence also reuses the same receipt


def test_bound_editorial_review_is_reused_without_second_model_call(tmp_path, monkeypatch):
    import hashlib
    from types import SimpleNamespace
    from hotpost.studio_top_pick import choose
    reference='다진 마늘 얼리지 마세요!'
    from hotpost.writing.contract import receipt
    contract=receipt()
    text='다진 마늘, 또 얼리려고요? 잠깐만요!'
    review={'status':'evaluated','review_contract_checked':True,'review_contract_policy':'review-contract-6','script_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'reference_sha256':hashlib.sha256(reference.encode()).hexdigest(),'contract':contract,
            'scores':dict(hook=5,appeal=4,direct_address=5,spoken=4,grounding=4),'total':4.5,'reason':'근거','issues':[]}
    monkeypatch.setattr('hotpost.studio_top_pick._generate',lambda *a,**k:(_ for _ in ()).throw(AssertionError('duplicate review')))
    index,result=choose(SimpleNamespace(data_dir=tmp_path),{'id':'bound','original_text':reference},
                        [(0,{'text':text,'editorial_review':review,'writing_contract':contract})])
    assert index == 0 and result['review_reused'] and result['script_priority']


def test_perfect_model_score_cannot_prefer_a_verbatim_hook(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from hotpost.studio_top_pick import choose
    reference='캠핑장에서 다들 쳐다보는 텐트 보셨어요? 차 뒤에 달고 다녀요.'
    drafts=[{'text':reference}, {'text':'이 텐트는 왜 사람들 시선을 끌까요? 차에 연결해 두었다 펼치는 방식이에요.'}]
    rows=[{'index':i,'eligible':True,'scores':dict(hook=5-i,grounding=5-i,narration=5-i,footage=5-i),
           'reason':'자동 점수','issues':[]} for i in range(2)]
    monkeypatch.setattr('hotpost.studio_top_pick._generate',lambda *a,**kw:{'evaluations':rows})
    index,result=choose(SimpleNamespace(data_dir=tmp_path),{'id':'copied','sources':[],'original_text':reference},list(enumerate(drafts)))
    assert index==1 and result['review_policy']==22
    assert result['evaluations'][0]['wording_issues']


def test_scoring_failure_still_prefers_rephrased_candidate(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from hotpost.studio_top_pick import choose
    reference='캠핑장에서 다들 쳐다보는 텐트 보셨어요? 차 뒤에 달고 다녀요.'
    def fail(*a,**kw):raise RuntimeError('offline')
    monkeypatch.setattr('hotpost.studio_top_pick._generate',fail)
    index,result=choose(SimpleNamespace(data_dir=tmp_path),{'id':'offline-copy','sources':[],'original_text':reference},
                       [(0,{'text':reference}),(1,{'text':'이 텐트는 왜 사람들 시선을 끌까요? 차에 연결해 두었다 펼쳐요.'})])
    assert index==1 and result['advisory_only']


def test_all_low_scores_are_advisory_and_still_select_a_script(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from hotpost.studio_top_pick import choose
    state = {'id':'advisory', 'sources':[], 'original_text':'원본 후킹이에요'}
    monkeypatch.setattr('hotpost.studio_top_pick._generate', lambda *a, **kw: {'evaluations':[
        {'index':0, 'eligible':False, 'scores':dict(hook=1,grounding=1,narration=2,footage=0),
         'reason':'검토 의견', 'issues':['개인 경험 미확인']}]})
    index, result = choose(SimpleNamespace(data_dir=tmp_path),state,[(0,{'text':'제가 직접 써봤어요'})])
    assert index == 0 and result['advisory_only']
    assert result['evaluations'][0]['issues']


def test_unavailable_ranking_continues_with_existing_generated_script(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from hotpost.studio_top_pick import choose
    def fail(*a, **kw): raise RuntimeError('평가 연결 실패')
    monkeypatch.setattr('hotpost.studio_top_pick._generate',fail)
    index, result = choose(SimpleNamespace(data_dir=tmp_path),
        {'id':'offline','sources':[],'original_text':'원본'},[(2,{'text':'생성된 대본이에요'})])
    assert index == 2 and result['advisory_only']
    assert '평가 연결 실패' in result['issues'][0]


def test_high_total_cannot_select_a_lost_reference_hook(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from hotpost.studio_top_pick import choose
    state={'id':'work-hook', 'sources':[], 'original_text':'다진 마늘 얼리기 전에 잠깐만요.',
           'reviewed_original_text':'다진 마늘, 얼리기 전에 잠깐만요!',
           'benchmark_analysis':{'hook_contract':{'mechanism':'행동 중단'}}}
    rows=[{'index':0,'eligible':True,'scores':dict(hook=2,grounding=5,narration=5,footage=5),'reason':'후킹 교체','issues':[]},
          {'index':1,'eligible':True,'scores':dict(hook=4,grounding=3,narration=3,footage=3),'reason':'원본 후킹 유지','issues':[]}]
    def evaluate(settings, instruction, evidence, **kw):
        assert evidence['original_speech']==state['reviewed_original_text']
        assert evidence['hook_contract']['mechanism']=='행동 중단'
        return {'evaluations':rows}
    monkeypatch.setattr('hotpost.studio_top_pick._generate',evaluate)
    index,result=choose(SimpleNamespace(data_dir=tmp_path),state,[(0,{'text':'한 스푼이면 끝?'}),(1,{'text':'얼리기 전에 잠깐만요!'})])
    assert rows[0]['total']>rows[1]['total'] and index==1


def test_model_cannot_approve_unverified_tipping_and_dust_guarantees():
    issues = unsupported_claims('튼튼한 원목이라 흔들리거나 넘어질 걱정도 없어요. 먼지 닦을 필요도 없어요.')
    assert len(issues) == 2


def test_critical_integrity_beats_low_model_score_and_copy_preference(tmp_path,monkeypatch):
    import hashlib
    from types import SimpleNamespace
    from hotpost.studio_top_pick import choose
    ref='냉장 보관해요.'
    bad={'text':'섞은 뒤 얼리면 좋아요.','integrity_review':{
        'script_sha256':hashlib.sha256('섞은 뒤 얼리면 좋아요.'.encode()).hexdigest(),
        'reference_sha256':hashlib.sha256(ref.encode()).hexdigest(),
        'issues':[{'severity':'critical','code':'storage_reversal'}]}}
    drafts=[bad,{'text':'필요한 만큼 덜어서 요리에 넣어요.'}]
    rows=[{'index':i,'eligible':i==0,'scores':dict(hook=5 if i==0 else 2,grounding=5,narration=5),
           'reason':'점수','issues':[]} for i in range(2)]
    monkeypatch.setattr('hotpost.studio_top_pick._generate',lambda *a,**kw:{'evaluations':rows})
    index,result=choose(SimpleNamespace(data_dir=tmp_path),{'id':'integrity','original_text':ref},list(enumerate(drafts)))
    assert index==1 and result['quality_status']=='unresolved'
    monkeypatch.setattr('hotpost.studio_top_pick._generate',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('offline')))
    index,_=choose(SimpleNamespace(data_dir=tmp_path),{'id':'offline-integrity','original_text':ref},list(enumerate(drafts)))
    assert index==1


def test_explicit_approved_recovery_precedes_model_and_needs_exact_binding(tmp_path,monkeypatch):
    import hashlib
    from types import SimpleNamespace
    from hotpost.studio_top_pick import choose,approved_recovery
    ref='얼리지 마세요.';text='다진 마늘, 또 얼리려고요? 잠깐만요!'
    candidate={'text':text,'origin':'user_approved_recovery','approval':{'id':'approved','origin':'explicit_user_approval',
        'approval_evidence':'사용자 승인','script_sha256':hashlib.sha256(text.encode()).hexdigest(),
        'reference_sha256':hashlib.sha256(ref.encode()).hexdigest()}}
    monkeypatch.setattr('hotpost.studio_top_pick._generate',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('must preserve approved text')))
    index,result=choose(SimpleNamespace(data_dir=tmp_path),{'id':'approved','original_text':ref},[(1,candidate)])
    assert index==1 and result['quality_status']=='user_approved_recovery'
    assert not approved_recovery(ref+'다른 내용',candidate)
    assert not approved_recovery(ref,{**candidate,'text':text+'바뀐 내용'})


def test_anecdotes_without_a_reference_still_need_source_support():
    assert unsupported_claims('제가 직접 써보니 우리 아이가 알아서 정리하더라고요.')
    assert unsupported_claims('엄마가 이걸 추천해 줬는데, 처음엔 그냥 미니 에코백 같았어요.')
    assert not unsupported_claims('엄마에게 선물할 가방을 찾고 계세요?')


def test_narrow_integrity_repair_does_not_clear_cta_or_ending_errors(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from hotpost.studio_top_pick import choose
    draft={'text':'시선을 끄는 텐트예요. 나도',
           'quality_recovery':{'status':'repaired','unresolved':False},
           'benchmark_review':{'issues':['주제와 연결되는 댓글 유도가 없습니다.']}}
    monkeypatch.setattr('hotpost.studio_top_pick._generate',lambda *a,**kw:{'evaluations':[
        {'index':0,'eligible':True,'scores':dict(hook=5,grounding=5,narration=5),'reason':'좋음','issues':[]}]})
    index,result=choose(SimpleNamespace(data_dir=tmp_path),{'id':'repaired','original_text':'이 텐트 보셨어요?'},[(0,draft)])
    assert index==0 and result['quality_status']=='unresolved'
    assert result['advisory_only']


def test_observation_questions_and_arrangement_suggestions_are_allowed():
    assert unsupported_claims('피규어는 어디에 두고 계세요? 투명문 안에 피규어가 보이네요. 좋아하는 수집품부터 한 칸씩 놓아보세요.') == []


def test_prompt_instructions_cannot_be_spoken_as_the_finished_script():
    assert unsupported_claims('문은 닫아 두면서 수집품을 볼 수 있다는 관찰과, 한 칸씩 배치해 보라는 제안만 설명하세요. 첫 질문은 일반적인 질문이며 시청자의 집에 이 제품이 있다고 가정하지 마세요.')


def test_installation_demo_cannot_establish_complete_intrusion_protection():
    assert unsupported_claims('호텔 문에 끼우면 외부 침입 완벽 차단! 도난 걱정도 없어요.')
    assert unsupported_claims('문 아래에 장치를 끼우고 나사를 돌리는 모습이 보여요. 설치할 문 구조부터 확인해 보세요.') == []


def test_unavailable_critic_preserves_other_candidate_evaluation(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from hotpost.studio_top_pick import choose
    rows=[{'index':0,'status':'unavailable','eligible':False,'reason':'규칙 충돌','issues':['평가 오류']},
          {'index':1,'eligible':True,'scores':dict(hook=4,grounding=4,narration=4),'reason':'기능 유지','issues':[]}]
    monkeypatch.setattr('hotpost.studio_top_pick._generate',lambda *a,**kw:{'evaluations':rows})
    index,result=choose(SimpleNamespace(data_dir=tmp_path),{'id':'partial-critic','original_text':'원본'},
                        [(0,{'text':'안쪽 칸을 나눴어요.'}),(1,{'text':'두 칸으로 나눠서 담아요.'})])
    assert index==1 and result['evaluations'][0]['status']=='unavailable'
    assert 'scores' not in result['evaluations'][0]


def test_unavailable_clean_critic_never_promotes_a_new_unsupported_anecdote(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from hotpost.studio_top_pick import choose
    rows=[{'index':0,'status':'unavailable','reason':'규칙 충돌','issues':['평가 오류']},
          {'index':1,'eligible':True,'scores':dict(hook=5,grounding=5,narration=5),'reason':'고득점','issues':[]}]
    monkeypatch.setattr('hotpost.studio_top_pick._generate',lambda *a,**kw:{'evaluations':rows})
    index,result=choose(SimpleNamespace(data_dir=tmp_path),{'id':'clean-critic','original_text':'원본'},
                        [(0,{'text':'안쪽 칸을 나눴어요.'}),(1,{'text':'친구가 추천해서 샀어요.'})])
    assert index==0 and result['quality_status']=='not_evaluated' and result['advisory_only']
    assert list((tmp_path/'studio/clean-critic/top-pick/reviews').glob('*.json'))


@pytest.mark.parametrize('old_policy',[None,'review-contract-5'])
def test_legacy_review_without_current_contract_validation_is_not_reused(tmp_path,monkeypatch,old_policy):
    import hashlib
    from types import SimpleNamespace
    from hotpost.studio_top_pick import choose
    ref='원본';text='두 칸으로 나눠 담아요.';contract={'version':'legacy','sha256':'rules'}
    review={'status':'evaluated','script_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'reference_sha256':hashlib.sha256(ref.encode()).hexdigest(),'contract':contract,
            'scores':dict(hook=5,appeal=5,direct_address=5,spoken=5,grounding=5),'total':5,'reason':'기존 평가','issues':[]}
    if old_policy:
        review.update(review_contract_checked=True,review_contract_policy=old_policy)
    calls=[]
    def generate(*a,**kw):
        calls.append(1)
        return {'evaluations':[{'index':0,'eligible':True,'scores':dict(hook=4,grounding=4,narration=4),
                                'reason':'새 평가','issues':[]}]}
    monkeypatch.setattr('hotpost.studio_top_pick._generate',generate)
    _,result=choose(SimpleNamespace(data_dir=tmp_path),{'id':'legacy-review','original_text':ref},
        [(0,{'text':text,'editorial_review':review,'writing_contract':contract})])
    assert len(calls)==1 and not result['review_reused'] and result['reason']=='새 평가'
