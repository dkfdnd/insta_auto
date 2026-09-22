"""소스 후보 플랫폼 배분, 관련성 게이트, 재업로드 중복 판정."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def platform_of(provider: str, url: str) -> str:
    text = (provider + " " + urlparse(url).netloc).lower()
    for key, markers in {
        "tiktok": ("tiktok",), "douyin": ("douyin",),
        "xiaohongshu": ("xiaohongshu", "xhs"),
        "youtube_bilibili": ("youtube", "youtu.be", "bilibili"),
        "stock": ("pexels", "vimeo"),
    }.items():
        if any(marker in text for marker in markers):
            return key
    return "other"


def round_robin_candidates(items: list, limit: int) -> list:
    pools = defaultdict(deque)
    priority = {"visual-match": 0, "local-cache": 1,
                "platform-search": 2, "keyword": 3}
    for item in sorted(items, key=lambda row: priority.get(row.match_kind, 4)):
        pools[platform_of(item.provider, item.url)].append(item)
    order = ("tiktok", "douyin", "xiaohongshu", "youtube_bilibili", "stock", "other")
    result = []
    while len(result) < limit and any(pools.values()):
        for platform in order:
            if pools[platform] and len(result) < limit:
                result.append(pools[platform].popleft())
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def frame_duplicate(left: list[int], right: list[int]) -> bool:
    if not left or not right:
        return False
    matches = sum(min((a ^ b).bit_count() for b in right) <= 10 for a in left)
    return matches >= min(2, len(left))


def title_query_agreement(title: str, query: str) -> float:
    tokens = lambda value: set(re.findall(r"[가-힣]{2,}|[a-z]{3,}|[\u3400-\u9fff]{2,}", value.lower()))
    wanted = tokens(query)
    return len(tokens(title) & wanted) / len(wanted) if wanted else 0.0


def relevance_reasons(candidate, meta: dict) -> list[str]:
    reasons = []
    if meta.get("duration") is None or not 4 <= meta["duration"] <= 180:
        reasons.append("invalid_duration")
    if (meta.get("width") or 0) < 360 or (meta.get("height") or 0) < 640:
        reasons.append("low_resolution")
    if (meta.get("width") or 0) > 2 * (meta.get("height") or 0):
        reasons.append("not_crop_friendly")
    semantic, scene, combined = candidate.semantic_similarity, candidate.hash_similarity, candidate.similarity
    if semantic is not None:
        if semantic < .70 or (scene or 0) < .56 or (combined or 0) < .67:
            reasons.append("low_product_or_scene_similarity")
    elif (scene or 0) < .72:
        reasons.append("low_scene_similarity_without_clip")
    if (combined or 0) < .75 and candidate.match_kind in {"keyword", "platform-search"}:
        if title_query_agreement(candidate.title, candidate.query) == 0:
            reasons.append("title_query_mismatch")
    return reasons


def reuse_reasons(candidate) -> list[str]:
    if candidate.source_quality == "edited-with-text":
        return ["heavy_text_overlay"]
    return []


def select_valid_candidates(candidates: list, limit: int, embeddings: dict | None = None) -> list:
    embeddings = embeddings or {}
    selected = []
    for candidate in candidates:
        if not candidate.downloaded_file:
            candidate.rejection_reasons = candidate.rejection_reasons or ["not_probed"]
            continue
        if candidate.rejection_reasons:
            continue
        if len(selected) >= limit:
            candidate.rejection_reasons = ["valid_candidate_limit_reached"]
            continue
        duplicate = None
        for prior in selected:
            same_file = bool(candidate.file_sha256 and candidate.file_sha256 == prior.file_sha256)
            same_frames = frame_duplicate([int(value, 16) for value in candidate.frame_hashes or []],
                                          [int(value, 16) for value in prior.frame_hashes or []])
            left, right = embeddings.get(id(candidate)), embeddings.get(id(prior))
            same_clip = left is not None and right is not None and float((left @ right).item()) >= .98
            if same_file or same_frames or same_clip:
                duplicate = prior
                break
        if duplicate:
            candidate.rejection_reasons = [f"duplicate_of:{duplicate.original_url}"]
            continue
        candidate.selected_for_zip = True
        candidate.selection_reason = (
            "relevant_unique_overlay_unclassified"
            if candidate.source_quality == "unknown"
            else "relevant_reusable_unique"
        )
        selected.append(candidate)
    return selected
