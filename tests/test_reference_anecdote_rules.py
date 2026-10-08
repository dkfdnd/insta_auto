import copy
import hashlib
import json

import pytest

from hotpost.studio_top_pick import choose, integrity_risk, unsupported_claims
from hotpost.writing import pipeline
from hotpost.writing.contract import snapshot
from hotpost.writing.script_integrity import inspect


REFERENCE = '친구 집에서 닭꼬치인 줄 알고 먹었는데 새송이버섯이라는 거예요. 댓글에 꼬치 남겨주세요.'
ADAPTED = ('고기인 줄 알았는데 버섯이었다니 놀랍지 않아요? '
           '친구네서 한 입 먹었는데 식감이 쫄깃하더라고요. 댓글에 꼬치 남겨주세요.')


def test_setting_reuse_is_allowed_but_verbatim_story_is_still_copy():
    assert not unsupported_claims(ADAPTED, REFERENCE)
    assert not [i for i in inspect(REFERENCE, ADAPTED)['issues'] if i['severity']=='critical']
    assert any(i['severity']=='copy' for i in inspect(REFERENCE, REFERENCE)['issues'])


def test_historical_blanket_experience_flag_does_not_lower_adapted_script():
    item={'text':ADAPTED,'integrity_review':{
        'script_sha256':hashlib.sha256(ADAPTED.encode()).hexdigest(),
        'reference_sha256':hashlib.sha256(REFERENCE.encode()).hexdigest(),
        'policy':'narration-integrity-10',
        'issues':[{'code':'borrowed_experience','severity':'critical','quote':ADAPTED}]}}
    before=copy.deepcopy(item)
    assert integrity_risk(REFERENCE,item)==(0,0)
    assert item==before


def test_allowed_story_does_not_waive_number_preservation():
    result=inspect(REFERENCE+' 삼 초면 구워요.', ADAPTED+' 삼십 초면 구워요.')
    assert any(i['code']=='quantity_changed' for i in result['issues'])


@pytest.mark.parametrize('offline',[False,True])
def test_top_pick_scoring_and_fallback_both_allow_reference_story(tmp_path,monkeypatch,offline):
    from types import SimpleNamespace
    def score(*args,**kwargs):
        if offline:raise RuntimeError('offline')
        return {'evaluations':[{'index':0,'eligible':True,
            'scores':dict(hook=5,grounding=5,narration=5),'reason':'경험담을 재작성','issues':[]}]}
    monkeypatch.setattr('hotpost.studio_top_pick._generate',score)
    index,result=choose(SimpleNamespace(data_dir=tmp_path),
        {'id':'reference-story','original_text':REFERENCE},[(0,{'text':ADAPTED})])
    assert index==0 and result['advisory_only']
    assert result['quality_status']!='unresolved'


def test_single_draft_does_not_repair_only_because_it_retells_an_experience(tmp_path,monkeypatch):
    calls=[]
    def chat(instruction,data,schema,check,state):
        calls.append((instruction,json.loads(data)))
        if len(calls)==1:return {'text':ADAPTED}
        if len(calls)==2:return {'issues':[]}
        pytest.fail('Allowed setting must not trigger a repair')
    monkeypatch.setattr(pipeline.codex_writer,'chat',chat)
    value=pipeline.generate({'reference_script':REFERENCE,'writing_contract':snapshot()},
        tmp_path,lambda:None,lambda *args:None)
    assert value['scripts'][0]['text']==ADAPTED and len(calls)==2
    assert '설정 차용 자체를 오류로 지적하지 말고' in calls[1][0]
    assert not json.loads((tmp_path/'writing-audit.json').read_text('utf-8'))['repair']['attempted']
