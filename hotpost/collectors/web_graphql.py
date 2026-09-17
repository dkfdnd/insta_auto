"""인스타그램 웹사이트가 쓰는 GraphQL 엔드포인트를 그대로 호출하는 수집기.

- 로그인 쿠키는 instaloader 세션 파일(data/sessions/session-<id>)에서 가져온다.
- 프로필 HTML 에서 LSD / fb_dtsg 토큰과 profile_id 를 읽고,
- 웹 번들(JS)에서 GraphQL doc_id 를 자동으로 찾아 data/graphql_docs.json 에 캐시한다.
  (인스타가 doc_id 를 바꿔도 다음 실행 때 다시 찾는다)
- 게시물 타임라인(PolarisProfilePostsQuery) + 릴스 탭(PolarisProfileReelsTabContentQuery, 조회수 확보)

`web_profile_info` 같은 api/v1 엔드포인트는 쉽게 차단(feedback_required/429)되므로 쓰지 않는다.
"""
from __future__ import annotations

import html as htmllib
import json
import logging
import random
import re
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests

from ..config import Settings
from ..models import Post, Profile
from ..observations import MetricObservation
from .base import CollectError

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")
CLIENT_HINTS = {
    "sec-ch-ua": '"Chromium";v="150", "Not=A?Brand";v="8", "Google Chrome";v="150"',
    "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"macOS"',
}
IG_APP_ID = "936619743392459"
_HASHTAG_RE = re.compile(r"#([\w가-힣]+)")

# 2026-09 기준 확인된 doc_id (자동 탐색 실패 시 폴백)
KNOWN_DOCS = {
    "PolarisProfilePostsQuery": ("38154989454116081", [
        "__relay_internal__pv__PolarisMultiCaptionCarouselEnabledrelayprovider",
        "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider",
        "__relay_internal__pv__PolarisReelsRecoDebugOverlayEnabledrelayprovider"]),
    "PolarisProfileReelsTabContentQuery": ("37945290971781723", [
        "__relay_internal__pv__PolarisMultiCaptionCarouselEnabledrelayprovider",
        "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider",
        "__relay_internal__pv__PolarisReelsRecoDebugOverlayEnabledrelayprovider"]),
    "PolarisProfilePageContentQuery": ("28036671149327607", []),
}

QUERIES = {
    "posts": "PolarisProfilePostsQuery",
    "reels": "PolarisProfileReelsTabContentQuery",
    "profile": "PolarisProfilePageContentQuery",
}


def _diagnostic_logger(settings: Settings) -> logging.Logger:
    """Instagram 요청 진단만 별도 순환 로그에 남긴다."""
    logger = logging.getLogger(f"hotpost.instagram.{settings.data_dir.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            settings.data_dir / "instagram_diagnostics.log",
            maxBytes=max(1, settings.instagram_diagnostic_log_max_mb) * 1024 * 1024,
            backupCount=max(1, settings.operational_log_backups),
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
    return logger


class _DocCache:
    def __init__(self, path: Path):
        self.path = path
        self.data = {}
        if path.exists():
            try:
                self.data = json.loads(path.read_text())
            except Exception:  # noqa: BLE001
                self.data = {}

    def get(self, name: str) -> dict | None:
        return self.data.get(name)

    def put(self, name: str, doc_id: str, provided: list[str]) -> None:
        self.data[name] = {"doc_id": doc_id, "provided": provided, "found_at": int(time.time())}
        self.path.write_text(json.dumps(self.data, indent=1))


class WebGraphQLCollector:
    name = "web"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8", **CLIENT_HINTS})
        self._load_cookies()
        self.docs = _DocCache(settings.data_dir / "graphql_docs.json")
        self._diagnostics = _diagnostic_logger(settings)
        self.lsd = self.dtsg = ""
        self._bundle_urls: list[str] = []
        self._current_user = ""

    # ------------------------------------------------------------ session
    def _load_cookies(self) -> None:
        from .instaloader_collector import load_session
        L = load_session(self.settings)
        self.s.cookies.update(L.context._session.cookies)
        if not self._cookie("sessionid"):
            raise CollectError("세션에 sessionid 쿠키가 없습니다. 다시 로그인하세요.")

    def _cookie(self, name: str) -> str:
        """같은 이름의 쿠키가 도메인별로 여러 개일 수 있어 마지막 값을 쓴다."""
        val = ""
        for c in self.s.cookies:
            if c.name == name:
                val = c.value
        return val

    def _api_headers(self, referer: str) -> dict:
        return {"x-ig-app-id": IG_APP_ID, "x-csrftoken": self._cookie("csrftoken"), "x-asbd-id": "129477",
                "x-ig-www-claim": "0", "x-requested-with": "XMLHttpRequest", "accept": "*/*",
                "referer": referer, "sec-fetch-site": "same-origin", "sec-fetch-mode": "cors", "sec-fetch-dest": "empty"}

    def _sleep(self, lo=1.2, hi=2.6) -> None:
        time.sleep(random.uniform(lo, hi))

    def _diagnostic(self, event: str, **fields) -> None:
        logger = getattr(self, "_diagnostics", None)
        if logger is None:
            logger = self._diagnostics = _diagnostic_logger(self.settings)
        safe = {"event": event}
        for key, value in fields.items():
            if value is None:
                continue
            safe[key] = " ".join(str(value).split())[:500] if isinstance(value, str) else value
        logger.info(json.dumps(safe, ensure_ascii=False, separators=(",", ":")))

    # ------------------------------------------------------------ html / tokens
    def _profile_html(self, username: str) -> str:
        self._current_user = username
        r = self.s.get(f"https://www.instagram.com/{username}/", timeout=30)
        if r.status_code == 404:
            raise CollectError(f"존재하지 않는 계정: {username}")
        if r.status_code == 429:
            raise CollectError("429 요청 제한. 잠시 후 다시 시도하세요.")
        r.raise_for_status()
        h = r.text
        if "/accounts/login/" in r.url or '"is_logged_out_user":true' in h:
            raise CollectError("로그인 세션이 만료되었습니다. `python -m hotpost login ...` 을 다시 실행하세요.")
        m = re.search(r'"LSD",\[\],\{"token":"([^"]+)"', h)
        if m:
            self.lsd = m.group(1)
        m = re.search(r'"DTSGInitialData",\[\],\{"token":"([^"]+)"', h)
        if m:
            self.dtsg = m.group(1)
        self._bundle_urls = re.findall(r'<script[^>]+src="([^"]+static\.cdninstagram\.com[^"]+\.js[^"]*)"', h)
        self._bundle_urls = [htmllib.unescape(u) for u in self._bundle_urls]
        return h

    @staticmethod
    def _parse_profile(username: str, h: str) -> Profile:
        pid = (re.search(r'"profile_id":"(\d+)"', h) or re.search(r'"id":"(\d+)","username":"%s"' % re.escape(username), h))
        og = re.search(r'<meta property="og:description" content="([^"]*)"', h)
        desc = htmllib.unescape(og.group(1)) if og else ""
        followers = _num(re.search(r"팔로워\s*([\d,.]+[만천KMk]?)", desc) or re.search(r"([\d,.]+[KMk]?)\s*Followers", desc))
        following = _num(re.search(r"팔로우\s*([\d,.]+[만천KMk]?)", desc) or re.search(r"([\d,.]+[KMk]?)\s*Following", desc))
        media = _num(re.search(r"게시물\s*([\d,.]+[만천KMk]?)", desc) or re.search(r"([\d,.]+[KMk]?)\s*Posts", desc))
        title = re.search(r"<title>([^<]*)</title>", h)
        full = ""
        if title:
            t = htmllib.unescape(title.group(1))
            m = re.match(r"(.*?)\s*\(@", t)
            full = m.group(1).strip() if m else ""
        return Profile(username=username, user_id=pid.group(1) if pid else "", full_name=full,
                       followers=followers, following=following, media_count=media)

    # ------------------------------------------------------------ doc id discovery
    def _bundles_from(self, url: str) -> list[str]:
        try:
            h = self.s.get(url, timeout=30).text
        except Exception:  # noqa: BLE001
            return []
        return [htmllib.unescape(u) for u in re.findall(r'<script[^>]+src="([^"]+static\.cdninstagram\.com[^"]+\.js[^"]*)"', h)]

    def _discover(self, qname: str) -> tuple[str, list[str]]:
        cached = self.docs.get(qname)
        if cached:
            return cached["doc_id"], cached["provided"]
        urls = list(self._bundle_urls)
        if qname == QUERIES["reels"] and self._current_user:
            # 릴스 탭 쿼리 모듈은 릴스 탭 페이지 번들에 들어있다
            for u in self._bundles_from(f"https://www.instagram.com/{self._current_user}/reels/"):
                if u not in urls:
                    urls.append(u)
        if not urls:
            raise CollectError("프로필 HTML 에서 JS 번들을 찾지 못했습니다.")
        doc_id, provided = "", []
        for u in urls:
            try:
                t = self.s.get(u, timeout=30).text
            except Exception:  # noqa: BLE001
                continue
            i = t.find(f'__d("{qname}_instagramRelayOperation"')
            if i >= 0 and not doc_id:
                m = re.search(r'"(\d{12,22})"', t[i:i + 400])
                if m:
                    doc_id = m.group(1)
            j = t.find(f'name:"{qname}",operationKind:"query"')
            if j >= 0 and not provided:
                m = re.search(r"providedVariables:\{([^}]*)\}", t[j:j + 4000])
                if m:
                    provided = re.findall(r"(__relay_internal__pv__\w+):", m.group(1))
            if doc_id and provided:
                break
        if not doc_id and qname in KNOWN_DOCS:
            # 번들에서 못 찾으면 마지막으로 확인된 값으로 시도 (인스타가 바꾸면 실패하고 다음 실행 때 다시 찾는다)
            doc_id, provided = KNOWN_DOCS[qname]
        if not doc_id:
            raise CollectError(f"GraphQL doc_id 를 찾지 못했습니다: {qname} (인스타 웹 구조 변경 가능성)")
        self.docs.put(qname, doc_id, provided)
        return doc_id, provided

    def _forget(self, qname: str) -> None:
        self.docs.data.pop(qname, None)

    # ------------------------------------------------------------ graphql
    def _gql(self, qname: str, variables: dict) -> dict:
        doc_id, provided = self._discover(qname)
        v = dict(variables)
        for p in provided:
            v.setdefault(p, False)
        # 주의: 로그인 상태여도 av/__user 는 "0" 이어야 한다 (viewer id 를 넣으면 1357001 오류)
        params = {
            "av": "0", "__d": "www", "__user": "0", "__a": "1", "__req": "1", "__comet_req": "7",
            "lsd": self.lsd, "jazoest": "2" + str(sum(ord(ch) for ch in self.dtsg)), "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": qname, "variables": json.dumps(v, separators=(",", ":")),
            "server_timestamps": "true", "doc_id": doc_id,
        }
        if self.dtsg:
            params["fb_dtsg"] = self.dtsg
        headers = {
            "content-type": "application/x-www-form-urlencoded", "x-fb-lsd": self.lsd,
            "x-csrftoken": self._cookie("csrftoken"), "x-ig-app-id": IG_APP_ID,
            "x-fb-friendly-name": qname, "x-asbd-id": "129477", "x-ig-www-claim": "0",
            "origin": "https://www.instagram.com", "referer": "https://www.instagram.com/",
            "accept": "*/*", "sec-fetch-site": "same-origin", "sec-fetch-mode": "cors", "sec-fetch-dest": "empty",
        }
        for attempt in range(3):
            request_started = time.monotonic()
            try:
                r = self.s.post("https://www.instagram.com/api/graphql", data=params, headers=headers, timeout=40)
            except requests.RequestException as exc:
                self._diagnostic(
                    "graphql_response", query=qname, doc_id=doc_id, attempt=attempt + 1,
                    outcome="network_error", elapsed_ms=int((time.monotonic() - request_started) * 1000),
                    error_type=type(exc).__name__,
                )
                raise CollectError(f"{qname}: 네트워크 오류 {type(exc).__name__}") from exc
            common = {
                "query": qname,
                "doc_id": doc_id,
                "attempt": attempt + 1,
                "http_status": r.status_code,
                "elapsed_ms": int((time.monotonic() - request_started) * 1000),
                "request_id": r.headers.get("x-fb-request-id") or r.headers.get("x-request-id"),
                "retry_after": r.headers.get("retry-after"),
                "response_bytes": len(r.content),
            }
            if r.status_code == 429:
                wait = 45 * (attempt + 1)
                self._diagnostic("graphql_response", **common, outcome="rate_limited", wait_seconds=wait)
                print(f"    429 제한 → {wait}s 대기", flush=True)
                time.sleep(wait)
                continue
            text = r.text
            if text.startswith("for (;;);"):
                try:
                    err = json.loads(text[9:])
                except ValueError:
                    err = {}
                code = err.get("error")
                self._diagnostic(
                    "graphql_response", **common, outcome="instagram_error",
                    error_code=code, error_summary=err.get("errorSummary", ""),
                )
                if code == 1357001:
                    raise CollectError("로그인이 필요합니다 (세션 만료). `python -m hotpost login ...` 을 다시 실행하세요.")
                raise CollectError(f"{qname}: 인스타 오류 {code} {err.get('errorSummary', '')}")
            try:
                j = r.json()
            except ValueError as e:
                self._diagnostic("graphql_response", **common, outcome="non_json")
                raise CollectError(f"{qname}: JSON 아님 (HTTP {r.status_code})") from e
            if j.get("errors") and not j.get("data"):
                msg = j["errors"][0].get("message", "")
                self._diagnostic("graphql_response", **common, outcome="graphql_error", error_message=msg)
                if "missing_required_variable" in msg or "field_exception" in msg:
                    self._forget(qname)
                raise CollectError(f"{qname}: {msg[:120]}")
            self._diagnostic("graphql_response", **common, outcome="ok", has_data=bool(j.get("data")))
            return j
        raise CollectError(f"{qname}: 반복된 429 제한")

    # ------------------------------------------------------------ fetch
    def fetch(self, username: str, limit: int, existing: dict[str, Post] | None = None) -> tuple[Profile, list[Post], list[MetricObservation]]:
        h = self._profile_html(username)
        profile = self._parse_profile(username, h)
        self._sleep(0.8, 1.6)

        posts: dict[str, Post] = {}
        # 1) 타임라인 (좋아요/댓글/캡션/썸네일)
        after = None
        while len(posts) < limit:
            data = {"count": 12, "include_reel_media_seen_timestamp": True, "include_relationship_info": True,
                    "latest_besties_reel_media": True, "latest_reel_media": True}
            vars_ = {"data": data, "username": username, "first": 12, "after": after, "before": None, "last": None}
            j = self._gql(QUERIES["posts"], vars_)
            conn = (j.get("data") or {}).get("xdt_api__v1__feed__user_timeline_graphql_connection") or {}
            edges = conn.get("edges") or []
            if not edges:
                break
            for e in edges:
                node = e.get("node") or {}
                p = _node_to_post(node, username)
                if p:
                    posts[p.shortcode] = p
                if not profile.user_id:
                    u = node.get("user") or {}
                    owner = node.get("owner_id")
                    if isinstance(owner, dict):
                        owner = owner.get("pk") or owner.get("id")
                    profile.user_id = str(owner or u.get("pk") or u.get("id") or "")
                    profile.full_name = u.get("full_name") or profile.full_name
            pi = conn.get("page_info") or {}
            if not pi.get("has_next_page") or not pi.get("end_cursor"):
                break
            after = pi["end_cursor"]
            self._sleep()

        # 2) 팔로워/게시물 수 (실패해도 치명적이지 않음)
        if profile.user_id and not profile.followers:
            try:
                self._sleep(0.8, 1.5)
                self._fill_profile_counts(profile)
            except CollectError as e:
                print(f"    프로필 수치 보강 실패: {e}", flush=True)

        # 3) 릴스 조회수 (media info, 게시물당 1요청) — 오래된 게시물은 이전 값 재사용
        if not posts:
            raise CollectError(f"{username}: 게시물을 가져오지 못했습니다 (비공개 계정이거나 차단)")
        out = sorted(posts.values(), key=lambda p: p.taken_at, reverse=True)[:limit]
        latest = {p.shortcode: p for p in out}
        observations = self._fill_video_views(latest, existing or {}) if any(p.is_video for p in out) else []
        return profile, out, observations

    def _fill_profile_counts(self, profile: Profile) -> None:
        j = self._gql(QUERIES["profile"], {"id": profile.user_id, "render_surface": "PROFILE"})
        user = (j.get("data") or {}).get("user") or {}
        profile.followers = int(user.get("follower_count") or profile.followers or 0)
        profile.following = int(user.get("following_count") or profile.following or 0)
        profile.media_count = int(user.get("media_count") or profile.media_count or 0)
        profile.full_name = user.get("full_name") or profile.full_name
        profile.is_private = bool(user.get("is_private", False))

    def _fill_video_views(self, posts: dict[str, Post], existing: dict[str, Post]) -> list[MetricObservation]:
        now = int(time.time())
        observations: list[MetricObservation] = []
        videos = sorted((p for p in posts.values() if p.is_video), key=lambda p: p.taken_at, reverse=True)
        fetched = 0
        for p in videos:
            old = existing.get(p.shortcode)
            age_days = (now - p.taken_at) / 86400
            if age_days > self.settings.views_refresh_days:
                if old and old.views is not None:
                    p.views = old.views
                    p.video_duration = p.video_duration or old.video_duration
                continue
            if fetched >= self.settings.views_lookup_limit:
                if old and old.views is not None:
                    p.views = old.views
                continue
            if not p.media_id:
                continue
            try:
                requested = int(time.time())
                fetched += 1
                r = self.s.get(f"https://www.instagram.com/api/v1/media/{p.media_id}/info/",
                               headers=self._api_headers(p.url), timeout=30)
                if r.status_code == 429:
                    print("    429 제한 (조회수 조회 중단, 나머지는 이전 값 사용)", flush=True)
                    observations.append(self._view_observation(p, requested, None, 429, "rate_limited", "latest"))
                    break
                item = ((r.json() or {}).get("items") or [{}])[0] if r.ok else {}
                views = next((item[key] for key in ("play_count", "ig_play_count", "view_count")
                              if item.get(key) is not None), None)
                if views is not None:
                    p.views = int(views)
                observations.append(self._view_observation(p, requested, item if views is not None else None,
                                                           r.status_code, "" if views is not None else "missing_views", "latest"))
                if item.get("video_duration"):
                    p.video_duration = float(item["video_duration"])
            except Exception as e:  # noqa: BLE001
                print(f"    조회수 조회 실패 {p.shortcode}: {type(e).__name__}", flush=True)
                observations.append(self._view_observation(p, requested,
                                                           None, None, type(e).__name__, "latest"))
            self._sleep(0.9, 1.8)
        return observations

    def refresh_video_views(self, posts: list[Post], limit: int = 50) -> list[MetricObservation]:
        """최신 5개 밖으로 밀린 터진 릴스도 게시 후 14일까지 조회수를 재조회한다."""
        observations: list[MetricObservation] = []
        now = int(time.time())
        for p in sorted((post for post in posts if post.is_video and post.media_id
                         and post.taken_at + self.settings.hot_view_tracking_days * 86400 >= now),
                        key=lambda post: post.taken_at, reverse=True)[:limit]:
            try:
                requested = int(time.time())
                r = self.s.get(f"https://www.instagram.com/api/v1/media/{p.media_id}/info/",
                               headers=self._api_headers(p.url), timeout=30)
                if r.status_code == 429:
                    print("    429 제한 (터진 릴스 조회수 추적 중단)", flush=True)
                    observations.append(self._view_observation(p, requested, None, 429, "rate_limited", "tracking"))
                    break
                item = ((r.json() or {}).get("items") or [{}])[0] if r.ok else {}
                views = next((item[key] for key in ("play_count", "ig_play_count", "view_count")
                              if item.get(key) is not None), None)
                if views is not None:
                    p.views = int(views)
                observations.append(self._view_observation(p, requested, item if views is not None else None,
                                                           r.status_code, "" if views is not None else "missing_views", "tracking"))
                if item.get("video_duration"):
                    p.video_duration = float(item["video_duration"])
            except Exception as exc:  # noqa: BLE001
                print(f"    추적 조회수 조회 실패 {p.shortcode}: {type(exc).__name__}", flush=True)
                observations.append(self._view_observation(p, requested,
                                                           None, None, type(exc).__name__, "tracking"))
            self._sleep(0.9, 1.8)
        return observations

    @staticmethod
    def _view_observation(p: Post, requested: int, item: dict | None, status: int | None,
                          reason: str, scope: str) -> MetricObservation:
        return MetricObservation(
            shortcode=p.shortcode, requested_at=requested,
            observed_at=int(time.time()) if item is not None else None,
            success=item is not None,
            views=int(next(item[key] for key in ("play_count", "ig_play_count", "view_count")
                           if item.get(key) is not None)) if item is not None else None,
            likes=int(item["like_count"]) if item is not None and item.get("like_count") is not None else None,
            comments=int(item["comment_count"]) if item is not None and item.get("comment_count") is not None else None,
            source="instagram_media_info", http_status=status, reason=reason,
            age_hours=max(0.0, (requested - p.taken_at) / 3600), scope=scope,
        )

def _num(m) -> int:
    if not m:
        return 0
    s = m.group(1).replace(",", "")
    mult = 1
    if s.endswith("만"):
        mult, s = 10000, s[:-1]
    elif s.endswith("천"):
        mult, s = 1000, s[:-1]
    elif s[-1] in "Kk":
        mult, s = 1000, s[:-1]
    elif s[-1] == "M":
        mult, s = 1000000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0


def _node_to_post(n: dict, username: str) -> Post | None:
    code = n.get("code")
    if not code:
        return None
    media_type = n.get("media_type")
    product = n.get("product_type") or ""
    if media_type == 2:
        kind = "reel" if product in ("clips", "igtv") else "video"
    elif media_type == 8:
        kind = "carousel"
    else:
        kind = "image"
    cap = ((n.get("caption") or {}).get("text")) or ""
    thumb = ""
    iv = (n.get("image_versions2") or {}).get("candidates") or []
    if iv:
        # 640px 근처 후보 선택
        thumb = min(iv, key=lambda c: abs((c.get("width") or 0) - 640)).get("url", "")
    views = next((n[key] for key in ("play_count", "ig_play_count", "view_count")
                  if n.get(key) is not None), None)
    owner = (n.get("user") or {}).get("username") or username
    return Post(
        shortcode=code, username=owner.lower(), taken_at=int(n.get("taken_at") or 0), kind=kind,
        likes=(None if n.get("like_and_view_counts_disabled") or n.get("like_count") is None
               else int(n["like_count"])),
        comments=(int(n["comment_count"]) if n.get("comment_count") is not None else None),
        views=(int(views) if (views is not None and kind in ("reel", "video")) else None),
        caption=cap, hashtags=[h.lower() for h in _HASHTAG_RE.findall(cap)],
        thumbnail_url=thumb, video_duration=(float(n["video_duration"]) if n.get("video_duration") else None),
        media_id=str(n.get("pk") or n.get("id") or ""),
    )
