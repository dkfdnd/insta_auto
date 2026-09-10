"""설정. 환경변수 또는 config.json 으로 덮어쓸 수 있다.

우선순위: 환경변수 > config.json > 기본값
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    # 입력
    influencer_file: Path = ROOT / "influencer_list.txt"

    # 저장 위치
    data_dir: Path = ROOT / "data"
    web_dir: Path = ROOT / "web"

    # 수집
    ig_user: str = ""                 # 로그인에 사용할 인스타 아이디 (세션 파일 이름)
    posts_per_account: int = 30       # 계정당 가져올 최근 게시물 수 (baseline 계산용)
    recent_days: int = 30             # 이 기간 밖의 게시물은 리포트에서 제외
    sleep_between_accounts: float = 3.0
    views_lookup_limit: int = 20      # 계정당 조회수(media info)를 새로 조회할 릴스 수
    views_refresh_days: int = 14      # 이 일수보다 오래된 릴스는 이전 조회수 재사용
    download_thumbs: bool = True
    thumb_width: int = 640

    # 분석
    hot_multiplier: float = 1.8       # 이 배수 이상이면 '터진 게시물'
    tier2_multiplier: float = 3.0
    tier3_multiplier: float = 5.0
    maturity_hours: float = 72.0      # 게시 후 이 시간까지는 반응이 덜 쌓였다고 보정
    min_peers_for_baseline: int = 4   # baseline 계산에 필요한 최소 비교 게시물 수
    min_engagement: int = 20          # 좋아요+댓글*5 가 이 값 미만이면 노이즈로 간주

    # 결과
    top_topics: int = 24

    @property
    def db_path(self) -> Path:
        return self.data_dir / "hotpost.db"

    @property
    def report_path(self) -> Path:
        return self.data_dir / "report.json"

    @property
    def thumbs_dir(self) -> Path:
        return self.web_dir / "thumbs"

    @property
    def session_dir(self) -> Path:
        return self.data_dir / "sessions"

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: (str(v) if isinstance(v, Path) else v) for k, v in d.items()}


def load_settings() -> Settings:
    s = Settings()
    cfg = ROOT / "config.json"
    if cfg.exists():
        with cfg.open(encoding="utf-8") as f:
            raw = json.load(f)
        for k, v in raw.items():
            if hasattr(s, k):
                cur = getattr(s, k)
                setattr(s, k, Path(v) if isinstance(cur, Path) else type(cur)(v))
    for k in list(vars(s)):
        env = os.environ.get("HOTPOST_" + k.upper())
        if env is None and k == "ig_user":
            env = os.environ.get("IG_USER")
        if env is not None:
            cur = getattr(s, k)
            if isinstance(cur, bool):
                setattr(s, k, env.lower() in ("1", "true", "yes"))
            elif isinstance(cur, Path):
                setattr(s, k, Path(env))
            else:
                setattr(s, k, type(cur)(env))
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.thumbs_dir.mkdir(parents=True, exist_ok=True)
    s.session_dir.mkdir(parents=True, exist_ok=True)
    return s
