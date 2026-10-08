from types import SimpleNamespace

from hotpost import source_finder as sf


def test_partial_download_audio_is_not_returned_as_video(tmp_path, monkeypatch):
    out = tmp_path / 'new' / 'videos'
    out.mkdir(parents=True)
    audio = out / '01_youtube_demo.f251.webm'
    audio.write_bytes(b'audio')
    monkeypatch.setattr(sf, '_executable', lambda _: 'yt-dlp')
    monkeypatch.setattr(sf, 'request_pause', lambda: None)
    monkeypatch.setattr(sf.time, 'sleep', lambda _: None)
    monkeypatch.setattr(sf, '_run', lambda *a, **kw: SimpleNamespace(
        returncode=1, stderr='File exceeds maximum size', stdout=''))
    monkeypatch.setattr(sf, 'probe_video', lambda p: {'duration': 30, 'width': None})
    candidate = sf.Candidate('https://www.youtube.com/watch?v=demo', 'youtube')
    assert sf.download_candidate(candidate, out, 1, 200) is None
    assert 'maximum size' in candidate.error
    assert audio.exists()


def test_audio_only_cache_is_skipped_before_real_video(tmp_path, monkeypatch):
    old = tmp_path / 'old' / 'videos'
    old.mkdir(parents=True)
    (old / 'a_demo.webm').write_bytes(b'audio')
    (old / 'b_demo.mp4').write_bytes(b'video')
    out = tmp_path / 'new' / 'videos'
    out.mkdir(parents=True)
    monkeypatch.setattr(sf, 'probe_video', lambda p: {'duration':30,
        'width':720 if p.suffix == '.mp4' else None})
    candidate = sf.Candidate('https://www.youtube.com/watch?v=demo', 'youtube')
    result = sf.download_candidate(candidate, out, 1, 200)
    assert result.read_bytes() == b'video'
