"""Playwright 기반 무료 역이미지/플랫폼 검색 공급자.

전용 Chrome 영구 프로필을 사용하며 CAPTCHA, 로그인, DOM 변경은 우회하지 않는다.
공급자 하나가 실패해도 다른 검색은 계속 수행하고 진단 스크린샷을 남긴다.
"""
from __future__ import annotations

import re
import time
import html
import json
from pathlib import Path
from urllib.parse import parse_qs, quote, quote_plus, unquote, urljoin, urlparse

from .config import Settings
from .request_pacing import request_pause
from .browser_profile import BROWSER_LOCK, export_cookies, restore_platform_cookies, save_platform_cookies, source_context_options
from .search_access import access_record, manual_required, challenge_on_page, challenge_in_text, login_wall_on_page, empty_results_on_page
from .source_urls import video_url
from .source_queries import platform_queries, clean_terms, language

VIDEO_HOSTS = ("tiktok.com", "douyin.com", "xiaohongshu.com", "youtube.com", "youtu.be", "bilibili.com",
               "vimeo.com", "lazada.", "manuals.plus", "made-in-china.com")
SKIP_HOSTS = ("google.com", "gstatic.com", "googleusercontent.com", "yandex.com", "yandex.ru", "yandex.net")
from .source_search.strategy import fresh_queries, fresh_frames, image_sha256, image_signature
from .source_search.readiness import readiness_blocked, record_unresolved, parser_revision
BROWSER_COOLDOWNS: dict[str, float] = {}


class SearchBudgetReached(Exception):
    pass


def _is_candidate(url: str) -> bool:
    return video_url(url)


def _unwrap(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.endswith("google.com") and parsed.path == "/url":
        return unquote(parse_qs(parsed.query).get("q", parse_qs(parsed.query).get("url", [url]))[0])
    return url


def _anchors(page, provider: str, query: str, match_kind: str) -> list[dict]:
    out = []
    try:
        # 동적 검색 페이지의 수천 개 노드를 Python에서 하나씩 조회하면 분 단위로 멈출 수 있다.
        anchors = page.locator("a[href]").evaluate_all(
            """els => els.slice(0, 1500).map(a => ({href: a.href,
              text: a.innerText || a.getAttribute('aria-label') || '',
              title: a.getAttribute('title') || a.querySelector('[title]')?.getAttribute('title') || '',
              duration: a.closest('.bili-video-card,.video-item')?.querySelector('.bili-video-card__stats__duration,.duration')?.textContent || ''}))"""
        )
    except Exception:  # noqa: BLE001
        return out
    for anchor in anchors:
        try:
            url = _unwrap(urljoin(page.url, anchor.get("href") or ""))
            if not _is_candidate(url):
                continue
            title = str(anchor.get("title") or anchor.get("text") or "").strip()
            item = {"url": url, "provider": provider, "title": re.sub(r"\s+", " ", title)[:240],
                    "query": query, "match_kind": match_kind}
            if 'bilibili' in urlparse(url).netloc:
                stamp = re.search(r'(?<!\d)(\d{1,2}:\d{2}(?::\d{2})?)(?!\d)',
                                  str(anchor.get('duration') or anchor.get('text') or ''))
                if stamp:
                    parts = [int(p) for p in stamp[1].split(':')]
                    if all(p < 60 for p in parts[1:]):
                        seconds = sum(p*60**i for i,p in enumerate(reversed(parts)))
                        item['discovery_meta'] = {'duration':seconds, 'duration_source':'search_card'}
                # Bilibili links the thumbnail (view counts) before the title.
                # Merge both so deduplication does not throw away the real title
                # or duration, which avoids downloading known overlong clips.
                from .source_urls import canonical_video_key
                old = next((v for v in out if canonical_video_key(v['url']) == canonical_video_key(url)), None)
                if old is not None:
                    if re.fullmatch(r'[\d\s.:万亿]*', old['title']) and item['title']:
                        old['title'] = item['title']
                    if item.get('discovery_meta'):
                        old.setdefault('discovery_meta', {}).update(item['discovery_meta'])
                    continue
            out.append(item)
        except Exception:  # noqa: BLE001 - 개별 동적 DOM 노드는 건너뛴다.
            continue
    return out


def _html_candidates(raw: str, provider: str, query: str) -> list[dict]:
    """서버 HTML·hydration 데이터에서 SPA 영상 ID와 상세 URL을 복구한다."""
    body = html.unescape(raw).replace("\\u002F", "/").replace("\\/", "/")
    urls = []
    if provider == "tiktok":
        urls += re.findall(r'https?://(?:www\.)?tiktok\.com/@[^"\'<>\s]+/video/\d+', body)
    elif provider == "douyin":
        urls += [f"https://www.douyin.com/video/{video_id}" for video_id in
                 re.findall(r'(?:aweme_id["\']?\s*[:=]\s*["\']|/video/)(\d{10,})', body)]
    elif provider == "xiaohongshu":
        note_ids = re.findall(r'(?:/explore/|noteId["\']?\s*[:=]\s*["\'])([0-9a-f]{24})', body, re.I)
        urls += [f"https://www.xiaohongshu.com/explore/{note_id}" for note_id in note_ids]
    elif provider == "bilibili":
        urls += [f"https://www.bilibili.com/video/{video_id}" for video_id in
                 re.findall(r'/video/(BV[0-9A-Za-z]+)', body)]
    return [{"url": url, "provider": f"playwright-{provider}", "title": "", "query": query,
             "match_kind": "platform-search"} for url in dict.fromkeys(urls) if _is_candidate(url)]


def _embedded_candidates(page, provider: str, query: str) -> list[dict]:
    """SPA가 링크를 anchor로 만들지 않아도 hydration 데이터의 영상 ID를 복구한다."""
    try:
        return _html_candidates(page.content(), provider, query)
    except Exception:  # noqa: BLE001
        return []


def _sample_frames(frames: list[Path], count: int) -> list[Path]:
    if count <= 1:
        return frames[len(frames) // 2:len(frames) // 2 + 1]
    if len(frames) <= count:
        return frames
    indexes = {round(i * (len(frames) - 1) / (count - 1)) for i in range(count)}
    return [frames[i] for i in sorted(indexes)]


class BrowserSearcher:
    def __init__(self, settings: Settings, debug_dir: Path):
        self.settings = settings
        self.debug_dir = debug_dir
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        self.candidates: list[dict] = []
        self.visual_candidates: list[dict] = []
        self.terms: list[str] = []
        self.notes: list[str] = []
        self.searches: list[dict] = []
        self.previous_searches: list[dict] = []
        self.routes = None
        self.progress = lambda _message: None
        self.deadline = None

    def _pace(self, provider, reserve=20):
        seconds = max(1, self.settings.source_browser_search_interval)
        if self.deadline is not None and time.monotonic()+seconds+reserve >= self.deadline:
            raise SearchBudgetReached('이번 검색 예산 완료')
        if seconds:
            self.progress(f'{provider} · 다음 검색 전 {seconds:g}초 대기')
            time.sleep(seconds)

    def _audit_request(self, audit, operation):
        audit.setdefault('requests', []).append({'operation': operation, 'at': time.time(),
            'minimum_interval_seconds': max(1, self.settings.source_browser_search_interval)})
        # Flush before navigation/upload: a worker termination must not turn a
        # real request into an unattempted "started" row on the next round.
        self.progress(f"{audit.get('provider')} · 요청 기록: {operation}")

    def _cooldown_path(self, provider):
        return self.settings.data_dir / 'search_cooldowns' / f'{provider}.json'

    def _cooling_down(self, provider):
        from .source_collection_access import disabled_platforms
        disabled = disabled_platforms(self.settings)
        if provider in disabled:
            self.searches.append({'provider':provider, 'query':'', 'language':'',
                                  'status':'platform_disabled', 'candidates':0,
                                  'reason':disabled[provider]})
            self.progress(f'{provider} · 사용자 설정으로 수집 제외')
            return True
        if readiness_blocked(self.settings.data_dir,provider):
            self.searches.append({'provider':provider,'query':'','language':'','status':'readiness_blocked',
                                  'parser_revision':parser_revision(provider),'candidates':0})
            self.notes.append(f'{provider} · 검색 화면 판독 실패 · 판독기 수정 또는 명시적 세션 재확인 전 재접근 중지')
            self.progress(f'{provider} · 검색 화면 판독 실패로 경로 중지')
            return True
        record=access_record(self.settings.data_dir,provider)
        if manual_required(record):
            reason='login_required' if record.get('reason')=='login_required' else 'verification_required'
            self.searches.append({'provider':provider,'query':'','language':'','status':reason,'candidates':0})
            self.notes.append(f'{provider} · 저장된 인증 문제 · 확인 전 자동 재접근하지 않음')
            self.progress(f'{provider} · 인증 확인 필요 · 다른 검색으로 진행')
            return True
        until = BROWSER_COOLDOWNS.get(provider, 0)
        try:
            target = self._cooldown_path(provider)
            saved = json.loads(target.read_text())
            # Apply the ten-minute ceiling to old persisted exponential pauses too.
            blocked_at = float(saved.get('blocked_at', target.stat().st_mtime))
            until = min(float(saved['until']), blocked_at + 600)
            BROWSER_COOLDOWNS[provider] = until
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if until <= time.time():
            return False
        self.notes.append(f'{provider} 인증/요청 제한 후 휴식 중 · 검색 건너뜀')
        self.searches.append({'provider': provider, 'query': '', 'language': '',
                              'status': 'cooldown', 'candidates': 0})
        self.progress(f'{provider} · 인증/요청 제한으로 이번 검색 건너뜀')
        return True

    def _block(self, provider, audit, reason):
        from .editing_adapter import _atomic_json
        target = self._cooldown_path(provider)
        previous = {}
        try:
            previous = json.loads(target.read_text())
        except (OSError, ValueError):
            pass
        now = time.time()
        strikes = (max(1, int(previous.get('strikes', 1))) + 1
                   if previous and now - float(previous.get('blocked_at', previous.get('until', 0))) < 86400 else 1)
        seconds = min(600, max(60, self.settings.source_browser_block_cooldown))
        until = now + seconds
        BROWSER_COOLDOWNS[provider] = until
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(target, {'until': until, 'reason': reason, 'blocked_at': now, 'strikes': strikes,
                             'requires_verification':reason in {'captcha','login_required'}})
        audit['status'] = reason
        self.notes.append(f'{provider} {reason} · '+('사용자 인증 확인 전 재검색 중지' if reason in {'captcha','login_required'} else f'{seconds}초 동안 재검색 중지'))
        self.progress(f'{provider} · 인증/요청 제한으로 검색 중지 · 다른 검색으로 진행')

    @staticmethod
    def _captcha(page):
        return challenge_on_page(page)

    def _check_block(self, page, provider, audit, response=None):
        if response is not None and response.status == 429:
            self._block(provider, audit, 'rate_limited')
            return True
        if not self._captcha(page):
            if login_wall_on_page(page,provider):
                self._block(provider,audit,'login_required')
                return True
            return False
        audit['challenge_detected_at'] = time.time()
        audit['challenge_page'] = page.url.split('?',1)[0]
        audit['challenge_wait_setting_seconds'] = self.settings.source_browser_captcha_wait
        self.progress(f'{provider} · CAPTCHA 인증 대기 · 열린 Chrome에서 직접 확인해 주세요')
        if not self.settings.source_browser_headless:
            deadline = time.monotonic() + self.settings.source_browser_captcha_wait
            if self.deadline is not None:deadline=min(deadline,self.deadline)
            while time.monotonic() < deadline:
                page.wait_for_timeout(1000)
                if not self._captcha(page):
                    if login_wall_on_page(page,provider):
                        self._block(provider,audit,'login_required')
                        return True
                    return False
        audit['challenge_still_present'] = True
        self._block(provider, audit, 'captcha')
        return True

    def run(self, frames: list[Path], queries: list[str], limit: int) -> dict:
        if not self.settings.source_browser_search or limit <= 0:
            return {"candidates": [], "terms": [], "notes": []}
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"candidates": [], "terms": [], "notes": ["Playwright가 설치되지 않아 브라우저 검색을 건너뜀"]}
        selected = frames
        with BROWSER_LOCK, sync_playwright() as pw:
            try:
                context = pw.chromium.launch_persistent_context(
                    str(self.settings.source_browser_profile_dir), **source_context_options(self.settings.source_browser_headless),
                )
            except Exception as exc:  # noqa: BLE001
                return {"candidates": [], "terms": [], "notes": [f"Chrome 시작 실패: {exc}"]}
            context.set_default_timeout(15000)
            try:
                restore_platform_cookies(context, self.settings.data_dir, ['google','tiktok', 'douyin', 'xiaohongshu', 'youtube'])
                from .login_exchange import apply_sessions
                apply_sessions(context, self.settings.data_dir, self.settings.source_browser_profile_dir,
                               ['google', 'tiktok', 'douyin', 'xiaohongshu', 'youtube'])
                routes = self.routes if self.routes is not None else ['tiktok','douyin','xiaohongshu','bilibili','google-lens','yandex-images']
                for provider in routes:
                    self.visual_candidates.extend(self.candidates)
                    self.candidates = []
                    if provider == 'google-lens' and selected:
                        self._google(context, selected, limit)
                    elif provider == 'yandex-images' and selected:
                        self._yandex(context, selected, limit)
                    elif provider in {'tiktok','douyin','xiaohongshu','bilibili'}:
                        self._platforms(context, queries, limit, providers={provider})
                # 역이미지 근거를 보존한다. 최종 플랫폼 분배는 source_finder에서 수행한다.
                seen = set()
                combined = []
                for item in [*self.visual_candidates, *self.candidates]:
                    normalized = item["url"].rstrip("/")
                    if normalized and normalized not in seen:
                        seen.add(normalized); combined.append(item)
                self.candidates = combined
            except SearchBudgetReached:
                self.notes.append('이번 브라우저 검색 예산 완료 · 세션과 중간 결과를 정상 저장')
                self.searches.append({'provider':'browser-worker','query':'','language':'','status':'budget_exhausted','candidates':0})
            finally:
                self.progress('브라우저 검색 중간 결과 저장')
                try:
                    cookies = context.cookies()
                    export_cookies(cookies, self.settings.source_browser_cookie_file)
                    for platform in ('google','tiktok', 'douyin', 'xiaohongshu', 'youtube'):
                        save_platform_cookies(cookies, self.settings.data_dir, platform)
                except Exception as exc:  # noqa: BLE001
                    self.notes.append(f"브라우저 쿠키 저장 실패: {type(exc).__name__}")
                context.close()
        # A cooperative budget stop can occur between visual and text searches.
        # Keep both groups, just as the incremental checkpoint does.
        combined={item['url'].rstrip('/'):item for item in [*self.visual_candidates,*self.candidates]}
        self.candidates=list(combined.values())
        return {"candidates": self.candidates, "terms": clean_terms(self.terms)[:20], "notes": self.notes,
                "searches": self.searches}

    def _google(self, context, frames: list[Path], limit: int) -> None:
        if self._cooling_down('google-lens'):
            return
        frames = self._fresh_images(frames, 'google-lens')
        if not frames:
            return
        page = context.new_page()
        try:
            for i, frame in enumerate(frames, 1):
                self._pace('Google Lens',reserve=100)
                self.progress(f'Google Lens · 장면 {i}/{len(frames)} 이미지 검색')
                audit = {'provider': 'google-lens', 'query': frame.name, 'language': 'image', 'image_sha256': image_sha256(frame), 'image_signature':image_signature(frame), 'status': 'started', 'candidates': 0}
                self.searches.append(audit)
                self._audit_request(audit, 'image_search_page')
                response = page.goto("https://www.google.com/imghp?hl=en", wait_until="domcontentloaded", timeout=60000)
                if self._check_block(page, 'google-lens', audit, response):
                    break
                request_pause()
                page.get_by_role("button", name="Search by image").click()
                upload = page.locator("input[type=file]")
                upload.wait_for(state="attached")
                self._pace('google-lens')
                self._audit_request(audit, 'image_upload')
                upload.set_input_files(str(frame))
                page.wait_for_timeout(3500)
                if self._check_block(page, 'google-lens', audit):
                    break
                found = _anchors(page, "google-lens", frame.name, "visual-match")
                self.candidates.extend(found)
                audit.update(status='results' if found else 'no_results', candidates=len(found))
                if len(self.candidates) >= limit:
                    break
                page.wait_for_timeout(1200)
        except SearchBudgetReached:
            raise
        except Exception as exc:  # noqa: BLE001
            if frames: audit.update(status='error', error=type(exc).__name__)
            self.notes.append(f"Google Lens 실패: {type(exc).__name__}: {str(exc)[:180]}")
            try: page.screenshot(path=str(self.debug_dir / "google_error.png"), full_page=True)
            except Exception: pass  # noqa: E701
        finally:
            page.close()

    def _yandex(self, context, frames: list[Path], limit: int) -> None:
        if self._cooling_down('yandex-images'):
            return
        frames = self._fresh_images(frames, 'yandex-images')
        if not frames:
            return
        page = context.new_page()
        try:
            for frame in frames:
                self._pace('Yandex',reserve=70)
                self.progress(f'Yandex · {frame.name} 이미지 검색')
                audit = {'provider': 'yandex-images', 'query': frame.name, 'language': 'image', 'image_sha256': image_sha256(frame), 'image_signature':image_signature(frame), 'status': 'started', 'candidates': 0}
                self.searches.append(audit)
                self._audit_request(audit, 'image_search_page')
                response = page.goto("https://yandex.com/images/", wait_until="domcontentloaded", timeout=60000)
                if self._check_block(page, 'yandex-images', audit, response):
                    break
                self._pace('yandex-images',reserve=85)
                self._audit_request(audit, 'image_upload')
                page.locator("input[type=file]").set_input_files(str(frame))
                page.wait_for_timeout(2500)
                if self._check_block(page, 'yandex-images', audit):
                    break
                page.wait_for_url("**/images/search**", timeout=60000)
                page.wait_for_timeout(2500)
                body = page.locator("body").inner_text()
                self._yandex_terms(body)
                found = _anchors(page, "yandex-images", frame.name, "visual-match")
                self.candidates.extend(found)
                audit.update(status='results' if found else 'no_results', candidates=len(found))
                if len(self.candidates) >= limit:
                    break
                page.wait_for_timeout(1000)
        except SearchBudgetReached:
            raise
        except Exception as exc:  # noqa: BLE001
            if frames: audit.update(status='error', error=type(exc).__name__)
            self.notes.append(f"Yandex Images 실패: {type(exc).__name__}: {str(exc)[:180]}")
            try: page.screenshot(path=str(self.debug_dir / "yandex_error.png"), full_page=True)
            except Exception: pass  # noqa: E701
        finally:
            page.close()

    def _fresh_images(self, frames, provider):
        fresh = fresh_frames(frames, provider, [*self.previous_searches, *self.searches])
        if not fresh:
            self.searches.append({'provider':provider, 'query':'', 'language':'image',
                                  'status':'image_exhausted', 'candidates':0})
        return _sample_frames(fresh, max(1, self.settings.source_browser_frames))

    def _yandex_terms(self, body: str) -> None:
        lines = [x.strip() for x in body.splitlines() if x.strip()]
        try:
            start = lines.index("Image appears to contain") + 1
        except ValueError:
            return
        for line in lines[start:start + 6]:
            if line in {"Similar images", "Sites", "Search"}:
                break
            if 2 <= len(line) <= 100:
                self.terms.append(line)

    def _platforms(self, context, queries: list[str], limit: int, providers=None) -> None:
        platforms = [
            ("tiktok", "https://www.tiktok.com/search/video?q={}"),
            ("douyin", "https://www.douyin.com/search/{}"),
            ("xiaohongshu", "https://www.xiaohongshu.com/search_result?keyword={}"),
            ("bilibili", "https://search.bilibili.com/all?keyword={}"),
        ]
        for provider, template in platforms:
            if providers is not None and provider not in providers:
                continue
            if self._cooling_down(provider):
                continue
            query_limit = max(3, self.settings.source_queries_per_platform) if provider == 'tiktok' else self.settings.source_queries_per_platform
            available = platform_queries(queries, provider, len(queries))
            selected = platform_queries(fresh_queries(available, provider, [*self.previous_searches, *self.searches]), provider, query_limit)
            if not selected:
                self.searches.append({'provider':provider, 'query':'', 'language':'',
                                      'status':'query_exhausted' if available else 'no_supported_queries', 'candidates':0})
                self.notes.append(f'{provider} · 지원 언어의 미사용 검색어가 없어 검색 건너뜀')
                continue
            planned_languages = {language(q) for q in selected}
            if provider == 'tiktok':
                missing = {'en','ko','zh'} - {language(q) for q in queries}
                if missing:
                    self.notes.append('TikTok 검색어 누락 언어: ' + ', '.join(sorted(missing)))
            per_provider_limit = min(limit, max(1, self.settings.source_candidates_per_platform,
                self.settings.source_tiktok_min_usable * 3 if provider == 'tiktok' else 0))
            # The necessary search response is the access check. An extra raw
            # HTTP request to /login did not execute site JavaScript and could
            # itself cause a new challenge; cookie presence is not auth proof.
            auth = 'unverified'
            page = context.new_page()
            page.route("**/*", lambda route: route.abort() if route.request.resource_type in {"media", "font"}
                       else route.continue_())
            provider_urls: set[str] = set()
            response_candidates = []
            current_query = ['']
            if provider == 'tiktok' and hasattr(page, 'on'):
                from .source_search.tiktok_results import search_response_candidates
                def receive_search(response):
                    parsed = urlparse(response.url)
                    if parsed.path not in ('/api/search/item/full/', '/api/search/general/full/'):
                        return
                    try:
                        response_candidates.extend(search_response_candidates(
                            response.url, response.json(), current_query[0]))
                    except Exception:
                        pass
                page.on('response', receive_search)
            try:
                per_query_limit = max(2, (per_provider_limit + len(selected) - 1) // max(1, len(selected)))
                searched_languages = set()
                for query in selected:
                    current_query[0] = query
                    response_candidates.clear()
                    searched_languages.add(language(query))
                    self.progress(f'{provider} · {language(query)} · {query}')
                    audit = {'provider': provider, 'query': query, 'language': language(query),
                             'parser_revision':parser_revision(provider),
                             'auth': auth, 'status': 'started', 'candidates': 0}
                    self.searches.append(audit)
                    loaded = False
                    encoded = quote(query, safe="") if provider == "douyin" else quote_plus(query)
                    search_url = template.format(encoded)
                    for attempt in range(2):
                        self._pace(provider,reserve=45)
                        self._audit_request(audit, 'search_navigation')
                        try:
                            response = page.goto(search_url, wait_until="commit", timeout=12000)
                            audit['http_status'] = response.status if response else None
                            loaded = True
                            if response and response.status == 429:
                                self._block(provider, audit, 'rate_limited')
                            break
                        except Exception as exc:  # SPA 로딩 지연은 1회 재시도한다.
                            audit.update(status='error', error=type(exc).__name__)
                            self.notes.append(f"{provider} 페이지 로딩 지연: {type(exc).__name__}")
                    if BROWSER_COOLDOWNS.get(provider, 0) > time.time():
                        break
                    if not loaded:
                        continue  # Never attribute stale results from the previous page to this query.
                    if (audit.get('http_status') or 200) >= 400:
                        audit['status'] = 'http_error'
                        continue
                    page.wait_for_timeout(2000)
                    if self._check_block(page, provider, audit):
                        break
                    page.mouse.wheel(0, 900)
                    page.wait_for_timeout(1000)
                    # The slider challenge may appear after the SPA hydrates
                    # or scrolls, after the initial block check has passed.
                    if self._check_block(page, provider, audit):
                        break
                    found = self._wait_platform_results(page, provider, query, audit, response_candidates)
                    if found is None:
                        break
                    added = 0
                    for item in found:
                        if item["url"] not in provider_urls and len(provider_urls) < per_provider_limit and added < per_query_limit:
                            provider_urls.add(item["url"])
                            self.candidates.append(item)
                            added += 1
                    audit.update(status='results' if found else ('no_results' if empty_results_on_page(page) else 'page_unresolved'),
                                 candidates=added)
                    if not found:
                        # HTTP 200 alone cannot distinguish empty results from
                        # a login/error/unfinished SPA. Keep visible evidence
                        # for diagnosis without copying scripts or cookie data.
                        try:
                            audit['page_url'] = page.url.split('?', 1)[0]
                            audit['page_excerpt'] = ' '.join(page.locator('body').inner_text().split())[:800]
                        except Exception:
                            pass
                        # A challenge can hydrate after the last polling check.
                        # Classify the actual captured body, rather than saving
                        # this known authentication wall as a parser failure.
                        if challenge_in_text(audit.get('page_excerpt', '')):
                            self._block(provider, audit, 'captcha')
                            break
                    if audit['status']=='page_unresolved':
                        record_unresolved(self.settings.data_dir,provider,query)
                        self.notes.append(f'{provider} · 검색 화면에서 결과·인증·빈 결과를 확인할 수 없어 이번 공급자 검색 종료')
                        self.progress(f'{provider} · 검색 화면 판독 실패 기록 · 이후 검색어를 바꿔도 자동 재접근 중지')
                        break
                    self.progress(f'{provider} · {language(query)} · {query} → 후보 {added}개')
                    if len(provider_urls) >= per_provider_limit and searched_languages >= planned_languages:
                        break
            except SearchBudgetReached:
                raise
            except Exception as exc:  # noqa: BLE001
                if 'audit' in locals() and audit.get('provider') == provider and audit['status'] == 'started':
                    audit.update(status='error', error=type(exc).__name__)
                self.notes.append(f"{provider} 검색 실패: {type(exc).__name__}: {str(exc)[:140]}")
            finally:
                page.close()

    def _wait_platform_results(self, page, provider, query, audit, response_candidates):
        """Bound hydration wait without another navigation or ignoring an auth wall."""
        started = time.monotonic()
        for attempt in range(16):
            if self._check_block(page, provider, audit):
                return None
            if provider == 'tiktok':
                # Activity notifications also contain /video/ links. Never use
                # the whole document or hydration payload as TikTok search hits.
                found = list(response_candidates)
            else:
                found = [*_anchors(page, f'playwright-{provider}', query, 'platform-search'),
                         *_embedded_candidates(page, provider, query)]
            if found or empty_results_on_page(page):
                if self._check_block(page, provider, audit):
                    return None
                audit['result_wait_seconds'] = round(time.monotonic() - started, 2)
                audit['result_method'] = 'search_response' if provider == 'tiktok' else 'page_links'
                return found
            if attempt == 15 or (self.deadline is not None and time.monotonic()+1 >= self.deadline):
                break
            page.wait_for_timeout(1000)
        audit['result_wait_seconds'] = round(time.monotonic() - started, 2)
        if self._check_block(page, provider, audit):
            return None
        return []


def browser_search(settings: Settings, frames: list[Path], queries: list[str], limit: int, debug_dir: Path,
                   previous_searches: list[dict] | None = None, progress=None, routes=None) -> dict:
    if not settings.source_browser_search or limit <= 0:
        return {'candidates': [], 'terms': [], 'notes': [], 'searches': []}
    from .source_browser_worker import isolated_search
    with BROWSER_LOCK:
        return isolated_search(settings, frames, queries, limit, debug_dir, previous_searches, progress, routes=routes)
