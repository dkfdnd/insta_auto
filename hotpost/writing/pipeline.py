"""One draft, one review, at most one targeted repair and comparison."""
import json
from . import codex_writer
from .checks import review
from .contract import receipt
from .reference_evidence import choose_keyword
from .script_integrity import digest, risk
from .script_quantities import quantity_readings

TEXT_SCHEMA = {'type':'object','properties':{'text':{'type':'string','minLength':1,'maxLength':3000}},
               'required':['text'],'additionalProperties':False}
ISSUE_SCHEMA = {'type':'object','properties':{'issues':{'type':'array','items':{'type':'object',
    'properties':{'quote':{'type':'string'},'reason':{'type':'string'}},'required':['quote','reason'],
    'additionalProperties':False}}},'required':['issues'],'additionalProperties':False}


def generate(payload, directory, check, progress):
    contract=payload['writing_contract'];reference=payload['reference_script']
    owned = payload.get('generation_mode') == 'self_shot'
    if not reference.strip():raise ValueError('집필할 원본 참고 내용이 없습니다.')
    mode = 'self_shot' if owned else 'benchmark'
    keyword=payload.get('comment_keyword') or choose_keyword(reference,payload.get('reference_caption',''))[0] or '나도'
    evidence={'reference':reference,'reference_kind':payload.get('reference_kind','provided_text'),
              'reference_caption':payload.get('reference_caption',''),'comment_keyword':keyword,
              'request':payload.get('notes',''),'quantity_readings':list(quantity_readings(reference))}
    if owned:
        evidence.update(reference_kind='product_information', product=payload.get('product'), research=payload.get('research', {}))
    state={'directory':directory,'calls':[]}
    rules=contract['prompt']
    def ask(instruction, data, schema):
        return codex_writer.chat(instruction+'\n공통 규칙:\n'+rules,json.dumps(data,ensure_ascii=False),schema,check,state)
    progress(.15,'Codex가 대본 한 편을 작성하는 중')
    text=ask(('제품 정보로 짧고 강렬한 제품 후킹 쇼츠의 새 내레이션 한 편을 쓰세요. ' if owned else
              '원본을 벤치마킹한 완성 내레이션 한 편을 쓰세요. ')+ '분석문 없이 text만 반환하세요.',evidence,TEXT_SCHEMA)['text'].strip()
    if not text:raise ValueError('Codex가 빈 대본을 반환했습니다.')
    initial=text
    local=review(text,reference,evidence_mode=mode,keyword=keyword,contract=contract)
    progress(.55,'의미·문장 복사·새 사연 추가·말투를 확인하는 중')
    editorial={'status':'unavailable','issues':[]};repair={'attempted':False};warnings=[]
    try:
        value=ask(('제품 근거 자료와 후보를 대조하세요. ' if owned else '원본과 후보를 대조하세요. ')+
                  '실제 문제가 있는 문구를 정확히 인용하고 이유를 적으세요. '
                  '일반 기능의 직접 서술은 이번 규칙에서 허용합니다. 전언 말투를 강요하지 마세요. '
                  '벤치마킹 원본에 있는 친구 집 시식 등 경험담의 설정과 1인칭 재작성은 허용합니다. '
                  '설정 차용 자체를 오류로 지적하지 말고 문장 복사나 원본에 없는 별도 사연 추가와 구분하세요. '
                  '수정할 필요가 없으면 issues는 빈 배열입니다. 새 사실·인물·수치 추가나 복사는 구분하세요.',
                  {**evidence,'candidate':text},ISSUE_SCHEMA)
        if any(not i['quote'] or i['quote'] not in text for i in value['issues']):
            raise ValueError('검사 의견의 인용이 실제 대본과 일치하지 않습니다.')
        editorial={'status':'evaluated',**value}
    except (RuntimeError,ValueError,OSError) as exc:
        check();warnings.append('검사 미완료: '+str(exc)[:200])
    issues=[*local['quality_summary']['issues'],*[i['reason'] for i in editorial['issues']]]
    if issues:
        progress(.72,'문제가 있는 부분만 한 번 보완하는 중')
        repair={'attempted':True,'accepted':False,'before_sha256':digest(text)}
        try:
            proposed=ask('문제 부분만 고치고 정상 문장은 유지한 완성 대본을 반환하세요. 새 소구점·사실을 만들지 마세요. '
                         'findings의 실제 인용을 수정 대상으로 삼으세요. 복사 지적은 어미만 바꾸지 말고 '
                         '해당 구절의 어휘와 문장 구성을 다시 쓰되 기능·수치·고유명사는 유지하세요.',
                         {**evidence,'candidate':text,'issues':issues,
                          'findings':{'integrity':local['integrity_review']['issues'],
                                      'naturalness':local['naturalness_review']['issues'],
                                      'editorial':editorial['issues']}},TEXT_SCHEMA)['text'].strip()
            if not proposed:raise ValueError('Codex가 빈 수정안을 반환했습니다.')
            proposed_review=review(proposed,reference,evidence_mode=mode,keyword=keyword,contract=contract)
            progress(.86,'수정 전후를 비교하는 중')
            comparison=ask('두 원고를 같은 규칙으로 비교하세요. 뒤의 원고가 더 낫다고 가정하지 마세요. '
                           '후보 1이 의미·재작성·말투에서 실제로 개선됐으면 preferred=1, 동점·악화면 0입니다. '
                           'issues에는 선택한 원고에 남아 있는 문제만 정확히 인용하세요.',
                           {**evidence,'candidates':[text,proposed]},
                           {'type':'object','properties':{'preferred':{'type':'integer','enum':[0,1]},
                            'reason':{'type':'string'},'issues':ISSUE_SCHEMA['properties']['issues']},
                            'required':['preferred','reason','issues'],'additionalProperties':False})
            chosen=proposed if comparison['preferred']==1 else text
            if any(not i['quote'] or i['quote'] not in chosen for i in comparison['issues']):
                raise ValueError('비교 결과의 인용이 선택 대본과 다릅니다.')
            accept=(comparison['preferred']==1 and risk(proposed_review['integrity_review'])<=risk(local['integrity_review'])
                    and len(proposed_review['quality_summary']['issues'])<=len(local['quality_summary']['issues']))
            repair.update(accepted=accept,proposed=proposed,comparison=comparison)
            if accept:
                text=proposed;local=proposed_review;editorial={'status':'evaluated','issues':comparison['issues']}
            elif comparison['preferred']==0:
                editorial={'status':'evaluated','issues':comparison['issues']}
        except (RuntimeError,ValueError,OSError) as exc:
            check();repair['error']=str(exc)[:200];warnings.append('보완 미완료 · 이전 대본 보존')
    check()
    remaining=list(dict.fromkeys([*local['quality_summary']['issues'],*[i['reason'] for i in editorial['issues']]]))
    local['quality_summary'].update(status='issues_found' if remaining else
        'checks_clear_not_guaranteed' if editorial['status']=='evaluated' else 'not_evaluated',issues=remaining)
    candidate={**local,'title':'자동 집필','origin':'codex_internal','source_ids':['R1'],
        'single_pass_review':{**editorial,'script_sha256':digest(text),'reference_sha256':digest(reference),
                              'contract':receipt(contract),'advisory_only':True},
        'estimated_seconds':round(len(text.replace(' ',''))/6,1)}
    audit={'initial_text':initial,'repair':repair,'calls':state['calls'],'warnings':warnings}
    (directory/'writing-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),'utf-8')
    return {'type':'scripts','scripts':[candidate],'writing_contract':receipt(contract),'flow':'single-draft-v1',
        'generation_model':'codex-cli','generation_inference':{'provider':'codex','calls':state['calls'],'fallback':False},
        'benchmark':{} if owned else {'analysis':{'comment_keyword':keyword}},'warnings':warnings,'evidence':{'mode':mode}}
