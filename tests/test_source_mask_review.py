"""Blur proposals require actual bounded evidence and an independent receipt."""
import copy
import shutil
import subprocess

import pytest
from PIL import Image

from hotpost.source_mask_review import (GEOMETRY, approve_masks, canvas_rectangle,
                                        propose_masks, sample_source_frames)
from hotpost.source_quality import sha256_file


@pytest.fixture
def evidence(tmp_path):
    source = tmp_path / 'preserved-source.mp4'
    source.write_bytes(b'unit fixture source identity')
    frames = []
    for i, timestamp in enumerate((1.0, 1.5, 1.9)):
        path = tmp_path / f'frame-{i}.png'
        Image.new('RGB', (1080, 1920), (40+i, 80, 110)).save(path)
        frames.append({'frame_id': f'f{i}', 'path': str(path), 'sha256': sha256_file(path),
                       'source_timestamp': timestamp, 'requested_timestamp': timestamp,
                       'interval_index': 0})
    return {'version': 1, 'source_path': str(source), 'source_sha256': sha256_file(source),
            'source_duration': 3.0, 'geometry': dict(GEOMETRY),
            'intervals': [{'index': 0, 'source_start': 1.0, 'source_end': 2.0}], 'frames': frames}


def proposal(evidence):
    return propose_masks(evidence, lambda _: [
        {'left': 108, 'top': 1440, 'width': 540, 'height': 192, 'text': '@creator', 'confidence': .99}],
        ocr_name='fixture OCR', padding=0)


def receipt(proposal):
    evidence = proposal['evidence']
    return {'reviewer': 'test-independent-visual-review',
            'proposal_sha256': proposal['proposal_sha256'],
            'source_sha256': evidence['source_sha256'], 'geometry': dict(GEOMETRY),
            'intervals': [{'source_start': 1.0, 'source_end': 2.0, 'mask_indices': [0],
                           'frame_ids': ['f0', 'f1', 'f2'],
                           'coverage_confirmed': True, 'subject_visible': True}]}


def test_proposal_is_unreviewed_despite_high_ocr_confidence_and_keeps_frame_evidence(evidence):
    draft = proposal(evidence)
    assert draft['status'] == 'unreviewed'
    assert len(draft['watermark_masks']) == 1  # identical static boxes, with all observations
    mask = draft['watermark_masks'][0]
    assert mask['reviewed'] is False
    assert mask['observation_indices'] == [0, 1, 2]
    assert mask['source_start'] == 1 and mask['source_end'] == 2
    assert draft['observations'][2]['source_timestamp'] == 1.9
    assert draft['evidence']['source_sha256'] == evidence['source_sha256']
    with pytest.raises(ValueError, match='review'):
        approve_masks(draft, {'confidence': 1, 'reviewed': True})


def test_ocr_canvas_box_matches_native_capcut_coordinates_and_clips_padding():
    assert canvas_rectangle({'left': 108, 'top': 1440, 'width': 540, 'height': 192}, 0) == pytest.approx({
        'width': .5, 'height': .1, 'centerX': -.3, 'centerY': -.6})
    rect = canvas_rectangle({'left': 0, 'top': 0, 'width': 100, 'height': 50}, 8)
    assert rect['width'] == .1 and rect['centerX'] == -.9
    assert rect['height'] == pytest.approx(58/1920)
    with pytest.raises(ValueError):
        canvas_rectangle({'left': 2000, 'top': 0, 'width': 100, 'height': 50})
    with pytest.raises(ValueError):
        canvas_rectangle({'left': 0, 'top': float('nan'), 'width': 100, 'height': 50})


def test_moving_text_positions_are_not_silently_treated_as_one_static_box(evidence):
    calls = iter((10, 60, 300))
    draft = propose_masks(evidence, lambda _: [
        {'left': next(calls), 'top': 100, 'width': 100, 'height': 40}], ocr_name='fixture OCR')
    assert len(draft['watermark_masks']) == 3
    assert all(mask['reviewed'] is False for mask in draft['watermark_masks'])
    wrong = receipt(draft)  # omits two detected positions
    with pytest.raises(ValueError, match='every region'):
        approve_masks(draft, wrong)


def test_explicit_visual_receipt_accepts_only_exact_interval_and_does_not_mutate_proposal(evidence):
    draft = proposal(evidence)
    accepted = approve_masks(draft, receipt(draft))
    assert accepted['watermark_masks'][0]['reviewed'] is True
    assert draft['watermark_masks'][0]['reviewed'] is False
    assert accepted['reviewed_intervals'] == [{'source_start': 1., 'source_end': 2.}]
    assert accepted['mask_review']['source_sha256'] == evidence['source_sha256']
    assert len(accepted['mask_review']['evidence_frames']) == 3
    # The output consists solely of the existing native CapCut mask contract.
    assert set(accepted['watermark_masks'][0]) == {
        'source_index', 'source_start', 'source_end', 'expected_scale', 'rectangle', 'strength', 'reviewed'}


@pytest.mark.parametrize('change', ['extend', 'omit_frame', 'no_coverage', 'hidden_subject', 'geometry', 'identity', 'alter_mask'])
def test_incomplete_stale_or_widened_visual_review_is_rejected(evidence, change):
    draft = proposal(evidence)
    reviewed = receipt(draft)
    if change == 'extend': reviewed['intervals'][0]['source_end'] = 3
    if change == 'omit_frame': reviewed['intervals'][0]['frame_ids'].pop()
    if change == 'no_coverage': reviewed['intervals'][0]['coverage_confirmed'] = False
    if change == 'hidden_subject': reviewed['intervals'][0]['subject_visible'] = False
    if change == 'geometry': reviewed['geometry']['expected_scale'] = 1.1
    if change == 'identity': reviewed['source_sha256'] = '0'*64
    if change == 'alter_mask': draft['watermark_masks'][0]['rectangle']['height'] = .5
    with pytest.raises(ValueError):
        approve_masks(draft, reviewed)


def test_changed_source_or_sample_file_invalidates_review(evidence):
    from pathlib import Path
    draft = proposal(evidence)
    reviewed = receipt(draft)
    source = Path(evidence['source_path'])
    saved = source.read_bytes()
    source.write_bytes(b'changed media')
    with pytest.raises(ValueError, match='Source identity changed'):
        approve_masks(draft, reviewed)
    source.write_bytes(saved)
    Image.new('RGB', (1080, 1920), 'red').save(evidence['frames'][0]['path'])
    with pytest.raises(ValueError, match='frame changed'):
        approve_masks(draft, reviewed)


def test_one_reviewed_interval_cannot_approve_other_sampled_or_unseen_intervals(evidence):
    extra = copy.deepcopy(evidence['frames'][0])
    extra.update(frame_id='other', source_timestamp=2.5, requested_timestamp=2.5, interval_index=1)
    evidence['frames'].append(extra)
    evidence['intervals'].append({'index': 1, 'source_start': 2.0, 'source_end': 3.0})
    draft = proposal(evidence)
    accepted = approve_masks(draft, receipt(draft))
    assert len(draft['watermark_masks']) == 2
    assert len(accepted['watermark_masks']) == 1
    assert accepted['watermark_masks'][0]['source_end'] == 2


def test_actual_media_sampling_records_decoded_pts_and_render_geometry(tmp_path):
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        pytest.skip('ffmpeg/ffprobe unavailable for actual video evidence test')
    source = tmp_path/'actual-video.mp4'
    subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-n', '-f', 'lavfi',
        '-i', 'testsrc2=size=640x360:rate=10:duration=2', '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p', str(source)], check=True, capture_output=True)
    source_hash = sha256_file(source)
    result = sample_source_frames(source, source_hash, tmp_path/'samples', [[.2, 1.5]],
                                  ffmpeg=ffmpeg, ffprobe=ffprobe)
    assert result['geometry'] == GEOMETRY
    assert len(result['frames']) == 3
    timestamps = [row['source_timestamp'] for row in result['frames']]
    assert timestamps == sorted(timestamps)
    assert all(.2 <= stamp < 1.5 for stamp in timestamps)
    assert all(abs(stamp*10-round(stamp*10)) < 1e-5 for stamp in timestamps)
    assert all(Image.open(row['path']).size == (1080, 1920) for row in result['frames'])
    assert sha256_file(source) == source_hash
    with pytest.raises(ValueError, match='identity changed'):
        sample_source_frames(source, '0'*64, tmp_path/'wrong', [[0, 1]])
    with pytest.raises(ValueError, match='outside'):
        sample_source_frames(source, source_hash, tmp_path/'wrong', [[0, 20]], ffmpeg=ffmpeg, ffprobe=ffprobe)


def test_empty_detection_requires_explicit_clean_visual_review(evidence):
    draft = propose_masks(evidence, lambda _: [], ocr_name='fixture empty detection')
    review = receipt(draft)
    review['intervals'][0]['mask_indices'] = []
    with pytest.raises(ValueError):
        approve_masks(draft, review)
    review['intervals'][0]['no_overlays_confirmed'] = True
    result = approve_masks(draft, review)
    assert result['watermark_masks'] == []
    assert result['reviewed_intervals'] == [{'source_start': 1., 'source_end': 2.}]
    review['intervals'][0]['frame_ids'].pop()
    with pytest.raises(ValueError):
        approve_masks(draft, review)
