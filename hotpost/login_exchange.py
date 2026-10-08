"""Transfer interactive login sessions without letting collectors overwrite them."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .private_file import private_output_path


def login_profile(data_dir, platform):
    return Path(data_dir) / 'platform_login_profiles' / (platform or 'all')


def read_session(data_dir, platform):
    path = Path(data_dir) / 'platform_sessions' / 'interactive' / f'{platform}.json'
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def publish_session(cookies, data_dir, platform):
    from .browser_profile import platform_cookie, _platform_rows
    selected = [c for c in cookies if platform_cookie(c, platform)
                and (float(c.get('expires') or 0) <= 0 or float(c['expires']) > time.time())]
    # A blank/closed login window must not erase the last usable session.
    if platform != 'google' and not next(r for r in _platform_rows(selected) if r['id'] == platform)['cookie_present']:
        return
    if not selected:
        return
    selected.sort(key=lambda c: (c['domain'], c.get('path', '/'), c['name']))
    revision = hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()
    if read_session(data_dir, platform).get('revision') == revision:
        return
    target = Path(data_dir) / 'platform_sessions' / 'interactive' / f'{platform}.json'
    with private_output_path(target) as temp:
        temp.write_text(json.dumps({'revision': revision, 'cookies': selected}), encoding='utf-8')


def apply_sessions(context, data_dir, profile_dir, platforms):
    """Apply a newer login once per profile, retaining subsequent live refreshes."""
    from .browser_profile import platform_cookie
    marker = Path(profile_dir) / 'hotpost-login-revisions.json'
    try:
        applied = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        applied = {}
    changed = False
    for platform in platforms:
        saved = read_session(data_dir, platform)
        revision = saved.get('revision')
        if not revision or applied.get(platform) == revision:
            continue
        cookies = [c for c in saved.get('cookies', []) if platform_cookie(c, platform)
                   and (float(c.get('expires') or 0) <= 0 or float(c['expires']) > time.time())]
        if cookies:
            context.add_cookies(cookies)
            applied[platform] = revision
            changed = True
    if changed:
        with private_output_path(marker) as temp:
            temp.write_text(json.dumps(applied), encoding='utf-8')


def downloader_cookies(fallback, platform, out_dir):
    """Give each downloader a private copy; yt-dlp cannot mutate saved login data."""
    if fallback is None:
        return None
    from .browser_profile import export_cookies
    saved = read_session(Path(fallback).parent, platform)
    if not saved.get('cookies'):
        return fallback
    target = Path(out_dir) / f'.{platform}-session.cookies.txt'
    export_cookies(saved['cookies'], target)
    return target
