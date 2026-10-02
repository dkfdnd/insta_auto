from types import SimpleNamespace

from hotpost import browser_search as bs
from hotpost.config import Settings


def test_pacing_announces_and_waits_before_each_search(tmp_path, monkeypatch):
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    messages, waits = [], []
    searcher.progress = messages.append
    monkeypatch.setattr(bs.time, 'sleep', waits.append)
    searcher._pace('Google Lens')
    searcher._pace('Google Lens')
    assert waits == [15, 15]
    assert all('15초 대기' in m for m in messages)


def test_captcha_cooldown_survives_worker_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path, source_browser_headless=True), tmp_path)
    page = SimpleNamespace(url='https://www.google.com/sorry/index')
    audit = {}
    messages = []
    searcher.progress = messages.append
    assert searcher._check_block(page, 'google-lens', audit)
    assert audit['status'] == 'captcha'
    assert any('CAPTCHA 인증 대기' in m for m in messages)
    bs.BROWSER_COOLDOWNS.clear()
    later = bs.BrowserSearcher(searcher.settings, tmp_path)
    # A blocked service must not even open a search tab.
    later._google(None, [], 10)
    assert later.searches[0]['status'] == 'cooldown'
    assert not later._cooling_down('yandex-images')


def test_captcha_on_same_url_does_not_masquerade_as_results(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path, source_browser_captcha_wait=0), tmp_path)
    page = SimpleNamespace(url='https://lens.google.com/search',
                           locator=lambda _: SimpleNamespace(inner_text=lambda: 'Unusual traffic'))
    audit = {}
    assert searcher._check_block(page, 'google-lens', audit)
    assert audit['status'] == 'captcha'


def test_tiktok_slider_challenge_stops_search_even_on_http_200(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path, source_browser_headless=True), tmp_path)
    page = SimpleNamespace(url='https://www.tiktok.com/search/video?q=camping',
                           locator=lambda _: SimpleNamespace(inner_text=lambda: 'Top Users Videos LIVE Drag the slider to fit the puzzle'))
    audit = {'http_status': 200}
    assert searcher._check_block(page, 'tiktok', audit)
    assert audit['status'] == 'captcha'
    assert searcher._cooling_down('tiktok')


def test_user_solved_captcha_continues_without_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    page = SimpleNamespace(url='https://www.google.com/sorry/index',
                           locator=lambda _: SimpleNamespace(inner_text=lambda: 'results'))
    page.wait_for_timeout = lambda _: setattr(page, 'url', 'https://lens.google.com/search')
    assert not searcher._check_block(page, 'google-lens', {})
    assert not searcher._cooling_down('google-lens')


def test_429_does_not_wait_or_retry_and_cooldown_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, 'BROWSER_COOLDOWNS', {})
    monkeypatch.setattr(bs.time, 'time', lambda: 100)
    searcher = bs.BrowserSearcher(Settings(data_dir=tmp_path), tmp_path)
    audit = {}
    assert searcher._check_block(None, 'tiktok', audit, SimpleNamespace(status=429))
    assert audit['status'] == 'rate_limited'
    assert bs.BROWSER_COOLDOWNS['tiktok'] == 1900
    monkeypatch.setattr(bs.time, 'time', lambda: 1901)
    assert not searcher._cooling_down('tiktok')
