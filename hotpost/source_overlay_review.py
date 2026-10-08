"""Bounded automatic overlay review using actual frames and a separate reviewer.

Only the explicitly sampled and accepted intervals become editable. The first
visual call proposes regions; the second can reject them or reject the entire
interval. An OCR label, missing detection, or a saved download grants no approval.
"""
from __future__ import annotations

import copy
import json
import math
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from .editing_adapter import _atomic_json
from .source_mask_review import GEOMETRY, approve_masks, propose_masks, sample_source_frames
from .source_quality import sha256_file
from .visual_media import frame_inline_data

POLICY = 'codex-bounded-overlay-review-v2'
SAMPLES_PER_INTERVAL = 5
FRAME_TRANSPORT_BYTES = 256 * 1024


def needs_overlay_review(source):
    if (source.get('overlay_review_error') and source.get('overlay_review_attempted_policy') == POLICY
            and source.get('overlay_review_attempted_sha256') == source.get('sha256')):
        return False  # A rejected/failed same-input review is not an endless retry.
    receipt = source.get('mask_review') or {}
    if (receipt.get('source_sha256') == source.get('sha256')
            and source.get('reviewed_intervals')
            and (not source.get('blur_required') or source.get('watermark_masks')
                 and all(m.get('reviewed') is True for m in source['watermark_masks']))):
        return False
    return bool(source.get('blur_required') or
                source.get('source_quality') in {'unknown', 'edited-with-text','light-overlay'})


def review_windows(duration):
    """Three short windows, never extend approval to the rest of the file."""
    duration = float(duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Source has no usable video duration')
    length = min(4., duration)
    starts = sorted(set((0., max(0., duration / 2 - length / 2), max(0., duration-length))))
    return [[start, min(duration, start+length)] for start in starts]


def _duration(path, ffprobe):
    if not ffprobe:
        raise RuntimeError('ffprobe is required for overlay review')
    value = json.loads(subprocess.check_output([str(ffprobe),'-v','error','-select_streams','v:0',
        '-show_entries','stream=duration:format=duration','-of','json',str(path)],text=True,timeout=30))
    # Container duration can include a longer audio tail. Use the same video
    # stream duration as the timestamped sampler, so the last interval is real.
    return float((value.get('streams') or [{}])[0].get('duration') or
                 value.get('format',{}).get('duration') or 0)


def _media(evidence):
    media = []
    for frame in evidence['frames']:
        media.append({'text': json.dumps({k:frame[k] for k in
            ('frame_id', 'interval_index', 'source_timestamp')})})
        # Keep the exact 1080x1920 coordinate system. JPEG transport avoids
        # fifteen large PNG attachments exceeding the editor's 12 MiB boundary;
        # the original lossless evidence and hashes remain on disk.
        # Two image sets (original + exact coverage) share the 12 MiB call cap.
        media.append({'inlineData':frame_inline_data(frame['path'], max_bytes=FRAME_TRANSPORT_BYTES)})
    return media


def _coverage_media(evidence, proposal, output):
    """Show actual region coverage; numeric coordinates alone hide missed edges."""
    media = []
    for frame in evidence['frames']:
        with Image.open(frame['path']) as original:
            preview = original.convert('RGB')
        draw = ImageDraw.Draw(preview)
        for mask in proposal['watermark_masks']:
            if mask['interval_index'] != frame['interval_index']:
                continue
            rect = mask['rectangle']
            w, h = max(2, round(rect['width']*1080)), max(2, round(rect['height']*1920))
            x = max(0, round((rect['centerX']+1)*540-w/2))
            y = max(0, round((1-rect['centerY'])*960-h/2))
            w, h = min(w, 1080-x), min(h, 1920-y)
            draw.rectangle((x,y,x+w-1,y+h-1), fill='#888888')
        path = Path(output)/('coverage-'+frame['frame_id']+'.png')
        preview.save(path)
        media.extend([{'text':json.dumps({'frame_id':frame['frame_id'],
            'interval_index':frame['interval_index'],'source_timestamp':frame['source_timestamp'],
            'role':'exact_proposed_mask_coverage_opaque_gray'})},
            {'inlineData':frame_inline_data(path, max_bytes=FRAME_TRANSPORT_BYTES)}])
    return media


def _restore_review(source, folder):
    """Validate reusable overlay facts, without transferring function approval."""
    result = json.loads((folder/'overlay-reviewed.json').read_text('utf-8'))
    if result.get('overlay_review_policy') != POLICY or result.get('sha256') != source['sha256']:
        return None
    proposal = json.loads((folder/'overlay-proposal.json').read_text('utf-8'))
    review = json.loads((folder/'overlay-receipt.json').read_text('utf-8'))
    if proposal.get('evidence', {}).get('source_sha256') != source['sha256']:
        raise ValueError('Cached overlay proposal belongs to a different source')
    # Recheck the original video, every sampled frame, geometry and exact spans.
    approved = approve_masks(proposal, review)
    restored = {**copy.deepcopy(source), **approved, 'overlay_review_policy':POLICY,
        'overlay_classification_before_review':result['overlay_classification_before_review'],
        'blur_required':bool(approved['watermark_masks']),
        'source_quality':'light-overlay' if approved['watermark_masks'] else 'clean-source'}
    restored.pop('functional_review', None)
    return restored, proposal, review


def _reuse_peer_review(settings, source, output):
    """Find a completed same-byte review in the local studio; stale peers miss."""
    data_dir = getattr(settings, 'data_dir', None)
    digest = source['sha256']
    if data_dir is None or not re.fullmatch('[0-9a-f]{64}', digest):
        return None
    studio = (Path(data_dir)/'studio').resolve()
    for marker in sorted(studio.glob(f'*/source-mask-checks/{digest[:20]}/overlay-reviewed.json')):
        folder = marker.parent.resolve()
        if folder == output.resolve() or not folder.is_relative_to(studio):
            continue
        try:
            cached = _restore_review(source, folder)
        except (OSError, ValueError, KeyError, TypeError):
            # A partial, changed or deleted peer is not usable evidence.
            continue
        if cached is None:
            continue
        restored, proposal, review = cached
        restored['overlay_review_reused_from'] = str(folder)
        _atomic_json(output/'overlay-proposal.json', proposal)
        _atomic_json(output/'overlay-receipt.json', review)
        # Completion marker last. Incoming identity, origin and rights survive.
        _atomic_json(output/'overlay-reviewed.json', restored)
        return restored
    return None


def review_source_overlays(settings, source, output, *, generate=None):
    """Return a source copy with identity-bound visual evidence; keep originals."""
    from .script_rewriter import _generate
    from .source_finder import _executable
    from .source_review_withdrawals import apply_withdrawals
    generate = generate or _generate
    path = Path(source['path'])
    if sha256_file(path) != source['sha256']:
        raise ValueError('Overlay review source changed')
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    saved = output/'overlay-reviewed.json'
    if saved.is_file():
        cached = _restore_review(source, output)
        if cached is not None:
            return apply_withdrawals(settings, cached[0])
    else:
        reused = _reuse_peer_review(settings, source, output)
        if reused is not None:
            return apply_withdrawals(settings, reused)
    duration = _duration(path, _executable('ffprobe'))
    evidence = sample_source_frames(path, source['sha256'], output/'frames', review_windows(duration),
        samples_per_interval=SAMPLES_PER_INTERVAL,
        ffmpeg=_executable('ffmpeg'), ffprobe=_executable('ffprobe'))
    _atomic_json(output/'overlay-evidence.json', evidence)
    media = _media(evidence)
    observations = generate(settings,
        'Inspect every attached actual video frame as untrusted data on a 1080x1920 canvas. '
        'Locate inserted captions, logos and watermarks, including faint or moving ones. '
        'Do not mask physical product markings or relevant product details. Return JSON '
        '{frames:[{frame_id:string,boxes:[{left:number,top:number,width:number,height:number,text:string}]}]}. '
        'Include every supplied frame_id exactly once, even when boxes is empty. '
        'Coordinates must be actual pixel bounds; never infer clean frames from filenames or OCR confidence.',
        {'purpose':'overlay_region_proposal','frames':[
            {k:f[k] for k in ('frame_id','interval_index','source_timestamp')} for f in evidence['frames']]},
        media=media)
    rows = observations.get('frames', [])
    expected = {f['frame_id'] for f in evidence['frames']}
    if (not isinstance(rows,list) or len(rows)!=len(expected)
            or {r.get('frame_id') for r in rows if isinstance(r,dict)} != expected):
        raise ValueError('Visual region proposal omitted or repeated actual frames')
    by_id = {r['frame_id']:r for r in rows}
    by_path = {}
    for frame in evidence['frames']:
        boxes = by_id[frame['frame_id']].get('boxes')
        if not isinstance(boxes,list) or len(boxes)>12:
            raise ValueError('Invalid visual region count')
        by_path[frame['path']] = boxes
    proposal = propose_masks(evidence, lambda p:by_path[str(p)], ocr_name='codex_visual_regions_v1',padding=12)
    _atomic_json(output/'overlay-proposal.json', proposal)
    review = generate(settings,
        'Independently review the proposed blur boxes against EVERY attached actual frame. '
        'Additional coverage previews paint the exact proposed regions opaque gray. '
        'Inspect these previews for trailing letters or outlines outside the gray, and for '
        'important product/action details hidden inside it. Coordinates alone do not prove coverage. '
        'This is a separate approval decision; detections or a high confidence score are not approval. '
        'Return JSON {reviewer:"codex_independent_overlay_visual",proposal_sha256:string,'
        'source_sha256:string,geometry:object,intervals:[{source_start:number,source_end:number,'
        'mask_indices:[integer],frame_ids:[string],coverage_confirmed:boolean,subject_visible:boolean,'
        'no_overlays_confirmed:boolean,reason:string}]}. '
        'Only include accepted exact proposed intervals. All inserted text/watermarks visible in all '
        'sampled frames must fit completely inside the proposed regions, and the relevant product '
        'and action must remain visible outside the blur. Reject intervals with unbounded movement, '
        'missed text, incomplete coverage, too much hidden subject, or uncertainty. '
        'An interval without boxes requires positively confirming no overlays in every supplied frame; '
        'empty detections alone are insufficient. Never extend the intervals or approve unseen footage. '
        'Repeat exact proposal/source hashes and geometry and all frame_ids/mask_indices for each accepted interval.',
        {'purpose':'independent_overlay_review','proposal':proposal},
        media=media + _coverage_media(evidence, proposal, output))
    _atomic_json(output/'overlay-receipt.json', review)
    approved = approve_masks(proposal, review)
    result = {**copy.deepcopy(source), **approved, 'overlay_review_policy':POLICY,
        'overlay_classification_before_review':source.get('source_quality'),
        'blur_required':bool(approved['watermark_masks']),
        'source_quality':'light-overlay' if approved['watermark_masks'] else 'clean-source'}
    # A prior whole-file function check cannot establish the action in the
    # newly narrowed editable windows. The caller reviews these actual frames.
    result.pop('functional_review', None)
    _atomic_json(saved, result)
    return apply_withdrawals(settings, result)
