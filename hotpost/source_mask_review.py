"""Evidence-backed blur proposals; visual approval is a separate explicit step.

This module performs no network access and changes no studio task. A caller must
actually inspect the sampled source frames and proposed coverage before supplying
an approval receipt. OCR confidence, a source quality label, and a filename are
never treated as review evidence. Unseen video intervals are not approved.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import shutil
import subprocess
import uuid
from fractions import Fraction
from pathlib import Path

from PIL import Image

from .source_quality import sha256_file


GEOMETRY = {
    'canvas_width': 1080, 'canvas_height': 1920, 'fit': 'static-center-fill',
    'expected_scale': 1.0, 'rotation': 0, 'flip': False,
    'coordinates': 'capcut-canvas',
}
CANVAS_FILTER = 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1'


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    return float(value)


def _source(path, expected_sha256):
    path = Path(path).resolve()
    if not re.fullmatch(r'[0-9a-f]{64}', str(expected_sha256)):
        raise ValueError('A complete source SHA-256 is required')
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise ValueError('Source identity changed; review the actual file again')
    return path


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _run(command, timeout=60):
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f'Mask evidence extraction failed: {result.stderr[-500:]}')
    return result


def sample_source_frames(source_path, source_sha256, output_dir, intervals, *,
                         samples_per_interval=3, ffmpeg=None, ffprobe=None):
    """Capture timestamped evidence on the renderer's fixed 1080x1920 canvas.

    ``intervals`` are explicit source-relative [start, end) seconds. FFmpeg's
    decoded PTS is recorded, including nonzero stream start-time adjustment.
    Existing contact-sheet/scene filenames are never used to infer timestamps.
    These sparse samples are evidence for review, not proof of full coverage.
    """
    source = _source(source_path, source_sha256)
    if type(samples_per_interval) is not int or not 3 <= samples_per_interval <= 15:
        raise ValueError('Choose 3 to 15 evidence frames per interval')
    if not isinstance(intervals, list) or not 1 <= len(intervals) <= 16:
        raise ValueError('Choose 1 to 16 explicit source intervals')
    ffmpeg, ffprobe = ffmpeg or shutil.which('ffmpeg'), ffprobe or shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('ffmpeg and ffprobe are required for actual frame evidence')
    probe = json.loads(_run([str(ffprobe), '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,start_time,duration,avg_frame_rate,r_frame_rate:format=duration,start_time',
        '-of', 'json', str(source)]).stdout)
    streams = probe.get('streams') or []
    if not streams:
        raise ValueError('Source has no video stream')
    stream, container = streams[0], probe.get('format') or {}
    duration = float(stream.get('duration') or container.get('duration') or 0)
    origin = float(stream.get('start_time') or container.get('start_time') or 0)
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(origin):
        raise ValueError('Source has no usable duration or timestamp origin')
    try:
        fps = float(Fraction(stream.get('avg_frame_rate') or stream.get('r_frame_rate') or '30'))
        if not math.isfinite(fps) or fps <= 0:
            fps = 30
    except (ValueError, ZeroDivisionError):
        fps = 30
    windows = []
    for index, interval in enumerate(intervals):
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            raise ValueError('Each interval must be [start, end]')
        start, end = (_number(v, 'interval boundary') for v in interval)
        if not 0 <= start < end <= duration:
            raise ValueError('Evidence interval is outside the actual video')
        if any(w['source_start'] == start and w['source_end'] == end for w in windows):
            raise ValueError('Duplicate evidence intervals are ambiguous')
        windows.append({'index': index, 'source_start': start, 'source_end': end})
    folder = Path(output_dir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    evidence = []
    for window in windows:
        start, end = window['source_start'], window['source_end']
        # Stay inside the exclusive end. The decoded PTS is checked below.
        last = max(start, end - min(max(0.05, 1/fps), (end - start) / 4))
        for index in range(samples_per_interval):
            requested = start + (last - start) * index / (samples_per_interval - 1)
            frame_id = uuid.uuid4().hex
            image_path = folder / f'mask-evidence-{frame_id}.png'
            # Decode source timestamps directly. Input seeking without preserved
            # PTS would reset the clock and make mask positions ambiguous.
            vf = f"select='gte(t,{origin + requested:.9f})',showinfo,{CANVAS_FILTER}"
            result = _run([str(ffmpeg), '-hide_banner', '-loglevel', 'info', '-n',
                '-copyts', '-i', str(source), '-an', '-vf', vf, '-frames:v', '1',
                '-fps_mode', 'vfr', str(image_path)])
            match = re.search(r'\bpts_time:([-+\d.eE]+)', result.stderr)
            if not image_path.is_file() or not match:
                raise ValueError('No decoded frame timestamp was returned')
            timestamp = float(match[1]) - origin
            if not math.isfinite(timestamp) or not start - 1e-6 <= timestamp < end:
                raise ValueError('Decoded frame falls outside the requested evidence interval')
            with Image.open(image_path) as frame:
                if frame.size != (1080, 1920):
                    raise ValueError('Frame does not match the production canvas')
            evidence.append({'frame_id': frame_id, 'path': str(image_path),
                'sha256': sha256_file(image_path), 'source_timestamp': timestamp,
                'requested_timestamp': requested, 'interval_index': window['index']})
    _source(source, source_sha256)
    return {'version': 1, 'source_path': str(source), 'source_sha256': source_sha256,
            'source_duration': duration, 'geometry': dict(GEOMETRY),
            'intervals': windows, 'frames': evidence}


def _check_evidence(evidence):
    _source(evidence.get('source_path', ''), evidence.get('source_sha256'))
    if evidence.get('geometry') != GEOMETRY:
        raise ValueError('Mask geometry differs from the current production canvas')
    if not evidence.get('frames') or not evidence.get('intervals'):
        raise ValueError('Timestamped source evidence is required')
    for row in evidence['frames']:
        path = Path(row['path'])
        if not path.is_file() or sha256_file(path) != row['sha256']:
            raise ValueError('A reviewed frame changed or is missing')
        with Image.open(path) as frame:
            if frame.size != (1080, 1920):
                raise ValueError('A reviewed frame has a different canvas')
        window = next((w for w in evidence['intervals'] if w['index'] == row['interval_index']), None)
        timestamp = _number(row['source_timestamp'], 'frame timestamp')
        if window is None or not window['source_start'] - 1e-6 <= timestamp < window['source_end']:
            raise ValueError('Frame timestamp is not inside its evidence interval')


def canvas_rectangle(box, padding=8):
    """Map an OCR pixel box on the sampled canvas to native CapCut coordinates."""
    x, y, w, h = (_number(box[k], 'OCR box '+k) for k in ('left', 'top', 'width', 'height'))
    padding = _number(padding, 'padding')
    if w <= 0 or h <= 0 or not 0 <= padding <= 64:
        raise ValueError('OCR boxes need positive dimensions and bounded padding')
    left, top = max(0, x-padding), max(0, y-padding)
    right, bottom = min(1080, x+w+padding), min(1920, y+h+padding)
    if right-left < 2 or bottom-top < 2:
        raise ValueError('OCR box lies outside the production canvas')
    return {'width': (right-left)/1080, 'height': (bottom-top)/1920,
            'centerX': (left+right)/1080-1, 'centerY': 1-(top+bottom)/1920}


def propose_masks(evidence, ocr, *, ocr_name, padding=8, strength=0.8):
    """Run an injected OCR provider; return UNREVIEWED box-backed proposals.

    ``ocr(Path)`` returns pixel boxes with left/top/width/height and optional
    text/confidence. A distinct moving position remains a distinct proposal.
    The caller must visually review all proposed regions and interval coverage.
    """
    _check_evidence(evidence)
    strength = _number(strength, 'strength')
    if not 0.01 <= strength <= 1 or not isinstance(ocr_name, str) or not ocr_name.strip():
        raise ValueError('An OCR provider and valid blur strength are required')
    masks, observations = [], []
    by_region = {}
    for frame in evidence['frames']:
        window = next(w for w in evidence['intervals'] if w['index'] == frame['interval_index'])
        for box in ocr(Path(frame['path'])):
            rect = canvas_rectangle(box, padding)
            observation = {'frame_id': frame['frame_id'], 'source_timestamp': frame['source_timestamp'],
                'box': {k: _number(box[k], 'OCR box '+k) for k in ('left', 'top', 'width', 'height')},
                'text': str(box.get('text', ''))[:300],
                'confidence': None if box.get('confidence') is None else _number(box['confidence'], 'OCR confidence')}
            observations.append(observation)
            key = (window['index'], *(round(rect[k], 6) for k in ('width', 'height', 'centerX', 'centerY')))
            if key not in by_region:
                by_region[key] = len(masks)
                masks.append({'source_index': 0, 'source_start': window['source_start'],
                    'source_end': window['source_end'], 'expected_scale': 1.0,
                    'rectangle': rect, 'strength': strength, 'reviewed': False,
                    'interval_index': window['index'], 'observation_indices': []})
            masks[by_region[key]]['observation_indices'].append(len(observations)-1)
    if len(masks) > 200:
        raise ValueError('More than 200 regions; narrow the review intervals')
    proposal = {'version': 1, 'status': 'unreviewed', 'evidence': copy.deepcopy(evidence),
                'ocr_provider': ocr_name, 'observations': observations, 'watermark_masks': masks}
    proposal['proposal_sha256'] = _fingerprint(proposal)
    return proposal


def approve_masks(proposal, review):
    """Accept an explicit independent visual-review receipt, never an OCR score.

    Receipt: reviewer, proposal_sha256, source_sha256, geometry, and intervals.
    Each interval must repeat exact source_start/end, all mask_indices and all
    frame_ids, with coverage_confirmed=True and subject_visible=True. A clean
    interval with no proposed regions additionally needs no_overlays_confirmed=True;
    an empty OCR result alone is never evidence that no overlay is present. A partial
    or moving region needs a new proposal; this method cannot widen its timing.
    Only the attested intervals are returned. The caller must restrict editing
    to ``reviewed_intervals``; sparse samples do not approve the rest of a video.
    """
    evidence = proposal['evidence']
    _check_evidence(evidence)
    unsigned = {k: v for k, v in proposal.items() if k != 'proposal_sha256'}
    if (proposal.get('status') != 'unreviewed'
            or _fingerprint(unsigned) != proposal.get('proposal_sha256')
            or review.get('proposal_sha256') != proposal['proposal_sha256']
            or review.get('source_sha256') != evidence['source_sha256']
            or review.get('geometry') != GEOMETRY):
        raise ValueError('Visual review does not match this source, proposal and geometry')
    reviewer = review.get('reviewer')
    if not isinstance(reviewer, str) or not reviewer.strip() or not review.get('intervals'):
        raise ValueError('An independent visual reviewer and exact intervals are required')
    accepted, intervals, seen = [], [], set()
    for receipt in review['intervals']:
        span = (_number(receipt.get('source_start'), 'review start'),
                _number(receipt.get('source_end'), 'review end'))
        window = next((w for w in evidence['intervals']
                       if (w['source_start'], w['source_end']) == span), None)
        if not window or window['index'] in seen:
            raise ValueError('Review must use each proposed interval once, without extension')
        indices = [i for i, mask in enumerate(proposal['watermark_masks'])
                   if mask['interval_index'] == window['index']]
        frames = [f['frame_id'] for f in evidence['frames'] if f['interval_index'] == window['index']]
        if ((not indices and receipt.get('no_overlays_confirmed') is not True)
                or not isinstance(receipt.get('mask_indices'), list)
                or any(type(i) is not int for i in receipt['mask_indices'])
                or sorted(receipt['mask_indices']) != indices
                or sorted(receipt.get('frame_ids', [])) != sorted(frames)
                or receipt.get('coverage_confirmed') is not True
                or receipt.get('subject_visible') is not True):
            raise ValueError('Review must confirm every region, frame, coverage and visible subject')
        seen.add(window['index'])
        intervals.append({'source_start': window['source_start'], 'source_end': window['source_end']})
        for index in indices:
            mask = proposal['watermark_masks'][index]
            accepted.append({k: copy.deepcopy(mask[k]) for k in (
                'source_index', 'source_start', 'source_end', 'expected_scale', 'rectangle', 'strength')})
            accepted[-1]['reviewed'] = True
    return {'watermark_masks': accepted, 'reviewed_intervals': intervals,
            'mask_review': {'reviewer': reviewer.strip(), 'source_sha256': evidence['source_sha256'],
                            'proposal_sha256': proposal['proposal_sha256'], 'geometry': dict(GEOMETRY),
                            'intervals': copy.deepcopy(review['intervals']),
                            'evidence_frames': copy.deepcopy(evidence['frames'])}}
