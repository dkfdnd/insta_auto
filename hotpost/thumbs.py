"""썸네일 다운로드/생성. Instagram CDN URL 은 만료되므로 로컬(web/thumbs)에 저장한다."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import requests

from .config import Settings
from .models import Post

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"


def thumb_path(settings: Settings, shortcode: str) -> Path:
    return settings.thumbs_dir / f"{shortcode}.jpg"


def ensure_thumbnail(settings: Settings, post: Post, session: requests.Session | None = None) -> str | None:
    """썸네일을 준비하고 web/ 기준 상대경로를 돌려준다. 실패하면 None."""
    out = thumb_path(settings, post.shortcode)
    rel = f"thumbs/{post.shortcode}.jpg"
    if out.exists() and out.stat().st_size > 0:
        return rel
    if not settings.download_thumbs:
        return None
    if not post.thumbnail_url:
        if post.shortcode.startswith("DEMO"):
            _make_placeholder(out, post, settings.thumb_width)
            return rel
        return None
    try:
        from PIL import Image
        s = session or requests.Session()
        r = s.get(post.thumbnail_url, headers={"User-Agent": _UA, "Referer": "https://www.instagram.com/"}, timeout=20)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        w = settings.thumb_width
        if img.width > w:
            img = img.resize((w, int(img.height * w / img.width)))
        img.save(out, "JPEG", quality=82, optimize=True)
        return rel
    except Exception:  # noqa: BLE001
        return None


def _make_placeholder(out: Path, post: Post, width: int) -> None:
    from PIL import Image, ImageDraw
    h = int(width * (16 / 9) if post.is_video else width)
    seed = int(hashlib.md5(post.shortcode.encode()).hexdigest(), 16)
    c1 = ((seed >> 0) % 120 + 90, (seed >> 8) % 120 + 90, (seed >> 16) % 120 + 90)
    c2 = ((seed >> 4) % 100 + 40, (seed >> 12) % 100 + 40, (seed >> 20) % 100 + 40)
    img = Image.new("RGB", (width, h))
    px = img.load()
    for y in range(h):
        f = y / h
        col = tuple(int(c1[i] * (1 - f) + c2[i] * f) for i in range(3))
        for x in range(width):
            px[x, y] = col
    d = ImageDraw.Draw(img)
    label = "SAMPLE"
    d.text((width // 2 - 30, h // 2 - 8), label, fill=(255, 255, 255))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=70)
