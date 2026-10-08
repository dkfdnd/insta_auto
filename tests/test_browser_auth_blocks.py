from types import SimpleNamespace

import pytest

from hotpost.browser_profile import probe_platform_auth
from hotpost.search_access import challenge_on_page


@pytest.mark.parametrize('text',[
    '슬라이더를 드래그하여 퍼즐을 맞추세요',
    '슬라이더를 끌어서 퍼즐을 맞춰 주세요',
])
def test_actual_korean_tiktok_challenge_is_not_misreported_as_empty_or_loading(text):
    page=SimpleNamespace(url='https://www.tiktok.com/search/video',
        locator=lambda _:SimpleNamespace(inner_text=lambda:text))
    assert challenge_on_page(page)


@pytest.mark.parametrize('url,body',[
    ('https://www.tiktok.com/captcha',''),
    ('https://www.tiktok.com/login','Drag the slider to fit the puzzle'),
])
def test_auth_probe_keeps_captcha_distinct_from_unverified(url,body):
    response=SimpleNamespace(status=200,url=url,text=lambda:body)
    context=SimpleNamespace(request=SimpleNamespace(get=lambda *a,**k:response))
    assert probe_platform_auth(context,'tiktok')=='verification_required'


def test_unused_captcha_script_is_not_a_live_challenge():
    response = SimpleNamespace(status=200, url='https://www.tiktok.com/login',
        text=lambda:'<script>const msg="Drag the slider to fit the puzzle";</script><main>Log in</main>')
    context = SimpleNamespace(request=SimpleNamespace(get=lambda *a, **k: response))
    assert probe_platform_auth(context, 'tiktok') == 'unverified'
