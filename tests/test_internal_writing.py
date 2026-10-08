import json
import threading
import pytest
from hotpost.config import Settings
from hotpost.studio_adapter import StudioAdapter
from hotpost.writing import pipeline
from hotpost.writing.contract import snapshot
from hotpost.writing.jobs import Jobs

REFERENCE='차문에 끼워서 컵을 놓고 휴대폰을 세울 수 있어요. 댓글에 홀더 남겨주세요.'
DRAFT='컵 놓을 자리가 모자라요? 문 쪽에 걸어 음료 자리를 하나 늘려요. 폰도 세워둘 수 있어요. 댓글에 홀더 남겨주세요.'

def run(tmp_path, monkeypatch, replies):
    calls=[]
    def chat(instruction, data, schema, check, state):
        calls.append((instruction,json.loads(data)))
        value=replies[len(calls)-1]
        if isinstance(value,Exception):raise value
        return value
    monkeypatch.setattr(pipeline.codex_writer,'chat',chat)
    value=pipeline.generate({'reference_script':REFERENCE,'writing_contract':snapshot()},tmp_path,lambda:None,lambda *a:None)
    return value,calls,json.loads((tmp_path/'writing-audit.json').read_text('utf-8'))

def test_single_draft_review_does_not_run_candidate_competition(tmp_path,monkeypatch):
    result,calls,audit=run(tmp_path,monkeypatch,[{'text':DRAFT},{'issues':[]}])
    assert len(calls)==2 and len(result['scripts'])==1
    assert result['scripts'][0]['text']==DRAFT and not audit['repair']['attempted']
    assert all(snapshot()['prompt'] in instruction for instruction,_ in calls)
    assert 'sources' not in calls[0][1]

def test_repair_bounded_and_worse_copy_does_not_replace_original(tmp_path,monkeypatch):
    result,calls,audit=run(tmp_path,monkeypatch,[{'text':DRAFT},
        {'issues':[{'quote':'음료 자리를 하나 늘려요','reason':'문장을 다듬어 주세요'}]},
        {'text':REFERENCE},{'preferred':1,'reason':'잘못된 모델 선호','issues':[]}])
    assert len(calls)==4 and result['scripts'][0]['text']==DRAFT
    assert audit['repair']['attempted'] and not audit['repair']['accepted']

def test_review_failure_is_advisory_and_retains_text(tmp_path,monkeypatch):
    result,calls,_=run(tmp_path,monkeypatch,[{'text':DRAFT},RuntimeError('offline')])
    assert len(calls)==2 and result['scripts'][0]['text']==DRAFT
    assert result['scripts'][0]['quality_summary']['status']=='not_evaluated'
    assert result['warnings']


def test_copy_repair_receives_the_actual_copied_quote_and_reference_span(tmp_path, monkeypatch):
    result,calls,audit=run(tmp_path,monkeypatch,[{'text':REFERENCE}, {'issues':[]},
        {'text':DRAFT}, {'preferred':1,'reason':'Copied wording was rewritten with the same function','issues':[]}])
    assert len(calls)==4
    findings=calls[2][1]['findings']['integrity']
    copy_findings=[f for f in findings if f['severity']=='copy']
    assert copy_findings
    assert all(f['quote'] in REFERENCE and f['source_quote'] in REFERENCE for f in copy_findings)
    assert result['scripts'][0]['text']==DRAFT and audit['repair']['accepted']


def test_editorial_repair_keeps_quote_connected_to_its_reason(tmp_path, monkeypatch):
    issue={'quote':'음료 자리를 하나 늘려요','reason':'같은 동작의 표현을 더 자연스럽게 바꿔 주세요'}
    result,calls,_=run(tmp_path,monkeypatch,[{'text':DRAFT}, {'issues':[issue]},
        {'text':DRAFT}, {'preferred':0,'reason':'No verified improvement','issues':[]}])
    assert calls[2][1]['findings']['editorial']==[issue]
    assert result['scripts'][0]['text']==DRAFT

def test_empty_draft_is_technical_failure(tmp_path,monkeypatch):
    with pytest.raises(ValueError,match='빈 대본'):run(tmp_path,monkeypatch,[{'text':' '}])


def test_short_nonempty_reference_reaches_codex_without_length_gate(tmp_path,monkeypatch):
    calls=[]
    def chat(instruction,data,schema,check,state):
        calls.append(json.loads(data))
        if len(calls)==1:return {'text':'설치하기 번거롭죠? 펼쳐서 바로 쓸 수 있어요. 댓글에 나도 남겨주세요.'}
        if len(calls)==2:return {'issues':[]}
        if len(calls)==3:return {'text':'설치가 번거롭죠? 펼쳐 놓으면 바로 쓸 수 있어요. 댓글에 나도 남겨주세요.'}
        return {'preferred':0,'reason':'원고 보존','issues':[]}
    monkeypatch.setattr(pipeline.codex_writer,'chat',chat)
    result=pipeline.generate({'reference_script':'펼치면 끝이에요!','writing_contract':snapshot()},tmp_path,lambda:None,lambda *a:None)
    assert result['scripts'] and calls[0]['reference']=='펼치면 끝이에요!'

def test_queue_durable_and_does_not_duplicate_active_work(tmp_path,monkeypatch):
    jobs=Jobs(tmp_path);job=jobs.create('script',{'reference':'fixture'})
    entered=threading.Event();release=threading.Event();calls=[]
    def execute(item):
        calls.append(item['id']);entered.set();release.wait(5)
        jobs.update(item['id'],state='completed',result={'fixture':True})
    monkeypatch.setattr(jobs,'execute',execute)
    jobs.start();assert entered.wait(3)
    duplicate=Jobs(tmp_path)
    monkeypatch.setattr(duplicate,'execute',lambda _:pytest.fail('duplicate worker'))
    duplicate.start()
    assert duplicate.create('script',{'reference':'fixture'})['id']==job['id']
    release.set()
    from hotpost.writing.jobs import _threads
    _threads[str(jobs.path.resolve())].join(4)
    assert calls==[job['id']]
    assert Jobs(tmp_path).get(job['id'])['result']=={'fixture':True}

def test_surviving_child_is_not_marked_interrupted_or_relaunched(tmp_path,monkeypatch):
    jobs=Jobs(tmp_path);job=jobs.create('script',{})
    jobs.update(job['id'],state='running')
    monkeypatch.setattr(jobs,'active_children',lambda _:True)
    monkeypatch.setattr(jobs,'execute',lambda _:pytest.fail('duplicate'))
    jobs.work()
    assert jobs.get(job['id'])['state']=='running'

def test_archived_job_read_without_external_service(tmp_path):
    adapter=StudioAdapter(Settings(data_dir=tmp_path))
    target=adapter.jobs.root/'legacy'/'a123.json';target.parent.mkdir()
    target.write_text(json.dumps({'id':'a123','state':'completed','result':{'scripts':[{'text':DRAFT}]}}),'utf-8')
    assert adapter.get('a123')['result']['scripts'][0]['text']==DRAFT
