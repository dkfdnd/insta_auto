"""검색 공급자에 관계없이 영상 상세 URL만 다운로드 예산을 사용한다."""
import re
import base64
from urllib.parse import urlparse, parse_qs

LAZADA_DOMAINS = {'lazada.com.ph', 'lazada.com.my', 'lazada.sg', 'lazada.co.th', 'lazada.co.id', 'lazada.vn'}


def unwrap_bing_video_url(url: str) -> str:
    """Decode Bing's observed search link without visiting its redirect."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or '').lower()
        if (parsed.scheme not in ('http', 'https') or parsed.username or parsed.password
                or not (host == 'bing.com' or host.endswith('.bing.com'))
                or parsed.path.rstrip('/') != '/ck/a'):
            return url
        values = parse_qs(parsed.query).get('u', [])
        if len(values) != 1 or not values[0].startswith('a1'):
            return url
        encoded = values[0][2:]
        target = base64.b64decode(encoded + '=' * (-len(encoded) % 4),
                                  altchars=b'-_', validate=True).decode('utf-8')
        # The caller downloads only supported public video detail URLs. Never
        # turn a redirect parameter into an arbitrary fetch or browser visit.
        return target if video_url(target) else url
    except (ValueError, UnicodeError):
        return url


def lazada_video_id(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if (parsed.scheme != 'https' or parsed.username or parsed.password
            or host.removeprefix('www.') not in LAZADA_DOMAINS
            or parsed.path.rstrip('/') != '/videodetail'):
        return ''
    values = parse_qs(parsed.query).get('video_id', [])
    return values[0] if len(values) == 1 and re.fullmatch(r'\d+', values[0]) else ''


def video_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host, path = (parsed.hostname or '').lower(), parsed.path
        if parsed.scheme not in ('https', 'http') or parsed.username or parsed.password:
            return False
        def domain(name):
            return host == name or host.endswith('.' + name)
        if domain('tiktok.com'):
            return bool(re.fullmatch(r'/@[^/]+/video/\d+/?', path))
        if domain('douyin.com'):
            return bool(re.fullmatch(r'/video/\d+/?', path))
        if domain('xiaohongshu.com'):
            return bool(re.fullmatch(r'/(?:explore|discovery/item)/[0-9a-fA-F]{24}/?', path))
        if domain('youtube.com'):
            return (path == '/watch' and bool(parse_qs(parsed.query).get('v', [''])[0])) or bool(re.fullmatch(r'/shorts/[\w-]+/?', path))
        if domain('youtu.be'):
            return bool(re.fullmatch(r'/[\w-]+/?', path))
        if domain('bilibili.com'):
            return bool(re.fullmatch(r'/video/(?:BV[0-9A-Za-z]+|av\d+)/?', path))
        if domain('vimeo.com'):
            return bool(re.fullmatch(r'/(?:video/)?\d+/?', path))
        if domain('pexels.com'):
            return path.lower().endswith('.mp4')
        if lazada_video_id(url):
            return True
    except ValueError:
        pass
    return False


def canonical_video_key(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if lazada_video_id(url):
        return host.removeprefix('www.') + '/videodetail/' + lazada_video_id(url)
    if host == 'youtu.be' or host.endswith('.youtu.be'):
        return 'youtube:' + parsed.path.strip('/')
    if host == 'youtube.com' or host.endswith('.youtube.com'):
        return 'youtube:' + (parse_qs(parsed.query).get('v', [''])[0] if parsed.path == '/watch'
                             else parsed.path.strip('/').split('/')[-1])
    return host.removeprefix('www.') + parsed.path.rstrip('/')
