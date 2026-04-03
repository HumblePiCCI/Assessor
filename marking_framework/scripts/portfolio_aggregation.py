#!/usr/bin/env python3
import copy
import json
import re
from pathlib import Path

try:
    from scripts.aggregate_helpers import get_level_band, get_level_bands
except ImportError:  # pragma: no cover - Running as a script
    from aggregate_helpers import get_level_band, get_level_bands  # pragma: no cover


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clean_text(value: str | None) -> str:
    return " ".join(str(value or "").lower().split())


def parse_portfolio_note_signal(note: str | None) -> dict | None:
    text = _clean_text(note)
    if not text:
        return None

    reasons = []
    estimate = None

    if re.search(r"\b(wts|working towards)\b", text):
        if re.search(r"low[- ]expected|low[- ]exs|boundary|near expected|towards/low|towards / low", text):
            estimate = 2.3
            reasons.append("working_towards_boundary")
        else:
            estimate = 2.0
            reasons.append("working_towards")
    elif re.search(r"\bworking at(?: the)? expected standard\b|\bexpected standard\b|\bexs\b", text):
        if re.search(r"greater depth|above expected|toward(?:s)? greater depth|near greater depth|at/near greater depth", text):
            estimate = 3.55
            reasons.append("expected_plus_strengths")
        else:
            estimate = 3.0
            reasons.append("expected_standard")
    elif re.search(r"greater depth|above expected|toward(?:s)? greater depth|near greater depth|at/near greater depth|greater-depth control", text):
        estimate = 3.6
        reasons.append("greater_depth")

    if estimate is None:
        positives = 0
        negatives = 0
        positive_markers = (
            "strong range",
            "generally effective",
            "effective execution",
            "clear understanding",
            "solid execution",
            "confident",
            "sophisticated",
            "coherent",
            "above expected",
        )
        negative_markers = (
            "frequent spelling errors",
            "inconsistent punctuation",
            "reduces clarity",
            "working towards",
            "not secure",
            "uneven",
            "inconsistent across pieces",
            "low expected",
        )
        positives = sum(1 for marker in positive_markers if marker in text)
        negatives = sum(1 for marker in negative_markers if marker in text)
        if positives or negatives:
            estimate = max(2.0, min(3.6, 3.0 + (0.18 * positives) - (0.2 * negatives)))
            reasons.append("sentiment_fallback")

    if estimate is None:
        return None

    return {
        "estimate": round(float(estimate), 2),
        "reasons": reasons,
    }


def signal_from_portfolio_fields(score: dict | None) -> dict | None:
    if not isinstance(score, dict):
        return None
    level = str(score.get("portfolio_overall_level", "") or "").strip()
    if not level:
        aggregation = score.get("portfolio_aggregation") or {}
        level = str(aggregation.get("overall_level", "") or "").strip()
    mapping = {
        "1": 1.0,
        "2": 2.0,
        "3": 3.0,
        "4": 3.6,
        "4+": 4.2,
    }
    estimate = mapping.get(level)
    if estimate is None:
        return None
    return {
        "estimate": round(float(estimate), 2),
        "reasons": ["portfolio_piece_aggregation"],
    }


def _score_range_for_estimate(estimate: float) -> dict:
    value = float(estimate)
    if value >= 3.45:
        return {"canonical_level": "4", "min_score": 80.0, "max_score": 89.0, "anchor_score": 84.0}
    if value >= 3.05:
        return {"canonical_level": "4", "min_score": 74.0, "max_score": 84.0, "anchor_score": 79.0}
    if value >= 2.55:
        return {"canonical_level": "3", "min_score": 70.0, "max_score": 79.0, "anchor_score": 74.0}
    if value >= 2.2:
        return {"canonical_level": "3", "min_score": 64.0, "max_score": 74.0, "anchor_score": 69.0}
    if value < 1.75:
        return {"canonical_level": "1", "min_score": 50.0, "max_score": 59.0, "anchor_score": 54.0}
    return {"canonical_level": "2", "min_score": 60.0, "max_score": 69.0, "anchor_score": 64.0}


def _student_summary(votes: list[dict]) -> dict:
    if not votes:
        return {}
    estimates = [float(vote["estimate"]) for vote in votes]
    mean_estimate = sum(estimates) / len(estimates)
    score_range = _score_range_for_estimate(mean_estimate)
    return {
        "note_votes": len(votes),
        "note_estimate_mean": round(mean_estimate, 2),
        "note_canonical_level": score_range["canonical_level"],
        "note_anchor_score": score_range["anchor_score"],
    }


def _level_value(level: str) -> int:
    token = str(level or "").strip().replace("+", "")
    try:
        return int(token)
    except ValueError:
        return 0


def _three_band_counts(count: int, top_fraction: float, bottom_fraction: float) -> tuple[int, int, int]:
    if count <= 0:
        return 0, 0, 0
    if count == 1:
        return 0, 1, 0
    if count == 2:
        return 1, 0, 1
    top = max(1, int(round(count * max(0.0, top_fraction))))
    bottom = max(1, int(round(count * max(0.0, bottom_fraction))))
    while top + bottom >= count and (top > 1 or bottom > 1):
        if top >= bottom and top > 1:
            top -= 1
        elif bottom > 1:
            bottom -= 1
    middle = count - top - bottom
    if middle <= 0:
        middle = 1
        if top >= bottom and top > 1:
            top -= 1
        elif bottom > 1:
            bottom -= 1
    return top, middle, bottom


def _band_for_level(level_bands: list[dict], level: str) -> dict | None:
    token = str(level or "").strip()
    for band in level_bands:
        if str(band.get("level", "")).strip() == token:
            return band
    return None


def _project_score_to_band(current_score: float, band: dict | None, floor_offset: float) -> float:
    if not band:
        return round(float(current_score), 2)
    band_min = _num(band.get("min"), current_score)
    band_max = _num(band.get("max"), current_score)
    offset = max(0.5, float(floor_offset or 0.0))
    if current_score < band_min:
        return round(min(band_max, band_min + offset), 2)
    if current_score > band_max:
        return round(max(band_min, band_max - offset), 2)
    return round(float(current_score), 2)


def _portfolio_sort_key(row: dict) -> tuple:
    return (
        -_num(row.get("_level_order"), -1.0),
        -_num(row.get("_composite_bucket"), 0.0),
        -_num(row.get("_borda_bucket"), 0.0),
        -_num(row.get("rubric_after_penalty_percent"), 0.0),
        _num(row.get("conventions_mistake_rate_percent"), 100.0),
        str(row.get("student_id", "")).lower(),
    )


def apply_portfolio_scale_calibration(
    rows: list[dict],
    config: dict,
    scope: dict | None,
    level_bands: list[dict],
) -> tuple[list[dict], dict]:
    scope = scope or {}
    portfolio_cfg = (config or {}).get("portfolio_mode", {}) if isinstance(config, dict) else {}
    scale_cfg = portfolio_cfg.get("ordinal_scale_calibration", {}) if isinstance(portfolio_cfg, dict) else {}
    if not scale_cfg.get("enabled", True):
        return rows, {"enabled": False, "applied": 0, "reason": "disabled"}
    if not scope.get("is_small_ordinal_portfolio"):
        return rows, {"enabled": False, "applied": 0, "reason": "scope_not_eligible"}
    if len(rows) < 3:
        return rows, {"enabled": False, "applied": 0, "reason": "insufficient_cohort"}

    sorted_rows = [dict(row) for row in sorted(rows, key=_portfolio_sort_key)]
    top_count, middle_count, bottom_count = _three_band_counts(
        len(sorted_rows),
        _num(scale_cfg.get("top_fraction"), 0.25),
        _num(scale_cfg.get("bottom_fraction"), 0.25),
    )
    target_levels = {}
    for idx, row in enumerate(sorted_rows, start=1):
        if idx <= top_count:
            target_levels[str(row.get("student_id", "")).strip()] = "4"
        elif idx > len(sorted_rows) - bottom_count:
            target_levels[str(row.get("student_id", "")).strip()] = "2"
        else:
            target_levels[str(row.get("student_id", "")).strip()] = "3"

    early_grade = bool(scope.get("grade_level") is not None and int(scope.get("grade_level")) <= 3)
    top_min_percent = _num(scale_cfg.get("early_grade_top_min_percent" if early_grade else "top_min_percent"), 74.0 if not early_grade else 72.0)
    middle_min_percent = _num(scale_cfg.get("early_grade_middle_min_percent" if early_grade else "middle_min_percent"), 66.0 if not early_grade else 63.25)
    bottom_max_percent = _num(scale_cfg.get("bottom_max_percent"), 70.0)
    max_rank_sd = _num(scale_cfg.get("max_rank_sd"), 1.5)
    floor_offset = _num(scale_cfg.get("band_floor_offset_percent"), 1.5)

    updated = []
    movements = []
    top_ids = {
        str(row.get("student_id", "")).strip()
        for idx, row in enumerate(sorted_rows, start=1)
        if idx <= top_count
    }
    bottom_ids = {
        str(row.get("student_id", "")).strip()
        for idx, row in enumerate(sorted_rows, start=1)
        if idx > len(sorted_rows) - bottom_count
    }
    for row in rows:
        updated_row = dict(row)
        student_id = str(row.get("student_id", "")).strip()
        current_level = str(row.get("adjusted_level", "") or "").strip()
        current_score = _num(row.get("rubric_after_penalty_percent"), 0.0)
        rubric_mean = _num(row.get("rubric_mean_percent"), current_score)
        rank_sd = _num(row.get("rank_sd"), 0.0)
        note_votes = int(_num(row.get("portfolio_note_votes"), 0))
        current_value = _level_value(current_level)
        target_level = target_levels.get(student_id, "")
        if student_id not in top_ids and student_id not in bottom_ids and current_value <= 2 and rubric_mean >= middle_min_percent:
            target_level = "3"
        target_value = _level_value(target_level)
        eligible = bool(target_level and note_votes > 0 and rank_sd <= max_rank_sd)
        if target_level == "4":
            eligible = eligible and rubric_mean >= top_min_percent
        elif target_level == "3" and current_value < target_value:
            eligible = eligible and rubric_mean >= middle_min_percent
        elif target_level == "2" and current_value > target_value:
            eligible = eligible and rubric_mean <= bottom_max_percent

        if eligible and target_level and current_level != target_level and abs(target_value - current_value) <= 1:
            band = _band_for_level(level_bands, target_level)
            projected_score = _project_score_to_band(current_score, band, floor_offset)
            updated_row["rubric_after_penalty_percent"] = projected_score
            updated_row["adjusted_level"] = target_level
            updated_row["adjusted_letter"] = str((band or {}).get("letter", "") or "")
            updated_row["_level_order"] = _num((band or {}).get("min"), updated_row.get("_level_order", 0.0))
            modifier = str(updated_row.get("level_modifier", "") or "").strip()
            if target_level.endswith("+") and modifier in {"", "+"}:
                updated_row["level_with_modifier"] = target_level
            else:
                updated_row["level_with_modifier"] = f"{target_level}{modifier}"
            updated_row["portfolio_scale_target_level"] = target_level
            updated_row["portfolio_scale_adjusted"] = "true"
            updated_row["portfolio_scale_reason"] = "ordinal_portfolio_rank_projection"
            flags = [item for item in str(updated_row.get("flags", "") or "").split(";") if item]
            if "portfolio_scale_calibration" not in flags:
                flags.append("portfolio_scale_calibration")
            updated_row["flags"] = ";".join(flags)
            movements.append(
                {
                    "student_id": student_id,
                    "from_level": current_level,
                    "to_level": target_level,
                    "from_score": round(current_score, 2),
                    "to_score": projected_score,
                }
            )
        else:
            updated_row.setdefault("portfolio_scale_target_level", target_level)
            updated_row.setdefault("portfolio_scale_adjusted", "false")
            updated_row.setdefault("portfolio_scale_reason", "")
        updated.append(updated_row)

    return updated, {
        "enabled": True,
        "applied": len(movements),
        "bucket_counts": {"top": top_count, "middle": middle_count, "bottom": bottom_count},
        "movements": movements,
        "scope": {
            "grade_level": scope.get("grade_level"),
            "genre": scope.get("genre"),
            "is_small_ordinal_portfolio": bool(scope.get("is_small_ordinal_portfolio")),
        },
    }


def apply_portfolio_mode(pass1: list[dict], config: dict, scope: dict | None = None) -> tuple[list[dict], dict]:
    portfolio_cfg = (config or {}).get("portfolio_mode", {}) if isinstance(config, dict) else {}
    scope = scope or {}
    if not portfolio_cfg.get("enabled", False) or not scope.get("is_portfolio"):
        return pass1, {"enabled": False, "applied": 0, "student_summaries": {}, "assessor_adjustments": []}

    updated = copy.deepcopy(pass1)
    clamp_threshold = _num(portfolio_cfg.get("note_clamp_threshold"), 4.0)
    adjustments = []
    notes_by_student: dict[str, list[dict]] = {}

    for assessor in updated:
        assessor_id = str(assessor.get("assessor_id", "")).strip()
        for score in assessor.get("scores", []):
            student_id = str(score.get("student_id", "")).strip()
            signal = signal_from_portfolio_fields(score) or parse_portfolio_note_signal(score.get("notes"))
            if signal is None:
                continue
            score_range = _score_range_for_estimate(signal["estimate"])
            notes_by_student.setdefault(student_id, []).append(signal)
            original_total = score.get("rubric_total_points")
            if original_total is None:
                criteria = score.get("criteria_points", {})
                original_total = sum(v for v in criteria.values() if isinstance(v, (int, float)))
            total = _num(original_total, 0.0)
            clamped = max(score_range["min_score"], min(score_range["max_score"], total))
            if abs(clamped - total) >= clamp_threshold:
                score["rubric_total_points"] = round(clamped, 2)
                score["portfolio_note_estimate"] = signal["estimate"]
                score["portfolio_note_level"] = score_range["canonical_level"]
                score["portfolio_note_adjusted"] = True
                adjustments.append(
                    {
                        "assessor_id": assessor_id,
                        "student_id": student_id,
                        "from_score": round(total, 2),
                        "to_score": round(clamped, 2),
                        "note_estimate": signal["estimate"],
                        "note_level": score_range["canonical_level"],
                        "reasons": signal["reasons"],
                    }
                )
            else:
                score["portfolio_note_estimate"] = signal["estimate"]
                score["portfolio_note_level"] = score_range["canonical_level"]
                score["portfolio_note_adjusted"] = False

    student_summaries = {student_id: _student_summary(votes) for student_id, votes in notes_by_student.items()}
    report = {
        "enabled": True,
        "applied": len(adjustments),
        "assessor_adjustments": adjustments,
        "student_summaries": student_summaries,
        "scope": {
            "grade_level": scope.get("grade_level"),
            "genre": scope.get("genre"),
            "assessment_unit": scope.get("assessment_unit"),
        },
    }
    return updated, report


def write_report(path: Path, report: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
