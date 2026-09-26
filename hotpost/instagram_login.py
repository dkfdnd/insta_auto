"""User-operated Instagram login in a persistent, application-owned browser."""
from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlsplit

from .collectors.base import CollectError
from .collectors.instaloader_collector import make_loader, session_file
from .config import Settings
from .private_file import private_output_path


def save_verified_session(settings: Settings, user: str, cookies: list[dict]) -> Path:
    """Save only Instagram cookies after verifying the account; preserve old files on failure."""
    loader = make_loader()
    loader.context.request_timeout = 20
    instagram = [c for c in cookies if c.get("domain", "").lstrip(".").lower() in
                 ("instagram.com", "www.instagram.com")]
    if not any(c.get("name") == "sessionid" and c.get("value") for c in instagram):
        raise CollectError("Instagram 로그인이 아직 완료되지 않았습니다.")
    loader.context._session.cookies.clear()
    for cookie in instagram:
        loader.context._session.cookies.set(cookie["name"], cookie["value"],
                                            domain=cookie["domain"], path=cookie.get("path", "/"))
    try:
        detected = loader.test_login()
    except Exception as exc:
        raise CollectError("수집 세션 인증 검사에 실패했습니다. 기존 세션은 유지됩니다.") from exc
    if not detected:
        raise CollectError("브라우저 로그인 후에도 수집 세션 인증이 확인되지 않았습니다.")
    if user and detected.lower() != user.lower():
        raise CollectError("로그인한 계정이 설정된 수집용 계정과 다릅니다. 올바른 계정으로 로그인하세요.")
    loader.context.username = detected
    target = session_file(settings, user or detected)
    with private_output_path(target) as temp:
        loader.save_session_to_file(str(temp))
    return target


def login_in_browser(settings: Settings, user: str, timeout: float = 900) -> Path:
    """전용 프로필에 로그인하고 실제 게시물 접근까지 검증한다. 쿠키를 이식하지 않는다."""
    from dataclasses import replace
    from .instagram_browser import InstagramBrowser
    from .collectors.browser import BrowserCollector
    from .accounts import AccountRegistry
    import json
    settings = replace(settings, ig_user=user or settings.ig_user)
    browser = InstagramBrowser(settings)
    print("전용 Chrome에서 수집용 계정의 로그인·인증을 완료해 주세요. 브라우저 프로필에 유지됩니다.", flush=True)
    try:
        browser.open()
        browser.page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=45000)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if browser.page.is_closed():
                raise CollectError("전용 로그인 창이 닫혔습니다.")
            try:
                browser.verify_identity()
            except CollectError:
                browser.page.wait_for_timeout(2000)
                continue
            names = AccountRegistry(settings).usernames()
            if not names:
                raise CollectError("로그인은 확인했지만 수집 검증을 위한 레퍼런스 계정이 없습니다.")
            collector = BrowserCollector(replace(settings, collect_recovery_limit=1))
            collector.browser = browser
            browser.page.on("response", collector._response)
            profile, posts, observations = collector.fetch(names[0], 1)
            target = settings.data_dir / "instagram_browser_ready.json"
            with private_output_path(target) as temp:
                temp.write_text(json.dumps({"verified_at": int(time.time()), "posts_checked": len(posts),
                                            "exact_view_observations": sum(o.success for o in observations)},
                                           ensure_ascii=False), encoding="utf-8")
            print("전용 브라우저 로그인과 실제 게시물 접근 확인 완료.", flush=True)
            return target
        raise CollectError("로그인 대기 시간이 끝났습니다. 전용 브라우저 로그인·인증을 확인하세요.")
    finally:
        browser.close()
