"""Cheap inspection order and continuation of genuinely unprobed candidates."""
import json
import re
from dataclasses import fields
from pathlib import Path

from .models import Candidate
from ..source_urls import canonical_video_key, video_url

ACTION_WORDS = {
    'cold_storage': r'refrigerat\w*|fridge|냉장|冷藏',
    'scoop': r'scoop\w*|spoon\w*|숟가락|스푼|떠서|舀|勺',
    'portion': r'portion\w*|소분|分装',
    'storage': r'stor\w*|preserv\w*|보관|저장|保存|储存',
}


def action_keys(text):
    return {key for key, pattern in ACTION_WORDS.items() if re.search(pattern,text,re.I)}


def rank_candidates(candidates, plan):
    """Titles inform priority only; they never grant/revoke editing eligibility."""
    action_rows = [q for q in plan.get('query_details',[]) if q.get('role') == 'subject_action' and q.get('evidence_quote')]
    wanted = set().union(*(action_keys(q['query']) for q in action_rows)) if action_rows else set()
    if 'cold_storage' in wanted:
        wanted.discard('storage')
    products = plan.get('products',[])
    for candidate in candidates:
        title = candidate.title.lower()
        points, reasons = 0.0, []
        for product in products:
            bases = [re.sub(r' preparation$|\s*준비$|准备$', '', product.get(lang,'')).strip().lower()
                     for lang in ('en','ko','zh')]
            if any(base and re.sub(r'\s+','',base) in re.sub(r'\s+','',title) for base in bases):
                points += 2
                reasons.append('제목에서 확인한 주제 일치')
                break
            # A preparation-specific subject can appear under the broader
            # ingredient name. Give weaker ordering evidence, never approval.
            if ('garlic' in product.get('en','').lower()
                    and re.search(r'\bgarlic\b|마늘|大蒜|蒜末',title,re.I)):
                points += 1
                reasons.append('제목의 상위 주제 일치 · 세부 재료·동작은 영상 검사로 판단')
                break
        observed = action_keys(title)
        matched = wanted & observed
        if matched:
            points += 3 + len(matched)
            reasons.append('제목의 핵심 행동 일치: ' + ', '.join(sorted(matched)))
        elif wanted and title:
            points -= 1
            reasons.append('제목에서 핵심 행동 미확인 · 영상 검사로 판단')
        if not title:
            reasons.append('제목 없음 · 영상 검사로 판단')
        if candidate.match_kind == 'visual-match':
            points += 1
            reasons.append('역이미지 장면 근거')
        candidate.discovery_score = points
        candidate.discovery_reasons = reasons
    return candidates


def discovery_duration_reasons(candidate, maximum):
    duration = (candidate.discovery_meta or {}).get('duration')
    if isinstance(duration,(float,int)) and not isinstance(duration,bool) and not 4 <= duration <= maximum:
        return ['invalid_duration']
    return []


def deferred_candidates(context, excluded_urls, maximum):
    """Recover unpaid work; never resurrect inspected/rejected/download-failed URLs."""
    excluded = {canonical_video_key(url) for url in excluded_urls or [] if url}
    keys = {f.name for f in fields(Candidate)}
    result, seen = [], set(excluded)
    for entry in reversed((context or {}).get('rounds', [])):
        try:
            data = json.loads(Path(entry['manifest_path']).read_text(encoding='utf-8'))
        except (OSError,ValueError,KeyError):
            continue
        for row in data.get('candidates',[]):
            url = row.get('original_url') or row.get('url','')
            identity = canonical_video_key(url)
            reasons = set(row.get('rejection_reasons') or [])
            if (not video_url(url) or identity in seen or row.get('downloaded_file') or row.get('error')
                    or row.get('download_attempted') is True
                    or reasons - {'platform_budget_exhausted','not_probed','download_budget_deferred'}):
                continue
            # Empty rejection metadata after a global time/attempt stop also
            # denotes unprobed work, not permission to use the candidate.
            values = {k:v for k,v in row.items() if k in keys}
            values.update(url=url,selected_for_zip=False,rejection_reasons=None,download_attempted=None,
                          selection_reason='',match_kind='deferred-candidate')
            result.append(Candidate(**values)); seen.add(identity)
            if len(result) >= maximum:
                return result
    return result
