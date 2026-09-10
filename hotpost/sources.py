"""influencer_list.txt 파서.

지원 형식 (한 줄에 하나, 빈 줄/`#` 주석 무시):
    https://www.instagram.com/username?stkn=...
    https://www.instagram.com/username/
    instagram.com/username/reels/
    @username
    username
    username | 메모나 별칭 (| 뒤는 무시)
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

_RESERVED = {"p", "reel", "reels", "explore", "stories", "accounts", "direct", "tv"}
_NAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def extract_username(line: str) -> str | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    line = line.split("|", 1)[0].strip()
    if line.startswith("@"):
        cand = line[1:]
    elif "instagram.com" in line:
        if not line.startswith("http"):
            line = "https://" + line
        path = urlparse(line).path
        parts = [p for p in path.split("/") if p]
        if not parts or parts[0] in _RESERVED:
            return None
        cand = parts[0]
    else:
        cand = line
    cand = cand.strip().lower()
    return cand if _NAME_RE.match(cand) else None


def load_usernames(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"인플루언서 목록 파일이 없습니다: {path}")
    seen: set[str] = set()
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        name = extract_username(raw)
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out
