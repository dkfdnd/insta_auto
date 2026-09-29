from types import SimpleNamespace

import requests

from hotpost import request_pacing as pacing
from hotpost.config import Settings


def test_pause_always_waits_one_to_three_seconds(monkeypatch):
    sleeps = []
    def uniform(low, high):
        assert (low, high) == (1.0, 3.0)
        return 2.2
    monkeypatch.setattr(pacing.random, 'uniform', uniform)
    monkeypatch.setattr(pacing.time, 'sleep', sleeps.append)
    pacing.request_pause()
    pacing.request_pause()
    assert sleeps == [2.2, 2.2]


def test_paced_session_waits_before_every_send(monkeypatch):
    events = []
    monkeypatch.setattr(pacing, 'request_pause', lambda: events.append('wait'))
    monkeypatch.setattr(requests.Session, 'send', lambda *a, **k: events.append('send'))
    s = pacing.PacedSession()
    s.send('first'); s.send('second')
    assert events == ['wait', 'send', 'wait', 'send']


def test_legacy_instagram_keeps_library_limiter(monkeypatch):
    from hotpost.collectors import instaloader_collector as ic
    events = []
    monkeypatch.setattr(ic.instaloader.RateController, 'wait_before_query', lambda *a: events.append('library'))
    monkeypatch.setattr(ic, 'request_pause', lambda: events.append('pause'))
    loader = ic.make_loader()
    loader.context._rate_controller.wait_before_query('test')
    assert events == ['library', 'pause']


def test_zero_browser_interval_still_waits_one_second(tmp_path, monkeypatch):
    from hotpost.browser_search import BrowserSearcher
    waits = []
    monkeypatch.setattr(pacing.time, 'sleep', waits.append)
    BrowserSearcher(Settings(data_dir=tmp_path, source_browser_search_interval=0), tmp_path)._pace('test')
    assert waits == [1]


def test_youtube_queries_pace_each_command(tmp_path, monkeypatch):
    from hotpost import source_finder as sf
    events, commands = [], []
    monkeypatch.setattr(sf, '_executable', lambda _: 'yt-dlp')
    monkeypatch.setattr(sf, 'request_pause', lambda: events.append('pause'))
    def run(command, **kwargs):
        events.append('request'); commands.append(command)
        return SimpleNamespace(returncode=0, stdout='{"entries":[]}', stderr='')
    monkeypatch.setattr(sf, '_run', run)
    sf.search_youtube(['camping bag', '캠핑 가방'], 4)
    assert events == ['pause', 'request', 'pause', 'request']
    for command in commands:
        assert command[command.index('--sleep-requests') + 1] == '1'
        assert command[command.index('--retry-sleep') + 1] == '2'


def test_download_wait_counts_toward_deadline(tmp_path, monkeypatch):
    from hotpost import source_finder as sf
    clock = [0]
    monkeypatch.setattr(sf.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(sf, 'request_pause', lambda: clock.__setitem__(0, 3))
    monkeypatch.setattr(sf, '_executable', lambda _: 'yt-dlp')
    monkeypatch.setattr(sf, '_run', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('deadline expired')))
    candidate = sf.Candidate('https://www.youtube.com/watch?v=test', 'youtube')
    assert sf.download_candidate(candidate, tmp_path, 1, 50, deadline=2) is None
    assert '시간 예산 소진' in candidate.error
