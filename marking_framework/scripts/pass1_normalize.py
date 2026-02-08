import re

from scripts.levels import coerce_level_and_score_to_percent, score_to_percent


def canonical_token(value) -> str:
    return re.sub(r"[^A-Za-z0-9+]", "", str(value or "").upper())


def criterion_lookup(required_ids: list | None) -> dict:
    lookup = {}
    for cid in required_ids or []:
        token = canonical_token(cid)
        if token:
            lookup[token] = cid
    return lookup


def canonical_criterion_id(value, lookup: dict) -> str:
    token = canonical_token(value)
    if not token:
        return ""
    if token in lookup:
        return lookup[token]
    for known, canonical in lookup.items():
        if token.startswith(known) or known.startswith(token):
            return canonical
    return token


def rescue_pass1_item(text: str, student_id: str, required_ids: list | None) -> dict:
    # Best-effort extraction for malformed model output.
    lookup = criterion_lookup(required_ids)
    points = {}
    for token, cid in lookup.items():
        pattern = rf"\b{re.escape(token)}\b[^0-9\n]{{0,16}}(?:LEVEL\s*)?(4\+|[1-4]|[0-9]{{1,3}}(?:\.[0-9]+)?)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw = match.group(1)
        level, percent = coerce_level_and_score_to_percent(raw, raw)
        score = percent if level else score_to_percent(float(raw))
        if isinstance(score, (int, float)):
            points[cid] = float(score)
    total = None
    total_match = re.search(r"rubric[_\s-]*total[_\s-]*points[^0-9]{0,12}([0-9]{1,3}(?:\.[0-9]+)?)", text, flags=re.IGNORECASE)
    if total_match:
        total = score_to_percent(float(total_match.group(1)))
    if total is None and points:
        total = sum(points.values()) / len(points)
    return {
        "student_id": student_id,
        "rubric_total_points": float(total) if isinstance(total, (int, float)) else None,
        "criteria_points": points,
        "criteria_evidence": [],
        "notes": text.strip()[:500],
    }
