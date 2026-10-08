import pytest
from hotpost.writing.script_quantities import quantities
from hotpost.writing.script_integrity import inspect


@pytest.mark.parametrize('text,want', [
    ('3초', [('3', '초')]), ('삼 초', [('3', '초')]), ('삼십 초', [('30', '초')]),
    ('사 인 가족', [('4', '명')]), ('네 명', [('4', '명')]),
    ('네 식구', [('4', '명')]), ('4인가족', [('4', '명')]),
    ('한식구나 다름없어요. 사인펜이에요.', []),
    ('사주기로 한 인형을 깜빡했어요. 세명대 금관대예요. 삼 초록 색연필.', []),
    ('한 사람당, 4인용, 네 명까지, 삼 초만에, 26cm보다', [('1','명'), ('4','명'), ('4','명'), ('3','초'), ('26','cm')]),
    ('이십육 센티미터', [('26', 'cm')]), ('두 시간', [('2', '시간')]),
    ('천이백삼십사 cm', [('1234', 'cm')]), ('삼사 초', []),
    ('냉기가 줄어들어요. 성인용이에요.', []), ('칠십오 인치', []),
])
def test_spoken_numeric_units(text, want):
    assert list(quantities(text)) == want


def test_number_readings_are_bound_to_the_exact_source_spelling():
    from hotpost.writing.script_quantities import quantity_readings
    source = '삼 초 만에 펴지고 사인 가족도 넉넉해요.'
    readings = list(quantity_readings(source))
    assert [(r['source_text'], r['value'], r['unit']) for r in readings] == [('삼 초','3','초'), ('사인','4','명')]
    assert all(source[r['start']:r['end']] == r['source_text'] for r in readings)
    assert not list(quantity_readings('세명대 금관대까지 채워요.'))


def codes(source, draft):
    return {r['code'] for r in inspect(source, draft)['issues']}


def test_changed_number_cannot_hide_in_korean_tts_spelling():
    assert 'quantity_changed' in codes('3초 만에 펴져요.', '삼십 초면 설치가 끝나요.')
    assert 'quantity_changed' not in codes('26cm 공간에 맞아요.', '이십육 센티미터 빈자리에 두어요.')


def test_family_size_cannot_change_by_switching_the_unit_word():
    source='컵홀더는 2개뿐이라 네 식구 음료 놓다 보면 꼭 하나는 쏟잖아요.'
    assert 'quantity_changed' in codes(source,'다섯 명 가족이 커피를 챙기면 모자라요.')
    assert 'quantity_changed' in codes('4인 가족도 들어가요.','다섯 명도 쓸 수 있어요.')
    assert 'quantity_changed' not in codes(source,'네 명 음료를 둘 곳이 모자랄 때가 있어요.')
    assert 'quantity_changed' not in codes('4인 가족도 들어가요.','네 식구도 쓸 수 있어요.')


@pytest.mark.parametrize('draft', [
    '바닥에서 직접 치지 않아도 습기와 냉기를 차단해줘요.',
    '냉기도 안 오르고 넉넉하게 머물 수 있어요.',
    '습기와 냉기 걱정 없이 머물러요.',
    '바닥에서 떨어져 있어서 습기와 냉기 거의 느껴지지 않아요.',
    '소음이 전혀 느껴지지 않아요. 습기와 냉기는 거의 느끼지 않아요.',
])
def test_unrelated_negation_does_not_hide_a_strengthened_claim(draft):
    assert 'mitigation_strengthened' in codes('습기랑 냉기가 덜해요.', draft)


@pytest.mark.parametrize('draft', [
    '냉기를 덜 느낄 수 있어요.',
    '냉기를 완전히 차단한다고 보장하지는 않아요.',
    '냉기를 차단하는 데 도움이 된다고 해요.',
    '냉기가 완전히 없어지는 건 아니에요.',
    '냉기 차단을 보장하는 것은 아니에요.',
    '냉기가 거의 느껴지지 않는다고 보장할 수는 없어요.',
    '냉기를 전혀 느끼지 않는다고 보장하기 어려워요.',
])
def test_explicit_limit_is_preserved(draft):
    assert 'mitigation_strengthened' not in codes('냉기가 덜해요.', draft)


def test_omitted_subject_is_still_a_fabricated_use_experience():
    assert 'unsupported_experience' in codes('얇은 양말이에요.', '이걸 신어보고는 깜짝 놀랐잖아요.')
    assert 'unsupported_experience' not in codes('얇은 양말이에요.', '신어보면 어떨까요?')


def test_reference_friend_tasting_setting_can_be_retold_in_first_person():
    ref='친구 집에서 닭꼬치인 줄 알고 먹었는데 새송이버섯이라는 거예요.'
    draft='친구네서 한 입 먹었는데 고기인 줄 알았거든요. 그런데 이게 버섯이었다니 놀랍지 않아요?'
    assert not codes(ref,draft)
    # Allowing the anecdote does not allow its original sentences to be copied.
    assert 'copied_hook' in codes(ref,ref)
