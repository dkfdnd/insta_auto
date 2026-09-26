"""영속 Chrome의 정상 페이지/응답에서 수집한다. 별도 GraphQL 요청을 만들지 않는다."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from urllib.parse import urlsplit

from .base import CollectError, CollectionBlocked
from .web_graphql import _node_to_post, WebGraphQLCollector
from ..instagram_browser import InstagramBrowser
from ..models import Post
from ..observations import MetricObservation


def media_nodes(value):
    """실제 게시물 노드만 추출. 응답 원문/쿠키/인증 토큰은 저장하지 않는다."""
    if isinstance(value, dict):
        # 릴스 목록 응답에는 조회수는 있지만 게시일이 없는 부분 노드가 있다.
        # shortcode로 프로필 노드와 합친 뒤, 게시일은 저장 전에 따로 검증한다.
        if value.get('code') and value.get('media_type'):
            yield value
        elif value.get('shortcode') and value.get('taken_at_timestamp'):
            caption_edges = (value.get('edge_media_to_caption') or {}).get('edges') or []
            yield {
                'code': value['shortcode'], 'taken_at': value['taken_at_timestamp'],
                'media_type': 2 if value.get('is_video') else 8 if value.get('__typename') == 'GraphSidecar' else 1,
                'product_type': value.get('product_type', ''), 'user': value.get('owner') or {},
                'pk': value.get('id', ''), 'caption': {'text': (caption_edges[0].get('node') or {}).get('text', '') if caption_edges else ''},
                'play_count': value.get('video_play_count', value.get('video_view_count')),
                'like_count': (value.get('edge_media_preview_like') or value.get('edge_liked_by') or {}).get('count'),
                'comment_count': (value.get('edge_media_to_parent_comment') or value.get('edge_media_to_comment') or {}).get('count'),
                'video_duration': value.get('video_duration'),
                'image_versions2': {'candidates': [{'url': value.get('display_url', ''), 'width': 640}]},
            }
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from media_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from media_nodes(child)


def exact_count(value):
    """화면의 축약/반올림 수치는 정확한 관측으로 승격하지 않는다."""
    text = str(value).strip().replace(',', '')
    return int(text) if re.fullmatch(r'\d+', text) else None


class BrowserCollector:
    name = 'browser'

    def __init__(self, settings):
        self.settings = settings
        self.browser = InstagramBrowser(settings)
        self.nodes = {}
        self.collection_notes = []
        self.blocked = None

    def preflight(self):
        self.browser.open()
        self.browser.page.on('response', self._response)
        self.browser.navigate('')
        self.browser.verify_identity()

    def _response(self, response):
        # 읽기 전용으로 정상 페이지가 받은 JSON 응답만 관찰한다.
        parsed = urlsplit(response.url)
        if parsed.hostname != 'www.instagram.com' or not parsed.path.startswith(('/api/', '/graphql/')):
            return
        if response.status == 429:
            self.blocked = CollectionBlocked('rate_limited', 'Instagram 요청 제한(429)으로 수집을 중단했습니다.')
            return
        # Instagram GraphQL은 JSON 본문을 text/javascript로도 반환한다.
        content_type = response.headers.get('content-type', '').split(';', 1)[0].strip().lower()
        if content_type not in {'application/json', 'text/javascript', 'application/javascript',
                                'application/x-javascript'}:
            return
        try:
            value = response.json()
            if isinstance(value, dict):
                message = str(value.get('message', '')).lower()
                if any(x in message for x in ('challenge_required', 'checkpoint_required', 'login_required', 'feedback_required')):
                    self.blocked = CollectionBlocked('verification_required', 'Instagram 인증 또는 접근 확인이 필요합니다.')
                    return
            self._ingest(value)
        except Exception:
            # 파싱 실패는 필드/계정 검증에서 수집 실패로 처리한다.
            pass

    def _ingest(self, value):
        for node in media_nodes(value):
            code = str(node['code'])
            old = self.nodes.get(code, {})
            self.nodes[code] = {**old, **{k: v for k, v in node.items() if v is not None}}

    def _bootstrap(self):
        for raw in self.browser.page.locator('script[type="application/json"]').all_text_contents():
            try:
                self._ingest(json.loads(raw))
            except (ValueError, RecursionError):
                continue
        if self.blocked:
            raise self.blocked
        self.browser.guard()

    def _links(self, username):
        rows = self.browser.page.evaluate('''() => Array.from(document.querySelectorAll('main a[href]'))
            .map(a => ({href:a.getAttribute('href'), text:a.innerText || '', caption:a.querySelector('img')?.alt || '',
                       thumbnail:a.querySelector('img')?.src || ''}))''')
        pattern = re.compile(r'^/(?:' + re.escape(username) + r'/)?(?:reel|p)/[A-Za-z0-9_-]+/?$')
        return [row for row in rows if pattern.fullmatch(row['href'])]

    def fetch(self, username, limit, existing=None):
        self.collection_notes = []
        self.nodes = {}
        self.browser.navigate(f'{username}/')
        self.browser.verify_identity()
        self._bootstrap()
        profile = WebGraphQLCollector._parse_profile(username, self.browser.page.content())
        # 대상 프로필에 실제 표시된 링크에 속한 노드만 수집한다.
        links = {}
        boundary = max((p.taken_at for p in (existing or {}).values()), default=0)
        newest_codes = {p.shortcode for p in (existing or {}).values() if p.taken_at == boundary}
        cap = max(limit, self.settings.collect_recovery_limit) if existing else limit
        for section in ('', 'reels/'):
            wanted_reels = {code for code in links
                            if (self.nodes.get(code) or {}).get('media_type') == 2}
            if section:
                self.browser.navigate(f'{username}/{section}')
            stable = 0
            section_codes = set()
            for _ in range(8):
                self._bootstrap()
                before = len(section_codes)
                for link in self._links(username):
                    code = link['href'].strip('/').split('/')[-1]
                    # 릴스 탭은 프로필에서 선택한 게시물의 조회수를 보강한다.
                    # 보강용 스크롤이 수집 범위를 오래된 릴스로 늘리지 않도록 한다.
                    if not section or code in links:
                        links[code] = link
                    section_codes.add(code)
                stable = stable + 1 if len(section_codes) == before else 0
                # 고정 게시물 때문에 첫 과거 게시물에서 멈추지 않는다.
                if len(section_codes) >= cap or stable >= 2:
                    break
                if section and wanted_reels and wanted_reels.issubset(section_codes):
                    break
                if not section and len(links) >= limit and newest_codes and newest_codes.issubset(links):
                    break
                self.browser.page.mouse.wheel(0, 900)
                self.browser.page.wait_for_timeout(1300)
        if not links:
            raise CollectError('게시물 목록이 비어 있습니다. 비공개/페이지 구조/로딩 상태 확인이 필요합니다.')
        now = int(time.time())
        posts, observations = [], []
        for code, link in list(links.items())[:cap]:
            node = self.nodes.get(code)
            owner = ((node or {}).get('user') or {}).get('username', username).lower()
            if owner != username.lower():
                continue
            post = _node_to_post(node, username) if node and node.get('taken_at') else None
            requested = now
            raw_views = link['text'].strip()
            # 구조화 데이터가 없으면 상세 페이지에서 실제 게시일을 확인한다.
            if not post:
                self.browser.navigate(link['href'])
                self._bootstrap()
                node = self.nodes.get(code)
                post = _node_to_post(node, username) if node and node.get('taken_at') else None
                if not post:
                    stamp = self.browser.page.locator('main time[datetime]').first
                    try:
                        date = stamp.get_attribute('datetime', timeout=5000)
                        taken_at = int(datetime.fromisoformat(date.replace('Z', '+00:00')).timestamp())
                    except Exception as exc:
                        raise CollectError(f'{code}: 게시 날짜를 확인할 수 없어 수집을 완료하지 않았습니다.') from exc
                    post = (_node_to_post({**node, 'taken_at': taken_at}, username) if node else
                            Post(code, username, taken_at, 'reel' if '/reel/' in link['href'] else 'image',
                                 likes=None, comments=None, caption=link['caption'], thumbnail_url=link['thumbnail']))
            if post.username.lower() != username.lower() or post.taken_at <= 0:
                raise CollectError('게시물 소유자 또는 게시 날짜 검증에 실패했습니다.')
            if post.is_video and post.views is None:
                # 확장 프로그램의 배수 등을 정수 조회수로 해석하지 않는다.
                post.views = exact_count(raw_views)
            if post.is_video:
                exact = post.views is not None
                reason = '' if exact else ('approximate_or_unavailable:' + raw_views[:60])
                observations.append(MetricObservation(code, requested, now if exact else None,
                    exact, post.views, post.likes, post.comments, 'instagram_browser',
                    reason=reason, age_hours=max(0, (now-post.taken_at)/3600)))
            posts.append(post)
        if not posts:
            raise CollectError('대상 계정의 검증된 게시물이 없습니다.')
        if len(links) >= cap and newest_codes and not newest_codes.issubset(links):
            self.collection_notes.append('복구 수집 상한에 도달했습니다. 이전 수집 경계까지 도달하지 못했을 수 있습니다.')
        missing = sum(not o.success for o in observations)
        if missing:
            self.collection_notes.append(f'영상 {len(observations)}개 중 정확한 조회수 미확인 {missing}개 (축약값 포함)')
        return profile, sorted(posts, key=lambda p:p.taken_at, reverse=True), observations

    def refresh_video_views(self, posts, max_lookups):
        observations = []
        for post in posts[:max_lookups]:
            requested = int(time.time())
            self.nodes.pop(post.shortcode, None)
            self.browser.navigate(f'reel/{post.shortcode}/')
            self._bootstrap()
            node = self.nodes.get(post.shortcode)
            fresh = _node_to_post(node, post.username) if node else None
            exact = bool(fresh and fresh.username == post.username and fresh.views is not None)
            if exact:
                post.views = fresh.views
                post.likes, post.comments = fresh.likes, fresh.comments
            observations.append(MetricObservation(post.shortcode, requested,
                int(time.time()) if exact else None, exact, fresh.views if exact else None,
                fresh.likes if exact else None, fresh.comments if exact else None,
                'instagram_browser', reason='' if exact else 'exact_views_unavailable',
                age_hours=max(0, (requested-post.taken_at)/3600), scope='tracking'))
        return observations

    def close(self):
        self.browser.close()
