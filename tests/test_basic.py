import time
from pathlib import Path

from hotpost.analyze import score_account, _terms
from hotpost.config import Settings
from hotpost.models import Post
from hotpost.sources import extract_username, load_usernames


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
