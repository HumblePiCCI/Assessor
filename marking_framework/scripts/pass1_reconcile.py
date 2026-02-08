import copy
import re

from scripts.levels import score_to_percent


def _token(value) -> str:
    return re.sub(r"[^A-Za-z0-9+]", "", str(value or "").upper())


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(value)))


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _to_percent(value) -> float | None:
    pct = score_to_percent(value)
    if pct is None:
        return None
    return float(pct)


def _scores_from_points(criteria_points: dict, required_ids: list[str]) -> tuple[dict[str, float], list[float]]:
    source = {}
    for key, value in (criteria_points or {}).items():
        score = _to_percent(value)
        token = _token(key)
        if score is None or not token:
            continue
        source[token] = score
    matched = {}
    for cid in required_ids:
        token = _token(cid)
        score = source.get(token)
        if score is not None:
            matched[cid] = score
    return matched, list(matched.values())


def _scores_from_evidence(evidence: list[dict], required_ids: list[str]) -> tuple[dict[str, float], list[float]]:
    required_by_token = {_token(cid): cid for cid in required_ids}
    matched = {}
    all_scores = []
    for entry in evidence or []:
        if not isinstance(entry, dict):
            continue
        score = _to_percent(entry.get("score"))
        if score is None:
            score = _to_percent(entry.get("level"))
        if score is None:
            continue
        all_scores.append(score)
        key = _token(entry.get("criterion_id") or entry.get("criteria_id") or entry.get("criterion"))
        cid = required_by_token.get(key)
        if cid and cid not in matched:
            matched[cid] = score
    return matched, all_scores


def _coverage(required_ids: list[str], points: dict[str, float], evidence: dict[str, float], evidence_total: int) -> float:
    if not required_ids:
        return 1.0
    point_count = len(points)
    evidence_count = len(evidence) if evidence else min(evidence_total, len(required_ids))
    return max(point_count, evidence_count) / max(1, len(required_ids))


def reconcile_pass1_item(item: dict, required_ids: list[str] | None) -> dict:
    result = copy.deepcopy(item)
    required = list(required_ids or [])
    points = result.get("criteria_points") if isinstance(result.get("criteria_points"), dict) else {}
    evidence = result.get("criteria_evidence") if isinstance(result.get("criteria_evidence"), list) else []
    points_by_required, point_scores = _scores_from_points(points, required)
    evidence_by_required, evidence_scores = _scores_from_evidence(evidence, required)
    point_mean = _mean(point_scores)
    evidence_mean = _mean(list(evidence_by_required.values()) or evidence_scores)
    total = _to_percent(result.get("rubric_total_points"))
    if total is None:
        total = evidence_mean if evidence_mean is not None else point_mean
    if total is None:
        total = 0.0
    coverage = _coverage(required, points_by_required, evidence_by_required, len(evidence_scores))
    if evidence_mean is not None and coverage >= 0.6 and abs(total - evidence_mean) >= 20.0:
        total = evidence_mean
    elif point_mean is not None and coverage >= 0.75:
        total = point_mean if evidence_mean is None else ((0.6 * point_mean) + (0.4 * evidence_mean))
    result["rubric_total_points"] = round(_clamp(total), 2)
    baseline = evidence_mean if evidence_mean is not None else point_mean
    coherence = abs(result["rubric_total_points"] - baseline) if baseline is not None else 99.0
    result["_criterion_coverage"] = round(_clamp(coverage, 0.0, 1.0), 4)
    result["_score_coherence"] = round(float(coherence), 4)
    return result


def guard_parameters(item: dict, max_score_delta: float, max_level_gap: int, anchor_blend: float) -> tuple[float, int, float]:
    coverage = float(item.get("_criterion_coverage", 0.0) or 0.0)
    coherence = float(item.get("_score_coherence", 99.0) or 99.0)
    if coverage >= 0.75 and coherence <= 12.0:
        return 100.0, max(4, int(max_level_gap or 1)), 0.0
    if coverage >= 0.5 and coherence <= 20.0:
        return max(35.0, float(max_score_delta or 0.0)), max(3, int(max_level_gap or 1)), min(float(anchor_blend or 0.0), 0.1)
    return float(max_score_delta), int(max_level_gap), float(anchor_blend)


def strip_internal_fields(item: dict) -> dict:
    result = copy.deepcopy(item)
    for key in list(result.keys()):
        if key.startswith("_"):
            result.pop(key, None)
    return result
