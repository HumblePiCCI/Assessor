import json
import re
from pathlib import Path


def load_rubric_criteria(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def total_points(criteria: dict) -> int | None:
    total = 0
    for category in criteria.get("categories", {}).values():
        total += int(category.get("max_points", 0) or 0)
    return total if total > 0 else None


def _base_criteria(criteria: dict) -> list:
    items = []
    for category in criteria.get("categories", {}).values():
        for item in category.get("criteria", []):
            items.append(item)
    return items


def criteria_for_genre(criteria: dict, genre: str | None) -> list:
    items = _base_criteria(criteria)
    if not genre:
        return items
    extras = criteria.get("genre_specific_criteria", {}).get(genre, {}).get("additional_criteria", [])
    return items + list(extras)


def criteria_ids(criteria: dict, genre: str | None) -> list:
    return [c.get("id") for c in criteria_for_genre(criteria, genre) if c.get("id")]


def criteria_prompt(criteria: dict, genre: str | None) -> str:
    if not criteria:
        return ""
    parts = ["CRITERIA (use these IDs exactly):"]
    for item in criteria_for_genre(criteria, genre):
        cid = item.get("id")
        name = item.get("name", "")
        desc = item.get("description", "")
        if cid:
            parts.append(f"- {cid}: {name} — {desc}")
            indicators = item.get("indicators")
            if isinstance(indicators, dict):
                for level, text in indicators.items():
                    parts.append(f"  Level {level}: {text}")
    return "\n".join(parts)


def evidence_requirements(criteria: dict) -> dict:
    return criteria.get("evidence_requirements", {})


def _canonical_token(value) -> str:
    return re.sub(r"[^A-Za-z0-9+]", "", str(value or "").upper())


def validate_criteria_evidence(items: list | None, required_ids: list, reqs: dict) -> list:
    errors = []
    if not required_ids:
        return errors
    if not isinstance(items, list) or not items:
        errors.append("Missing criteria evidence list.")
        return errors
    required_map = {_canonical_token(cid): cid for cid in required_ids}
    by_id = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        cid = item.get("criterion_id")
        if not cid:
            cid = item.get("criteria_id")
        if not cid:
            cid = item.get("criterion")
        if not cid:
            cid = item.get("criteria")
        if cid:
            token = _canonical_token(cid)
            canonical = required_map.get(token)
            if canonical:
                by_id[canonical] = item
    for cid in required_ids:
        entry = by_id.get(cid)
        if not entry:
            errors.append(f"Missing evidence for {cid}.")
            continue
        if reqs.get("quote_validation", True):
            quote = entry.get("evidence_quote") or entry.get("evidence", "")
            if not isinstance(quote, str) or not quote.strip():
                errors.append(f"Missing evidence quote for {cid}.")
        rationale = entry.get("rationale", "")
        min_words = int(reqs.get("rationale_min_words", 0) or 0)
        if min_words and len(str(rationale).split()) < min_words:
            errors.append(f"Rationale too short for {cid}.")
        score = entry.get("score")
        level = entry.get("level")
        if not isinstance(score, (int, float)) and (not isinstance(level, str) or not level.strip()):
            errors.append(f"Missing score/level for {cid}.")
    return errors
