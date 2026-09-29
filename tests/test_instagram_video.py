from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost import instagram_video as iv, source_finder as sf
from hotpost.collectors.base import CollectionBlocked


def test_candidates_exclude_recommended_posts():
    data = [{'code': 'other', 'video_versions': [{'url': 'wrong', 'width': 4000, 'height': 4000}]},
            {'nested': {'code': 'target', 'video_versions': [{'url': 'right', 'width': 720, 'height': 1280}]}},
            {'shortcode': 'target', 'video_url': 'legacy'}]
    assert list(iv.video_candidates(data, 'target')) == [(720 * 1280, 'right'), (0, 'legacy')]


def test_browser_resolves_exact_post_and_closes(monkeypatch):
    events = []
    page = SimpleNamespace(
        on=lambda *_: None,
        locator=lambda _: SimpleNamespace(all_text_contents=lambda: [
            '{"code":"other","video_url":"wrong"}',
            '{"code":"target","video_versions":[{"url":"small","width":10,"height":10},'
            '{"url":"large","width":100,"height":100}]}']),
    )
    browser = SimpleNamespace(page=page, open=lambda: None, navigate=lambda p: events.append(p),
                              verify_identity=lambda: events.append('verified'), guard=lambda: None,
                              close=lambda: events.append('closed'))
    monkeypatch.setattr(iv, 'InstagramBrowser', lambda _: browser)
    assert iv.browser_video_url(Settings(), 'target') == 'large'
    assert events == ['p/target/', 'verified', 'closed']


def test_browser_auth_failure_is_preserved_and_closed(monkeypatch):
    closed = []
    def blocked(_):
        raise CollectionBlocked('verification_required', 'verification required')
    browser = SimpleNamespace(page=SimpleNamespace(on=lambda *_: None), open=lambda: None,
                              navigate=blocked, close=lambda: closed.append(True))
    monkeypatch.setattr(iv, 'InstagramBrowser', lambda _: browser)
    with pytest.raises(CollectionBlocked, match='verification required'):
        iv.browser_video_url(Settings(), 'target')
    assert closed == [True]


def test_browser_download_needs_no_legacy_session_or_media_id(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, collection_source='browser')
    calls = []
    monkeypatch.setattr(iv, 'browser_video_url', lambda s, code: calls.append(code) or 'https://s.cdninstagram.com/video.mp4')
    response = SimpleNamespace(status_code=200, iter_content=lambda _: [b'video'], close=lambda: None)
    monkeypatch.setattr(sf.requests, 'get', lambda *a, **kw: response)
    target = tmp_path / 'video.mp4'
    assert sf._download_reference(settings, SimpleNamespace(shortcode='target'), target) == target
    assert target.read_bytes() == b'video'
    assert calls == ['target']


def test_transcript_video_reused_without_browser(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path)
    cached = settings.transcript_dir / 'target-old' / 'reference.mp4'
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b'cached-video')
    monkeypatch.setattr(sf, 'probe_video', lambda _: {'duration': 12, 'width': 720})
    monkeypatch.setattr(iv, 'browser_video_url', lambda *_: pytest.fail('cache must be used'))
    target = tmp_path / 'reference.mp4'
    sf._download_reference(settings, SimpleNamespace(shortcode='target'), target)
    assert target.read_bytes() == b'cached-video'


def test_browser_url_still_requires_instagram_cdn(tmp_path, monkeypatch):
    monkeypatch.setattr(iv, 'browser_video_url', lambda *_: 'https://other.example/video')
    monkeypatch.setattr(sf.requests, 'get', lambda *a, **kw: pytest.fail('must reject URL'))
    with pytest.raises(RuntimeError, match='CDN'):
        sf._download_reference(Settings(data_dir=tmp_path), SimpleNamespace(shortcode='target'), tmp_path / 'video.mp4')
