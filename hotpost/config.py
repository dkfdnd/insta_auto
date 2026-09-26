"""설정. 환경변수 또는 config.json 으로 덮어쓸 수 있다.

우선순위: 환경변수 > config.json > 기본값
"""
from __future__ import annotations

import json
import os
import sys
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
    auto_capcut_root: Path = ROOT.parent / "auto_capcut"
    auto_capcut_python: Path = ROOT.parent / "auto_capcut" / ".venv" / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    auto_capcut_timeout: int = 7200
    production_enabled: bool = False
    script_model: str = "gemini-3.6-flash"
    voicebench_root: Path = ROOT.parent / "VoiceBench"
    voicebench_url: str = "http://127.0.0.1:8877"
    voicebench_api_key_file: Path = ROOT.parent / "VoiceBench" / ".runtime" / "external-api-key.txt"
    voicebench_timeout: int = 14400
    voicebench_poll_interval: float = 5.0
    studio_url: str = "http://127.0.0.1:18765"
    studio_api_key_file: Path = ROOT.parent / "script_auto" / "data" / "access-token.txt"
    studio_timeout: int = 7200
    acquisition_min_views_per_follower: float = 1.8
    acquisition_min_views: int = 1000
    acquisition_daily_limit: int = 5

    @property
    def production_dir(self) -> Path:
        return self.data_dir / "productions"

    # 수집
    ig_user: str = ""                 # 로그인에 사용할 인스타 아이디 (세션 파일 이름)
    collection_source: str = "browser"  # 로그인과 동일한 영속 브라우저 사용
    collect_posts_per_account: int = 5  # 매 수집 때 Instagram에서 새로 확인할 최신 게시물 수
    collect_recovery_limit: int = 60   # 수집 공백을 따라갈 때 계정당 최대 게시물 수
    baseline_views_lookup_limit: int = 10  # 기준선의 누락 조회수 보강 요청 수
    recent_views_lookup_limit: int = 5  # 아직 핫이 아닌 최근 릴스도 순환 관측
    posts_per_account: int = 30       # DB에서 평소 성과 기준선 계산에 사용할 과거 게시물 수
    recent_days: int = 30             # 이 기간 밖의 게시물은 리포트에서 제외
    # 계정 사이에 일정하지 않은 간격을 두어 연속 요청과 오류 전파를 줄인다.
    # 기존 sleep_between_accounts는 하한으로 유지해 config.json/HOTPOST_* 호환성을 보존한다.
    sleep_between_accounts: float = 4.0
    sleep_between_accounts_max: float = 9.0
    sleep_after_error_min: float = 20.0
    sleep_after_error_max: float = 45.0
    views_lookup_limit: int = 5       # 계정당 조회수(media info)를 새로 조회할 릴스 수
    views_refresh_days: int = 14      # 이 일수보다 오래된 릴스는 이전 조회수 재사용
    hot_view_tracking_days: int = 14  # 터진 릴스는 게시일부터 이 기간까지 매일 조회수 추적
    hot_view_tracking_limit: int = 50 # 계정당 하루 최대 추적 릴스 수
    job_concurrency: int = 1         # 브라우저/OpenCLIP/Whisper 작업 기본 동시 실행 수
    cleanup_retention_days: int = 30 # 미보관 임시 파일 보관 기간
    cleanup_max_gb: float = 10.0     # 정리 판단용 최대 데이터 용량
    operational_log_max_mb: int = 10
    operational_log_backups: int = 3
    instagram_diagnostic_log_max_mb: int = 10
    download_thumbs: bool = True
    thumb_width: int = 640

    # 소스 영상 탐색 (선택 API 키는 환경변수 사용 권장)
    source_max_candidates: int = 40
    source_max_downloads: int = 20
    source_max_probe_downloads: int = 30  # 먼저 받아 검사한 뒤 상위 source_max_downloads만 ZIP에 포함
    source_max_attempts: int = 60      # 다운로드 실패 시 다음 후보로 보충하는 요청 상한
    source_probe_time_budget: int = 900  # 다운로드/검증 단계 시간 예산(초)
    source_queries_per_platform: int = 6
    source_candidates_per_platform: int = 12
    source_refine_max_candidates: int = 12  # 검증된 후보 제목으로 한 차례 추가 탐색
    source_match_mode: str = "product"  # product: 같은 제품의 대체영상 / scene: 같은 장면
    source_max_file_mb: int = 200
    source_google_vision_api_key: str = ""
    source_pexels_api_key: str = ""
    source_browser_search: bool = True
    source_browser_headless: bool = False
    source_browser_frames: int = 4
    source_browser_captcha_wait: int = 60
    source_use_openclip: bool = True
    source_openclip_model: str = "ViT-B-32-quickgelu"
    source_openclip_pretrained: str = "openai"
    source_detect_text_overlays: bool = True
    transcript_model: str = "mlx-community/whisper-small-mlx-8bit"
    transcript_faster_whisper_model: str = "small"
    transcript_ocr_fps: float = 1.0

    # 분석
    hot_multiplier: float = 1.8       # 이 배수 이상이면 '터진 게시물'
    tier2_multiplier: float = 3.0
    tier3_multiplier: float = 5.0
    maturity_hours: float = 72.0      # 게시 후 이 시간까지는 반응이 덜 쌓였다고 보정
    min_peers_for_baseline: int = 4   # baseline 계산에 필요한 최소 비교 게시물 수
    min_engagement: int = 20          # 좋아요+댓글*5 가 이 값 미만이면 노이즈로 간주
    confirmation_min_peers: int = 8
    metric_freshness_hours: int = 30

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

    @property
    def source_dir(self) -> Path:
        return self.data_dir / "source_jobs"

    @property
    def transcript_dir(self) -> Path:
        return self.data_dir / "transcripts"

    @property
    def editing_dir(self) -> Path:
        return self.data_dir / "editing_jobs"

    @property
    def source_browser_profile_dir(self) -> Path:
        return self.data_dir / "source_browser_profile"

    @property
    def source_browser_cookie_file(self) -> Path:
        """Playwright와 yt-dlp 사이에서만 공유하는 Netscape 쿠키 파일."""
        return self.data_dir / "source_browser_cookies.txt"

    @property
    def source_model_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def source_tessdata_dir(self) -> Path:
        return self.source_model_dir / "tessdata"

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
    s.source_dir.mkdir(parents=True, exist_ok=True)
    s.transcript_dir.mkdir(parents=True, exist_ok=True)
    s.editing_dir.mkdir(parents=True, exist_ok=True)
    s.source_browser_profile_dir.mkdir(parents=True, exist_ok=True)
    s.source_model_dir.mkdir(parents=True, exist_ok=True)
    s.source_tessdata_dir.mkdir(parents=True, exist_ok=True)
    return s
