"""Public source-search diagnostics; no cookies, headers or downloader command lines."""
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


def summarize(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return None
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
                       and (data.get('user_supplied') or row.get('source_quality') in {'clean-source', 'light-overlay'}))
        reasons.update(row.get('rejection_reasons') or [])
        if 'download_failed' in (row.get('rejection_reasons') or []):
            error = row.get('error', '').lower()
            reason = ('다운로드 실행 환경 오류' if 'challenge solving' in error or 'javascript runtime' in error else
                      '다운로드 시간 초과' if 'timeout' in error or '시간' in error else
                      '요청 제한' if '429' in error or 'cooldown' in error or '쿨다운' in error else
                      '인증·접근 확인 필요' if any(w in error for w in ('login', 'captcha', 'private', 'drm')) else
                      '영상 이용 불가' if 'unavailable' in error else '기타 다운로드 오류')
            failures[reason] += 1
    return {'job_id': data.get('job_id'), 'created_at': data.get('created_at'),
            'planned_queries': data.get('query_details', []), 'searches': data.get('search_audit', []),
            'execution_audit_available': 'search_audit' in data,
            'platforms': platforms, 'rejections': dict(reasons), 'download_errors': dict(failures), 'selected': data.get('downloaded', 0),
            'usable': usable, 'needs_review': max(0, data.get('downloaded', 0) - usable),
            'target': data.get('source_target'), 'stop_reason': data.get('budget_stop', ''),
            'platform_targets': data.get('platform_targets', {}),
            'notes': data.get('browser_notes', []) + data.get('verification_notes', [])}
