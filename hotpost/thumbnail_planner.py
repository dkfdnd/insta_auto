"""Provider-independent editorial plan. No TTS, browser, or CapCut imports.

Seven levers are configurable editorial heuristics, not a universal scientific
taxonomy or a promise of conversion. Copy remains separate from spoken script.
"""
from __future__ import annotations

import hashlib

LEVERS = {
    "curiosity": "호기심", "loss_aversion": "손실 회피", "contrast": "대조",
    "specificity": "구체성", "self_relevance": "자기 관련성",
    "social_proof": "사회적 증거", "scarcity": "희소성",
}


def validate_caption(text: str) -> str:
    """A short hook can have an intentional setup/payoff line break."""
    if (not isinstance(text, str) or not 1 <= len(text.strip()) <= 20
            or any(c in text for c in "\r\t") or len(text.split("\n")) > 2
            or any(not line.strip() for line in text.split("\n"))):
        raise ValueError("caption needs 1–2 nonempty lines, at most 20 characters total")
    return text.strip()


def create_plan(*, subject: str, script: str, feature: str = "",
                claims: dict | None = None, preferred: str = "curiosity",
                custom_hook: dict | None = None,
                visual_direction: dict | None = None,
                caption_placement: str = "upper_third") -> dict:
    """Generate conservative candidates; evidence-heavy levers are opt-in.

    `claims` entries: {lever: {text, evidence, source, reviewed: true}}. The
    caller owns factual/semantic review; string checks cannot prove truth.
    """
    subject = subject.strip()
    if not subject or len(subject) > 12 or any(c in subject for c in "\r\n\t"):
        raise ValueError("subject must be a short, approved product/topic label")
    if not script.strip():
        raise ValueError("script is required for topic grounding")
    if preferred not in LEVERS:
        raise ValueError("unknown hook lever")
    if feature and (feature not in script or len(feature) > 10 or "\n" in feature):
        raise ValueError("feature must be a short verbatim phrase from the script")
    templates = {
        "curiosity": f"{subject}, 왜 눈길이 갈까?",
        "loss_aversion": f"{subject} 사기 전 볼 것",
        "contrast": f"{subject}, 보기와 다를까?",
        "self_relevance": f"내게 맞는 {subject}일까?",
    }
    if feature:
        templates["specificity"] = f"{feature}, 직접 확인"
    candidates = []
    for lever, label in LEVERS.items():
        claim = (claims or {}).get(lever)
        evidence = "approved subject/script; rhetorical question, not a popularity claim"
        text = templates.get(lever)
        if lever in {"social_proof", "scarcity"} and claim:
            if (claim.get("reviewed") is not True or not claim.get("source")
                    or not claim.get("evidence") or not isinstance(claim.get("text"), str)):
                raise ValueError(f"{lever} requires reviewed evidence and source")
            text, evidence = claim["text"].strip(), claim
        if text and (len(text) > 20 or any(c in text for c in "\r\n\t")):
            text = None
        candidates.append({"lever": lever, "label": label, "text": text,
                           "eligible": bool(text), "evidence": evidence if text else None})
    eligible = [c for c in candidates if c["eligible"]]
    if not eligible:
        raise ValueError("No candidate fits the one-line length limit")
    selected = next((c for c in eligible if c["lever"] == preferred), eligible[0])
    if custom_hook is not None:
        text, lever = custom_hook.get("text"), custom_hook.get("lever")
        quote = custom_hook.get("script_quote")
        text = validate_caption(text)
        if (lever not in LEVERS
                or not isinstance(quote, str) or not quote.strip() or quote not in script):
            raise ValueError("custom_hook needs short copy, a known lever and a script quote")
        if lever in {"scarcity", "social_proof"}:
            raise ValueError("Use reviewed claims for scarcity/social proof, not custom_hook")
        selected = {"text": text.strip(), "lever": lever, "label": LEVERS[lever],
                    "eligible": True, "evidence": {"script_quote": quote}, "origin": "editorial"}
        candidates.append(selected)
    if caption_placement not in {"top", "upper_third", "center"}:
        raise ValueError("Unknown caption_placement")
    if visual_direction is not None:
        if not isinstance(visual_direction, dict):
            raise ValueError("visual_direction must be an object")
        for key in ("desire", "scene", "composition"):
            if not isinstance(visual_direction.get(key), str) or not visual_direction[key].strip():
                raise ValueError(f"visual_direction requires {key}")
    return {"schema_version": "1.0", "subject": subject,
            "script_sha256": hashlib.sha256(script.encode("utf-8")).hexdigest(),
            "candidates": candidates, "selected": selected,
            "review_required": True,
            "image_brief": {
                "caption_placement": caption_placement,
                "visual_direction": visual_direction,
                "quality_checks": ["At feed size, product and desired outcome read immediately.",
                                   "Image makes the headline's promise visible, not just decorative.",
                                   "Strong focal contrast; no unsupported scarcity, prices or endorsements."],
                "subject": subject, "aspect_ratio": "9:16", "text_in_image": False,
                "reference_required": True,
                "composition": "Product clearly visible in the lower half; leave the central caption band uncluttered.",
                "constraints": ["Preserve the reference product's shape, color, material and existing branding.",
                                "Do not invent logos, labels, features, endorsements or before/after results.",
                                "No captions, promotional text, added watermarks or UI elements.",
                                "Use a clean editorial background and soft directional lighting."]}}


def flow_prompt(plan: dict) -> str:
    brief = plan["image_brief"]
    direction = brief.get("visual_direction")
    creative = (f"Viewer desire: {direction['desire']}\nScene: {direction['scene']}\n"
                f"Composition: {direction['composition']}\n" if direction else brief["composition"] + "\n")
    constraints = brief["constraints"]
    if direction:
        constraints = [c for c in constraints if c != "Use a clean editorial background and soft directional lighting."]
    return (f"Create ONE photorealistic vertical 9:16 editorial cover still for {brief['subject']}.\n"
            "Use the attached, authorized product reference image as the identity anchor.\n"
            + creative + "\n".join(constraints) + "\n"
            "Keep the product fully recognizable. Korean hook text will be added separately in CapCut.")
