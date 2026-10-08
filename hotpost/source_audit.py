"""Public source-search diagnostics; no cookies, headers or downloader command lines."""
import json
from copy import deepcopy
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from .source_quality import editing_ready


def reviewed_candidates(path, data, sources):
    """Project current task reviews onto exact acquired files, without rewriting history."""
    rows = deepcopy(data.get('candidates', []))
    if data.get('user_supplied'):
        # Owned footage has a separate contract, without external function reviews.
        return rows
    by_file = {(s.get('sha256'), Path(s['path']).resolve()): s
               for s in sources if s.get('sha256') and s.get('path')}
    for row in rows:
        if not row.get('selected_for_zip') or not row.get('downloaded_file') or not row.get('file_sha256'):
            continue
        source = by_file.get((row['file_sha256'], (Path(path).parent / row['downloaded_file']).resolve()))
        if not source or 'editing_eligible' not in source:
            continue
        review = source.get('functional_review') or {}
        verified = (review.get('reviewed') is True and review.get('source_sha256') == row['file_sha256']
                    and bool(review.get('observed_actions')) and bool(review.get('evidence_frames')))
        if source.get('editing_eligible') is True and not verified:
            # Legacy approval does not supply a new task review. Leave its
            # acquisition evidence unchanged instead of revoking completion.
            continue
        for key in ('source_quality', 'blur_required', 'watermark_masks', 'reviewed_intervals',
                    'mask_review', 'functional_review'):
            if key in source:
                row[key] = deepcopy(source[key])
        row['editing_eligible'] = bool(source.get('editing_eligible') is True and editing_ready(source) and verified)
        row['inspection_stage'] = 'studio_review'
    return rows


def reviewed_platform_outcomes(path, data, sources):
    from .source_outcomes import platform_outcomes
    targets = data.get('platform_targets') or (data.get('source_policy') or {}).get('platform_minimums') or {}
    targets = {name: value.get('target', 0) if isinstance(value, dict) else value
               for name, value in targets.items()}
    return platform_outcomes(reviewed_candidates(path, data, sources), data.get('search_audit', []),
        targets, data.get('budget_stop', ''))


def summarize(path, reviewed_sources=None):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return None
    if reviewed_sources is not None:
        acquisition_outcomes = data.get('platform_outcomes', {})
        data['candidates'] = reviewed_candidates(path, data, reviewed_sources)
        if data.get('execution_audit_available', 'search_audit' in data):
            data['platform_outcomes'] = reviewed_platform_outcomes(path, data, reviewed_sources)
    platforms = {}
    reasons = Counter()
    failures = Counter()
    usable = 0
    for row in data.get('candidates', []):
        host = urlparse(row.get('original_url') or row.get('url', '')).netloc
        provider = next((name for name in ('tiktok', 'douyin', 'xiaohongshu', 'bilibili', 'youtube', 'pexels')
                         if name in host), 'youtube' if 'youtu.be' in host else 'other')
        if data.get('user_supplied'):
            provider = '직접 업로드'
        counts = platforms.setdefault(provider, {'candidates': 0, 'received': 0, 'selected': 0})
        counts['candidates'] += 1
        counts['received'] += bool(row.get('downloaded_file') or data.get('user_supplied'))
        counts['selected'] += bool(row.get('selected_for_zip'))
        usable += bool(row.get('selected_for_zip') and row.get('editing_eligible', True)
                       and (data.get('user_supplied') or editing_ready(row)))
        reasons.update(row.get('rejection_reasons') or [])
        if 'download_failed' in (row.get('rejection_reasons') or []):
            error = row.get('error', '').lower()
            reason = ('다운로드 실행 환경 오류' if 'challenge solving' in error or 'javascript runtime' in error else
                      '다운로드 시간 초과' if 'timeout' in error or '시간' in error else
                      '요청 제한' if '429' in error or 'cooldown' in error or '쿨다운' in error else
                      '인증·접근 확인 필요' if any(w in error for w in ('login', 'captcha', 'private', 'drm')) else
                      '영상 이용 불가' if 'unavailable' in error else '기타 다운로드 오류')
            failures[reason] += 1
    result = {'job_id': data.get('job_id'), 'created_at': data.get('created_at'),
            'planned_queries': data.get('query_details', []), 'searches': data.get('search_audit', []),
            'strategy': data.get('search_strategy'),
            'inspection': [{'title':row.get('title',''), 'score':row.get('discovery_score'),
                            'reasons':row.get('discovery_reasons',[]), 'duration':(row.get('discovery_meta') or {}).get('duration'),
                            'download_budget_seconds':row.get('download_budget_seconds'),
                            'download_attempted':row.get('download_attempted'), 'rejections':row.get('rejection_reasons',[])}
                           for row in data.get('candidates',[])[:40]],
            'platform_probe_seconds':data.get('platform_probe_seconds',{}),
            'execution_audit_available': data.get('execution_audit_available', 'search_audit' in data),
            'platforms': platforms, 'rejections': dict(reasons), 'download_errors': dict(failures), 'selected': data.get('downloaded', 0),
            'usable': usable, 'needs_review': max(0, data.get('downloaded', 0) - usable),
            'target': data.get('source_target'), 'stop_reason': data.get('budget_stop', ''),
            'platform_targets': data.get('platform_targets', {}),
            'source_policy': data.get('source_policy'), 'platform_outcomes':data.get('platform_outcomes', {}),
            'notes': data.get('browser_notes', []) + data.get('verification_notes', [])}
    if reviewed_sources is not None:
        result['acquisition_platform_outcomes'] = acquisition_outcomes
        result['inspection_stage'] = ('studio_review' if any(r.get('inspection_stage') == 'studio_review'
                                      for r in data.get('candidates', [])) else 'acquisition')
    return result
