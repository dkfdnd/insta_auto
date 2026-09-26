"""검색 공급자에 관계없이 영상 상세 URL만 다운로드 예산을 사용한다."""
import re
from urllib.parse import urlparse, parse_qs


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
    except ValueError:
        pass
    return False


def canonical_video_key(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if host == 'youtu.be' or host.endswith('.youtu.be'):
        return 'youtube:' + parsed.path.strip('/')
    if host == 'youtube.com' or host.endswith('.youtube.com'):
        return 'youtube:' + (parse_qs(parsed.query).get('v', [''])[0] if parsed.path == '/watch'
                             else parsed.path.strip('/').split('/')[-1])
    return host.removeprefix('www.') + parsed.path.rstrip('/')
