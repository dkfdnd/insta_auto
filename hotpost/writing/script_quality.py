"""Short spoken-script checks; these are review signals, not authorship scores."""
import hashlib
import re

POLICY_VERSION = 'spoken-quality-5-repeated-sentence'


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def naturalness_review(text):
    issues = []
    patterns = [
        ('source_commentary', r'(?:방법|방식|제품|상품|기능)(?:이|가|을|를)?\s*(?:소개|설명|공개)(?:됐|되었|되어|돼)|(?:원본|참고\s*영상|이\s*영상)(?:에서는|에서|은|는)\s*(?:설명|소개|보여)',
         '자료를 해설하지 말고 시청자의 불편·달라지는 행동·생활 이득을 직접 말하세요.'),
        ('formal_phrase', r'에\s*있어서', '조사나 짧은 동사로 자연스럽게 말할 수 있는지 확인하세요.'),
        ('double_passive', r'(?:되어|보여|쓰여)\s*지(?:는|고|면|게|기|다|어요)', '겹친 피동 표현을 간단히 다듬어 보세요.'),
        ('empty_summary', r'시사하는\s*바가\s*크|결론적으로|요약하자면|종합적으로', '설명문식 요약이 필요한지 확인하세요. 짧은 CTA 뒤에는 덧붙이지 마세요.'),
    ]
    for code, pattern, message in patterns:
        for match in re.finditer(pattern, text):
            issues.append(dict(code=code, start=match.start(), end=match.end(),
                               excerpt=match.group(), message=message))
    # A local replacement can repeat the unchanged prefix at the patch boundary.
    # Match long adjacent clauses, not intentional short emphasis such as 톡톡.
    mapped=[(i,c) for i,c in enumerate(text) if re.match(r'[가-힣A-Za-z0-9]', c)]
    compact=''.join(c for _,c in mapped)
    for match in re.finditer(r'(?P<clause>[가-힣A-Za-z0-9]{8,80}?)(?P=clause)',compact):
        start=mapped[match.start()][0];end=mapped[match.end()-1][0]+1
        issues.append(dict(code='repeated_clause',start=start,end=end,excerpt=text[start:end],
                           message='같은 구절이 바로 반복됐어요. 교체 구간과 앞뒤 문장의 중복을 제거하세요.'))
    # Short complete questions can also be duplicated across a replacement
    # boundary. Require sentence boundaries instead of lowering the clause
    # threshold and flagging intentional short emphasis everywhere.
    previous = None
    for match in re.finditer(r'[^.!?。！？\n]+[.!?。！？]?', text):
        key = re.sub(r'[^가-힣A-Za-z0-9]', '', match.group())
        if previous and key == previous[0] and len(key) >= 6:
            start, end = previous[1], match.end()
            if not any(i['code']=='repeated_clause' and i['start'] <= start and i['end'] >= end-1 for i in issues):
                issues.append(dict(code='repeated_clause', start=start, end=end, excerpt=text[start:end],
                    message='같은 문장이 바로 반복됐어요. 수정 구간과 앞뒤 문장의 중복을 제거하세요.'))
        previous = (key, match.start()) if key else None
    # Familiar 해요 endings, an intentional contrast, short sentences, and
    # breathing commas are not errors in spoken Shorts.
    for connector in ('그리고', '또한', '따라서', '이를 통해'):
        matches = list(re.finditer(r'(?:^|(?<=[.!?。！？\n]))\s*(' + connector + r')\s', text))
        if len(matches) >= 3:
            match = matches[2]
            issues.append(dict(code='repeated_connector', start=match.start(1), end=match.end(1),
                               excerpt=connector, message='같은 연결어로 시작하는 문장이 반복돼요. 흐름에 필요한 것만 남겨 보세요.'))
    return dict(policy_version=POLICY_VERSION, script_sha256=digest(text),
                status='suggestions' if issues else 'no_flags', issues=issues,
                notice='표현 참고 검사입니다. 사실성·자연스러움·사람이 쓴 글인지 여부를 보증하지 않습니다.')
