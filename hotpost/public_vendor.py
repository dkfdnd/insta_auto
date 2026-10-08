"""Receive only the primary public video advertised by a vendor detail page."""
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import requests

from .request_pacing import request_pause
from .source_urls import canonical_video_key, lazada_video_id


class _Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'meta' and values.get('property') and values.get('content'):
            self.values.setdefault(values['property'], values['content'])


def primary_video_url(page_url: str, markup: str) -> str:
    if not lazada_video_id(page_url):
        raise ValueError('지원되는 공개 판매처 영상 주소가 아닙니다.')
    metadata = _Metadata()
    metadata.feed(markup)
    identity = metadata.values.get('og:url', '')
    if not lazada_video_id(identity) or canonical_video_key(identity) != canonical_video_key(page_url):
        raise ValueError('판매처 영상 페이지의 게시물 ID가 일치하지 않습니다.')
    media = metadata.values.get('og:video:url', '')
    parsed = urlparse(media)
    if (parsed.scheme != 'https' or parsed.hostname != 'pro-video.lazcdn.com'
            or parsed.username or parsed.password or not parsed.path.lower().endswith('.mp4')):
        raise ValueError('판매처가 허용된 공개 영상 CDN 주소를 반환하지 않았습니다.')
    return media


def download(page_url: str, target: Path, max_bytes: int, deadline: float | None):
    deadline = deadline if deadline is not None else time.monotonic() + 90
    def timeout():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('판매처 영상 다운로드 시간 예산 소진')
        return min(30, remaining)

    request_pause()
    with requests.get(page_url, timeout=timeout(), stream=True, allow_redirects=False) as response:
        if response.status_code != 200:
            response.raise_for_status()
            raise ValueError('판매처 페이지가 다른 주소로 이동했습니다.')
        content = bytearray()
        for chunk in response.iter_content(64 * 1024):
            timeout()
            content.extend(chunk)
            if len(content) > 2 * 1024 * 1024:
                raise ValueError('판매처 페이지 크기 제한 초과')
    media_url = primary_video_url(page_url, content.decode('utf-8', errors='replace'))
    request_pause()
    try:
        with requests.get(media_url, timeout=timeout(), stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                response.raise_for_status()
                raise ValueError('판매처 영상이 다른 주소로 이동했습니다.')
            size = 0
            with target.open('wb') as stream:
                for chunk in response.iter_content(256 * 1024):
                    timeout()
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError('판매처 영상 크기 제한 초과')
                    stream.write(chunk)
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise
