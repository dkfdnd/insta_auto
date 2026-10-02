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
from .browser_profile import BROWSER_LOCK, export_cookies, probe_platform_auth
from .source_urls import video_url
from .source_queries import platform_queries, clean_terms, language

VIDEO_HOSTS = ("tiktok.com", "douyin.com", "xiaohongshu.com", "youtube.com", "youtu.be", "bilibili.com",
               "vimeo.com", "lazada.", "manuals.plus", "made-in-china.com")
SKIP_HOSTS = ("google.com", "gstatic.com", "googleusercontent.com", "yandex.com", "yandex.ru", "yandex.net")
BROWSER_COOLDOWNS: dict[str, float] = {}


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
            "els => els.slice(0, 1500).map(a => ({href: a.href, text: a.innerText || a.getAttribute('aria-label') || ''}))"
        )
    except Exception:  # noqa: BLE001
        return out
    for anchor in anchors:
        try:
            url = _unwrap(urljoin(page.url, anchor.get("href") or ""))
            if not _is_candidate(url):
                continue
            title = str(anchor.get("text") or "").strip()
            out.append({"url": url, "provider": provider, "title": re.sub(r"\s+", " ", title)[:240],
                        "query": query, "match_kind": match_kind})
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
        self.progress = lambda _message: None

    def _pace(self, provider):
        seconds = max(1, self.settings.source_browser_search_interval)
        if seconds:
            self.progress(f'{provider} · 다음 검색 전 {seconds:g}초 대기')
            time.sleep(seconds)

    def _cooldown_path(self, provider):
        return self.settings.data_dir / 'search_cooldowns' / f'{provider}.json'

    def _cooling_down(self, provider):
        until = BROWSER_COOLDOWNS.get(provider, 0)
        try:
            until = max(until, float(json.loads(self._cooldown_path(provider).read_text())['until']))
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
        seconds = max(60, self.settings.source_browser_block_cooldown)
        until = time.time() + seconds
        BROWSER_COOLDOWNS[provider] = until
        target = self._cooldown_path(provider)
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(target, {'until': until, 'reason': reason})
        audit['status'] = reason
        self.notes.append(f'{provider} {reason} · {seconds}초 동안 재검색 중지')
        self.progress(f'{provider} · 인증/요청 제한으로 검색 중지 · 다른 검색으로 진행')

    @staticmethod
    def _captcha(page):
        if any(token in page.url.lower() for token in ('/sorry/', '/showcaptcha', '/captcha')):
            return True
        body = page.locator('body').inner_text().lower()
        return any(token in body for token in ('unusual traffic', 'verify you are human',
                   'confirm you are not a robot', '로봇이 아닙니다', '비정상적인 트래픽',
                   'drag the slider', 'fit the puzzle', 'slide to verify',
                   '拖动滑块', '滑动验证', '슬라이더를 끌어', '퍼즐을 맞춰'))

    def _check_block(self, page, provider, audit, response=None):
        if response is not None and response.status == 429:
            self._block(provider, audit, 'rate_limited')
            return True
        if not self._captcha(page):
            return False
        self.progress(f'{provider} · CAPTCHA 인증 대기 · 열린 Chrome에서 직접 확인해 주세요')
        if not self.settings.source_browser_headless:
            deadline = time.monotonic() + self.settings.source_browser_captcha_wait
            while time.monotonic() < deadline:
                page.wait_for_timeout(1000)
                if not self._captcha(page):
                    return False
        self._block(provider, audit, 'captcha')
        return True

    def run(self, frames: list[Path], queries: list[str], limit: int) -> dict:
        if not self.settings.source_browser_search or limit <= 0:
            return {"candidates": [], "terms": [], "notes": []}
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"candidates": [], "terms": [], "notes": ["Playwright가 설치되지 않아 브라우저 검색을 건너뜀"]}
        selected = _sample_frames(frames, max(1, self.settings.source_browser_frames))
        with BROWSER_LOCK, sync_playwright() as pw:
            try:
                context = pw.chromium.launch_persistent_context(
                    str(self.settings.source_browser_profile_dir), channel="chrome",
                    headless=self.settings.source_browser_headless, locale="en-US",
                    viewport={"width": 1280, "height": 900},
                )
            except Exception as exc:  # noqa: BLE001
                return {"candidates": [], "terms": [], "notes": [f"Chrome 시작 실패: {exc}"]}
            context.set_default_timeout(15000)
            try:
                # Reserve the first browser budget for all three TikTok languages.
                self._platforms(context, queries, limit, providers={'tiktok'})
                self.visual_candidates = list(self.candidates)
                self.candidates = []
                if selected:
                    self._google(context, selected, limit)
                    self._yandex(context, selected, limit)
                visual_candidates = [*self.visual_candidates, *self.candidates]
                self.visual_candidates = visual_candidates
                self.candidates = []
                expanded = list(dict.fromkeys([*queries, *clean_terms(self.terms)]))
                self._platforms(context, expanded, limit, providers={'douyin', 'xiaohongshu', 'bilibili'})
                # 역이미지 근거를 보존한다. 최종 플랫폼 분배는 source_finder에서 수행한다.
                seen = set()
                combined = []
                for item in [*visual_candidates, *self.candidates]:
                    normalized = item["url"].rstrip("/")
                    if normalized and normalized not in seen:
                        seen.add(normalized); combined.append(item)
                self.candidates = combined
            finally:
                self.progress('브라우저 검색 중간 결과 저장')
                try:
                    export_cookies(context.cookies(), self.settings.source_browser_cookie_file)
                except Exception as exc:  # noqa: BLE001
                    self.notes.append(f"브라우저 쿠키 저장 실패: {type(exc).__name__}")
                context.close()
        return {"candidates": self.candidates, "terms": clean_terms(self.terms)[:20], "notes": self.notes,
                "searches": self.searches}

    def _google(self, context, frames: list[Path], limit: int) -> None:
        if self._cooling_down('google-lens'):
            return
        page = context.new_page()
        try:
            for i, frame in enumerate(frames, 1):
                self._pace('Google Lens')
                self.progress(f'Google Lens · 장면 {i}/{len(frames)} 이미지 검색')
                audit = {'provider': 'google-lens', 'query': frame.name, 'language': 'image', 'status': 'started', 'candidates': 0}
                self.searches.append(audit)
                response = page.goto("https://www.google.com/imghp?hl=en", wait_until="domcontentloaded", timeout=60000)
                if self._check_block(page, 'google-lens', audit, response):
                    break
                request_pause()
                page.get_by_role("button", name="Search by image").click()
                upload = page.locator("input[type=file]")
                upload.wait_for(state="attached")
                request_pause()
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
        page = context.new_page()
        try:
            for frame in frames:
                self._pace('Yandex')
                self.progress(f'Yandex · {frame.name} 이미지 검색')
                audit = {'provider': 'yandex-images', 'query': frame.name, 'language': 'image', 'status': 'started', 'candidates': 0}
                self.searches.append(audit)
                response = page.goto("https://yandex.com/images/", wait_until="domcontentloaded", timeout=60000)
                if self._check_block(page, 'yandex-images', audit, response):
                    break
                request_pause()
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
        except Exception as exc:  # noqa: BLE001
            if frames: audit.update(status='error', error=type(exc).__name__)
            self.notes.append(f"Yandex Images 실패: {type(exc).__name__}: {str(exc)[:180]}")
            try: page.screenshot(path=str(self.debug_dir / "yandex_error.png"), full_page=True)
            except Exception: pass  # noqa: E701
        finally:
            page.close()

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
            used = {r.get('query') for r in self.previous_searches if r.get('provider') == provider}
            query_limit = max(3, self.settings.source_queries_per_platform) if provider == 'tiktok' else self.settings.source_queries_per_platform
            selected = platform_queries([q for q in queries if q not in used], provider, query_limit)
            if not selected:
                self.searches.append({'provider':provider, 'query':'', 'language':'',
                                      'status':'no_supported_queries', 'candidates':0})
                self.notes.append(f'{provider} · 지원 언어의 미사용 검색어가 없어 검색 건너뜀')
                continue
            planned_languages = {language(q) for q in selected}
            if provider == 'tiktok':
                missing = {'en','ko','zh'} - {language(q) for q in queries}
                if missing:
                    self.notes.append('TikTok 검색어 누락 언어: ' + ', '.join(sorted(missing)))
            per_provider_limit = min(limit, max(1, self.settings.source_candidates_per_platform,
                self.settings.source_tiktok_min_usable * 3 if provider == 'tiktok' else 0))
            auth = probe_platform_auth(context, provider)
            if auth != "authenticated":
                self.notes.append(f"{provider} 인증 확인: {auth} (공개 검색은 계속 진행)")
            page = context.new_page()
            page.route("**/*", lambda route: route.abort() if route.request.resource_type in {"media", "font"}
                       else route.continue_())
            provider_urls: set[str] = set()
            try:
                per_query_limit = max(2, (per_provider_limit + len(selected) - 1) // max(1, len(selected)))
                searched_languages = set()
                for query in selected:
                    searched_languages.add(language(query))
                    self.progress(f'{provider} · {language(query)} · {query}')
                    audit = {'provider': provider, 'query': query, 'language': language(query),
                             'auth': auth, 'status': 'started', 'candidates': 0}
                    self.searches.append(audit)
                    loaded = False
                    encoded = quote(query, safe="") if provider == "douyin" else quote_plus(query)
                    search_url = template.format(encoded)
                    for attempt in range(2):
                        self._pace(provider)
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
                    found = [*_anchors(page, f"playwright-{provider}", query, "platform-search"),
                             *_embedded_candidates(page, provider, query)]
                    added = 0
                    for item in found:
                        if item["url"] not in provider_urls and len(provider_urls) < per_provider_limit and added < per_query_limit:
                            provider_urls.add(item["url"])
                            self.candidates.append(item)
                            added += 1
                    audit.update(status='results' if added else ('login_required' if auth == 'login_required' else 'no_results'),
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
                    self.progress(f'{provider} · {language(query)} · {query} → 후보 {added}개')
                    if len(provider_urls) >= per_provider_limit and searched_languages >= planned_languages:
                        break
            except Exception as exc:  # noqa: BLE001
                if 'audit' in locals() and audit.get('provider') == provider and audit['status'] == 'started':
                    audit.update(status='error', error=type(exc).__name__)
                self.notes.append(f"{provider} 검색 실패: {type(exc).__name__}: {str(exc)[:140]}")
            finally:
                page.close()


def browser_search(settings: Settings, frames: list[Path], queries: list[str], limit: int, debug_dir: Path,
                   previous_searches: list[dict] | None = None, progress=None) -> dict:
    if not settings.source_browser_search or limit <= 0:
        return {'candidates': [], 'terms': [], 'notes': [], 'searches': []}
    from .source_browser_worker import isolated_search
    with BROWSER_LOCK:
        return isolated_search(settings, frames, queries, limit, debug_dir, previous_searches, progress)
