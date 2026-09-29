"""Resolve a reference video through the same browser used for login/collection."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from .instagram_browser import InstagramBrowser


def video_candidates(value, shortcode):
    """Only accept metadata belonging to the requested post, not recommendations."""
    if isinstance(value, dict):
        if value.get('code', value.get('shortcode')) == shortcode:
            for version in value.get('video_versions') or []:
                if version.get('url'):
                    yield (version.get('width', 0) * version.get('height', 0), version['url'])
            if value.get('video_url'):
                yield (0, value['video_url'])
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from video_candidates(child, shortcode)
    elif isinstance(value, list):
        for child in value:
            yield from video_candidates(child, shortcode)


def browser_video_url(settings, shortcode):
    from playwright.sync_api import Error as PlaywrightError
    browser = InstagramBrowser(settings)
    candidates = []

    def response_received(response):
        host = (urlsplit(response.url).hostname or '').lower()
        if host not in ('www.instagram.com', 'instagram.com'):
            return
        try:
            if response.status == 200 and 'json' in response.headers.get('content-type', ''):
                candidates.extend(video_candidates(response.json(), shortcode))
        except (ValueError, PlaywrightError):
            pass

    try:
        browser.open()
        browser.page.on('response', response_received)
        # /reel/ can open a recommended reel instead; /p/ resolves this exact post.
        browser.navigate(f'p/{shortcode}/')
        browser.verify_identity()
        for _ in range(10):
            browser.guard()
            for raw in browser.page.locator('script[type="application/json"]').all_text_contents():
                try:
                    candidates.extend(video_candidates(json.loads(raw), shortcode))
                except ValueError:
                    continue
            if candidates:
                return max(candidates, key=lambda item: item[0])[1]
            browser.page.wait_for_timeout(1000)
        raise RuntimeError('전용 Instagram 브라우저에서 이 게시물의 영상 정보를 찾지 못했습니다.')
    finally:
        browser.close()
