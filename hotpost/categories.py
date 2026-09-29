"""Stable broad content categories; never expose arbitrary caption nouns as topics."""
import re

CATEGORIES = {
    '캠핑·여행': ('캠핑', '차박', '텐트', '여행', '캐리어', 'camping', '아웃도어'),
    '육아·반려동물': ('육아', '아기', '유아', '아이방', '반려', '강아지', '고양이', '육묘'),
    '뷰티·패션': ('뷰티', '화장품', '메이크업', '스킨케어', '선크림', '코디', '패션', '헤어', '네일'),
    '디지털·가전': ('가전', '충전', '스마트폰', '스마트워치', '이어폰', '노트북', '키보드', '로봇청소기'),
    '청소·세탁': ('청소', '세탁', '얼룩', '곰팡이', '물때', '세제', '빨래', '먼지', '욕실'),
    '정리·수납': ('수납', '정리함', '정리법', '정리템', '옷장', '서랍', '옷걸이', '압축팩'),
    '주방·요리': ('주방', '요리', '레시피', '조리', '프라이팬', '후라이팬', '냄비', '식기', '도마', '싱크대', '밀폐용기', '설거지'),
    '인테리어·생활': ('인테리어', '가구', '조명', '침구', '커튼', '집꾸미기', '이불', '침대', '소파', '생활용품'),
    '건강·운동': ('운동', '스트레칭', '헬스', '필라테스', '요가', '건강', '마사지', '러닝'),
    '식품·맛집': ('맛집', '간식', '디저트', '베이커리', '식품', '먹방', '카페', '과일'),
}


def post_categories(post):
    text = re.sub(r'https?://\S+', ' ', post.caption.lower()) + ' ' + ' '.join(post.hashtags).lower()
    scores = [(sum(1 for word in words if word in text), label) for label, words in CATEGORIES.items()]
    best = max(scores, key=lambda item: item[0])
    return [best[1]] if best[0] else ['생활·기타']


def category_topics(scored, limit):
    groups = {}
    for item in scored:
        if item.tier < 1:
            continue
        for label in post_categories(item.post):
            group = groups.setdefault(label, {'score': 0, 'codes': set(), 'accounts': set()})
            group['score'] += item.tier
            group['codes'].add(item.post.shortcode)
            group['accounts'].add(item.post.username)
    return [dict(label=label, kind='category', score=g['score'], posts=len(g['codes']),
                 accounts=len(g['accounts']), examples=sorted(g['codes'])[:8])
            for label, g in sorted(groups.items(), key=lambda pair: (pair[0] == '생활·기타', -pair[1]['score']))[:limit]]
