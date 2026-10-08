"""Evidence-only acquisition outcomes, including providers that were never tried."""
from collections import Counter
from dataclasses import asdict, is_dataclass
import re

from .source_policy import source_platform
from .source_quality import editing_ready

PLATFORMS = ('tiktok', 'douyin', 'xiaohongshu', 'instagram', 'youtube', 'bilibili', 'stock', 'other')
SKIPPED = {'not_attempted', 'cooldown', 'verification_required', 'login_required', 'no_supported_queries', 'query_exhausted', 'image_exhausted', 'budget_exhausted', 'strategy_skipped', 'readiness_blocked', 'platform_disabled'}


def failure_reason(text, default='download_failed'):
    text = str(text).lower()
    if '429' in text or 'rate_limited' in text: return 'rate_limited'
    if 'captcha' in text or 'verification_required' in text: return 'captcha'
    if any(v in text for v in ('login', '401', 'authentication', 'sign in')): return 'auth_required'
    if '403' in text: return 'access_denied'
    if any(v in text for v in ('drm', 'private', 'rights')): return 'access_restricted'
    if 'cooldown' in text: return 'cooldown'
    if 'budget' in text or text in {'time_limit', 'attempt_limit', 'probe_limit'}: return 'budget_exhausted'
    return default


def search_platforms(row):
    provider = row.get('provider', '')
    if provider in PLATFORMS: return [provider]
    # An indexed platform query is a search-engine attempt, not in-site
    # navigation. Keep that distinction in each provider's search_channels.
    return sorted({source_platform({'url':'https://'+host})
                   for host in re.findall(r'\bsite:([a-z0-9.-]+)', row.get('query', '').lower())}
                  - {'other'})


def platform_outcomes(candidates, searches, targets=None, budget_stop=''):
    candidates = [asdict(c) if is_dataclass(c) else c for c in candidates]
    result = {}
    for platform in PLATFORMS:
        rows = [r for r in searches if platform in search_platforms(r)]
        items = [c for c in candidates if source_platform(c) == platform]
        reasons = Counter()
        skipped = Counter()
        attempts = [r for r in rows if r.get('requests') or
                    (r.get('query') and r.get('status') not in SKIPPED)]
        for row in rows:
            status = row.get('status', '')
            if row not in attempts:
                # Persisted gates are skipped navigation, not fresh CAPTCHA,
                # authentication failures or new requests to the provider.
                skipped[status or 'not_attempted'] += 1
                continue
            if status == 'no_results': reasons['no_candidates'] += 1
            elif status not in {'results', 'started', 'not_attempted'}:
                reason = failure_reason(status + ' ' + str(row.get('http_status', '')))
                reasons['search_failed' if reason == 'download_failed' else reason] += 1
        download_attempts = 0
        for item in items:
            rejected = item.get('rejection_reasons') or []
            attempted = item.get('download_attempted')
            if attempted is None:
                attempted = bool(item.get('downloaded_file') or 'download_failed' in rejected)
            download_attempts += bool(attempted)
            if any(r.startswith('duplicate_of:') for r in rejected): reasons['duplicate'] += 1
            elif 'download_failed' in rejected:
                reasons[failure_reason(item.get('error', ''))] += 1
            elif 'platform_cooldown' in rejected: reasons['cooldown'] += 1
            elif 'platform_budget_exhausted' in rejected: reasons['budget_exhausted'] += 1
            elif item.get('downloaded_file') and (rejected or not editing_ready(item)):
                if not rejected and item.get('selected_for_zip') and item.get('editing_eligible') is None:
                    reasons['review_pending'] += 1
                elif rejected != ['valid_candidate_limit_reached']: reasons['quality_rejected'] += 1
            elif 'invalid_duration' in rejected and (item.get('discovery_meta') or {}).get('duration') is not None:
                reasons['metadata_rejected'] += 1
            elif not attempted and not item.get('downloaded_file'): reasons['not_attempted'] += 1
        usable = sum(bool(c.get('selected_for_zip') and not c.get('rejection_reasons') and editing_ready(c)) for c in items)
        target = (targets or {}).get(platform, 0)
        if not attempts and not download_attempts:
            reasons['not_attempted'] = max(1, reasons['not_attempted'])
        if budget_stop and usable < target: reasons['budget_exhausted'] += 1
        result[platform] = {'target': target, 'usable': usable, 'candidates': len(items),
            'received': sum(bool(c.get('downloaded_file')) for c in items),
            'local_reuses':sum(bool(c.get('downloaded_file') and c.get('acquisition')=='local-cache') for c in items),
            'network_received':sum(bool(c.get('downloaded_file') and c.get('acquisition')=='network') for c in items),
            'search_attempts': len(attempts), 'search_channels': sorted({r.get('provider', '') for r in attempts}),
            'skipped_searches':sum(skipped.values()), 'skipped_reasons':dict(skipped),
            'search_evidence':[{'stage':'search', 'channel':r.get('provider'), 'status':r.get('status'),
                                'attempted':r in attempts, 'http_status':r.get('http_status')}
                               for r in rows],
            'download_attempts': download_attempts, 'reasons': dict(reasons),
            'status': 'met' if target and usable >= target else 'shortfall' if target else
                      'not_attempted' if not attempts and not download_attempts else 'attempted'}
    return result
