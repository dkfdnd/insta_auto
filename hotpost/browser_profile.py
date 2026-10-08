"""소스 검색용 Chrome 프로필과 다운로드 쿠키를 안전하게 공유한다."""
from __future__ import annotations

import sqlite3
import json
import threading
import time
from pathlib import Path

from .private_file import private_output_path

BROWSER_LOCK = threading.Lock()


def source_context_options(headless=False):
    """Login and collection use the same real Chrome profile and locale."""
    return dict(channel='chrome',headless=headless,locale='ko-KR',viewport={'width':1280,'height':900})

PLATFORMS = {
    "google": {
        "label": "Google 검색",
        "url": "https://www.google.com/imghp?hl=ko",
        "domains": ("google.com",),
        "cookies": ("NID", "SOCS", "SID"),
    },
    "tiktok": {
        "label": "TikTok",
        "url": "https://www.tiktok.com/login?lang=ko-KR",
        "domains": ("tiktok.com",),
        "cookies": ("sessionid", "sessionid_ss", "sid_guard"),
    },
    "douyin": {
        "label": "더우인",
        "url": "https://www.douyin.com/",
        "domains": ("douyin.com",),
        "cookies": ("sessionid", "sessionid_ss", "sid_guard"),
    },
    "xiaohongshu": {
        "label": "샤오홍슈",
        "url": "https://www.xiaohongshu.com/",
        "domains": ("xiaohongshu.com", "xhslink.com"),
        "cookies": ("web_session",),
    },
    "instagram": {
        "label": "Instagram",
        "url": "https://www.instagram.com/accounts/login/",
        "domains": ("instagram.com",),
        "cookies": ("sessionid",),
    },
    "youtube": {
        "label": "YouTube",
        "url": "https://www.youtube.com/",
        "domains": ("youtube.com", "google.com"),
        "cookies": ("SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID", "LOGIN_INFO"),
    },
}


def platform_cookie(cookie: dict, platform: str) -> bool:
    host = str(cookie.get('domain', '')).lower().lstrip('.')
    return any(host == domain or host.endswith('.' + domain) for domain in PLATFORMS[platform]['domains'])


def _platform_rows(cookies: list[dict], checks: dict[str, str] | None = None) -> list[dict]:
    rows = []
    for key, spec in PLATFORMS.items():
        found = any(
            platform_cookie(cookie, key)
            and cookie.get("name") in spec["cookies"]
            and bool(cookie.get("value") or cookie.get("has_value"))
            and (float(cookie.get('expires') or 0) <= 0 or float(cookie['expires']) > time.time())
            for cookie in cookies
        )
        auth_status = (checks or {}).get(key, "unverified")
        rows.append({"id": key, "label": spec["label"], "cookie_present": found,
                     "auth_status": auth_status,
                     "connected": found and auth_status == "authenticated"})
    return rows


def probe_platform_auth(context, platform: str) -> str:
    """저장 쿠키를 사용하는 가벼운 요청으로 인증 신호를 확인한다.

    응답에 명시적 로그인 상태가 없으면 성공이라고 추정하지 않는다.
    """
    import re
    urls = {"tiktok": "https://www.tiktok.com/login",
            "douyin": "https://www.douyin.com/",
            "xiaohongshu": "https://www.xiaohongshu.com/",
            "youtube": "https://www.youtube.com/account"}
    if platform not in urls:
        return "unverified"
    try:
        response = context.request.get(urls[platform], timeout=6000)
        if response.status == 429:
            return "rate_limited"
        if response.status in (401, 403) or any(word in response.url.lower() for word in
                                                   ("accounts.google.com", "/login?", "/signin")):
            return "login_required"
        body = response.text()[:1_000_000]
        # Login HTML also contains unused CAPTCHA strings in scripts/templates.
        # Only visible markup, or a challenge URL, is evidence of a challenge.
        from html.parser import HTMLParser
        class VisibleText(HTMLParser):
            def __init__(self):
                super().__init__(); self.hidden = 0; self.parts = []
            def handle_starttag(self, tag, attrs):
                if tag in {'script', 'style', 'template'}: self.hidden += 1
            def handle_endtag(self, tag):
                if tag in {'script', 'style', 'template'}: self.hidden = max(0, self.hidden - 1)
            def handle_data(self, data):
                if not self.hidden: self.parts.append(data)
        visible = VisibleText(); visible.feed(body)
        challenge_text = ' '.join(visible.parts).lower()
        if (any(token in response.url.lower() for token in ('/sorry/', '/captcha', '/showcaptcha'))
                or any(token in challenge_text for token in ('unusual traffic', 'verify you are human',
                    'drag the slider', 'fit the puzzle', 'slide to verify'))):
            return 'verification_required'
        if re.search(r'(?i)["\'](?:isLogin|isLoggedIn|loggedIn)["\']\s*:\s*true', body):
            return "authenticated"
        if re.search(r'(?i)["\'](?:isLogin|isLoggedIn|loggedIn)["\']\s*:\s*false', body):
            return "login_required"
    except Exception:  # 플랫폼 오류는 인증 성공으로 추정하지 않는다.
        return "unverified"
    return "unverified"


def profile_cookie_status(profile_dir: Path) -> list[dict]:
    """복호화 없이 쿠키의 도메인·이름·값 존재 여부만 검사한다."""
    db = profile_dir / "Default" / "Network" / "Cookies"
    if not db.is_file(): db = profile_dir / "Default" / "Cookies"
    if not db.is_file():
        return _platform_rows([])
    try:
        conn = sqlite3.connect(db.resolve().as_uri()+"?mode=ro", uri=True, timeout=.25)
        records = conn.execute(
            "SELECT host_key, name, length(value) + length(encrypted_value), expires_utc FROM cookies"
        ).fetchall()
        conn.close()
        cookies = [{"domain": host, "name": name, "has_value": size > 0,
                    "expires": expiry / 1_000_000 - 11644473600 if expiry else 0}
                   for host, name, size, expiry in records]
    except sqlite3.Error:
        return [dict(row,cookie_readable=False) for row in _platform_rows([])]
    return [dict(row,cookie_readable=True) for row in _platform_rows(cookies)]


def save_platform_cookies(cookies: list[dict], data_dir: Path, platform: str) -> None:
    """Save browser session cookies privately as well as downloader cookies."""
    selected = [c for c in cookies if platform_cookie(c, platform)
                and (float(c.get('expires') or 0) <= 0 or float(c['expires']) > time.time())]
    root = data_dir / 'platform_sessions'
    export_cookies(selected, root / f'{platform}.cookies.txt')
    with private_output_path(root / f'{platform}.json') as temp:
        temp.write_text(json.dumps({'cookies': selected}), encoding='utf-8')


def restore_platform_cookies(context, data_dir: Path, platforms) -> None:
    """Restore missing, unexpired session cookies without replacing live cookies."""
    root = data_dir / 'platform_sessions'
    files = [(key, root / f'{key}.json') for key in platforms if (root / f'{key}.json').is_file()]
    if not files: return
    existing = {(c['domain'], c.get('path', '/'), c['name']) for c in context.cookies()}
    pending = []
    for key, file in files:
        try:
            cookies = json.loads(file.read_text(encoding='utf-8')).get('cookies', [])
        except (ValueError, OSError): continue
        for cookie in cookies:
            if not platform_cookie(cookie, key) or not cookie.get('value'): continue
            expires = float(cookie.get('expires') or 0)
            identity = (cookie.get('domain'), cookie.get('path', '/'), cookie.get('name'))
            if identity in existing or (expires > 0 and expires <= time.time()): continue
            pending.append({**cookie, 'expires': expires if expires > 0 else -1})
            existing.add(identity)
    if pending: context.add_cookies(pending)


def export_cookies(cookies: list[dict], target: Path) -> None:
    """Playwright 쿠키를 yt-dlp가 읽는 Netscape 형식으로 원자적으로 저장한다."""
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Netscape HTTP Cookie File", "# Generated by hotpost; do not share this file."]
    now = int(time.time())
    for cookie in cookies:
        domain = str(cookie.get("domain", "")).replace("\t", "").replace("\n", "")
        name = str(cookie.get("name", "")).replace("\t", "").replace("\n", "")
        value = str(cookie.get("value", "")).replace("\t", "").replace("\n", "")
        if not domain or not name or not value:
            continue
        expires = int(cookie.get("expires") or 0)
        if expires > 0 and expires <= now:
            continue
        prefix = "#HttpOnly_" if cookie.get("httpOnly") else ""
        lines.append("\t".join((prefix + domain, "TRUE" if domain.startswith(".") else "FALSE",
                                str(cookie.get("path") or "/"), "TRUE" if cookie.get("secure") else "FALSE",
                                str(max(0, expires)), name, value)))
    with private_output_path(target) as temp:
        temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
