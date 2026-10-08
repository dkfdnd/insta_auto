"""Persistent access failures; elapsed time is not proof of completed authentication."""
import json
import time
from pathlib import Path

MANUAL_REASONS={'captcha','login_required'}
PROVIDERS={'google':'google-lens','tiktok':'tiktok','douyin':'douyin','xiaohongshu':'xiaohongshu'}


def access_record(data_dir,provider):
    try:
        value=json.loads((Path(data_dir)/'search_cooldowns'/f'{provider}.json').read_text(encoding='utf-8'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}


def manual_required(record):
    # Also honor older CAPTCHA receipts whose fixed timer already expired.
    return record.get('reason') in MANUAL_REASONS and record.get('requires_verification',True)


def indexed_gate(provider, response=None, settings=None):
    """Stop indexed searches on a real challenge, retaining no response body."""
    if settings is None:
        from .config import load_settings
        settings = load_settings()
    record = access_record(settings.data_dir, provider)
    if response is None:
        if manual_required(record):
            return {'status':'verification_required', 'reason':record['reason']}
        if record.get('until', 0) > time.time():
            return {'status':'cooldown', 'reason':record.get('reason', '')}
        return {}
    import re
    raw = response.text.lower()
    visible = re.sub(r'<(?:script|style)\b[^>]*>.*?</(?:script|style)>', '', raw, flags=re.S)
    visible = re.sub(r'<[^>]+>', ' ', visible)
    challenge = ('/captcha' in response.url.lower() or '/sorry/' in response.url.lower()
                 or bool(re.search(r'<form\b[^>]*\bid=[\"\']challenge-form[\"\']', raw))
                 or any(token in visible for token in
                        ('bots use duckduckgo', 'verify you are human', 'confirm you are not a robot',
                         'unusual traffic', '로봇이 아닙니다', '비정상적인 트래픽')))
    reason = 'captcha' if challenge else 'rate_limited' if response.status_code == 429 else ''
    if not reason:
        return {}
    from .editing_adapter import _atomic_json
    _atomic_json(settings.data_dir/'search_cooldowns'/f'{provider}.json',
                 {'provider':provider, 'reason':reason, 'at':time.time(),
                  'requires_verification':challenge, 'http_status':response.status_code,
                  'until':0 if challenge else time.time()+300})
    return {'status':reason, 'reason':reason, 'http_status':response.status_code}


def request_manual_recheck(data_dir,provider):
    """Only the explicit session-save action can authorize one new search check.

    This records a user-requested recheck, not a claim that CAPTCHA is solved.
    Any challenge on that next check closes the gate again.
    """
    from .editing_adapter import _atomic_json
    from .source_search.readiness import request_readiness_recheck
    readiness_recheck = request_readiness_recheck(data_dir,provider)
    record=access_record(data_dir,provider)
    if not manual_required(record):return readiness_recheck
    record.update(requires_verification=False,until=0,manual_recheck_at=time.time())
    _atomic_json(Path(data_dir)/'search_cooldowns'/f'{provider}.json',record)
    return True


def challenge_in_text(text):
    """Recognize a captured visible body, never unexecuted HTML/script text."""
    body=str(text).lower()
    return any(token in body for token in ('unusual traffic','verify you are human','confirm you are not a robot',
        '로봇이 아닙니다','비정상적인 트래픽','drag the slider','fit the puzzle','slide to verify',
        '拖动滑块','拖動滑塊','滑动验证','滑動驗證','请完成下方验证','请完成安全验证',
        '슬라이더를 끌어','슬라이더를 드래그','퍼즐을 맞춰','퍼즐을 맞추'))


def challenge_on_page(page):
    if any(token in page.url.lower() for token in ('/sorry/','/showcaptcha','/captcha')):return True
    return challenge_in_text(page.locator('body').inner_text())


def login_wall_on_page(page,provider):
    body=page.locator('body').inner_text().lower()
    patterns={'douyin':('登录后即可搜索','登录后查看搜索结果','请登录后搜索'),
              'xiaohongshu':('登录后查看搜索结果','登录后探索更多','登录后搜索'),
              'tiktok':('log in to search','log in to see search results','로그인하여 검색')}
    # A normal header's login button, or the name of an SMS login method,
    # does not by itself indicate either a challenge or a search access wall.
    return any(token in body for token in patterns.get(provider,()))


def empty_results_on_page(page):
    body=page.locator('body').inner_text().lower()
    return any(token in body for token in ('no results found','no search results','검색 결과가 없습니다',
        '검색 결과 없음','暂无搜索结果','没有找到相关','未找到相关','暂无相关结果'))
