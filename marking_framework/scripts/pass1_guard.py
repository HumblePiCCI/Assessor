import copy

from scripts.levels import normalize_level


LEVEL_ANCHORS = {"1": 54.0, "2": 64.0, "3": 75.0, "4": 84.0, "4+": 95.0}
LEVEL_ORDER = ["1", "2", "3", "4", "4+"]


def _rank(score: float) -> int | None:
    level = normalize_level(score)
    if level is None:
        return None
    return LEVEL_ORDER.index(level)


def _anchor_for_rank(rank: int) -> float:
    key = LEVEL_ORDER[max(0, min(rank, len(LEVEL_ORDER) - 1))]
    return LEVEL_ANCHORS[key]


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(value)))


def stabilize_pass1_item(item: dict, fallback_item: dict, max_score_delta: float, max_level_gap: int) -> dict:
    result = copy.deepcopy(item)
    raw = float(result.get("rubric_total_points", 0.0) or 0.0)
    anchor = float(fallback_item.get("rubric_total_points", 0.0) or 0.0)
    original = raw
    if max_score_delta >= 0 and abs(raw - anchor) > max_score_delta:
        raw = anchor + (max_score_delta if raw > anchor else -max_score_delta)
    r_raw = _rank(raw)
    r_anchor = _rank(anchor)
    if r_raw is not None and r_anchor is not None and abs(r_raw - r_anchor) > max_level_gap:
        allowed = r_anchor + (max_level_gap if r_raw > r_anchor else -max_level_gap)
        raw = _anchor_for_rank(allowed)
    raw = round(_clamp(raw), 2)
    result["rubric_total_points"] = raw
    delta = raw - original
    if abs(delta) > 0.001 and isinstance(result.get("criteria_points"), dict):
        shifted = {}
        for key, value in result["criteria_points"].items():
            if isinstance(value, (int, float)):
                shifted[key] = round(_clamp(float(value) + delta), 2)
            else:
                shifted[key] = value
        result["criteria_points"] = shifted
    return result
