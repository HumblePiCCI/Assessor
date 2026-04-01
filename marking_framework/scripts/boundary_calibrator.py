#!/usr/bin/env python3
import json
import math
from pathlib import Path

try:
    from scripts.aggregate_helpers import get_level_band, get_level_bands
    from scripts.assessor_context import load_class_metadata, load_grade_profiles, normalize_genre, select_grade_level
except ImportError:  # pragma: no cover - Running as a script
    from aggregate_helpers import get_level_band, get_level_bands  # pragma: no cover
    from assessor_context import load_class_metadata, load_grade_profiles, normalize_genre, select_grade_level  # pragma: no cover


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _level_order_map(level_bands: list[dict]) -> dict[str, int]:
    mapping = {}
    for idx, band in enumerate(sorted(level_bands, key=lambda item: _num(item.get("min"), 0.0)), start=1):
        mapping[str(band.get("level", "")).strip()] = idx
    return mapping


def _level_floor(level_bands: list[dict], level: str) -> float | None:
    for band in level_bands:
        if str(band.get("level", "")).strip() == str(level).strip():
            return _num(band.get("min"), None)
    return None


def load_scope_context(metadata_path: Path, profiles_path: Path) -> dict:
    metadata = load_class_metadata(metadata_path)
    profiles = load_grade_profiles(profiles_path)
    grade_level = select_grade_level(None, metadata)
    raw_genre = (
        metadata.get("genre")
        or metadata.get("assignment_genre")
        or metadata.get("genre_form")
        or metadata.get("assessment_unit")
    )
    genre = normalize_genre(raw_genre)
    assessment_unit = str(metadata.get("assessment_unit", "") or "").strip().lower()
    genre_form = str(metadata.get("genre_form", "") or "").strip().lower()
    is_portfolio = genre == "portfolio" or assessment_unit == "portfolio" or "portfolio" in genre_form
    is_early_grade_narrative = bool(grade_level is not None and grade_level <= 3 and genre == "narrative")
    profile = profiles.get(f"grade_{grade_level}", {}) if grade_level is not None else {}
    scoring_scale = metadata.get("scoring_scale") if isinstance(metadata.get("scoring_scale"), dict) else {}
    scoring_labels = scoring_scale.get("labels") if isinstance(scoring_scale.get("labels"), list) else []
    numeric_mapping = scoring_scale.get("numeric_mapping") if isinstance(scoring_scale.get("numeric_mapping"), dict) else {}
    scoring_scale_size = len(scoring_labels) or len(numeric_mapping)
    scoring_scale_type = str(scoring_scale.get("type", "") or "").strip().lower()
    small_ordinal_portfolio = bool(
        is_portfolio
        and scoring_scale_type == "ordinal"
        and scoring_scale_size == 3
        and 0 < int(_num(metadata.get("sample_count"), 0)) <= 6
    )
    return {
        "metadata": metadata,
        "profiles": profiles,
        "grade_level": grade_level,
        "genre": genre,
        "assessment_unit": assessment_unit,
        "genre_form": genre_form,
        "is_portfolio": is_portfolio,
        "is_early_grade_narrative": is_early_grade_narrative,
        "scoring_scale": scoring_scale,
        "scoring_scale_type": scoring_scale_type,
        "scoring_scale_size": scoring_scale_size,
        "is_small_ordinal_portfolio": small_ordinal_portfolio,
        "grade_profile": profile if isinstance(profile, dict) else {},
    }


def _sort_key(row: dict) -> tuple:
    return (
        -_num(row.get("_level_order"), -1.0),
        -_num(row.get("_composite_bucket"), 0.0),
        -_num(row.get("_borda_bucket"), 0.0),
        -_num(row.get("rubric_after_penalty_percent"), 0.0),
        _num(row.get("conventions_mistake_rate_percent"), 100.0),
        str(row.get("student_id", "")).lower(),
    )


def _cap_adjustment(current: float, target: float, max_adjustment: float) -> tuple[float, bool]:
    cap = max(0.0, float(max_adjustment or 0.0))
    if cap <= 0.0:
        return target, False
    delta = target - current
    if abs(delta) <= cap:
        return target, False
    return current + (cap if delta > 0 else -cap), True


def _append_flag(flags_value: str, token: str) -> str:
    parts = [item for item in str(flags_value or "").split(";") if item]
    if token not in parts:
        parts.append(token)
    return ";".join(parts)


def _apply_level_modifier(level: str, modifier: str) -> str:
    level = str(level or "").strip()
    modifier = str(modifier or "").strip()
    if not level:
        return ""
    if level.endswith("+") and modifier in {"", "+"}:
        return level
    return f"{level}{modifier}"


def apply_boundary_calibration(rows: list[dict], config: dict, scope: dict | None = None) -> tuple[list[dict], dict]:
    calibration_cfg = (config or {}).get("boundary_calibration", {}) if isinstance(config, dict) else {}
    scope = scope or {}
    if not calibration_cfg.get("enabled", False) or not rows:
        return rows, {"enabled": False, "applied": 0, "movements": [], "scope": scope}
    if scope.get("is_portfolio"):
        updated = []
        for row in rows:
            updated_row = dict(row)
            current_score = round(_num(row.get("rubric_after_penalty_percent"), 0.0), 2)
            updated_row.setdefault("pre_boundary_calibration_percent", current_score)
            updated_row.setdefault("boundary_calibrated_percent", current_score)
            updated_row.setdefault("boundary_calibration_delta", 0.0)
            updated_row.setdefault("boundary_calibration_reason", "")
            updated_row.setdefault("boundary_calibration_capped", "false")
            updated.append(updated_row)
        return updated, {
            "enabled": True,
            "applied": 0,
            "movement_count": 0,
            "scope": {
                "grade_level": scope.get("grade_level"),
                "genre": scope.get("genre"),
                "is_portfolio": True,
                "is_early_grade_narrative": bool(scope.get("is_early_grade_narrative")),
            },
            "config": {
                "mode": "skipped_for_portfolio_scope",
            },
            "movements": [],
        }

    level_bands = get_level_bands(config if isinstance(config, dict) else {})
    level_map = _level_order_map(level_bands)
    floor_level_3 = _level_floor(level_bands, "3") or 70.0
    floor_level_4 = _level_floor(level_bands, "4") or 80.0

    strong_rank_fraction = _num(calibration_cfg.get("strong_rank_fraction"), 0.35)
    strong_borda_min = _num(calibration_cfg.get("strong_borda_min"), 0.6)
    max_rank_sd = _num(calibration_cfg.get("max_rank_sd"), 1.5)
    max_rubric_sd_points = _num(calibration_cfg.get("max_rubric_sd_points"), 8.0)
    severe_min_rubric = _num(calibration_cfg.get("severe_collapse_min_rubric_percent"), 58.0)
    severe_floor = _num(calibration_cfg.get("severe_collapse_target_floor_percent"), floor_level_3)
    severe_max_adjustment = _num(calibration_cfg.get("severe_collapse_max_adjustment_percent"), 14.0)
    top_boundary_margin = _num(calibration_cfg.get("top_boundary_margin_percent"), 6.0)
    early_bonus = _num(calibration_cfg.get("early_grade_narrative_boundary_bonus_percent"), 2.0)
    default_max_adjustment = _num(calibration_cfg.get("max_score_adjustment_percent"), 8.0)
    severe_gap_levels = int(_num(calibration_cfg.get("severe_gap_levels"), 2))

    n_students = len(rows)
    strong_rank_limit = max(1, int(math.ceil(n_students * strong_rank_fraction)))

    provisional = sorted(rows, key=_sort_key)
    provisional_rank_map = {row.get("student_id", ""): idx for idx, row in enumerate(provisional, start=1)}

    movements = []
    updated = []
    for row in rows:
        current_score = _num(row.get("rubric_after_penalty_percent"), 0.0)
        base_score = _num(row.get("rubric_mean_percent"), current_score)
        student_id = str(row.get("student_id", "")).strip()
        adjusted_level = str(row.get("adjusted_level", "") or "").strip()
        base_level = str(row.get("base_level", "") or "").strip()
        provisional_rank = int(provisional_rank_map.get(student_id, n_students or 1))
        borda_percent = _num(row.get("borda_percent"), 0.0)
        rank_sd = _num(row.get("rank_sd"), 0.0)
        rubric_sd = _num(row.get("rubric_sd_points"), 0.0)
        level_gap = max(0, level_map.get(base_level, level_map.get(adjusted_level, 0)) - level_map.get(adjusted_level, 0))
        strong_support = (
            provisional_rank <= strong_rank_limit
            and borda_percent >= strong_borda_min
            and rank_sd <= max_rank_sd
            and rubric_sd <= max_rubric_sd_points
        )

        target_score = current_score
        reasons = []
        capped = False

        if adjusted_level in {"1", "2"}:
            severe_signal = (
                (strong_support and base_score >= severe_min_rubric)
                or level_gap >= severe_gap_levels
            )
            if severe_signal:
                target_score = max(target_score, severe_floor)
                reasons.append("severe_collapse_floor")

        boundary_margin = top_boundary_margin
        if scope.get("is_early_grade_narrative"):
            boundary_margin += early_bonus

        if scope.get("is_early_grade_narrative") and provisional_rank == 1 and adjusted_level in {"1", "2"} and base_score >= 64.0:
            target_score = max(target_score, severe_floor)
            reasons.append("early_grade_narrative_floor")

        top_boundary_supported = strong_support
        if adjusted_level == "3" and top_boundary_supported and current_score >= (floor_level_4 - boundary_margin):
            target_score = max(target_score, floor_level_4)
            reasons.append("top_boundary_uplift")
        elif scope.get("is_early_grade_narrative") and adjusted_level == "2" and provisional_rank <= max(1, strong_rank_limit) and current_score >= 67.0:
            target_score = max(target_score, floor_level_3)
            reasons.append("early_grade_narrative_boundary")

        max_adjustment = severe_max_adjustment if "severe_collapse_floor" in reasons else default_max_adjustment
        target_score, capped = _cap_adjustment(current_score, target_score, max_adjustment)
        target_score = round(float(target_score), 2)

        calibrated_band = get_level_band(target_score, level_bands)
        calibrated_level = str(calibrated_band.get("level", "") if calibrated_band else adjusted_level)
        calibrated_letter = str(calibrated_band.get("letter", "") if calibrated_band else row.get("adjusted_letter", ""))

        updated_row = dict(row)
        updated_row["pre_boundary_calibration_percent"] = round(current_score, 2)
        updated_row["boundary_calibrated_percent"] = target_score
        updated_row["boundary_calibration_delta"] = round(target_score - current_score, 2)
        updated_row["boundary_calibration_reason"] = ";".join(dict.fromkeys(reasons))
        updated_row["boundary_calibration_capped"] = str(bool(capped)).lower()

        if abs(target_score - current_score) >= 0.01:
            updated_row["rubric_after_penalty_percent"] = target_score
            updated_row["adjusted_level"] = calibrated_level
            updated_row["adjusted_letter"] = calibrated_letter
            updated_row["level_with_modifier"] = _apply_level_modifier(
                calibrated_level,
                updated_row.get("level_modifier", ""),
            )
            updated_row["_level_order"] = _num(calibrated_band.get("min"), updated_row.get("_level_order", -1.0)) if calibrated_band else updated_row.get("_level_order", -1.0)
            updated_row["flags"] = _append_flag(updated_row.get("flags", ""), "boundary_calibration")
            if "severe_collapse_floor" in reasons:
                updated_row["flags"] = _append_flag(updated_row.get("flags", ""), "severe_collapse_rescue")
            movements.append(
                {
                    "student_id": student_id,
                    "from_percent": round(current_score, 2),
                    "to_percent": target_score,
                    "from_level": adjusted_level,
                    "to_level": calibrated_level,
                    "provisional_rank": provisional_rank,
                    "borda_percent": round(borda_percent, 4),
                    "rank_sd": round(rank_sd, 2),
                    "rubric_sd_points": round(rubric_sd, 2),
                    "reason": updated_row["boundary_calibration_reason"],
                    "capped": bool(capped),
                }
            )

        updated.append(updated_row)

    summary = {
        "enabled": True,
        "applied": len(movements),
        "movement_count": len(movements),
        "scope": {
            "grade_level": scope.get("grade_level"),
            "genre": scope.get("genre"),
            "is_portfolio": bool(scope.get("is_portfolio")),
            "is_early_grade_narrative": bool(scope.get("is_early_grade_narrative")),
        },
        "config": {
            "strong_rank_fraction": strong_rank_fraction,
            "strong_borda_min": strong_borda_min,
            "top_boundary_margin_percent": top_boundary_margin,
            "severe_collapse_target_floor_percent": severe_floor,
        },
        "movements": movements,
    }
    return updated, summary


def write_report(path: Path, report: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
