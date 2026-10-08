import base64
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost.source_urls import unwrap_bing_video_url
from hotpost import source_finder


def wrapped(target):
    encoded=base64.urlsafe_b64encode(target.encode()).decode().rstrip('=')
    return 'https://www.bing.com/ck/a?!&amp;u=a1'+encoded+'&amp;ntb=1'


@pytest.mark.parametrize('url',[
    'https://www.tiktok.com/@cardigan/video/7549906573993315606',
    'https://www.youtube.com/shorts/AbCdEf12345',
    'https://www.youtube.com/watch?v=AbCdEf12345&t=3',
])
def test_observed_bing_redirect_preserves_actual_video_url(url):
    import html
    assert unwrap_bing_video_url(html.unescape(wrapped(url)))==url
    assert unwrap_bing_video_url(url)==url


@pytest.mark.parametrize('target',[
    'javascript:alert(1)', 'http://127.0.0.1:8775/api/studio',
    'https://www.tiktok.com/search?q=cardigan',
    'https://user:secret@www.youtube.com/watch?v=123',
])
def test_redirect_cannot_promote_non_video_or_private_url(target):
    import html
    url=html.unescape(wrapped(target))
    assert unwrap_bing_video_url(url)==url


@pytest.mark.parametrize('url',[
    'https://www.bing.com/ck/a?u=a1***',
    'https://www.bing.com/ck/a?u=a1abc&u=a1def',
    'https://www.bing.com/ck/a?u=unknown',
    'https://bing.com.evil.test/ck/a?u=a1abcd',
])
def test_invalid_or_foreign_wrapper_is_not_followed(url):
    assert unwrap_bing_video_url(url)==url


def test_real_search_parser_keeps_video_redirect_and_filters_non_video(tmp_path,monkeypatch):
    monkeypatch.setattr('hotpost.config.load_settings',lambda:Settings(data_dir=tmp_path))
    monkeypatch.setattr(source_finder,'request_pause',lambda:None)
    target='https://www.tiktok.com/@cardigan/video/7549906573993315606'
    body='<li class="b_algo"><h2><a href="'+wrapped(target)+'">Cardigan <b>outfit</b></a></h2></li>'
    body+='<li class="b_algo"><h2><a href="'+wrapped('https://example.test/shop')+'">Shop</a></h2></li>'
    response=SimpleNamespace(status_code=200,url='https://www.bing.com/search',
                             text=body,raise_for_status=lambda:None)
    monkeypatch.setattr(source_finder.requests,'get',lambda *a,**k:response)
    audit=[]
    candidates=source_finder.search_bing(['cardigan'],5,audit)
    assert [(c.url,c.title) for c in candidates]==[(target,'Cardigan outfit')]
    assert audit[0]['status']=='results' and audit[0]['decoded_video_links']==1
    assert audit[0]['result_links']==2
