import json
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hotpost.analyze import score_account
from hotpost.config import Settings
from hotpost.criteria import defaults
from hotpost.models import Post, Profile
from hotpost.server import serve
from hotpost.storage import Storage


def test_historical_baseline_uses_only_older_thirty_and_lowers_mixed_confidence():
    now = int(time.time())
    settings = Settings(posts_per_account=50)
    posts = [Post(f"old{i}", "u", now - (i + 3) * 86400, "reel", 100, 10, 1000)
             for i in range(35)]
    posts += [Post("new", "u", now - 86400, "reel", 1000, 100, 10000)]
    scored = {s.post.shortcode: s for s in score_account(posts, settings, now=now)}
    assert scored["new"].baseline["peers"] == 30
    assert scored["new"].baseline["views"] == 1000
    assert scored["old0"].baseline["views"] == 1000
    assert scored["old34"].baseline["peers"] == 0

    mixed = [Post("target", "u", now - 86400, "reel", 100, 10, 1000)]
    mixed += [Post(f"photo{i}", "u", now - (i + 2) * 86400, "image", 100, 10)
              for i in range(5)]
    result = score_account(mixed, settings, now=now)[0]
    assert result.baseline["supplemented"]
    assert result.confidence == "low"


def test_missing_metrics_are_not_observed_zero():
    now = int(time.time())
    posts = [Post("new", "u", now - 86400, "reel", None, 10, None)]
    posts += [Post(f"old{i}", "u", now - (i + 2) * 86400, "reel", 100, 10, 1000)
              for i in range(5)]
    result = score_account(posts, Settings(), now=now)[0]
    assert result.ratios["views"] is None
    assert result.ratios["likes"] == 1


def test_criteria_api_reanalyzes_and_tracking_uses_same_tier(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", web_dir=tmp_path / "web",
                        influencer_file=tmp_path / "missing.txt", download_thumbs=False)
    settings.web_dir.mkdir()
    store = Storage(settings.db_path)
    now = int(time.time())
    store.upsert_profile(Profile("creator", followers=10000))
    posts = [Post(f"older{i}", "creator", now - (i + 2) * 86400,
                  "reel", 100, 10, 1000, media_id=f"m{i}") for i in range(6)]
    posts.append(Post("latest", "creator", now - 3600, "reel", 300, 30, 4000, media_id="latest-m"))
    store.upsert_posts(posts, collected_at=now)
    store.upsert_managed_account("creator")
    store.close()

    httpd = serve(settings, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    try:
        with urlopen(base + "/api/criteria") as response:
            active = json.load(response)
        assert active["version"] == 1
        invalid = defaults(settings)
        invalid["t1"] = 20
        request = Request(base + "/api/criteria", data=json.dumps({"values": invalid}).encode(),
                          headers={"Content-Type": "application/json"}, method="PUT")
        try:
            urlopen(request)
            assert False, "역순 기준은 거절되어야 합니다"
        except HTTPError as exc:
            assert exc.code == 400
        values = defaults(settings)
        values["t1"] = 10
        values["t2"] = 11
        values["t3"] = 12
        request = Request(base + "/api/criteria", data=json.dumps({"values": values}).encode(),
                          headers={"Content-Type": "application/json"}, method="PUT")
        with urlopen(request) as response:
            result = json.load(response)
        assert result["criteria"]["version"] == 2
        latest = next(p for p in result["report"]["posts"] if p["shortcode"] == "latest")
        assert latest["tier"] == 0
        assert result["report"]["criteria"]["values"] == values
        assert json.loads(settings.report_path.read_text(encoding="utf-8"))["criteria"]["version"] == 2
        assert "window.HOTPOST_REPORT" in (
            settings.web_dir / "data.js").read_text(encoding="utf-8")

        values["t1"], values["t2"], values["t3"] = 1.1, 2, 3
        request = Request(base + "/api/criteria", data=json.dumps({"values": values}).encode(),
                          headers={"Content-Type": "application/json"}, method="PUT")
        with urlopen(request) as response:
            result = json.load(response)
        latest = next(p for p in result["report"]["posts"] if p["shortcode"] == "latest")
        assert latest["tier"] >= 1
        check = Storage(settings.db_path)
        assert "latest" in [p.shortcode for p in check.tracked_hot_posts("creator", now=now)]
        assert check.criteria(settings)["version"] == 3
        check.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
