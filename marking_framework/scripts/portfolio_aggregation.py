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


def piece_distribution_signal(score: dict | None) -> dict | None:
    if not isinstance(score, dict):
        return None
    piece_rows = score.get("portfolio_piece_scores") or []
    aggregation = score.get("portfolio_aggregation") or {}
    stats = aggregation.get("piece_score_stats") if isinstance(aggregation, dict) else {}
    if not isinstance(piece_rows, list):
        piece_rows = []
    if not isinstance(stats, dict):
        stats = {}
    piece_scores = [
        _num(piece.get("rubric_total_points"), 0.0)
        for piece in piece_rows
        if isinstance(piece, dict)
    ]
    if not piece_scores and not stats:
        return None
    overall_score = _num(score.get("rubric_total_points"), aggregation.get("raw_score", 0.0))
    return {
        "piece_count": int(_num(score.get("portfolio_piece_count"), len(piece_scores))),
        "overall_score": round(overall_score, 2),
        "median": round(_num(stats.get("median"), overall_score), 2),
        "lower_half_mean": round(_num(stats.get("lower_half_mean"), overall_score), 2),
        "upper_half_mean": round(_num(stats.get("upper_half_mean"), overall_score), 2),
        "top70_count": round(sum(1 for value in piece_scores if value >= 70.0), 2),
        "top80_count": round(sum(1 for value in piece_scores if value >= 80.0), 2),
        "below60_count": round(sum(1 for value in piece_scores if value < 60.0), 2),
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


def _mean_field(rows: list[dict], key: str) -> float:
    values = [_num(row.get(key), None) for row in rows if isinstance(row, dict) and row.get(key) is not None]
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def _student_summary(votes: list[dict], piece_summaries: list[dict] | None = None) -> dict:
    if not votes:
        summary = {}
    else:
        estimates = [float(vote["estimate"]) for vote in votes]
        mean_estimate = sum(estimates) / len(estimates)
        score_range = _score_range_for_estimate(mean_estimate)
        summary = {
            "note_votes": len(votes),
            "note_estimate_mean": round(mean_estimate, 2),
            "note_canonical_level": score_range["canonical_level"],
            "note_anchor_score": score_range["anchor_score"],
        }
    piece_summaries = piece_summaries or []
    if piece_summaries:
        summary.update(
            {
                "piece_count_mean": _mean_field(piece_summaries, "piece_count"),
                "piece_overall_mean": _mean_field(piece_summaries, "overall_score"),
                "piece_median_mean": _mean_field(piece_summaries, "median"),
                "piece_lower_half_mean": _mean_field(piece_summaries, "lower_half_mean"),
                "piece_upper_half_mean": _mean_field(piece_summaries, "upper_half_mean"),
                "piece_top70_mean": _mean_field(piece_summaries, "top70_count"),
                "piece_top80_mean": _mean_field(piece_summaries, "top80_count"),
                "piece_lt60_mean": _mean_field(piece_summaries, "below60_count"),
            }
        )
    return summary


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


def _portfolio_sort_key_with_strategy(row: dict, strategy: str) -> tuple:
    strategy = str(strategy or "").strip().lower()
    if strategy == "piece_distribution_then_conventions":
        return (
            -_num(row.get("portfolio_piece_top80_mean"), -1.0),
            -_num(row.get("portfolio_piece_top70_mean"), -1.0),
            -_num(row.get("portfolio_note_estimate"), -1.0),
            _num(row.get("conventions_mistake_rate_percent"), 100.0),
            -_num(row.get("portfolio_piece_upper_half_mean"), -1.0),
            -_num(row.get("portfolio_piece_median_mean"), -1.0),
            -_num(row.get("portfolio_piece_overall_mean"), -1.0),
            _num(row.get("portfolio_piece_lt60_mean"), 999.0),
            -_num(row.get("_composite_bucket"), 0.0),
            -_num(row.get("_borda_bucket"), 0.0),
            str(row.get("student_id", "")).lower(),
        )
    if strategy == "note_then_conventions":
        return (
            -_num(row.get("_level_order"), -1.0),
            -_num(row.get("portfolio_note_estimate"), -1.0),
            _num(row.get("conventions_mistake_rate_percent"), 100.0),
            -_num(row.get("_composite_bucket"), 0.0),
            -_num(row.get("_borda_bucket"), 0.0),
            -_num(row.get("rubric_after_penalty_percent"), 0.0),
            str(row.get("student_id", "")).lower(),
        )
    return _portfolio_sort_key(row)


def _merge_scale_config(scale_cfg: dict, scope: dict | None) -> dict:
    merged = dict(scale_cfg or {})
    scope = scope or {}
    overrides = merged.get("model_family_overrides", {})
    if not isinstance(overrides, dict):
        merged.pop("model_family_overrides", None)
        return merged
    model_family = str(scope.get("pass1_model_family", "") or "").strip().lower()
    for key, override in overrides.items():
        if str(key or "").strip().lower() != model_family:
            continue
        if isinstance(override, dict):
            merged.update(override)
        break
    merged.pop("model_family_overrides", None)
    return merged


def apply_portfolio_scale_calibration(
    rows: list[dict],
    config: dict,
    scope: dict | None,
    level_bands: list[dict],
) -> tuple[list[dict], dict]:
    scope = scope or {}
    portfolio_cfg = (config or {}).get("portfolio_mode", {}) if isinstance(config, dict) else {}
    scale_cfg = portfolio_cfg.get("ordinal_scale_calibration", {}) if isinstance(portfolio_cfg, dict) else {}
    scale_cfg = _merge_scale_config(scale_cfg, scope)
    if not scale_cfg.get("enabled", True):
        return rows, {"enabled": False, "applied": 0, "reason": "disabled"}
    if not scope.get("is_small_ordinal_portfolio"):
        return rows, {"enabled": False, "applied": 0, "reason": "scope_not_eligible"}
    if len(rows) < 3:
        return rows, {"enabled": False, "applied": 0, "reason": "insufficient_cohort"}

    sort_strategy = str(scale_cfg.get("sort_strategy", "") or "").strip().lower()
    sorted_rows = [dict(row) for row in sorted(rows, key=lambda row: _portfolio_sort_key_with_strategy(row, sort_strategy))]
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
    middle_margin = _num(
        scale_cfg.get("early_grade_middle_margin_percent" if early_grade else "middle_margin_percent"),
        0.0,
    )
    bottom_max_percent = _num(scale_cfg.get("bottom_max_percent"), 70.0)
    max_rank_sd = _num(scale_cfg.get("max_rank_sd"), 1.5)
    floor_offset = _num(scale_cfg.get("band_floor_offset_percent"), 1.5)
    min_projection_note_votes = int(_num(scale_cfg.get("min_projection_note_votes"), 1))
    max_upward_jump_levels = int(_num(scale_cfg.get("max_upward_jump_levels"), 1))
    allow_strong_rank_projection = bool(scale_cfg.get("allow_strong_rank_projection", False))
    strong_top_piece_min_count = _num(scale_cfg.get("strong_top_piece_min_count"), 2.0)
    strong_top_upper_half_min_percent = _num(
        scale_cfg.get("strong_top_upper_half_min_percent"),
        max(68.0, top_min_percent - 2.0),
    )
    strong_top_overall_min_percent = _num(
        scale_cfg.get("strong_top_overall_min_percent"),
        max(62.0, middle_min_percent),
    )
    strong_top_max_lt60_mean = _num(scale_cfg.get("strong_top_max_lt60_mean"), 2.0)

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
        piece_top70 = _num(row.get("portfolio_piece_top70_mean"), 0.0)
        piece_upper_half = _num(row.get("portfolio_piece_upper_half_mean"), 0.0)
        piece_overall = _num(row.get("portfolio_piece_overall_mean"), 0.0)
        piece_lt60 = _num(row.get("portfolio_piece_lt60_mean"), 0.0)
        current_value = _level_value(current_level)
        target_level = target_levels.get(student_id, "")
        strong_top_piece_support = (
            piece_top70 >= strong_top_piece_min_count
            and piece_upper_half >= strong_top_upper_half_min_percent
            and max(current_score, rubric_mean, piece_overall) >= strong_top_overall_min_percent
            and piece_lt60 <= strong_top_max_lt60_mean
        )
        middle_projection_floor = max(0.0, middle_min_percent - max(0.0, middle_margin))
        if (
            student_id not in top_ids
            and student_id not in bottom_ids
            and current_value <= 2
            and max(current_score, rubric_mean) >= middle_projection_floor
        ):
            target_level = "3"
        target_value = _level_value(target_level)
        eligible = bool(target_level and note_votes >= min_projection_note_votes and rank_sd <= max_rank_sd)
        if target_level == "4":
            eligible = eligible and (rubric_mean >= top_min_percent or strong_top_piece_support)
        elif target_level == "3" and current_value < target_value:
            eligible = eligible and (
                max(current_score, rubric_mean) >= middle_projection_floor
                or (
                    allow_strong_rank_projection
                    and target_value - current_value > 1
                    and student_id not in bottom_ids
                )
            )
        elif target_level == "2" and current_value > target_value:
            eligible = eligible and rubric_mean <= bottom_max_percent

        upward_gap = max(0, target_value - current_value)
        allowed_gap = max_upward_jump_levels if upward_gap > 0 else 1
        if eligible and target_level and current_level != target_level and abs(target_value - current_value) <= allowed_gap:
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
            updated_row["portfolio_scale_reason"] = (
                "ordinal_portfolio_rank_projection_piece_support"
                if target_level == "4" and strong_top_piece_support and rubric_mean < top_min_percent
                else (
                    "ordinal_portfolio_rank_projection_strong"
                    if upward_gap > 1
                    else "ordinal_portfolio_rank_projection"
                )
            )
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
            "pass1_model_family": scope.get("pass1_model_family", ""),
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
    piece_summaries_by_student: dict[str, list[dict]] = {}

    for assessor in updated:
        assessor_id = str(assessor.get("assessor_id", "")).strip()
        for score in assessor.get("scores", []):
            student_id = str(score.get("student_id", "")).strip()
            signal = signal_from_portfolio_fields(score) or parse_portfolio_note_signal(score.get("notes"))
            if signal is None:
                continue
            score_range = _score_range_for_estimate(signal["estimate"])
            notes_by_student.setdefault(student_id, []).append(signal)
            piece_signal = piece_distribution_signal(score)
            if piece_signal is not None:
                piece_summaries_by_student.setdefault(student_id, []).append(piece_signal)
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

    student_ids = sorted(set(notes_by_student) | set(piece_summaries_by_student))
    student_summaries = {
        student_id: _student_summary(notes_by_student.get(student_id, []), piece_summaries_by_student.get(student_id, []))
        for student_id in student_ids
    }
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
