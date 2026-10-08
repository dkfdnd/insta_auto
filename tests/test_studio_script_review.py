import pytest

from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.studio_adapter import StudioAdapter


@pytest.mark.parametrize('benchmark, mode', [(False, 'research'), (True, 'benchmark')])
def test_review_is_readonly_and_uses_internal_contract(tmp_path, monkeypatch, benchmark, mode):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    task,_=studio.store.create('review-fixture','대본 검사')
    studio.store.change(task['id'],lambda s,db: s.update(original_text='원본 발화', benchmark_analysis={'hook': '관찰'} if benchmark else {}))
    before=studio.store.get(task['id'])
    calls=[]
    def review(self,text,reference,*,evidence_mode):
        calls.append((text,reference,evidence_mode))
        return {'text':text,'naturalness_review':{'issues':[]}}
    monkeypatch.setattr(StudioAdapter,'review',review)
    text='보관에 있어서 손잡이를 접는 게 편해요.'
    assert studio.action(task['id'],'check-script',{'text':text})['text']==text
    assert calls==[(text,'원본 발화',mode)]
    assert studio.store.get(task['id'])==before


def test_unavailable_review_does_not_lose_task_or_save_input(tmp_path, monkeypatch):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    task,_=studio.store.create('review-offline','연결 실패')
    before=studio.store.get(task['id'])
    def fail(*args,**kwargs):
        raise OSError('offline')
    monkeypatch.setattr(StudioAdapter,'review',fail)
    with pytest.raises(ValueError,match='입력 내용은 그대로'):
        studio.action(task['id'],'check-script',{'text':'현재 편집 중인 대본이에요.'})
    assert studio.store.get(task['id'])==before
    with pytest.raises(ValueError,match='1~3000'):
        studio.action(task['id'],'check-script',{'text':' '})


def test_review_is_local_and_preserves_exact_text(tmp_path):
    from types import SimpleNamespace
    calls=[]
    key=tmp_path/'key.txt'
    key.write_text('fixture-key')
    def request(*args,**kwargs):
        calls.append((args,kwargs))
        return SimpleNamespace(status_code=200,json=lambda:{'naturalness_review':{'issues':[]}})
    adapter=StudioAdapter(Settings(data_dir=tmp_path,studio_api_key_file=key),SimpleNamespace(request=request))
    result=adapter.review('  그대로 두세요.  ','원본')
    assert calls==[]
    assert result['text']=='  그대로 두세요.  '
    assert result['writing_contract']['sha256']==adapter.writing_contract()['sha256']
    assert not (tmp_path/'writing').exists()
