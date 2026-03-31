from __future__ import annotations
import re


LEVEL_TO_PERCENT = {
    "1": 54.0,
    "2": 64.0,
    "3": 75.0,
    "4": 84.0,
    "4+": 95.0,
}


def normalize_level(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        # Treat small numbers as levels (1-4/4+). Treat larger values as percent.
        if 0.0 <= num <= 4.5:
            if num >= 4.5:
                return "4+"
            if num >= 4.0:
                return "4"
            if num >= 3.0:
                return "3"
            if num >= 2.0:
                return "2"
            if num >= 1.0:
                return "1"
            return None
        if 0.0 <= num <= 100.0:
            if num >= 90.0:
                return "4+"
            if num >= 80.0:
                return "4"
            if num >= 70.0:
                return "3"
            if num >= 60.0:
                return "2"
            if num >= 50.0:
                return "1"
            return None
        return None
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    if not lowered:
        return None
    lowered = lowered.replace("level", "").replace(":", "").strip()
    lowered = lowered.replace("plus", "+").replace(" ", "")
    if lowered in {"4+", "4plus"}:
        return "4+"
    if lowered in {"4", "3", "2", "1"}:
        return lowered
    return None


def level_to_percent(level: str) -> float | None:
    return LEVEL_TO_PERCENT.get(level)


def score_to_percent(score) -> float | None:
    if isinstance(score, str):
        token = score.strip().lower().replace("%", "")
        lvl = normalize_level(token)
        if lvl:
            return level_to_percent(lvl)
        if not token:
            return None
        token = re.sub(r"[^0-9.+-]", "", token)
        if not token:
            return None
        try:
            score = float(token)
        except ValueError:
            return None
    if not isinstance(score, (int, float)):
        return None
    if 0.0 <= float(score) <= 4.5:
        lvl = normalize_level(float(score))
        return level_to_percent(lvl) if lvl else None
    if 0.0 <= float(score) <= 100.0:
        return float(score)
    return None


def coerce_level_and_score_to_percent(level_value, score_value) -> tuple[str | None, float | None]:
    lvl = normalize_level(level_value)
    if lvl:
        return lvl, level_to_percent(lvl)
    pct = score_to_percent(score_value)
    if pct is None:
        return None, None
    inferred = normalize_level(pct)
    return inferred, pct
