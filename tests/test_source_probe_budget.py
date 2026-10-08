"""Slow local verification must not look like excessive platform traffic."""
import subprocess
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from hotpost.config import Settings
from hotpost.models import Post
from hotpost.source_finder import Candidate


@pytest.fixture
def probe_run(tmp_path, monkeypatch):
    from hotpost import source_finder as sf, source_functional, text_overlay

    clock = SimpleNamespace(now=100.0, network=2.0, review=400.0, fail=False)
    monkeypatch.setattr(sf.time, 'monotonic', lambda: clock.now)
    settings = Settings(data_dir=tmp_path, source_browser_search=False,
                        source_query_model_enabled=False, source_transcribe_reference=False,
                        source_refine_max_candidates=0, source_match_mode='functional',
                        source_max_downloads=4, source_max_probe_downloads=4,
                        source_probe_time_budget=900, source_platform_probe_budget=300)
    monkeypatch.setattr(sf, '_post', lambda *_: Post('ref', 'u', 1, 'reel', caption='차 뒤에 달고 다니다 펼치는 텐트'))
    monkeypatch.setattr(sf, '_download_reference', lambda *args: args[-1])

    def frames(_video, directory, *_args, **_kwargs):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / 'candidate_001.jpg'
        Image.new('RGB', (20, 30), 'white').save(path)
        return [path]

    monkeypatch.setattr(sf, 'extract_frames', frames)
    monkeypatch.setattr(sf, 'OpenClipVerifier', lambda *_: SimpleNamespace(
        error='', product_evidence=[], last_embedding=None, subject_reference_indices=[],
        focus_subject=lambda _: None, discover_product_queries=lambda: [], score=lambda _: .7))
    monkeypatch.setattr(sf, 'search_google_vision', lambda *_: ([], []))
    monkeypatch.setattr(sf, 'search_local_hints', lambda *_: [
        Candidate('https://youtube.com/watch?v=first', 'youtube'),
        Candidate('https://youtube.com/watch?v=second', 'youtube')])
    monkeypatch.setattr(text_overlay, 'TextOverlayDetector', lambda *_: SimpleNamespace(
        note='', reference_text=lambda _: '', analyze=lambda _: {'source_quality': 'clean-source'}))
    monkeypatch.setattr(sf, 'probe_video', lambda _: {'duration': 10, 'width': 720, 'height': 1280})

    def compare(reference, video, directory):
        frames(video, directory)
        return .3  # Requires functional review; appearance alone cannot pass.

    monkeypatch.setattr(sf, 'compare_videos', compare)
    attempts, reviews = [], []

    def download(candidate, directory, index, *_args, deadline, **_kwargs):
        attempts.append({'url': candidate.url, 'started': clock.now, 'deadline': deadline})
        clock.now += clock.network
        if clock.fail:
            raise subprocess.TimeoutExpired('download', clock.network)
        path = directory / f'{index}.mp4'
        path.write_bytes(str(index).encode())
        return path

    def review(_settings, candidate, reference, candidate_frames):
        reviews.append(candidate.url)
        clock.now += clock.review
        return {'reviewed': True, 'same_core_function': False,
                'reason': 'Different mechanism', 'source_sha256': candidate.file_sha256}

    monkeypatch.setattr(sf, 'download_candidate', download)
    monkeypatch.setattr(source_functional, 'review_function', review)
    return SimpleNamespace(clock=clock, settings=settings, attempts=attempts, reviews=reviews,
                           run=lambda: sf.find_sources(settings, 'ref'))


def test_slow_local_ai_does_not_exhaust_platform_download_budget(probe_run):
    result = probe_run.run()
    assert result['probe_attempts'] == len(probe_run.reviews) == 2
    assert result['platform_probe_seconds'] == {'youtube': 4.0}
    assert [call['deadline'] for call in probe_run.attempts] == [160.0, 562.0]
    assert result['downloaded'] == 0  # Negative functional reviews still reject.
    assert all('different_core_function' in c['rejection_reasons'] for c in result['candidates'])


@pytest.mark.parametrize('failed_download', [False, True])
def test_network_time_and_failures_still_exhaust_platform_budget(probe_run, failed_download):
    probe_run.clock.network, probe_run.clock.review = 300.0, 0.0
    probe_run.clock.fail = failed_download
    result = probe_run.run()
    assert result['probe_attempts'] == 1
    assert probe_run.attempts[0]['deadline'] == 160.0
    assert result['platform_probe_seconds'] == {'youtube': 300.0}
    skipped = next(c for c in result['candidates'] if c['url'].endswith('second'))
    assert skipped['rejection_reasons'] == ['platform_budget_exhausted']


def test_local_review_still_counts_toward_overall_round_deadline(probe_run):
    probe_run.clock.review = 1000.0
    result = probe_run.run()
    assert result['probe_attempts'] == 1
    assert result['budget_stop'] == 'time_limit'
    assert result['platform_probe_seconds'] == {'youtube': 2.0}


def test_download_deadline_remains_clamped_to_overall_budget(probe_run):
    probe_run.settings.source_probe_time_budget = 10
    probe_run.clock.network, probe_run.clock.review = 10.0, 0.0
    result = probe_run.run()
    assert probe_run.attempts[0]['deadline'] == 110.0
    assert result['probe_attempts'] == 1 and result['budget_stop'] == 'time_limit'


def test_each_probe_checkpoint_survives_before_next_network_attempt(probe_run, monkeypatch):
    from hotpost import source_finder as sf
    download = sf.download_candidate
    receipts = []
    def checked_download(*args, **kwargs):
        receipt = json.loads(next(probe_run.settings.source_dir.glob('ref-*/manifest.json')).read_text(encoding='utf-8'))
        receipts.append(receipt)
        return download(*args, **kwargs)
    monkeypatch.setattr(sf, 'download_candidate', checked_download)
    result = probe_run.run()
    assert len(receipts)==2
    assert receipts[0]['candidates'][0]['download_attempted'] is True
    assert receipts[1]['candidates'][0]['downloaded_file']
    assert 'different_core_function' in receipts[1]['candidates'][0]['rejection_reasons']
    assert result['source_target']==10 and result['platform_targets']['tiktok']['target']==5
    assert result['platform_outcomes']['tiktok']['search_attempts']==0
    assert result['platform_outcomes']['tiktok']['reasons']['not_attempted']==1


def test_many_ranked_candidates_can_finish_within_unchanged_platform_cap(probe_run, monkeypatch):
    from hotpost import source_finder as sf
    # Extraction, request pacing and a valid transfer need forty seconds.
    # Twelve proposals must not all be cancelled at 300/12=25 seconds.
    monkeypatch.setattr(sf, 'search_local_hints', lambda *_: [
        Candidate(f'https://youtube.com/watch?v=proposal-{i}', 'youtube') for i in range(12)])
    probe_run.clock.network, probe_run.clock.review = 40.0, 0.0
    original_download = sf.download_candidate

    def timed_transfer(candidate, directory, index, *args, deadline, **kwargs):
        if probe_run.clock.now+40 > deadline:
            probe_run.clock.now = deadline
            candidate.error = 'Valid transfer cancelled by deadline'
            return None
        return original_download(candidate, directory, index, *args, deadline=deadline, **kwargs)

    monkeypatch.setattr(sf, 'download_candidate', timed_transfer)
    result = probe_run.run()
    assert result['probe_attempts'] == len(probe_run.attempts) == 4
    assert len(probe_run.reviews) >= 1  # Transfers reach the independent quality gate.
    assert result['platform_probe_seconds']['youtube'] == 160
    assert result['platform_probe_seconds']['youtube'] <= probe_run.settings.source_platform_probe_budget
    assert result['downloaded'] == 0  # The negative function verdict is preserved.


@pytest.mark.parametrize('candidate_cap,platform_left,overall_left,expected', [
    (60, 300, 900, 60), (20, 300, 900, 20),
    (60, 17, 900, 17), (60, 300, 9, 9), (60, 0, 900, 0),
])
def test_useful_download_slice_preserves_every_actual_cap(candidate_cap, platform_left, overall_left, expected):
    from hotpost.source_search.budget import candidate_probe_seconds
    settings = SimpleNamespace(source_candidate_download_budget=candidate_cap)
    assert candidate_probe_seconds(settings, platform_left, overall_left, 12) == expected
