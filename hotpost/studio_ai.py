"""Studio proposals never overwrite user text; visual observations use actual frames."""
from __future__ import annotations

import re
from pathlib import Path

from .script_rewriter import _generate


def propose_script(settings, state, text, request):
    from .reference_context import reference_kind
    evidence = {"purpose": "script_revision", "original_speech": state.get('reviewed_original_text', state['original_text']), "current_script": text,
                "reference_kind":reference_kind(state),
                "hook_contract":state.get('benchmark_analysis', {}).get('hook_contract', {}),
                "request": request, "research": state.get("research", {})}
    instruction = ("Revise ONE Korean Shorts narration. Return {text:string, summary:string}. "
        "Apply the internal shared writing contract and the user's requested changes. "
        "This returns a proposal; preserve the user's saved text until they apply it.")
    if state.get('creation_mode') == 'self_shot':
        instruction += (' This is an original owned-footage project without a benchmark hook. '
            'Create or revise the hook under the same short product-hook style. Use only supplied product facts '
            'and explicitly supplied real user experience. Do not enforce benchmark copying or original hook preservation.')
    feedback = ""
    best = None
    for attempt in range(3):  # one draft, at most two repairs
        candidate = _generate(settings, instruction, {**evidence, "feedback": feedback})
        result = str(candidate.get("text", "")).strip()
        if not result or len(result) > 3000 or re.search(r"https?://|```", result):
            feedback = "Return a nonempty plain spoken script under 3000 characters."
            continue
        try:
            review = _generate(settings,
                "Independently review ONLY the proposed narration under the common writing contract. "
                "Grade only claims still in the proposal; deleting an unsupported earlier claim is correct. "
                "Return {passed:boolean,issues:[string]}. "
                "Explain issues using actual proposal wording in Korean.",
                {"purpose":"script_review", "original_speech":evidence['original_speech'], "proposal":result,
                 "reference_kind":evidence['reference_kind'],
                 "research":state.get('research', {}), "hook_contract":evidence['hook_contract']})
        except (RuntimeError, ValueError, OSError) as exc:
            review = {'passed':False, 'issues':['자동 평가 미완료: '+str(exc)[:200]], 'status':'unavailable'}
        issues = review.get('issues', [])
        if not isinstance(issues, list): issues = ['평가 응답 형식 미확인']
        value = {"text":result, "summary":str(candidate.get('summary','수정안'))[:500],
                 "editorial_review":{**review, 'advisory_only':True}, 'repairs_attempted':attempt}
        score = (review.get('passed') is True and not issues, -len(issues))
        if best is None or score > best[0]: best = (score, value)
        if score[0]: return value
        feedback = str(issues)
    if best: return best[1]
    raise RuntimeError("AI가 사용할 수 있는 낭독문을 반환하지 못했습니다. 저장한 대본은 유지됩니다.")


def restrict_context_shots(plan, sources):
    """Carry hash-bound usage limits; context-only footage stays non-direct."""
    context = {}
    restrictions = {}
    for source in sources:
        review = source.get('functional_review') or {}
        if (review.get('reviewed') is True and review.get('context_usage_limits')
                and review.get('source_sha256') == source.get('sha256')):
            path = str(Path(source['path']).resolve())
            restrictions[path] = review['context_usage_limits']
            if review.get('same_core_function') is False and review.get('context_usable') is True:
                context[path] = review['context_usage_limits']
    ids = set()
    for shot in plan['shots']:
        path = str(Path(shot['path']).resolve())
        limits = restrictions.get(path)
        if limits:
            shot['context_usage_limits'] = [limits] if isinstance(limits, str) else list(limits)
        limits = context.get(path)
        if limits:
            shot.update(source_role='context_only', context_usage_limits=[limits] if isinstance(limits, str) else list(limits))
            ids.add(shot['id'])
    for beat in plan['beats']:
        for option in beat.get('options', []):
            if option.get('shot_id') in ids and option.get('relation') == 'direct':
                option.update(relation='context', reason='보조 상황 장면 · 핵심 동작의 증거로 사용하지 않음. '+str(option.get('reason','')))


def describe_shots(settings, catalog, beats):
    """Stable entry point for bounded observations followed by text-only ranking."""
    from .scene_analysis import analyze_shots
    return analyze_shots(settings, catalog, beats, _generate)


def plan_revision(settings, plan, request, start, end):
    value = _generate(settings,
        "Interpret a Korean video edit request. Return {changes:[{beat_id,emphasis,choose_candidates}], "
        "summary:string}. Only include beats overlapping the selected interval. emphasis may be 0 (off), "
        "1 (clear), 2 (strong). Set choose_candidates:true for a requested visual replacement; do not select "
        "a replacement yourself. Multiple requested changes are allowed. Do not change spoken text or timing. "
        "If the request cannot be represented return {changes:[],summary: explanation in Korean}.",
        {"request": request, "selection": [start, end], "beats": plan["beats"]})
    allowed = {b["id"] for b in plan["beats"] if b["start"] < end and b["end"] > start}
    changes = [c for c in value.get("changes", []) if c.get("beat_id") in allowed]
    for c in changes:
        if "emphasis" in c and (type(c["emphasis"]) is not int or c["emphasis"] not in (0, 1, 2)):
            raise ValueError("AI 효과 강도 응답이 올바르지 않습니다.")
    return {"changes": changes, "summary": str(value.get("summary", ""))[:600]}
