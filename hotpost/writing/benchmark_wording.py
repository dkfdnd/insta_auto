"""Detect literal reuse without demanding a new angle or a similarity quota."""
import re
from difflib import SequenceMatcher

POLICY = 'hook-and-body-rephrase-20261006-v5'
RULE = (
    '후킹 보존은 문장 복사가 아니라 후킹 효과의 보존입니다. 첫 문장부터 본문까지 우리 표현으로 소폭 재작성하세요. '
    '원본의 대상·경고/질문/반전 방식·소구점·궁금증·정보 공개 순서는 유지하되 실제 어휘와 문장 구성을 바꾸세요. '
    '문장부호·띄어쓰기·숫자 교정·어미 변경·댓글 문장 추가만으로 재작성했다고 보지 마세요. '
    '겹침 비율을 낮추려고 새 사실이나 다른 장점을 만들거나 순서를 뒤집지 마세요. '
)


def normalize(text):
    return re.sub(r'[^가-힣a-z0-9]', '', text.lower())


def sentences(text):
    return [v.strip() for v in re.split(r'(?<!\d)[.!?。！？]+|[.!?。！？]+(?!\d)|\n+', text) if v.strip()]


def ending_only_reuse(left,right):
    a,b=normalize(left),normalize(right)
    shared=0
    for x,y in zip(a,b):
        if x!=y:break
        shared+=1
    return shared>=12 and max(len(a),len(b))-shared<=5


def greeting_only_reuse(left, right):
    """Adding/removing a greeting does not rewrite the rest of a hook."""
    def core(value):
        return re.sub(r'^(?:(?:와|자|여러분)(?:\s*[,!]?\s+|(?=[,!]))[,!]?\s*)+',
                      '', value.strip())
    a, b = normalize(core(left)), normalize(core(right))
    return len(a) >= 7 and a == b


def wording_review(reference, text):
    original, draft = sentences(reference), sentences(text)
    left, right = normalize(reference), normalize(text)
    codes, reasons = [], []
    if left and left == right:
        codes.append('unchanged_script')
        reasons.append('공백·문장부호 외에 바뀐 내용이 없습니다. 후킹과 본문을 실제로 재작성하세요.')
    opening = normalize(original[0]) if original else ''
    hook = normalize(draft[0]) if draft else ''
    # Appending a clause or changing only the sentence ending is still reuse.
    shared = 0
    for a, b in zip(opening, hook):
        if a != b:
            break
        shared += 1
    # Dropping a scene-setting prefix and a filler inside it still leaves the
    # same hook. A substring check alone misses this two-part deletion.
    source_characters=iter(opening)
    deletion_only=bool(len(hook)>=12 and all(char in source_characters for char in hook))
    copied_hook = bool(opening and (opening == hook or opening in hook or
        deletion_only or
        (draft and greeting_only_reuse(original[0], draft[0])) or
        # A longer question tag does not rewrite an intact source clause.
        # The source remainder matters here: adding "혹시 본 적 있어요?"
        # must not evade the same check applied to a short "보셨나요?".
        (shared >= 12 and len(opening) - shared <= 5)))
    if copied_hook:
        codes.append('unchanged_hook')
        reasons.append('첫 후킹 문장을 그대로 쓰거나 끝부분만 바꿨습니다. 같은 효과를 다른 문장으로 표현하세요.')
    copied = [part for part in original[1:] if len(normalize(part)) >= 12
              and not re.search(r'댓글|남겨', part) and (normalize(part) in right or
                  any(ending_only_reuse(part,p) for p in draft))]
    # Removing one noun or inserting line breaks must not hide long reused
    # clauses. Preserve source offsets so repairs can cite the actual phrase.
    opening_end = reference.find(original[0]) + len(original[0]) if original else 0
    cta_ranges=[]
    position=0
    for part in original:
        start=reference.find(part,position)
        position=start+len(part)
        if start>=0 and re.search(r'댓글|남겨',part):
            cta_ranges.append((start,position))
    mapped = [(i,c.lower()) for i,c in enumerate(reference)
              if i >= opening_end and re.match(r'[가-힣a-zA-Z0-9]',c)
              and not any(start<=i<end for start,end in cta_ranges)]
    body = ''.join(c for _,c in mapped)
    for block in SequenceMatcher(None, body, right, autojunk=False).get_matching_blocks():
        if block.size < 18:
            continue
        phrase = reference[mapped[block.a][0]:mapped[block.a+block.size-1][0]+1]
        if re.search(r'댓글|남겨',phrase):
            continue
        if not any(normalize(phrase) in normalize(p) for p in copied):
            copied.append(phrase)
    if copied:
        codes.append('copied_body')
        reasons.append('본문에 원문 그대로인 문장이 남았습니다. 의미와 순서는 유지하고 해당 문장을 다시 쓰세요.')
    return {'policy': POLICY, 'codes': codes, 'issues': reasons,
            'copied_hook': copied_hook, 'copied_body_spans': copied, 'advisory_only': True}


def candidate_wording(reference, scripts):
    reviews = [wording_review(reference, s['text']) for s in scripts]
    for i, script in enumerate(scripts):
        if any(i != j and normalize(script['text']) == normalize(other['text'])
               for j, other in enumerate(scripts)):
            reviews[i]['codes'].append('duplicate_candidate')
            reviews[i]['issues'].append('다른 후보와 같은 대본입니다. 같은 소구점을 다른 표현으로 작성하세요.')
    return reviews
