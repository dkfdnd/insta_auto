"""Grounded comparative editorial selection; scores are not predicted engagement."""
import hashlib
import json
import re

from .script_rewriter import _generate
from .studio_script_checks import refresh_local_reviews, ReviewUnavailable

REVIEW_POLICY = 22


def wording_issues(reference, candidate):
    review = candidate.get('rewrite_review', {}).get('wording_review') or {}
    issues = list(review.get('issues', []))
    issues.extend(candidate.get('benchmark_review', {}).get('wording', {}).get('issues', []))
    compact = lambda value: re.sub(r'[^가-힣a-z0-9]', '', value.lower())
    opening = lambda value: re.split(r'[.!?。！？]+|\n+', value.strip())[0]
    if compact(reference) and compact(reference) == compact(candidate['text']):
        issues.append('원본 대본과 동일합니다.')
    elif compact(opening(reference)) and compact(opening(reference)) == compact(opening(candidate['text'])):
        issues.append('원본 후킹 문장을 그대로 사용했습니다.')
    return list(dict.fromkeys(issues))


def unsupported_claims(text, reference=''):
    """Reference anecdotes are allowed; new stories and absolute claims differ."""
    from .writing.script_integrity import experience_issues
    reasons = list(dict.fromkeys(i['message'] for i in experience_issues(reference, text)))
    if re.search(r'(?:흔들|넘어|다칠|다치|위험)[^.!?\n]{0,35}(?:걱정|염려|없|방지|안전)', text):
        reasons.append('영상만으로 흔들림·전도·상해 방지나 안전을 보장할 수 없습니다.')
    if re.search(r'먼지[^.!?\n]{0,35}(?:필요\s*(?:도\s*)?없|완벽|완전|100\s*%)', text):
        reasons.append('영상만으로 청소가 불필요하거나 먼지가 완전히 차단된다고 보장할 수 없습니다.')
    if re.search(r'(?:침입|도난|강제\s*개방)[^.!?\n]{0,35}(?:완벽|완전|100\s*%|절대|걱정\s*(?:이|도)?\s*없)', text):
        reasons.append('설치 시연만으로 침입·도난·강제 개방을 완전히 막는다고 보장할 수 없습니다.')
    if re.search(r'첫\s*(?:문장|질문)|가정하지\s*마세요|(?:대본|스크립트|내레이터)[^.!?\n]{0,30}(?:작성|생성|검토)|관찰과[^.!?\n]{0,35}제안만\s*설명|Return\s+(?:one\s+)?JSON|observed_facts', text, re.I):
        reasons.append('제작 지시문이 내레이션에 섞여 있습니다.')
    return reasons


def integrity_risk(reference,item):
    review=item.get('integrity_review',{})
    bound=(review.get('script_sha256')==hashlib.sha256(item['text'].encode()).hexdigest() and
           review.get('reference_sha256')==hashlib.sha256(reference.encode()).hexdigest())
    # Historical receipts retain the obsolete blanket ban for audit only.
    # Recheck absent-reference anecdotes under the current rule below.
    issues=[i for i in review.get('issues',[]) if i.get('code') != 'borrowed_experience'] if bound else []
    return (max(len(unsupported_claims(item['text'],reference)),sum(i.get('severity')=='critical' for i in issues)),
            max(len(wording_issues(reference,item)),sum(i.get('severity')=='copy' for i in issues)))


def remaining_quality_issues(reference,item):
    summary=item.get('quality_summary',{})
    bound=(summary.get('script_sha256')==hashlib.sha256(item['text'].encode()).hexdigest() and
           summary.get('reference_sha256')==hashlib.sha256(reference.encode()).hexdigest())
    issues=list(summary.get('issues',[])) if bound else []
    # Legacy results also retain local errors after focused recovery.
    issues.extend(item.get('benchmark_review',{}).get('issues',[]))
    issues.extend(item.get('rewrite_review',{}).get('reasons',[]))
    issues.extend(item.get('editorial_review',{}).get('local_issues',[]))
    return list(dict.fromkeys(issues))


def approved_recovery(reference,item):
    approval=item.get('approval',{})
    return (item.get('origin')=='user_approved_recovery' and approval.get('origin')=='explicit_user_approval' and
        approval.get('script_sha256')==hashlib.sha256(item['text'].encode()).hexdigest() and
        approval.get('reference_sha256')==hashlib.sha256(reference.encode()).hexdigest() and
        bool(approval.get('approval_evidence')) and integrity_risk(reference,item)==(0,0))


def choose(settings, state, valid):
    if not valid:
        raise ValueError('선택할 생성 대본이 없습니다.')
    reference=state.get('reviewed_original_text',state.get('original_text',''))
    if len(valid)==1 and valid[0][1].get('origin')=='codex_internal':
        from .writing.contract import receipt
        index,item=valid[0];bound=item.get('single_pass_review',{})
        if (bound.get('script_sha256')==hashlib.sha256(item['text'].encode()).hexdigest()
                and bound.get('reference_sha256')==hashlib.sha256(reference.encode()).hexdigest()
                and bound.get('contract')==receipt()):
            return index,{'selected_index':index,'review_policy':REVIEW_POLICY,'advisory_only':True,
                'quality_status':item['quality_summary']['status'],'issues':item['quality_summary']['issues'],
                'reason':'Codex 단일 집필·검사 결과로 제작 계속','script_priority':True,'footage_role':'editing_only'}
    approved=next(((i,s) for i,s in valid if approved_recovery(reference,s)),None)
    if approved:
        return approved[0], {'selected_index':approved[0],'review_policy':REVIEW_POLICY,
            'reason':'동일 원본에 대해 사용자가 승인한 대본으로 복구','approval_id':approved[1]['approval']['id'],
            'advisory_only':True,'script_priority':True,'footage_role':'editing_only','quality_status':'user_approved_recovery'}
    try:
        valid = refresh_local_reviews(settings, reference, valid)
        return _choose_scored(settings, state, valid)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        # Ranking is optional editorial assistance, not a production gate.
        if isinstance(exc, ReviewUnavailable):
            valid = exc.candidates
        index, item = min(valid, key=lambda pair: (integrity_risk(reference,pair[1]), len(
            pair[1].get('rewrite_review', {}).get('reasons', [])), pair[0]))
        return index, {'selected_index': index, 'review_policy': REVIEW_POLICY,
                       'reason': '자동 평가 미완료 · 생성 대본으로 제작 계속',
                       'advisory_only': True, 'quality_status':'unresolved' if any(integrity_risk(reference,item)) or remaining_quality_issues(reference,item) else 'not_evaluated',
                       'issues': [str(exc)[:500]],'script_priority':True,'footage_role':'editing_only'}


def _choose_scored(settings, state, valid):
    from .writing.contract import receipt as contract_receipt
    from .reference_context import reference_kind
    folder = settings.data_dir / 'studio' / state['id'] / 'top-pick'
    folder.mkdir(parents=True, exist_ok=True)
    reference = state.get('reviewed_original_text', state.get('original_text', ''))
    evidence = {'purpose':'script_selection', 'review_policy':REVIEW_POLICY, 'writing_provider':'codex', 'writing_contract':contract_receipt(), 'original_speech':reference,
                'reference_kind':reference_kind(state),
                'hook_contract':state.get('benchmark_analysis', {}).get('hook_contract', {}),
                'candidates':[{'index':i,'text':v['text'], 'wording_issues':wording_issues(reference,v),
                               'editorial_review':v.get('editorial_review', {}),
                               'writing_contract':v.get('writing_contract', {}),
                               'integrity_risk':integrity_risk(reference,v),
                               'local_checks':{'integrity_policy':v.get('integrity_review',{}).get('policy'),
                                   'rewrite_policy':v.get('rewrite_review',{}).get('policy_version'),
                                   'issues':remaining_quality_issues(reference,v)}} for i,v in valid]}
    key = hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest()
    receipt = folder / (key+'.json')
    if receipt.is_file():
        evaluation = json.loads(receipt.read_text(encoding='utf-8'))
        return evaluation['selected_index'], evaluation
    # Reuse only a review bound to this exact text and contract. Do not perform
    # a second, footage-dependent ranking of already reviewed narration.
    reviewed = all(v.get('editorial_review', {}).get('status') == 'evaluated'
        and v['editorial_review'].get('review_contract_checked') is True
        and v['editorial_review'].get('review_contract_policy')=='review-contract-6'
        and v['editorial_review'].get('script_sha256') == hashlib.sha256(v['text'].encode()).hexdigest()
        and v['editorial_review'].get('reference_sha256') == hashlib.sha256(reference.encode()).hexdigest()
        and v['editorial_review'].get('contract') == v.get('writing_contract')
        and v.get('writing_contract') == contract_receipt()
        for _,v in valid)
    if reviewed:
        result = {'evaluations':[{'index':i, 'eligible':True,
            'scores':{'hook':v['editorial_review']['scores']['hook'],
                      'grounding':v['editorial_review']['scores']['grounding'],
                      'narration':min(v['editorial_review']['scores'][k] for k in ('direct_address','spoken','appeal'))},
            'editorial_total':v['editorial_review']['total'],
            'reason':v['editorial_review']['reason'],
            'issues':[x['reason'] for x in v['editorial_review'].get('issues', [])] + v['editorial_review'].get('local_issues', [])}
            for i,v in valid]}
    else:
        result = _generate(settings,
            'Compare Korean narration candidates using ONLY original speech and the common writing contract. '
            'Ignore source availability and ease of editing; the narration takes priority. Do not rewrite any text. '
            'Preserve the original hook effect, appeal and sequence but rephrase the opening AND body. '
            'Use wording_issues. Allow adaptations of reference anecdotes, including first-person friend-house tasting stories. '
            'Do not penalize a borrowed setting; distinguish it from copied wording and new unsupported anecdotes or facts. '
            'Follow the shared rules on direct statements. '
            'Narration score measures direct viewer address, specific everyday payoff, curiosity and spoken rhythm; '
            'do not reward source commentary such as 방법이 소개됐어요. '
            'Scores 0..5: hook=fidelity and rephrasing, grounding=evidence and uncertainty, narration=viewer experience. '
            'A replaced hook mechanism must score below 3. Product-name omission and missing footage are not failures. '
            'Return {evaluations:[{index,eligible:boolean,scores:{hook,grounding,narration},reason:string,issues:[string]}]}. '
            'Include every candidate once. Reasons in Korean with actual wording. These are editorial scores, not virality.', evidence)
    # Keep the actual response even when ranking must fall back without scores.
    audit_folder=folder/'reviews'
    audit_folder.mkdir(exist_ok=True)
    (audit_folder/(key+'.json')).write_text(
        json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    values = result.get('evaluations', [])
    expected = {i for i,_ in valid}
    if len(values)!=len(expected) or {v.get('index') for v in values}!=expected:
        raise ValueError('Top Pick 후보 평가 응답이 누락되었습니다.')
    for row in values:
        item=next(s for i,s in valid if i==row['index'])
        row['integrity_risk']=integrity_risk(reference,item)
        if row.get('status')=='unavailable':
            # A rejected critic response has no usable score. Preserve its audit
            # without throwing away other candidates' valid evaluations.
            row.pop('scores',None)
            row.pop('total',None)
            row.pop('editorial_total',None)
            row['eligible']=False
            continue
        scores = row.get('scores', {})
        if any(type(scores.get(k)) is not int or not 0<=scores[k]<=5 for k in ('hook','grounding','narration')):
            raise ValueError('Top Pick 점수 응답이 올바르지 않습니다.')
        row['total'] = row.get('editorial_total', sum(scores[k]*w for k,w in [('hook',.4),('grounding',.2),('narration',.4)]))
        issues = unsupported_claims(next(item['text'] for index, item in valid if index == row['index']),reference)
        row['wording_issues'] = wording_issues(reference, next(item for index,item in valid if index == row['index']))
        issues.extend(row['wording_issues'])
        row['detected_issues'] = list(dict.fromkeys(issues + remaining_quality_issues(reference,item)))
        if issues:
            row['eligible'] = False
            row['issues'] = list(dict.fromkeys([*row.get('issues', []), *issues]))
            row['reason'] = ' / '.join(issues)
    lowest=min(v['integrity_risk'] for v in values)
    pool = [v for v in values if v['integrity_risk']==lowest and v.get('status')!='unavailable']
    if not pool:
        # Do not promote a known meaning/copy error just because a cleaner
        # candidate's critic is unavailable. choose() retains advisory fallback.
        raise ValueError('오류가 가장 적은 후보의 자동 평가를 완료하지 못했습니다.')
    acceptable = [v for v in pool if v.get('eligible') is True and v['scores']['grounding']>=3 and v['scores']['hook']>=3]
    winner = max(acceptable or pool, key=lambda v:(-len(v['detected_issues']),v['total'],-len(v.get('issues', [])),-v['index']))
    evaluation = {'selected_index':winner['index'], 'reason':winner['reason'], 'evaluations':values,
                  'advisory_only':True, 'review_policy':REVIEW_POLICY,
                  'quality_status':'unresolved' if any(lowest) or winner['detected_issues'] or winner.get('issues')
                      or min(winner['scores'].values())<3 else 'checks_clear_not_guaranteed',
                  'script_priority':True, 'footage_role':'editing_only', 'review_reused':reviewed,
                  'evidence_sha256':key, 'rubric':'대본 평가 우선 · 확보 장면은 순위와 무관'}
    receipt.write_text(json.dumps(evaluation,ensure_ascii=False,indent=2),encoding='utf-8')
    return winner['index'], evaluation
