"""Keep demonstrated bad source intervals excluded across review versions."""
from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path


def apply_withdrawals(settings, source):
    data_dir = getattr(settings, 'data_dir', None)
    digest = source.get('sha256', '')
    if data_dir is None or not re.fullmatch('[0-9a-f]{64}', digest):
        return source
    path = Path(data_dir)/'source_review_withdrawals'/f'{digest}.json'
    if not path.is_file():
        return source
    receipt = json.loads(path.read_text('utf-8'))
    denied = receipt.get('intervals')
    if receipt.get('source_sha256') != digest or not isinstance(denied, list) or not denied:
        raise ValueError('Source withdrawal identity or intervals are invalid')
    for span in denied:
        start, end = span.get('source_start'), span.get('source_end')
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end
                or not span.get('evidence') or not span.get('reason')):
            raise ValueError('Source withdrawal needs bounded intervals and evidence')

    def overlaps(span):
        return any(max(span['source_start'], bad['source_start']) <
                   min(span['source_end'], bad['source_end']) for bad in denied)

    result = copy.deepcopy(source)
    windows = result.get('reviewed_intervals') or []
    kept = [span for span in windows if not overlaps(span)]
    if windows and len(kept) == len(windows):
        return result
    result['reviewed_intervals'] = kept
    result['watermark_masks'] = [mask for mask in result.get('watermark_masks', [])
                                 if not overlaps(mask)]
    review = result.get('mask_review')
    if review:
        review['intervals'] = [span for span in review.get('intervals', []) if not overlaps(span)]
        review['evidence_frames'] = [frame for frame in review.get('evidence_frames', [])
            if any(span['source_start'] <= frame['source_timestamp'] < span['source_end'] for span in kept)]
    result['source_interval_withdrawal'] = {'receipt': str(path), 'intervals': copy.deepcopy(denied)}
    # A removed interval cannot contribute its old function approval. Remaining
    # actual frames must establish the task-scoped action again.
    result.pop('functional_review', None)
    result.pop('source_role', None)
    result['editing_eligible'] = False
    if not kept:
        result['manual_usage_review'] = {**result.get('manual_usage_review', {}),
            'editing_eligible': False, 'reason': '검토한 모든 구간이 제외됨', 'receipt': str(path)}
    return result


def validate_plan(settings, plan, changes=()):
    """A saved semantic/revision plan cannot resurrect a withdrawn interval."""
    sources = {source['id']: apply_withdrawals(settings, source) for source in plan['sources']}
    shots = {shot['id']: shot for shot in plan['shots']}
    replacements = {change['beat_id']: change['shot_id'] for change in changes if 'shot_id' in change}
    for beat in plan['beats']:
        chosen = replacements.get(beat.get('id')) or beat.get('selected_shot_id') or (beat.get('options') or [{}])[0].get('shot_id')
        shot = shots.get(chosen)
        if shot is None:
            continue  # The renderer validates ordinary missing-shot contracts.
        source = sources.get(shot['source_id'])
        if source is None or not source.get('source_interval_withdrawal'):
            continue
        start = shot['start'] if beat.get('id') in replacements else beat.get('source_start', shot['start'])
        end = shot['end'] if beat.get('id') in replacements else beat.get('source_end', shot['end'])
        if not any(span['source_start'] <= start < end <= span['source_end']
                   for span in source.get('reviewed_intervals', [])):
            raise ValueError('출력 검토에서 제외한 소스 구간이 선택되어 있습니다. 다른 장면으로 교체하세요.')
