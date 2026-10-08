import pytest

from hotpost.public_vendor import primary_video_url
from hotpost.source_urls import canonical_video_key, lazada_video_id, video_url

PAGE = 'https://www.lazada.com.ph/videodetail/?video_id=123456'
MEDIA = 'https://pro-video.lazcdn.com/psp/demo.mp4'


def markup(identity=PAGE, media=MEDIA):
    return f'<meta property="og:url" content="{identity}"><meta property="og:video:url" content="{media}">'


def test_primary_video_does_not_take_recommended_product_urls():
    assert primary_video_url(PAGE, markup() + '<script>{"videoUrl":"https://other.invalid/recommendation.mp4"}</script>') == MEDIA


@pytest.mark.parametrize('identity', [PAGE.replace('123456', '654321'), 'https://evil.invalid/videodetail/?video_id=123456', ''])
def test_vendor_page_requires_exact_video_identity(identity):
    with pytest.raises(ValueError, match='ID'):
        primary_video_url(PAGE, markup(identity=identity))


@pytest.mark.parametrize('media', ['http://pro-video.lazcdn.com/a.mp4', 'https://pro-video.lazcdn.com.evil.invalid/a.mp4', 'https://127.0.0.1/a.mp4', 'https://user:pass@pro-video.lazcdn.com/a.mp4', 'https://pro-video.lazcdn.com/a.html'])
def test_vendor_media_is_limited_to_public_https_mp4_cdn(media):
    with pytest.raises(ValueError, match='CDN'):
        primary_video_url(PAGE, markup(media=media))


def test_vendor_identity_is_retained_in_deduplication():
    assert video_url(PAGE)
    assert canonical_video_key(PAGE) != canonical_video_key(PAGE.replace('123456', '654321'))
    assert canonical_video_key(PAGE) == canonical_video_key(PAGE + '&spm=tracking')
    assert not lazada_video_id(PAGE.replace('lazada.com.ph', 'lazada.com.ph.evil.invalid'))
    assert not video_url(PAGE.replace('123456', '123456&video_id=654321'))
