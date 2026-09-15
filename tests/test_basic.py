import time
from pathlib import Path

from hotpost.analyze import score_account, _terms
from hotpost.config import Settings
from hotpost.models import Post
from hotpost.sources import extract_username, load_usernames
from hotpost.source_finder import Candidate, PRODUCT_CONCEPTS, _dedupe, build_queries, dhash
from hotpost.browser_search import _embedded_candidates, _html_candidates, _is_candidate, _sample_frames
from hotpost.browser_profile import _platform_rows, export_cookies
from hotpost.text_overlay import classify_overlay
from hotpost.accounts import AccountRegistry
from hotpost.scheduler import launch_agent_config
from hotpost.transcript import _easyocr_text, collapse_screen_samples
from PIL import Image


def test_screen_ocr_merges_only_consecutive_matching_text():
    rows = collapse_screen_samples([(0, "제품 소개"), (1, "제품  소개"), (2, ""),
                                    (4, "가격 9,900원"), (5, "가격 9,900원")], 1, 6)
    assert len(rows) == 2
    assert rows[0] == {"source": "screen_text", "start": 0, "end": 2, "text": "제품 소개"}
    assert rows[1]["start"] == 4 and rows[1]["end"] == 6


def test_easyocr_keeps_caption_but_excludes_edge_watermark(tmp_path: Path):
    frame = tmp_path / "frame.jpg"
    Image.new("RGB", (720, 1280), "black").save(frame)
    class Reader:
        def readtext(self, _path, detail=1):
            return [([(0, 570), (600, 570), (600, 630), (0, 630)], "꺼내기도 불편했는데", .65),
                    ([(0, 1100), (200, 1100), (200, 1140), (0, 1140)], "tem doctor", .9)]
    assert _easyocr_text(frame, Reader()) == "꺼내기도 불편했는데"


def test_extract_username_variants():
    assert extract_username("https://www.instagram.com/salimpickle?stkn=MTdk") == "salimpickle"
    assert extract_username("https://www.instagram.com/Yiseo.Home/reels/") == "yiseo.home"
    assert extract_username("instagram.com/home_banjang_/") == "home_banjang_"
    assert extract_username("@reviewunnie | 메모") == "reviewunnie"
    assert extract_username("tem.doctor") == "tem.doctor"
    assert extract_username("# 주석") is None
    assert extract_username("https://www.instagram.com/p/ABC123/") is None
    assert extract_username("") is None


def test_load_usernames_dedupes(tmp_path: Path):
    f = tmp_path / "list.txt"
    f.write_text("@a\n\nhttps://instagram.com/a?x=1\nb\n#c\n", encoding="utf-8")
    assert load_usernames(f) == ["a", "b"]


def _posts(n=10, likes=100, comments=10, views=5000, username="u"):
    now = int(time.time())
    return [Post(shortcode=f"c{i}", username=username, taken_at=now - (i + 3) * 86400, kind="reel",
                 likes=likes, comments=comments, views=views) for i in range(n)]


def test_hot_post_detected():
    s = Settings()
    posts = _posts()
    posts[0].views, posts[0].comments, posts[0].likes = 25000, 40, 250
    scored = {x.post.shortcode: x for x in score_account(posts, s)}
    assert scored["c0"].tier >= 2
    assert "views_spike" in scored["c0"].flags
    assert scored["c5"].tier == 0
    assert 0.8 < scored["c5"].multiplier < 1.3


def test_low_engagement_is_not_hot():
    s = Settings()
    posts = _posts(likes=2, comments=1, views=30)
    posts[0].likes = 8
    assert all(x.tier == 0 for x in score_account(posts, s))


def test_terms_extract_nouns_and_bigrams():
    t = _terms("다이소 신상 주방 정리템 추천해요")
    assert "다이소" in t and "주방" in t
    assert any(" " in x for x in t)


def test_source_queries_include_product_intent():
    queries = build_queries("차량용품인데 차문에 달아 음료와 커피를 넣는 홀더")
    assert "car door hanging cup holder" in queries
    assert any("车门" in q for q in queries)


def test_youtube_dedupe_keeps_video_ids():
    items = [Candidate(url="https://www.youtube.com/watch?v=aaa", provider="youtube"),
             Candidate(url="https://www.youtube.com/watch?v=bbb", provider="youtube"),
             Candidate(url="https://www.youtube.com/watch?v=aaa&feature=share", provider="youtube")]
    assert [x.url for x in _dedupe(items)] == [items[0].url, items[1].url]


def test_dhash_is_stable_for_same_image(tmp_path: Path):
    image = Image.new("RGB", (120, 200), "white")
    for x in range(60):
        for y in range(200):
            image.putpixel((x, y), (20, 20, 20))
    left = tmp_path / "left.jpg"; copy = tmp_path / "copy.jpg"
    image.save(left); image.save(copy)
    assert dhash(left) == dhash(copy)


def test_browser_frame_sampling_handles_one():
    frames = [Path(f"{i}.jpg") for i in range(5)]
    assert _sample_frames(frames, 1) == [frames[2]]
    assert _sample_frames(frames, 3) == [frames[0], frames[2], frames[4]]


def test_browser_candidates_require_detail_urls():
    assert _is_candidate("https://www.tiktok.com/@creator/video/123")
    assert _is_candidate("https://www.douyin.com/video/123")
    assert not _is_candidate("https://www.tiktok.com/search/video?q=test")


def test_platform_cookie_status_is_domain_specific():
    rows = _platform_rows([
        {"domain": ".douyin.com", "name": "sessionid", "value": "ok"},
        {"domain": ".xiaohongshu.com", "name": "web_session", "value": "ok"},
    ])
    status = {row["id"]: row["connected"] for row in rows}
    assert status["douyin"] and status["xiaohongshu"]
    assert not status["tiktok"] and not status["youtube"]


def test_cookie_export_is_private_and_netscape_compatible(tmp_path: Path):
    target = tmp_path / "cookies.txt"
    export_cookies([{"domain": ".douyin.com", "name": "sessionid", "value": "secret", "path": "/",
                     "secure": True, "httpOnly": True, "expires": int(time.time()) + 3600}], target)
    text = target.read_text()
    assert "#HttpOnly_.douyin.com\tTRUE\t/\tTRUE" in text
    assert target.stat().st_mode & 0o777 == 0o600


def test_text_overlay_classification_prioritizes_clean_sources():
    clean, clean_score = classify_overlay(.1, 0, 0, .001)
    captioned, captioned_score = classify_overlay(.9, .75, .2, .025)
    assert clean == "clean-source"
    assert captioned == "edited-with-text"
    assert clean_score < captioned_score


def test_visual_product_catalog_has_english_chinese_pairs():
    assert len(PRODUCT_CONCEPTS) >= 30
    assert all(any("a" <= char.lower() <= "z" for char in english) for english, _ in PRODUCT_CONCEPTS)
    assert all(any("\u3400" <= char <= "\u9fff" for char in chinese) for _, chinese in PRODUCT_CONCEPTS)


def test_spa_embedded_video_ids_are_recovered():
    class Page:
        @staticmethod
        def content():
            return '<script>{"aweme_id":"7123456789012345678"}</script>'
    items = _embedded_candidates(Page(), "douyin", "杯架")
    assert items[0]["url"] == "https://www.douyin.com/video/7123456789012345678"
    xhs = _html_candidates('{"noteId":"0123456789abcdef01234567"}', "xiaohongshu", "收纳")
    assert xhs[0]["url"].endswith("/explore/0123456789abcdef01234567")


def test_account_registry_migrates_legacy_once_and_supports_crud(tmp_path: Path):
    legacy = tmp_path / "influencer_list.txt"
    legacy.write_text("@first | 주방\nhttps://instagram.com/second/\n", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", influencer_file=legacy)
    registry = AccountRegistry(settings)
    assert registry.usernames() == ["first", "second"]
    assert registry.list()[0]["note"] == "주방"

    item, created = registry.add("https://instagram.com/third/?x=1", "캠핑")
    assert created and item["username"] == "third" and item["note"] == "캠핑"
    _, created_again = registry.add("@third", "캠핑·여행")
    assert not created_again
    assert next(row for row in registry.list() if row["username"] == "third")["note"] == "캠핑·여행"

    assert registry.delete("first")
    assert not registry.delete("first")
    assert AccountRegistry(settings).usernames() == ["second", "third"]


def test_daily_launch_agent_runs_collection_at_seven(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    config = launch_agent_config(settings)
    assert config["StartCalendarInterval"] == {"Hour": 7, "Minute": 0}
    assert config["ProgramArguments"][-3:] == ["-m", "hotpost", "run"]
    assert config["StandardOutPath"].endswith("data/daily_collect.log")
