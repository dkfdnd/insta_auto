"""instaloader 기반 수집기 (로그인 세션 필요).

세션 준비:
    python -m hotpost login --user <인스타아이디>            # 비밀번호 직접 입력
    python -m hotpost login --user <아이디> --browser chrome  # 브라우저 쿠키 가져오기
"""
from __future__ import annotations

import itertools
import re
import time
from pathlib import Path

import instaloader

from ..config import Settings
from ..models import Post, Profile
from ..observations import MetricObservation
from ..private_file import private_output_path
from .base import CollectError

_HASHTAG_RE = re.compile(r"#([\w가-힣]+)")


def session_file(settings: Settings, user: str) -> Path:
    return settings.session_dir / f"session-{user}"


def make_loader(*, quiet: bool = True) -> instaloader.Instaloader:
    return instaloader.Instaloader(
        download_pictures=False, download_videos=False, download_video_thumbnails=False,
        download_geotags=False, download_comments=False, save_metadata=False,
        compress_json=False, quiet=quiet, max_connection_attempts=2,
        user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    )


def load_session(settings: Settings) -> instaloader.Instaloader:
    user = settings.ig_user
    if not user:
        raise CollectError("로그인 아이디가 없습니다. IG_USER 환경변수 또는 config.json 의 ig_user 를 설정하세요.")
    f = session_file(settings, user)
    if not f.exists():
        raise CollectError(f"세션 파일이 없습니다: {f}\n  먼저 `python -m hotpost login --user {user}` 를 실행하세요.")
    L = make_loader()
    L.load_session_from_file(user, str(f))
    return L


def login_with_password(settings: Settings, user: str) -> Path:
    """터미널에서 비밀번호를 직접 입력받아 로그인하고 세션을 저장한다 (2단계 인증 지원)."""
    L = make_loader(quiet=False)
    L.interactive_login(user)
    f = session_file(settings, user)
    with private_output_path(f) as temp:
        L.save_session_to_file(str(temp))
    return f


def login_from_browser(settings: Settings, user: str, browser: str) -> Path:
    """브라우저(chrome/firefox/safari...)에 이미 로그인된 쿠키를 가져와 세션으로 저장한다."""
    if browser == "dedicated":
        from ..instagram_login import login_in_browser
        return login_in_browser(settings, user)
    try:
        import browser_cookie3
    except ImportError as e:
        raise CollectError("browser_cookie3 가 필요합니다: pip install browser-cookie3") from e
    getter = getattr(browser_cookie3, browser, None)
    if getter is None:
        raise CollectError(f"지원하지 않는 브라우저: {browser}")
    try:
        jar = getter(domain_name="instagram.com")
    except Exception as exc:
        raise CollectError(
            "브라우저 쿠키를 읽지 못했습니다. 저장된 로그인은 변경하지 않았습니다. "
            "`python -m hotpost login --browser dedicated`로 전용 창에서 로그인하세요."
        ) from exc
    L = make_loader()
    L.context._session.cookies.update(jar)
    try:
        detected = L.test_login()
    except Exception as e:  # noqa: BLE001
        raise CollectError(f"쿠키로 로그인 확인 실패: {e}") from e
    if not detected:
        raise CollectError(f"{browser} 에 instagram.com 로그인 쿠키가 없습니다. 브라우저에서 먼저 로그인하세요.")
    if user and detected.lower() != user.lower():
        raise CollectError("브라우저 계정이 설정된 수집용 로그인 계정과 다릅니다. 올바른 계정으로 로그인하세요.")
    L.context.username = detected
    name = user or detected
    f = session_file(settings, name)
    with private_output_path(f) as temp:
        L.save_session_to_file(str(temp))
    return f


def _kind(post: instaloader.Post) -> str:
    node = getattr(post, "_node", {}) or {}
    product = node.get("product_type") or ""
    if post.is_video:
        return "reel" if product in ("clips", "igtv") or post.typename == "GraphVideo" else "video"
    if post.typename == "GraphSidecar":
        return "carousel"
    return "image"


class InstaloaderCollector:
    name = "instaloader"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._loader: instaloader.Instaloader | None = None

    @property
    def loader(self) -> instaloader.Instaloader:
        if self._loader is None:
            self._loader = load_session(self.settings)
        return self._loader

    def fetch(self, username: str, limit: int, existing: dict[str, Post] | None = None) -> tuple[Profile, list[Post], list[MetricObservation]]:
        try:
            prof = instaloader.Profile.from_username(self.loader.context, username)
        except instaloader.exceptions.ProfileNotExistsException as e:
            raise CollectError(f"존재하지 않는 계정: {username}") from e
        except instaloader.exceptions.InstaloaderException as e:
            raise CollectError(f"{username} 프로필 조회 실패: {e}") from e

        profile = Profile(
            username=prof.username, user_id=str(prof.userid), full_name=prof.full_name or "",
            followers=prof.followers, following=prof.followees, media_count=prof.mediacount,
            biography=prof.biography or "", profile_pic_url=prof.profile_pic_url, is_private=prof.is_private,
        )
        if prof.is_private and not prof.followed_by_viewer:
            raise CollectError(f"{username} 은 비공개 계정입니다.")

        posts: list[Post] = []
        try:
            for p in itertools.islice(prof.get_posts(), limit):
                caption = p.caption or ""
                posts.append(Post(
                    shortcode=p.shortcode, username=prof.username,
                    taken_at=int(p.date_utc.timestamp()), kind=_kind(p),
                    likes=p.likes or 0, comments=p.comments or 0,
                    views=(p.video_view_count if p.is_video else None),
                    caption=caption, hashtags=[h.lower() for h in _HASHTAG_RE.findall(caption)],
                    thumbnail_url=p.url, video_duration=(p.video_duration if p.is_video else None),
                    media_id=str(p.mediaid),
                ))
        except instaloader.exceptions.InstaloaderException as e:
            if not posts:
                raise CollectError(f"{username} 게시물 조회 실패: {e}") from e
        now = int(time.time())
        observations = [MetricObservation(
            shortcode=p.shortcode, requested_at=now,
            observed_at=now if p.views is not None else None,
            success=p.views is not None, views=p.views, likes=p.likes, comments=p.comments,
            source="instaloader", reason="" if p.views is not None else "missing_views",
            age_hours=max(0, (now - p.taken_at) / 3600), scope="latest",
        ) for p in posts if p.is_video]
        return profile, posts, observations
