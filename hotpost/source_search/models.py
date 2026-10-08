"""Source candidate metadata shared by providers and quality checks."""
from __future__ import annotations
from dataclasses import dataclass
from ..source_quality import platform_of

@dataclass
class Candidate:
    url: str
    provider: str
    original_url: str = ""
    title: str = ""
    uploader: str = ""
    query: str = ""
    match_kind: str = "keyword"
    rights: str = "unknown-check-before-reuse"
    downloaded_file: str = ""
    preview_file: str = ""
    hash_similarity: float | None = None
    semantic_similarity: float | None = None
    similarity: float | None = None
    match_quality: str = "unverified"
    source_quality: str = "unknown"
    text_overlay_score: float | None = None
    text_frame_ratio: float | None = None
    caption_frame_ratio: float | None = None
    watermark_frame_ratio: float | None = None
    ocr_languages: list[str] | None = None
    ocr_unreadable_frame_ratio: float | None = None
    source_score: float | None = None
    platform: str = "other"
    video_meta: dict | None = None
    file_sha256: str = ""
    frame_hashes: list[str] | None = None
    selection_reason: str = ""
    rejection_reasons: list[str] | None = None
    selected_for_zip: bool = False
    error: str = ""
    download_attempted: bool | None = None
    original_downloaded_file: str = ""
    source_interval: dict | None = None
    functional_review: dict | None = None
    blur_required: bool = False
    watermark_masks: list[dict] | None = None
    discovery_meta: dict | None = None
    discovery_score: float | None = None
    discovery_reasons: list[str] | None = None
    download_budget_seconds: float | None = None
    cached_path: str = ""
    acquisition: str = ""
    reused_from: str = ""

    def __post_init__(self) -> None:
        self.original_url = self.original_url or self.url
        self.platform = platform_of(self.provider, self.url)
