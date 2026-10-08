from hotpost.source_queries import product_query_plan
from hotpost.source_queries import feedback_queries


def test_daily_subjects_have_three_grounded_search_languages():
    captions = ['발바닥에 쏙 신어주는 전용 핫팩', '직접 만든 투두리스트',
                '분사부터 문지르기, 물기 제거까지 3in1', '슬림신발장',
                '무타공 자동블라인드', '쌀가루로 블루베리 찐빵을 만들어요',
                '문틀에서 푸시업부터 풀업까지', '나그랑 롱슬리브',
                '걸이 하나에 바지가 층층이', '코바늘로 꽃잎 컵받침',
                '온러닝 운동화', '휴대용 얼룩제거 리무버']
    for caption in captions:
        plan = product_query_plan(caption, [], [], {}, [])
        assert plan['products'], caption
        assert {'en','ko','zh'} <= {q['language'] for q in plan['query_details']}, caption


def test_background_or_generic_words_do_not_invent_specific_products():
    assert not product_query_plan('초슬림 선반', [], [], {}, [])['products']
    plan = product_query_plan('쌀가루로 팬케이크를 만들어요', [], [], {}, [])
    assert plan['products'][0]['ko'] == '쌀가루 요리'
    assert '블루베리' not in str(plan)
    assert '꽃잎' not in str(product_query_plan('코바늘 담요', [], [], {}, []))


def test_garlic_subject_displaces_generic_recipes_and_has_three_languages():
    plan=product_query_plan('다진마늘, 매번 꽝꽝 얼려두셨다면 이렇게 보관해보세요',[],[],{},['recipes cooking','egg recipe'])
    assert plan['products'][0]['en']=='minced garlic preparation'
    assert {'ko','en','zh'} <= {q['language'] for q in plan['query_details']}
    assert not any(q['query'] in ['recipes cooking','egg recipe'] or 'unboxing' in q['query'] for q in plan['query_details'])


def test_feedback_instructions_are_not_truncated_into_search_queries():
    request='다진 마늘 준비와 용기 소분 장면만 찾으세요. 샐러드는 보조 장면으로 허용하세요. '+('긴 지시문 ' * 35)
    assert feedback_queries(request)==[]
    assert feedback_queries('검색어: minced garlic jar, garlic meal prep\n다진 마늘 소분\n蒜末准备')==[
        'minced garlic jar','garlic meal prep','다진 마늘 소분','蒜末准备']


def test_tent_and_clothesline_have_searchable_subjects():
    for caption in ('차박·캠핑 텐트 추천, 차 뒤에 달고 다니다 펼쳐요', '다 마르면 줄이 상자 안으로 쏙 감겨 들어가요'):
        plan=product_query_plan(caption,[],[],{},[])
        assert plan['products']
        assert {'en','ko','zh'} <= {r['language'] for r in plan['query_details']}
    for generic in ('차 지붕에 올리는 차박 텐트', '나무 사이에 묶는 빨랫줄'):
        assert not product_query_plan(generic,[],[],{},[])['products']


def test_model_only_subject_keeps_expanding_after_first_queries_are_used():
    from hotpost.source_queries import next_round_queries
    plan={'products':[], 'query_details':[
        {'query':'unusual folding tool','language':'en','role':'subject_action','evidence_quote':'접이 도구','sources':['caption']}]}
    result=next_round_queries(plan,1,[{'query':'unusual folding tool','status':'results'}])
    assert result and all(r['query'].startswith('unusual folding tool ') for r in result)
    assert all(r['origin']=='automatic_expansion' for r in result)
