"""Choose a grounded search objective and routes from the previous outcome."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .strategy import attempted, query_fingerprint, fresh_queries
from .readiness import parser_revision

TEXT_ROUTES = ['tiktok', 'douyin', 'xiaohongshu', 'bilibili', 'duckduckgo', 'bing', 'youtube']
IMAGE_ROUTES = ['google-lens', 'yandex-images']
LABELS = {'core_action':'핵심 행동 검색', 'clean_action':'원본·무자막 행동 장면 검색',
          'scene_discovery':'다른 장면과 클로즈업 검색', 'alternate_access':'수신 가능한 다른 경로 검색'}


def grounded_actions(plan, evidence):
    """Build fallback action translations only when literal evidence names it."""
    specifications = [
        (r'냉장|refrigerat\w*|冷藏', ('refrigerator storage', '냉장 보관법', '冷藏保存方法'), 'technique'),
        (r'숟가락|스푼|떠서|scoop\w*|spoon|舀', ('scooping with a spoon', '한 스푼 떠서 사용하기', '用勺子舀取'), 'demonstrated_action'),
        (r'소분|portion\w*|分装', ('portioning', '소분 장면', '分装'), 'demonstrated_action'),
        (r'보관|저장|storage|保存', ('storage', '보관법', '保存方法'), 'technique'),
    ]
    rows = []
    cold = any(re.search(specifications[0][0], str(body), re.I) for body in evidence.values())
    for pattern, suffixes, intent in specifications:
        if cold and suffixes[0] == 'storage':
            continue
        hit = next(((source, match.group(0)) for source, body in evidence.items()
                    if (match := re.search(pattern, str(body), re.I))), None)
        if not hit:
            continue
        for product in plan.get('products', []):
            for lang, suffix in zip(('en','ko','zh'), suffixes):
                base = product.get(lang, '')
                if not base:
                    continue
                base = re.sub(r' preparation$|\s*준비$|准备$', '', base).strip()
                rows.append({'query':f'{base} {suffix}', 'language':lang, 'intent':intent,
                             'role':'subject_action', 'sources':[hit[0]], 'evidence_quote':hit[1],
                             'origin':'grounded_action', 'confidence':'literal_action'})
    return rows


def _last_results(context):
    count = context.get('completed_rounds', 0)
    if not context.get('rounds'):
        return []
    results = []
    # Explicitly resuming resets budgets, not knowledge of the last failure.
    limit = min(2, count) if count else 2
    for entry in context.get('rounds', [])[-limit:]:
        try:
            results.append(json.loads(Path(entry['manifest_path']).read_text(encoding='utf-8')))
        except (OSError, ValueError, KeyError):
            results.append({'platform_outcomes':entry.get('platform_outcomes', {})})
    return results


def choose_strategy(plan, context=None, history=None):
    context = context or {}
    previous = _last_results(context)
    latest = previous[-1] if previous else {}
    outcomes = latest.get('platform_outcomes', {})
    reasons = {}
    for outcome in outcomes.values():
        for reason, count in outcome.get('reasons', {}).items():
            reasons[reason] = reasons.get(reason, 0) + count
    last_phase = next((r.get('strategy') for r in reversed(latest.get('search_audit', []))
                       if attempted(r) and r.get('strategy')), latest.get('search_strategy', {}).get('phase'))
    phase, explanation = 'core_action', ['캡션·음성·화면에서 확인한 핵심 행동을 우선 검색']
    if previous:
        if reasons.get('download_failed', 0) > reasons.get('quality_rejected', 0):
            phase = 'alternate_access'
            explanation = ['이전 후보 다운로드 실패: 실패 플랫폼을 쉬고 다른 수신 경로로 전환']
        elif reasons.get('quality_rejected', 0):
            phase = 'scene_discovery' if last_phase == 'clean_action' else 'clean_action'
            explanation = ['이전 후보가 검증에서 탈락: 원본·무자막 또는 다른 클로즈업 장면으로 조건 변경']
        else:
            phase = 'scene_discovery' if last_phase != 'scene_discovery' else 'clean_action'
            explanation = ['이전 회차에서 유효 소스 증가 없음: 다른 장면·검색 조건으로 전환']
    routes = [*TEXT_ROUTES, *IMAGE_ROUTES]
    skipped = {}
    audits = latest.get('search_audit', [])
    for provider in routes:
        unresolved = [r for r in audits if r.get('provider') == provider
                      and r.get('status') in {'page_unresolved','readiness_blocked'}
                      and r.get('parser_revision') == parser_revision(provider)]
        if unresolved and provider not in context.get('rechecked_routes',[]):
            skipped[provider] = '검색 화면 판독 실패 · 같은 판독기로 검색어만 바꿔 재접근하지 않음'
        rows = [r for r in audits if r.get('provider') == provider and attempted(r)]
        if rows and all(r.get('status') in {'no_results','error','http_error','timeout'} and not r.get('candidates') for r in rows):
            skipped[provider] = '이전 회차의 모든 검색에서 후보 없음·요청 실패 · 이번 회차 다른 경로 사용'
    if phase == 'alternate_access':
        for provider, outcome in outcomes.items():
            if outcome.get('reasons', {}).get('download_failed') and not outcome.get('usable'):
                skipped[provider] = '이전 회차 다운로드 실패 · 이번 회차 다른 플랫폼 사용'
    # Prevent the image upload phase consuming the whole text-search budget.
    # When text yielded nothing, give *new scenes* the first browser budget.
    if phase == 'scene_discovery' and not reasons.get('quality_rejected'):
        routes = [*IMAGE_ROUTES, *TEXT_ROUTES]
    elif phase == 'alternate_access':
        routes = ['youtube', 'bing', 'bilibili', 'tiktok', 'douyin', 'xiaohongshu',
                  'duckduckgo', *IMAGE_ROUTES]
    routes = [r for r in routes if r not in skipped]
    kinds = {plan.get('subject_kind')}
    if any(p.get('en') in {'minced garlic preparation','honey garlic soy chicken',
                           'pan fried fish cooking','rice flour recipe','tile repair'}
           for p in plan.get('products', [])):
        kinds.add('recipe')
    vendor = bool(plan.get('products') or plan.get('subject_kind') == 'product') and 'recipe' not in kinds and 'repair' not in kinds
    strategy = {'version':2, 'phase':phase, 'label':LABELS[phase], 'reasons':explanation,
                'previous_failure_counts':reasons, 'routes':routes, 'skipped_routes':skipped,
                'vendor_search':vendor, 'completed_rounds':context.get('completed_rounds',0)}
    if history:
        from ..source_queries import platform_queries
        blocked = context.get('blocked_routes', [])
        # A resumed budget must not rewind to an exhausted objective. Include
        # the indexed corpus, but do not mistake an auth-blocked site's unused
        # query pool for a runnable text search.
        phases = list(dict.fromkeys([phase, 'clean_action', 'scene_discovery']))
        for proposed in phases:
            candidate = {**strategy, 'phase':proposed}
            words = [q['query'] for q in round_queries(plan, candidate)]
            usable = False
            for provider in routes:
                if provider not in TEXT_ROUTES or provider in blocked:
                    continue
                pool = platform_queries(words,provider,len(words))
                if provider in {'duckduckgo','bing'}:
                    pool += [q+' site:tiktok.com/@ inurl:video' for q in words]
                if fresh_queries(pool,provider,history):
                    usable = True
                    break
            if usable:
                if proposed != phase:
                    strategy.update(phase=proposed, label=LABELS[proposed])
                    strategy['reasons'].append('이전 이력에서 같은 행동·조건 검색을 이미 수행해 미사용 영상 조건으로 전환')
                break
    return strategy


def round_queries(plan, strategy):
    details = plan.get('query_details', [])
    actions = [d for d in details if d.get('role') == 'subject_action'
               and d.get('evidence_quote') and d.get('intent') != 'close_up_footage']
    if not actions:
        # No observed action: retain grounded subject phrases, never invent one.
        actions = [d for d in details if d.get('intent') in {'product','unbranded','subject','action'}]
    if not actions:
        actions = details
    phase = strategy['phase']
    suffixes = {'clean_action': {'en':'raw footage no captions', 'ko':'원본 영상 자막 없는', 'zh':'实拍 无字幕'},
                'scene_discovery': {'en':'close up footage', 'ko':'클로즈업 영상', 'zh':'特写视频'}}
    result, seen = [], set()
    for row in actions:
        item = dict(row)
        suffix = suffixes.get(phase, {}).get(item.get('language'))
        if suffix:
            item['query'] = item['query'] + ' ' + suffix
            item['search_condition'] = phase
        identity = query_fingerprint(item['query'])
        if identity not in seen and item['query'].strip():
            result.append(item); seen.add(identity)
    return result


def annotate_audit(audit, strategy):
    for row in audit:
        row.setdefault('strategy', strategy['phase'])
        if row.get('query') and row.get('language') != 'image':
            row['semantic_key'] = query_fingerprint(row['query'])
