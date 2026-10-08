"""근거가 있는 제품·브랜드·특징을 언어와 검색 의도별로 확장한다.

브랜드/품번은 관측된 텍스트에서만 추출한다. 사전에 없는 제품의 번역을 만들어내지 않는다.
"""
from __future__ import annotations

import re
from itertools import zip_longest

PRODUCTS = [
    ('차량 후면 텐트', 'car rear tent', '车尾帐篷', ('차 뒤에 달고', 'car rear tent', 'hitch tent', '车尾帐篷')),
    ('자동 감김 빨랫줄', 'retractable clothesline', '伸缩晾衣绳', ('자동 감김 빨랫줄', '줄이 상자 안으로', 'retractable clothesline', '伸缩晾衣绳')),
    ('다진 마늘 준비', 'minced garlic preparation', '蒜末准备', ('다진마늘', '다진 마늘', '마늘보관', '마늘 보관', 'minced garlic', 'garlic storage', '蒜末')),
    ('발 전용 핫팩', 'foot warmer wrap', '暖脚贴', ('발바닥 핫팩', '발 전용 핫팩', '전용 핫팩', 'foot warmer', '暖脚贴')),
    ('투두 리스트', 'DIY checklist board', '自制待办清单板', ('투두', '투두리스트', 'to do list', 'checklist board', '待办清单')),
    ('분사형 유리 청소기', '3 in 1 spray squeegee', '三合一喷水玻璃刮', ('분사부터 문지르기', '3in1', 'spray squeegee', '喷水玻璃刮')),
    ('신발장', 'shoe cabinet demonstration', '鞋柜演示', ('신발장', 'shoe cabinet', '鞋柜')),
    ('무타공 전동 블라인드', 'no drill motorized cellular blinds', '免打孔电动蜂巢帘', ('무타공 자동블라인드', '무타공블라인드', '무타공 전동', 'no drill motorized', '免打孔电动')),
    ('쌀가루 요리', 'rice flour recipe', '米粉食谱', ('쌀가루', 'rice flour', '米粉食谱')),
    ('문틀 운동 기구', 'door frame pull up gym', '门框单杠', ('푸시업부터 풀업', '문틀 운동', 'door frame gym', '门框单杠')),
    ('래글런 롱슬리브', 'raglan long sleeve outfit', '插肩长袖穿搭', ('나그랑', '래글런', 'raglan', '插肩')),
    ('다단 바지걸이', 'multi layer pants hanger', '多层裤架', ('바지가 층층이', '바지걸이', 'pants hanger', '裤架')),
    ('코바늘 뜨개', 'crochet tutorial', '钩针教程', ('코바늘', 'crochet', '钩针')),
    ('온 러닝 운동화', 'On running shoes outfit', 'On跑鞋穿搭', ('온러닝', '온 러닝', 'on running', 'On跑鞋')),
    ('휴대용 얼룩 제거기', 'portable stain remover demonstration', '便携去渍笔演示', ('얼룩제거', '얼룩 제거', '리무버', 'stain remover', '去渍笔')),
    ('진열장', 'display cabinet', '展示柜', ('진열장', '장식장', 'display cabinet', '展示柜', '陈列柜')),
    ('캠핑 주방세트', 'camping kitchen set', '露营厨具套装', ('캠핑 주방세트', '캠핑 주방 세트', 'camping kitchen set', '露营厨具')),
    ('생선구이', 'pan fried fish cooking', '煎鱼技巧', ('생선구이', '생선 구이', '생선 굽', '생선을 구', '생선 부서', 'pan fried fish', 'frying fish', '煎鱼')),
    ('타일 보수', 'tile repair', '瓷砖修补', ('타일 보수', '타일보수', 'tile repair', '瓷砖修补')),
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
            if product['en'] in {'honey garlic soy chicken', 'pan fried fish cooking', 'minced garlic preparation'}:
                intents = {'en': ('recipe', 'cooking tutorial', 'close up cooking'),
                           'zh': ('做法', '制作教程', '烹饪 特写'), 'ko': ('레시피', '요리 과정', '만들기')}
            elif product['en'] == 'tile repair':
                intents = {'en': ('crack repair tutorial', 'repair process', 'before after repair'),
                           'zh': ('裂缝修复教程', '修补过程', '修复前后'), 'ko': ('균열 보수 방법', '보수 과정', '보수 전후')}
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


def feedback_queries(request: str) -> list[str]:
    """Accept concise explicit keywords, never a truncated instruction paragraph."""
    result = []
    for line in request.splitlines():
        line = re.sub(r'^(?:검색어|keywords?|queries)\s*[:：]\s*', '', line.strip(), flags=re.I)
        if len(line) > 180 or re.search(r'찾으세요|찾아주세요|제외하세요|허용하지|확정하지|레퍼런스|장면만|등의.*검색', line):
            continue
        for query in re.split(r'[,;；]', line):
            query = ' '.join(query.strip(' \"\'').split())
            if 2 <= len(query) <= 80 and not re.search(r'https?://|[.!?。!?]', query):
                result.append(query)
    return list(dict.fromkeys(result))[:8]


def next_round_queries(plan, round_number, history):
    """Change grounded search intents; never recycle an instruction paragraph."""
    # A query tried on YouTube is still new on TikTok. Provider-specific
    # exhaustion belongs to discovery, never to this shared grounded pool.
    from .source_search.strategy import normalize_query
    used = {normalize_query(r.get('query', '')) for r in history if not r.get('provider')
            and r.get('status') in {'results', 'no_results'}}
    details = [dict(q) for q in plan['query_details'] if q['query'].casefold() not in used]
    intents = {
        'en': [('close up demonstration','how to use'),('step by step tutorial','hands on review'),('preparation process','storage tips'),('product demonstration video','daily use'),('long review','detailed tutorial')],
        'ko': [('사용 장면 클로즈업','사용 방법'),('단계별 사용법','실사용 후기'),('준비 과정','보관 방법'),('제품 시연 영상','일상 활용'),('상세 리뷰','자세한 사용법')],
        'zh': [('使用 特写','使用方法'),('步骤 教程','实际体验'),('准备过程','保存方法'),('产品演示 视频','日常使用'),('详细评测','完整教程')],
    }
    offset = (round_number-1)%5
    products = list(plan.get('products', []))
    # Subjects identified by the model also need future search intents. Without
    # a catalog match, exhausting their first queries used to leave an empty
    # plan and only unrelated image-search labels in subsequent rounds.
    if not products:
        for lang in ('en', 'ko', 'zh'):
            bases = [q for q in plan['query_details'] if q.get('language') == lang
                     and q.get('role') == 'subject_action' and q.get('evidence_quote')]
            for base in sorted(bases, key=lambda q: len(q['query']))[:2]:
                products.append({lang:base['query'], 'sources':base.get('sources', [])})
    for product in products:
        for lang in ('en','ko','zh'):
            base = product.get(lang)
            if not base: continue
            groups = intents[lang]
            if plan.get('subject_kind') == 'recipe' or product.get('en') in {
                    'minced garlic preparation', 'honey garlic soy chicken', 'pan fried fish cooking', 'rice flour recipe'}:
                groups = {
                    'en': [('close up preparation', 'step by step cooking'), ('preparation process', 'portioning'),
                           ('storage preparation', 'spooning demonstration'), ('cooking technique', 'hands on preparation'),
                           ('detailed cooking tutorial', 'ingredient preparation')],
                    'ko': [('준비 장면 클로즈업', '단계별 조리 과정'), ('준비 과정', '소분 장면'),
                           ('보관 준비', '숟가락으로 뜨는 장면'), ('조리 방법', '직접 준비하는 장면'),
                           ('자세한 조리 과정', '재료 준비')],
                    'zh': [('准备 特写', '分步烹饪'), ('准备过程', '分装'), ('保存准备', '舀取演示'),
                           ('烹饪方法', '实际准备'), ('详细制作教程', '食材准备')],
                }[lang]
            # Visit every remaining intent, starting at a different group. A
            # modulo-selected exhausted group must not erase the whole pool.
            for suffix in [s for group in groups[offset:] + groups[:offset] for s in group]:
                query = f'{base} {suffix}'
                if query.casefold() not in used:
                    details.insert(0, {'query':query,'language':lang,'role':'product','intent':suffix,'sources':product.get('sources',[]),'origin':'automatic_expansion'})
    return list({normalize_query(d['query']): d for d in details}.values())


def platform_queries(queries: list[str], provider: str, limit: int) -> list[str]:
    """지원 언어별 풀에서 고른다. 앞쪽 네 검색어에서 잘라 중국어를 버리지 않는다."""
    languages = ('zh', 'en', 'ko') if provider in {'douyin', 'xiaohongshu', 'bilibili'} else ('en', 'ko', 'zh')
    pools = {lang: [q for q in dict.fromkeys(queries) if language(q) == lang] for lang in languages}
    if provider in {'douyin', 'xiaohongshu', 'bilibili'}:
        return pools['zh'][:max(0, limit)]
    if provider == 'tiktok':
        # One query in each language before spending a second slot on any language.
        return [q for batch in zip_longest(*(pools[l] for l in ('en', 'ko', 'zh')))
                for q in batch if q][:max(0, limit)]
    out = []
    # 영어 우선 두 개마다 한국어 등 보조 언어 하나를 배분한다.
    preferred = pools[languages[0]]
    secondary = [q for batch in zip_longest(pools[languages[1]], pools[languages[2]]) for q in batch if q]
    while preferred or secondary:
        out.extend(preferred[:2]); del preferred[:2]
        if secondary:
            out.append(secondary.pop(0))
    return out[:max(0, limit)]
