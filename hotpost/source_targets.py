"""Platform goals never relax relevance, overlay or duplicate checks."""
import copy

from .source_quality import round_robin_candidates, select_valid_candidates, editing_ready
from dataclasses import asdict
from .source_outcomes import platform_outcomes
from .source_policy import source_platform


def usable_tiktok(candidate):
    item = asdict(candidate)
    return source_platform(item) == 'tiktok' and editing_ready(item)


def candidate_batch(candidates, limit, target):
    # Preserve platform diversity, but spend each platform's first slices on
    # candidates whose titles actually name the observed action.
    ordered = round_robin_candidates(sorted(candidates,key=lambda c:-(c.discovery_score or 0)), len(candidates))
    # Inspect enough TikTok candidates for quality rejection, before other platforms
    # consume the shared download budget. All original time/request limits remain.
    first = [c for c in ordered if c.platform == 'tiktok'][:min(limit, max(0, target) * 3)]
    ids = {id(c) for c in first}
    return (first + [c for c in ordered if id(c) not in ids])[:limit]


def select_sources(candidates, limit, target):
    # Probe a copy so duplicate/limit annotations do not reject the final pool.
    preferred = select_valid_candidates(copy.deepcopy([c for c in candidates if usable_tiktok(c)]),
                                        min(limit, max(0, target)))
    urls = {c.original_url for c in preferred}
    ordered = [c for c in candidates if c.original_url in urls]
    ordered += [c for c in candidates if c.original_url not in urls]
    return select_valid_candidates(ordered, limit)


def tiktok_count(candidates, limit):
    return len(select_valid_candidates(copy.deepcopy([c for c in candidates if usable_tiktok(c)]), limit))


def tiktok_coverage(candidates, searches, target, budget_stop=''):
    count = sum(c.selected_for_zip and usable_tiktok(c) for c in candidates)
    rows = [r for r in searches if r.get('provider') == 'tiktok']
    languages = {lang: any(r.get('language') == lang and r.get('status') in {'results','no_results'}
                           for r in rows) for lang in ('en','ko','zh')}
    reasons = []
    if count < target:
        reasons.append(f'품질·관련성·중복 검사 통과 소스 {count}/{target}개')
    if not all(languages.values()):
        reasons.append('검색 미완료 언어: ' + ', '.join(k for k,v in languages.items() if not v))
    failures = sorted({r.get('status') for r in rows if r.get('status') not in {'results','no_results'}})
    if failures:
        reasons.append('검색 상태: ' + ', '.join(str(v) for v in failures))
    if budget_stop:
        reasons.append('검사 예산 종료: ' + budget_stop)
    outcome = platform_outcomes(candidates, searches, {'tiktok':target}, budget_stop)['tiktok']
    return {**outcome, 'target':target, 'usable':count, 'languages':languages,
            'search_complete':all(languages.values()), 'reason_codes':list(outcome['reasons']),
            'status':'met' if count >= target else 'shortfall', 'reasons':reasons}
