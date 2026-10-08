"""소스 후보 플랫폼 배분, 관련성 게이트, 재업로드 중복 판정."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def subject_frame_indices(subject_scores: list[float], background_scores: list[float]) -> list[int]:
    """Require several positively identified subject frames before refocusing.

    Passport test: product frames scored .26–.34; airport introduction .17–.18.
    A single incidental product-like frame is insufficient evidence.
    """
    ranked = sorted((i for i, (s, b) in enumerate(zip(subject_scores, background_scores))
                     if s >= .24 and s - b >= .015),
                    key=lambda i: subject_scores[i] - background_scores[i], reverse=True)[:6]
    return ranked if len(ranked) >= 3 else []


def platform_of(provider: str, url: str) -> str:
    text = (provider + " " + urlparse(url).netloc).lower()
    for key, markers in {
        "tiktok": ("tiktok",), "douyin": ("douyin",),
        "xiaohongshu": ("xiaohongshu", "xhs"),
        "youtube": ("youtube", "youtu.be"), "bilibili": ("bilibili",),
        "stock": ("pexels", "vimeo"),
    }.items():
        if any(marker in text for marker in markers):
            return key
    return "other"


def round_robin_candidates(items: list, limit: int) -> list:
    pools = defaultdict(deque)
    priority = {"visual-match": 0, "local-cache": 1, "cached-candidate": 1,
                "operator-shortlist": 1, "platform-search": 2, "keyword": 3}
    for item in sorted(items, key=lambda row: (-(getattr(row,'discovery_score',None) or 0), priority.get(row.match_kind,4))):
        pools[platform_of(item.provider, item.url)].append(item)
    order = ("tiktok", "douyin", "xiaohongshu", "youtube", "bilibili", "stock", "other")
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


def media_format_reasons(meta: dict, max_duration: float = 180) -> list[str]:
    reasons = []
    if meta.get("duration") is None or not 4 <= meta["duration"] <= max_duration:
        reasons.append("invalid_duration")
    if (meta.get("width") or 0) < 360 or (meta.get("height") or 0) < 640:
        reasons.append("low_resolution")
    if (meta.get("width") or 0) > 2 * (meta.get("height") or 0):
        reasons.append("not_crop_friendly")
    return reasons


def relevance_reasons(candidate, meta: dict, mode: str = 'scene') -> list[str]:
    reasons = media_format_reasons(meta)
    semantic, scene, combined = candidate.semantic_similarity, candidate.hash_similarity, candidate.similarity
    review = getattr(candidate, 'functional_review', None) or {}
    # A cooking context clip is useful footage without being proof of the
    # reference action. Keep its restricted role and exact reviewed file.
    if (mode == 'functional' and review.get('reviewed') is True
            and review.get('same_core_function') is False and review.get('context_usable') is True
            and review.get('context_usage_limits') and review.get('observed_actions')
            and review.get('evidence_frames') and candidate.file_sha256
            and review.get('source_sha256') == candidate.file_sha256):
        return reasons
    if mode == 'functional' and review.get('reviewed') is True and review.get('same_core_function') is False:
        return [*reasons, 'different_core_function']
    # A reviewed demonstration can establish the same function despite color,
    # silhouette and camera changes. Category/title similarity alone cannot.
    if (mode == 'functional' and review.get('reviewed') is True
            and review.get('same_core_function') is True
            and review.get('observed_actions') and review.get('evidence_frames')
            and candidate.file_sha256
            and review.get('source_sha256') == candidate.file_sha256):
        return reasons
    # 같은 제품을 다른 구도로 촬영한 대체영상은 장면 지문이 달라도 의미 근거로 보존한다.
    if mode in {'product', 'functional'} and semantic is not None and semantic >= .82:
        return reasons
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
    if (candidate.source_quality == "edited-with-text"
            or (getattr(candidate, 'watermark_frame_ratio', 0) or 0)>0
            or (getattr(candidate, 'caption_frame_ratio', 0) or 0)>0):
        # Retain the original source for masking; never relabel it as clean.
        candidate.blur_required = True
    return []


def editing_ready(item: dict) -> bool:
    if not item.get('editing_eligible', True):
        return False
    if item.get('blur_required') or item.get('source_quality') == 'edited-with-text':
        masks = item.get('watermark_masks')
        return bool(isinstance(masks, list) and masks
                    and all(isinstance(m, dict) and m.get('reviewed') is True for m in masks))
    return item.get('source_quality') in {'clean-source', 'light-overlay'}


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
            if same_file or same_frames:
                duplicate = prior
                break
        if duplicate:
            candidate.rejection_reasons = [f"duplicate_of:{duplicate.original_url}"]
            continue
        candidate.selected_for_zip = True
        candidate.selection_reason = (
            "reviewed_context_only_requires_capcut_blur" if getattr(candidate, 'blur_required', False)
            and (getattr(candidate, 'functional_review', None) or {}).get('same_core_function') is False
            and (candidate.functional_review or {}).get('context_usable') is True else
            "reviewed_context_only" if (getattr(candidate, 'functional_review', None) or {}).get('same_core_function') is False
            and (candidate.functional_review or {}).get('context_usable') is True else
            "relevant_unique_requires_capcut_blur" if getattr(candidate, 'blur_required', False) else
            "relevant_unique_overlay_unclassified"
            if candidate.source_quality == "unknown"
            else "relevant_reusable_unique"
        )
        selected.append(candidate)
    return selected
