from hotpost.source_finder import Candidate, build_grounded_queries
from hotpost.source_quality import (platform_of, round_robin_candidates, relevance_reasons,
                                    reuse_reasons, select_valid_candidates, frame_duplicate)


def _candidate(url, provider, similarity=.8, semantic=.85, scene=.7, quality="clean-source"):
    c = Candidate(url, provider, title="car door cup holder demonstration", query="car door cup holder")
    c.downloaded_file = "video.mp4"
    c.similarity, c.semantic_similarity, c.hash_similarity = similarity, semantic, scene
    c.source_quality = quality
    c.file_sha256 = url
    c.frame_hashes = [f"{123:064x}", f"{456:064x}"]
    return c


def test_platform_round_robin_prevents_one_pool_from_filling_forty():
    items = [_candidate(f"https://tiktok.com/@u/video/{i}", "tiktok") for i in range(20)]
    items += [_candidate(f"https://youtube.com/watch?v={i}", "youtube") for i in range(3)]
    items += [_candidate(f"https://douyin.com/video/{i}", "douyin") for i in range(2)]
    mixed = round_robin_candidates(items, 10)
    assert [platform_of(x.provider, x.url) for x in mixed[:3]] == ["tiktok", "douyin", "youtube_bilibili"]
    assert len(mixed) == 10


def test_platform_round_robin_prioritizes_visual_matches():
    keyword = _candidate("https://tiktok.com/@u/video/1", "tiktok")
    keyword.match_kind = "keyword"
    visual = _candidate("https://tiktok.com/@u/video/2", "google-lens")
    visual.match_kind = "visual-match"
    assert round_robin_candidates([keyword, visual], 2)[0] is visual


def test_relevance_gate_and_reuse_gate_do_not_fill_to_twenty():
    meta = {"duration": 25, "width": 720, "height": 1280}
    clean = _candidate("https://youtube.com/watch?v=good", "youtube")
    unrelated = _candidate("https://youtube.com/watch?v=wrong", "youtube", .6, .5, .52)
    captions = _candidate("https://tiktok.com/@u/video/3", "tiktok", quality="edited-with-text")
    landscape = _candidate("https://youtube.com/watch?v=wide", "youtube")
    for candidate, details in [(clean, meta), (unrelated, meta), (captions, meta),
                                (landscape, {"duration": 25, "width": 1920, "height": 640})]:
        candidate.rejection_reasons = relevance_reasons(candidate, details) + reuse_reasons(candidate)
    selected = select_valid_candidates([clean, unrelated, captions, landscape], 20)
    assert selected == [clean]
    assert clean.selection_reason == "relevant_reusable_unique"
    assert "low_product_or_scene_similarity" in unrelated.rejection_reasons
    assert "heavy_text_overlay" in captions.rejection_reasons
    assert "not_crop_friendly" in landscape.rejection_reasons


def test_unknown_overlay_is_kept_for_manual_review():
    candidate = _candidate("https://youtube.com/watch?v=unknown", "youtube",
                           quality="unknown")
    candidate.rejection_reasons = reuse_reasons(candidate)
    assert select_valid_candidates([candidate], 1) == [candidate]
    assert candidate.selection_reason == "relevant_unique_overlay_unclassified"


def test_cross_platform_reupload_removed_by_file_and_multiple_frames():
    first = _candidate("https://tiktok.com/@u/video/1", "tiktok")
    file_copy = _candidate("https://youtube.com/watch?v=copy", "youtube")
    file_copy.file_sha256 = first.file_sha256
    frame_copy = _candidate("https://douyin.com/video/2", "douyin")
    frame_copy.file_sha256 = "different-file"
    assert frame_duplicate([int(v, 16) for v in first.frame_hashes],
                           [int(v, 16) for v in frame_copy.frame_hashes])
    selected = select_valid_candidates([first, file_copy, frame_copy], 20)
    assert selected == [first]
    assert all(c.rejection_reasons[0].startswith("duplicate_of:") for c in (file_copy, frame_copy))
    assert file_copy.original_url in {c.original_url for c in (file_copy, frame_copy)}


def test_queries_require_two_sources_and_strip_generic_visual_words():
    details = build_grounded_queries("차문에 컵홀더를 달았어요", [], ["Text in image", "Person", "컵홀더"],
                                     {"speech": "컵홀더 사용", "screen_text": ""})
    assert any(item["query"] == "cup holder" and item["confidence"] == "high"
               and "speech" in item["sources"] for item in details)
    assert not any(item["query"].lower() in {"text in image", "person", "car"} for item in details)
