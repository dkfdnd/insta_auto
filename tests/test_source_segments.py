from types import SimpleNamespace
import subprocess

import pytest

from hotpost.source_segments import extract_relevant_segment


class Verifier:
    def __init__(self, scores):
        self.scores = iter(scores)
        self.calls = 0

    def score(self, frames):
        assert len(frames) == 3 and all(p.is_file() for p in frames)
        self.calls += 1
        return next(self.scores)


def install_encoder(monkeypatch):
    commands = []

    def run(command, **kwargs):
        from pathlib import Path
        commands.append(command)
        Path(command[-1]).write_bytes(b'encoded media')
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr('hotpost.source_finder._executable', lambda name: name)
    monkeypatch.setattr('hotpost.source_finder._run', run)
    monkeypatch.setattr('hotpost.source_segments.time.monotonic', lambda: 100)
    return commands


def settings(mode='functional'):
    return SimpleNamespace(source_long_video_max_seconds=1800,
                           source_segment_seconds=30, source_match_mode=mode)


def test_functional_variant_is_proposed_from_best_interval_without_approval(tmp_path, monkeypatch):
    commands = install_encoder(monkeypatch)
    verifier = Verifier([.20, .35, .45, .62, .73, .65, .40, .30])
    result = extract_relevant_segment(settings(), tmp_path/'original.mp4',
                                     {'duration':450}, verifier, tmp_path/'scan', 300)
    file, interval = result
    assert verifier.calls == 8 and file.is_file()
    assert interval == {'start':240., 'end':270., 'original_duration':450, 'scan_similarity':.73}
    assert 'reviewed' not in interval and 'same_core_function' not in interval
    assert '-ss' in commands[-1] and commands[-1][commands[-1].index('-ss')+1] == '240.0'


@pytest.mark.parametrize('mode, score',[('functional',.59), ('product',.73), ('scene',.73)])
def test_scan_below_mode_threshold_does_not_encode_or_grant_approval(tmp_path, monkeypatch, mode, score):
    commands = install_encoder(monkeypatch)
    result = extract_relevant_segment(settings(mode), tmp_path/'original.mp4',
                                     {'duration':450}, Verifier([score]*8), tmp_path/'scan', 300)
    assert result is None and len(commands) == 24
    assert not (tmp_path/'scan/segment.mp4').exists()


def test_expired_budget_preserves_original_without_scanning(tmp_path, monkeypatch):
    commands = install_encoder(monkeypatch)
    original = tmp_path/'original.mp4'; original.write_bytes(b'original video')
    result = extract_relevant_segment(settings(), original, {'duration':450},
                                     Verifier([]), tmp_path/'scan', 99)
    assert result is None and not commands
    assert original.read_bytes() == b'original video'
