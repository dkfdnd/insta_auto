"""Keep narration, visible text and post captions distinct in writing inputs."""
import hashlib
import re


def comment_keyword(text):
    # Quote/bracket/emoji wrappers are common in typed Instagram captions.
    wrap = r'[^가-힣A-Za-z0-9\n]*'
    keyword = r'([가-힣A-Za-z0-9]{1,20})'
    quote = r'[\'"‘’“”\[\]]'
    leave = r'(?:남(?:겨|기)|쓰(?:면|세|시)|적(?:어|으))'
    patterns = [
        r'댓글\s*(?:에|로)?\s*(?:[한두세네1234]\s*글자)?\s*[（(]\s*' + keyword + r'\s*[)）]\s*' + leave,
        r'댓글(?:에|로)?' + wrap + keyword + wrap + r'\s*(?:이라고|라고)?\s*' + leave,
        quote + keyword + quote + r'\s*(?:이라고|라고)?\s*(?:댓글(?:에|로)?\s*)?' + leave,
        r'(?:정보는|비법은|궁금하시면|궁금하신\s*분은)\s+' + keyword + r'\s*' + leave,
        r'(?:^|\n)' + wrap + keyword + r'\s+' + leave,
    ]
    for pattern in patterns:
        match = re.search(pattern, str(text))
        if match and match.group(1) not in {
            '아무거나', '아무', '댓글', '두글자', '세글자', '후기', '의견',
            '감상', '한마디', '자유롭게', '말씀', '질문', '정보',
        }:
            return match.group(1)
    return ''


def context(payload):
    """These are reference claims, not independently verified product facts."""
    return [{
        'id': 'C1', 'kind': 'post_caption', 'title': '원본 게시물 본문',
        'text': payload['reference_caption'], 'independently_verified': False,
        'sha256': hashlib.sha256(payload['reference_caption'].encode()).hexdigest(),
    }] if payload.get('reference_caption', '').strip() else []


def choose_keyword(reference, caption=''):
    # Typed source text is not subject to ASR pronunciation mistakes.
    for kind, text in [('post_caption', caption), ('reference_text', reference)]:
        value = comment_keyword(text)
        if value:
            return value, kind
    return '', 'default'


def comment_issues(text, keyword):
    """Shared writing/recovery checks; no feature metadata required."""
    issues=[]
    if keyword not in text or not re.search(r'댓글|남겨',text):
        issues.append('주제와 연결되는 댓글 유도가 없습니다.')
    extracted=comment_keyword(text)
    if extracted and extracted!=keyword:
        issues.append('댓글 요청의 키워드가 선택한 키워드와 다릅니다.')
    if len(re.findall(r'댓글(?:에|로)?',text))>1:
        issues.append('댓글 요청이 반복됩니다. 선택한 키워드로 한 번만 요청하세요.')
    if re.search(r'(?:정보|링크|할인|선물).{0,15}(?:보내|드릴|드려)',text):
        issues.append('확인되지 않은 댓글 보상을 약속했습니다.')
    return issues


def source_record(reference, kind='speech'):
    kinds = {
        'speech': ('reference_narration', '원본 발화'),
        'screen_text': ('reference_screen_text', '원본 화면 글자'),
        'mixed': ('reference_mixed', '원본 발화·화면 글자 대조본'),
        'provided_text': ('reference_text', '저장된 원본 대본 · 출처 구분 미확인'),
    }
    source_kind, title = kinds[kind]
    return {'id': 'R1', 'kind': source_kind, 'title': title, 'text': reference, 'url': ''}
