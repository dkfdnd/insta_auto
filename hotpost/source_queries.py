"""근거가 있는 제품·브랜드·특징을 언어와 검색 의도별로 확장한다.

브랜드/품번은 관측된 텍스트에서만 추출한다. 사전에 없는 제품의 번역을 만들어내지 않는다.
"""
from __future__ import annotations

import re
from itertools import zip_longest

PRODUCTS = [
    ('여권 복대', 'hidden passport money belt', '隐形护照腰包', ('여권지갑', '여권 지갑', '여권 복대', '여행 복대', 'money belt', 'passport pouch', '护照腰包')),
    ('뮬 운동화', 'backless mule sneakers', '半拖运动鞋', ('뮬', 'mule sneakers', 'backless sneakers', '半拖运动鞋')),
    ('마늘간장 치킨', 'honey garlic soy chicken', '蜂蜜蒜香酱油鸡', ('마늘간장', '마늘 간장', 'honey garlic chicken', '蒜香鸡')),
    ('백팩', 'backpack', '双肩包', ('백팩', '배낭', 'backpack', 'rucksack', '双肩包', '背包')),
    ('숄더백', 'shoulder bag', '单肩包', ('숄더백', 'shoulder bag', '单肩包')),
    ('여행 정리 가방', 'travel organizer bag', '旅行收纳袋', ('여행 정리', 'travel organizer', '旅行收纳袋')),
    ('컵홀더', 'cup holder', '杯架', ('컵홀더', '컵 홀더', 'cup holder', '杯架')),
    ('차량 수납함', 'car seat gap organizer', '汽车座椅缝隙收纳盒', ('차량 수납', 'seat gap organizer', '缝隙收纳')),
    ('쓰레기통', 'trash bin', '垃圾桶', ('쓰레기통', 'trash bin', '垃圾桶')),
    ('주방 수납함', 'kitchen storage organizer', '厨房收纳盒', ('주방 수납', 'kitchen storage', '厨房收纳')),
    ('청소 브러시', 'cleaning brush', '清洁刷', ('청소솔', '청소 브러시', 'cleaning brush', '清洁刷')),
    ('채칼', 'vegetable slicer', '切菜器', ('채칼', 'vegetable slicer', '切菜器')),
    ('보관 용기', 'food storage container', '食品保鲜盒', ('밀폐용기', '보관 용기', 'food storage', '保鲜盒')),
    ('휴대용 선풍기', 'portable fan', '便携风扇', ('휴대용 선풍기', 'portable fan', '便携风扇')),
    ('휴대폰 거치대', 'phone holder stand', '手机支架', ('폰 거치대', '휴대폰 거치대', 'phone holder', '手机支架')),
    ('신발 세척 도구', 'shoe cleaning tool', '鞋子清洁工具', ('신발 세척', 'shoe cleaning', '鞋子清洁')),
    ('반려동물 털 제거기', 'pet hair remover', '宠物除毛器', ('털 제거', 'pet hair remover', '除毛器')),
]
BRANDS = [('adidas', '阿迪达斯', ('adidas', '아디다스', '阿迪达斯')),
          ('UGG', 'UGG', ('ugg', '어그')),
          ('nike', '耐克', ('nike', '나이키', '耐克')),
          ('dyson', '戴森', ('dyson', '다이슨', '戴森')),
          ('xiaomi', '小米', ('xiaomi', '샤오미', '小米'))]
FEATURES = [('nylon', '尼龙', ('나일론', 'nylon', '尼龙')),
            ('suede', '绒面革', ('스웨이드', 'suede', '绒面革')),
            ('flap', '翻盖', ('플랩', 'flap', '翻盖')),
            ('drawstring', '抽绳', ('조임끈', 'drawstring', '抽绳')),
            ('front zip pocket', '前拉链口袋', ('앞 지퍼', 'front zip', '前拉链')),
            ('foldable', '可折叠', ('접이식', 'foldable', '可折叠')),
            ('car door hanging', '车门挂式', ('차문', 'car door', '车门'))]
NOISE = {'recognize text', 'text in image', 'similar images', 'image appears to contain',
         'person', 'people', 'human', 'video', 'image', 'photo', 'search'}


def language(text: str) -> str:
    if re.search(r'[가-힣]', text):
        return 'ko'
    if re.search(r'[\u3400-\u9fff]', text):
        return 'zh'
    if re.search(r'[A-Za-z]', text) and not re.search(r'[\u0400-\u04ff]', text):
        return 'en'
    return 'other'


def clean_terms(terms: list[str]) -> list[str]:
    return list(dict.fromkeys(t.strip() for t in terms if t.strip().lower() not in NOISE
                             and len(t.strip()) >= 3))


def _hits(aliases: tuple, sources: dict[str, str]) -> list[str]:
    def present(alias, body):
        if re.fullmatch(r'[a-z ]+', alias):
            return bool(re.search(r'(?<![a-z])' + re.escape(alias) + r'(?![a-z])', body.lower()))
        return alias.lower() in body.lower()
    return [name for name, body in sources.items() if any(present(a, body) for a in aliases)]


def product_query_plan(caption: str, visual_queries: list[str], vision_terms: list[str],
                       transcript: dict[str, str], fallback: list[str], candidate_titles: list[str] | None = None) -> dict:
    sources = {'caption': caption, 'screen_text': transcript.get('screen_text', ''),
               'speech': transcript.get('speech', ''), 'vision': ' '.join(clean_terms(vision_terms))}
    if candidate_titles:
        sources['verified_candidate_title'] = ' '.join(candidate_titles)[:3000]
    # Caption and speech identify the subject more reliably than search-engine
    # guesses. Keep vision evidence, but never let a matched background object
    # occupy the two subject slots ahead of an explicitly named subject.
    direct_sources = {k: v for k, v in sources.items() if k != 'vision'}
    products = []
    for ko, en, zh, aliases in PRODUCTS:
        evidence = _hits(aliases, sources)
        if evidence:
            products.append({'ko': ko, 'en': en, 'zh': zh, 'sources': evidence,
                             'confidence': 'high' if len(evidence) >= 2 else 'medium'})
    direct_products = [p for p in products if any(s != 'vision' for s in p['sources'])]
    if direct_products:
        products = direct_products
    # 직접 식별한 제품이 있으면 넓은 CLIP 카탈로그가 그것을 덮어쓰지 않는다.
    if not products:
        for en, zh in zip(visual_queries[::2], visual_queries[1::2]):
            if language(en) == 'en' and language(zh) == 'zh':
                products.append({'ko': '', 'en': en, 'zh': zh, 'sources': ['openclip'], 'confidence': 'medium'})
    products = products[:2]
    brands = [{'en': en, 'zh': zh, 'sources': evidence, 'confidence': 'high' if len(evidence) >= 2 else 'medium'}
              for en, zh, aliases in BRANDS if (evidence := _hits(aliases, direct_sources if direct_products else sources))]
    features = [{'en': en, 'zh': zh, 'sources': evidence}
                for en, zh, aliases in FEATURES if (evidence := _hits(aliases, sources))][:3]
    models = []
    for name, body in sources.items():
        for value in re.findall(r'(?:품번|모델명|型号|货号|\bmodel|\bsku)\s*[:：#]?\s*([A-Za-z0-9-]{4,18})', body, re.I):
            if re.search('[A-Za-z]', value) and re.search('[0-9]', value):
                models.append({'value': value, 'sources': [name], 'confidence': 'medium'})
    pools = {'en': [], 'zh': [], 'ko': []}
    def add(query, lang, intent, evidence, confidence='medium'):
        query = ' '.join(query.split())[:180]
        if query:
            pools[lang].append({'query': query, 'language': lang, 'intent': intent, 'role': 'product',
                                'sources': list(dict.fromkeys(evidence)), 'confidence': confidence})
    for product in products:
        for lang in ('en', 'zh', 'ko'):
            base = product[lang]
            if not base:
                continue
            brand = brands[0].get(lang, brands[0]['en']) if brands else ''
            evidence = product['sources'] + (brands[0]['sources'] if brand else [])
            confidence = 'high' if product['confidence'] == 'high' and (not brand or brands[0]['confidence'] == 'high') else 'medium'
            add(f'{brand} {base}', lang, 'product', evidence, confidence)
            add(base, lang, 'unbranded', product['sources'], product['confidence'])
            if models:
                add(f"{brand} {models[0]['value']} {base}", lang, 'model', evidence + models[0]['sources'])
            attrs = ' '.join(f[lang] for f in features if lang in f)
            if attrs:
                add(f'{brand} {attrs} {base}', lang, 'appearance', evidence + [s for f in features for s in f['sources']])
            intents = {'en': ('detail review', 'demonstration', 'unboxing'),
                       'zh': ('细节展示', '使用演示', '开箱 实拍'), 'ko': ('실물 리뷰', '사용 영상', '언박싱')}
            if product['en'] == 'honey garlic soy chicken':
                intents = {'en': ('recipe', 'cooking tutorial', 'close up cooking'),
                           'zh': ('做法', '制作教程', '烹饪 特写'), 'ko': ('레시피', '요리 과정', '만들기')}
            for intent in intents[lang]:
                add(f'{brand} {base} {intent}', lang, intent, evidence)
    if not products:
        for query in clean_terms(fallback + vision_terms):
            lang = language(query)
            if lang in pools:
                add(query, lang, 'fallback', ['caption' if query in fallback else 'vision'], 'low')
    details = []
    seen = set()
    for batch in zip_longest(*pools.values()):
        for item in batch:
            if item and item['query'].casefold() not in seen:
                details.append(item); seen.add(item['query'].casefold())
    return {'products': products, 'brands': brands, 'features': features, 'models': models,
            'query_details': details[:30]}


def platform_queries(queries: list[str], provider: str, limit: int) -> list[str]:
    """지원 언어별 풀에서 고른다. 앞쪽 네 검색어에서 잘라 중국어를 버리지 않는다."""
    languages = ('zh', 'en', 'ko') if provider in {'douyin', 'xiaohongshu', 'bilibili'} else ('en', 'ko', 'zh')
    pools = {lang: [q for q in dict.fromkeys(queries) if language(q) == lang] for lang in languages}
    if provider in {'douyin', 'xiaohongshu', 'bilibili'} and pools['zh']:
        return pools['zh'][:limit]
    out = []
    # 영어 우선 두 개마다 한국어 등 보조 언어 하나를 배분한다.
    preferred = pools[languages[0]]
    secondary = pools[languages[1]] + pools[languages[2]]
    while preferred or secondary:
        out.extend(preferred[:2]); del preferred[:2]
        if secondary:
            out.append(secondary.pop(0))
    return out[:max(0, limit)]
