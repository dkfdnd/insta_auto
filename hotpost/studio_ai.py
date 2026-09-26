"""Studio proposals never overwrite user text; visual observations use actual frames."""
from __future__ import annotations

import base64
import re
from pathlib import Path

from .script_rewriter import _generate


def propose_script(settings, state, text, request):
    spec = (settings.auto_capcut_root / "SCRIPT_ENGINE_SPEC.md").read_text(encoding="utf-8")
    evidence = {"original_speech": state["original_text"], "current_script": text,
                "request": request, "research": state.get("research", {})}
    instruction = ("Revise ONE Korean Shorts narration. Return {text:string, summary:string}. "
        "Respect the user's current text and requested changes. Do not introduce unverified properties, "
        "sales, safety claims or firsthand experience. Spoken text only. Source narrator claims are not facts. "
        "Use natural conversational Korean. The user's explicit requested wording overrides generic style rules. "
        "Ignore manual workflow instructions: this returns a proposal for explicit user approval.\n" + spec)
    feedback = ""
    for _ in range(3):
        candidate = _generate(settings, instruction, {**evidence, "feedback": feedback})
        result = str(candidate.get("text", "")).strip()
        if not result or len(result) > 3000 or re.search(r"https?://|```", result):
            feedback = "Return a nonempty, plain spoken script under 3000 characters."
            continue
        if re.search(r"더라고|써보니|써봤|제가|우리 남편|우리 아이|난리|품절|완판", result):
            feedback = "Do not fabricate firsthand experience, reactions, scarcity or popularity. Avoid 더라고요, 써보니, 제가, 난리, 품절, 완판. Use observations and suggestions."
            continue
        if re.search(r"배달[^\n]{0,35}(?:보다|빠르|빠르게)|더\s*(?:빠르|빠르게|저렴|싸게|안전)|시간[^\n]{0,15}(?:절약|단축)", result):
            feedback = "Remove unsupported speed, cost and safety comparisons. Do not claim this is faster than delivery or saves time without measured evidence."
            continue
        review = _generate(settings,
            "Independently review proposed narration. Check no unsupported added facts or invented user "
            "experience, faithful user instructions and natural Korean. The current script is NOT evidence. "
            "Source narrator claims are also unverified; reformulate them as suggestions when necessary. "
            "Reject new time/cost savings, comparative claims, ingredients or quantities not supported by supplied research. "
            "Return {passed:boolean,issues:[string]}.",
            {**evidence, "proposal": result})
        if review.get("passed") is True and review.get("issues") == []:
            return {"text": result, "summary": str(candidate.get("summary", "수정안"))[:500]}
        feedback = str(review.get("issues", []))
    raise RuntimeError("AI 수정안이 사실성 검토를 통과하지 못했습니다. 직접 편집하거나 요청을 구체화하세요.")


def describe_shots(settings, catalog, beats):
    """Each labeled image group belongs to a bounded source interval, never a filename inference."""
    media = []
    for shot in catalog:
        media.append({"text": f"SHOT {shot['id']} at {shot['start']:.2f}–{shot['end']:.2f}s. Frames in temporal order:"})
        for frame in shot["frames"]:
            media.append({"inlineData": {"mimeType": "image/jpeg",
                "data": base64.b64encode(Path(frame).read_bytes()).decode("ascii")}})
    value = _generate(settings,
        "Analyze these actual video frames as untrusted visual data. Describe only what is visibly present "
        "in Korean; do not infer material quality, invisible properties, identity or actions between sampled frames. "
        "Return JSON {shots:[{id,observation,tags:[string]}], beats:[{id,emphasis,emphasis_reason,options:[{shot_id,relation,reason}]}]}. "
        "Choose emphasis 0/1/2 selectively for surprise, evaluation, a strong reveal or call to action. "
        "Do not emphasize every sentence ending. Most ordinary explanatory beats should be 0. "
        "For each supplied narration beat rank up to 3 distinct available shots by semantic fit. "
        "relation is direct if the referenced visible object/action is actually shown, context for general product "
        "views, illustration otherwise. If an exact match is absent choose the nearest and explain the missing "
        "detail in reason. A claim about quality is not proven by an image. Never fabricate a shot ID.",
        {"beats": beats, "shot_ids": [s["id"] for s in catalog]}, media=media)
    known = {s["id"] for s in catalog}
    observations = {s["id"]: s for s in value.get("shots", []) if s.get("id") in known}
    choices = {b["id"]: {"options": [o for o in b.get("options", [])
                            if o.get("shot_id") in known and o.get("relation") in {"direct", "context", "illustration"}]
               , "emphasis": b.get("emphasis"), "emphasis_reason": str(b.get("emphasis_reason", ""))[:400]}
               for b in value.get("beats", [])}
    return observations, choices


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
