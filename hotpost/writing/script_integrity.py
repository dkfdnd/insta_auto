"""Auditable narrow checks, not a general factual or semantic validator."""
import hashlib
import re
from decimal import Decimal

from .benchmark_wording import normalize, sentences, wording_review, ending_only_reuse
from .script_quantities import quantities

POLICY = 'narration-integrity-11-reference-anecdotes'
PERSONAL = re.compile(
    r'더라고|써보니|써봤|따라\s*샀|직접\s*(?:써|사용해|해봤)|'
    r'(?:친구|지인)(?:분|들)?(?:이|가|는|은|도)|'
    r'(?:저도|저는|제가|나는|내가).{0,45}(?:썼|샀|봤|했|생각|느꼈|얼려|사용)|'
    r'(?:친구|남편|아내|지인|우리\s*아이)(?:들)?(?:는|은|가|이|도|한테|에게)?.{0,35}'
    r'(?:샀|봤|본\s*적|가본|갔|추천|놀랐|알려|썼|쓰더|말해|말했|따라\s*사)|'
    r'(?:엄마|아빠|어머니|아버지|딸|아들|언니|오빠|동생|부모님).{0,35}'
    r'(?:추천\s*해\s*(?:줘서|준|줬)|추천하더|샀|사줬|알려줬|보더|좋아했|놀랐|물어봤|말했|찾아왔|'
    r'건네\s*(?:준|줬)|선물\s*(?:해\s*준|해\s*줬|받았|받은))|'
    r'(?:신어|입어|써|먹어|따라해)보(?:고|니|니까).{0,20}(?:놀랐|느꼈|반했)|'
    r'(?:썼|샀|신었|입었|먹었|써봤|신어봤|입어봤|주문했|설치했|챙겨봤|해봤)'
    r'(?:는데|더니|어요|거든|잖아)')


def strengthened(subject, part):
    """A negation elsewhere in the sentence must not excuse an absolute claim."""
    for match in re.finditer(re.escape(subject), part):
        clause = re.split(r'[,，;]|하지만|그러나|그리고', part[match.start():], maxsplit=1)[0]
        claim = re.search(r'피하|차단|완벽|완전|없어|방지|걱정\s*없이|안\s*(?:올라|오르|들어|생겨|생기|받|타|느끼)|'
                          r'(?:거의|전혀)\s*(?:느껴지|느끼|받)지\s*않', clause)
        if not claim:
            continue
        prefix = clause[:claim.start()]
        predicate = clause[claim.start():claim.start()+48]
        if re.search(r'덜|줄|일부|낮', prefix):
            continue
        if re.search(r'(?:차단|방지|피하|없어).{0,10}(?:않|못|어렵|아니)|'
                     r'(?:보장|확인).{0,5}(?:않|아니)|(?:차단|방지).{0,6}도움|'
                     r'안\s*(?:받|타|느끼).{0,12}(?:아니|않)|'
                     r'(?:보장|확인)할\s*수(?:는|도)?\s*없|(?:보장|확인)하기\s*(?:어렵|어려)', predicate):
            continue
        return True
    return False


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def experience_issues(reference, text):
    """Flag a new anecdote only when the reference has no experience language.

    Reference anecdotes may be adapted, including first-person narration. This
    narrow lexical check cannot establish that two stories mean the same thing;
    the shared Codex review checks additions and changes within an adaptation.
    """
    if PERSONAL.search(reference):
        return []
    return [{'code':'unsupported_experience','severity':'critical','quote':part,
             'message':'원본에 없는 체험·별도 사연을 추가했는지 확인하세요. 원본에 있는 경험담 설정의 차용과 재작성은 허용합니다.'}
            for part in sentences(text) if PERSONAL.search(part)]


def invariants(reference):
    """Extract explicit source constraints; do not invent explanatory prose."""
    rows=[]
    for part in sentences(reference):
        if (re.search(r'(?:바닥|지면|땅)(?:에서|과|와)?\s*(?:떠\s*있|떨어져|띄워|띄운)',part)
                and not re.search(r'(?:떠\s*있|떨어져).{0,5}(?:않|아니)',part)):
            rows.append({'kind':'ground_clearance','value':'off_ground','source_quote':part})
        if re.search(r'냉장.{0,12}보관', part) and not re.search(r'냉장.{0,15}(?:말고|않|마세요)',part):
            rows.append({'kind':'storage','value':'냉장','source_quote':part})
        if re.search(r'안\s*섞|섞.{0,5}않|섞.{0,8}(?:일|걱정).{0,4}없',part):
            rows.append({'kind':'separation','value':'not_mixed','source_quote':part})
        if re.search(r'덜|줄어|줄여',part):
            for subject in re.findall(r'습기|냉기|소음|먼지|오염|부담',part):
                rows.append({'kind':'mitigation','value':subject,'source_quote':part})
        for value,unit in quantities(part):
            rows.append({'kind':'quantity','value':value,'unit':unit,'source_quote':part})
    return rows


def inspect(reference, text):
    issues=experience_issues(reference, text)
    anchors=invariants(reference)
    for part in sentences(text):
        clearance=next((r for r in anchors if r['kind']=='ground_clearance'),None)
        contact=re.search(r'(?:바닥|지면|땅)에\s*(?:닿(?:아|는|아요)|놓(?:여|인)|붙(?:어|은)|깔(?:려|린))',part)
        if clearance and contact:
            clause=re.split(r'[,，;]|으니|때문|덕분|그래서|그리고|하지만',part[contact.start():],maxsplit=1)[0]
            contrasting=re.search(r'(?:아니라|않|것보다|텐트보다|경우보다|와\s*달리|과\s*달리)',clause)
            if not contrasting:
                issues.append({'code':'ground_clearance_reversal','severity':'critical','quote':part,
                    'source_quote':clearance['source_quote'],
                    'message':'원본은 바닥과 떨어진 구조입니다. 바닥에 닿거나 놓인 구조로 뒤집지 마세요.'})
        cold=next((r for r in anchors if r['kind']=='storage'),None)
        wrong_cold=(re.search(r'냉동(?:실)?.{0,10}(?:보관|넣|두|둬)',part) or
                    re.search(r'(?:넣|섞|더해|붓|부어).{0,20}얼리(?:면|고|세요)|얼려\s*두면.{0,15}(?:돼|좋|달라)',part))
        caution=re.search(r'마세요|말고|않|안\s*(?:돼|되)|잠깐|(?:넣|얼리).{0,6}(?:려고요|려구요)',part)
        if cold and wrong_cold and not caution:
            issues.append({'code':'storage_reversal','severity':'critical','quote':part,'source_quote':cold['source_quote'],
                'message':'원본은 냉장 보관입니다. 해결 방법을 냉동으로 바꾸지 마세요.'})
        separation=next((r for r in anchors if r['kind']=='separation'),None)
        if (separation and re.search(r'섞(?:이니까|여서|여요|여도|입니다|여\s*좋)',part)
                and not re.search(r'안\s*섞|않|없|않게|방지|곤란|불편|걱정|잖아요',part)):
            issues.append({'code':'functional_polarity_reversal','severity':'critical','quote':part,
                'source_quote':separation['source_quote'],
                'message':'원본은 분리해 섞이지 않는 기능입니다. 섞이는 것이 이득인 것처럼 바꾸지 마세요.'})
        for anchor in (r for r in anchors if r['kind']=='mitigation'):
            if strengthened(anchor['value'], part):
                issues.append({'code':'mitigation_strengthened','severity':'critical','quote':part,
                    'source_quote':anchor['source_quote'],
                    'message':'원본의 줄임·완화 효과를 차단·완전 회피로 강화하지 마세요.'})
        for value,unit in quantities(part):
            known=[r for r in anchors if r.get('unit')==unit]
            if known and Decimal(value) not in {Decimal(r['value']) for r in known}:
                issues.append({'code':'quantity_changed','severity':'critical','quote':part,
                    'source_quote':known[0]['source_quote'],'message':'원본의 수치·단위를 바꾸거나 새 수치를 추가하지 마세요.'})
    wording=wording_review(reference,text)
    originals=sentences(reference);draft=sentences(text)
    if wording['copied_hook'] and draft:
        issues.append({'code':'copied_hook','severity':'copy','quote':draft[0],
                       'source_quote':originals[0],'message':'후킹 효과를 유지하되 실제 표현을 바꾸세요.'})
    for original in wording['copied_body_spans']:
        quote=next((p for p in draft if normalize(original) in normalize(p) or ending_only_reuse(original,p)),None)
        if quote is None:
            # A copied source sentence can span several lines in the candidate.
            mapped=[(i,c.lower()) for i,c in enumerate(text) if re.match(r'[가-힣a-zA-Z0-9]',c)]
            compact=''.join(c for _,c in mapped);pos=compact.find(normalize(original))
            if pos>=0:quote=text[mapped[pos][0]:mapped[pos+len(normalize(original))-1][0]+1]
        if quote:
            issues.append({'code':'copied_body','severity':'copy','quote':quote,'source_quote':original,
                           'message':'어미 교정만 하지 말고 같은 동작·이득을 다른 문장으로 표현하세요.'})
    unique={(r['code'],r['quote']):r for r in issues}
    return {'policy':POLICY,'script_sha256':digest(text),'reference_sha256':digest(reference),
            'status':'issues_found' if unique else 'no_flags','issues':list(unique.values()),
            'invariants':anchors,'advisory_only':True,'semantic_guarantee':False}


def risk(review):
    return (sum(r['severity']=='critical' for r in review['issues']),
            sum(r['severity']=='copy' for r in review['issues']))
