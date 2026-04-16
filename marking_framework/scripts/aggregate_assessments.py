#!/usr/bin/env python3
import argparse
import json
import logging
from pathlib import Path
try:
    from scripts.aggregate_helpers import (
        apply_bias_correction,
        apply_level_drop_penalty,
        calculate_irr_metrics,
        consensus_central,
        get_level_band,
        get_level_bands,
        level_modifier_from_mistake_rate,
        load_config,
        mean,
        read_conventions_report,
        read_pass1,
        read_pass2,
        resolve_bias_entry,
        stdev,
        weighted_central,
    )
    from scripts.rubric_criteria import load_rubric_criteria, total_points
    from scripts.aggregate_output import (
        write_consensus_csv,
        write_disagreements,
        write_irr_metrics,
        write_ranked_list,
    )
    from scripts.boundary_calibrator import apply_boundary_calibration, load_scope_context, write_report
    from scripts.portfolio_aggregation import (
        apply_portfolio_mode,
        apply_portfolio_scale_calibration,
        write_report as write_portfolio_report,
    )
except ImportError:  # pragma: no cover - Running as a script
    from aggregate_helpers import (  # pragma: no cover
        apply_bias_correction,  # pragma: no cover
        apply_level_drop_penalty,  # pragma: no cover
        calculate_irr_metrics,  # pragma: no cover
        consensus_central,  # pragma: no cover
        get_level_band,  # pragma: no cover
        get_level_bands,  # pragma: no cover
        level_modifier_from_mistake_rate,  # pragma: no cover
        load_config,  # pragma: no cover
        mean,  # pragma: no cover
        read_conventions_report,  # pragma: no cover
        read_pass1,  # pragma: no cover
        read_pass2,  # pragma: no cover
        resolve_bias_entry,  # pragma: no cover
        stdev,  # pragma: no cover
        weighted_central,  # pragma: no cover
    )
    from rubric_criteria import load_rubric_criteria, total_points  # pragma: no cover
    from aggregate_output import (  # pragma: no cover
        write_consensus_csv,  # pragma: no cover
        write_disagreements,  # pragma: no cover
        write_irr_metrics,  # pragma: no cover
        write_ranked_list,  # pragma: no cover
    )
    from boundary_calibrator import apply_boundary_calibration, load_scope_context, write_report  # pragma: no cover
    from portfolio_aggregation import (  # pragma: no cover
        apply_portfolio_mode,  # pragma: no cover
        apply_portfolio_scale_calibration,  # pragma: no cover
        write_report as write_portfolio_report,  # pragma: no cover
    )
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    token = str(value or "").strip().lower()
    return token in {"1", "true", "yes", "y"}


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _level_order_value(level: str, level_bands: list[dict]) -> float:
    for band in level_bands:
        if str(band.get("level", "") or "").strip() == str(level or "").strip():
            return float(band.get("min", 0.0) or 0.0)
    return -1.0


def _interpolate_anchor_patch(score: float, patch: dict) -> tuple[float, float]:
    points = patch.get("interpolation_points", []) if isinstance(patch, dict) else []
    ordered = []
    for point in points if isinstance(points, list) else []:
        if not isinstance(point, dict):
            continue
        if "x" not in point or "y" not in point:
            continue
        ordered.append((float(point["x"]), float(point["y"])))
    ordered.sort(key=lambda item: item[0])
    if len(ordered) >= 2:
        x = float(score)
        if x <= ordered[0][0]:
            corrected = ordered[0][1]
        elif x >= ordered[-1][0]:
            corrected = ordered[-1][1]
        else:
            corrected = x
            for idx in range(1, len(ordered)):
                x0, y0 = ordered[idx - 1]
                x1, y1 = ordered[idx]
                if x0 <= x <= x1:
                    ratio = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
                    corrected = y0 + ((y1 - y0) * ratio)
                    break
        return corrected, corrected - x
    delta = float(patch.get("mean_delta", 0.0) or 0.0)
    return float(score) + delta, delta


def apply_anchor_patch(rows: list[dict], patch: dict, level_bands: list[dict]) -> tuple[list[dict], dict]:
    if not isinstance(patch, dict) or not patch or not patch.get("active", False):
        return rows, {"active": False, "applied": 0, "fit_method": "", "movement_count": 0}
    updated = []
    movement_count = 0
    for row in rows:
        current = float(row.get("rubric_after_penalty_percent", row.get("rubric_mean_percent", 0.0)) or 0.0)
        corrected, delta = _interpolate_anchor_patch(current, patch)
        corrected = max(0.0, min(100.0, corrected))
        if abs(delta) >= 0.01:
            movement_count += 1
        adjusted_band = get_level_band(corrected, level_bands)
        adjusted_level = adjusted_band["level"] if adjusted_band else row.get("adjusted_level", "")
        adjusted_letter = adjusted_band["letter"] if adjusted_band else row.get("adjusted_letter", "")
        level_modifier = row.get("level_modifier", "")
        level_with_modifier = f"{adjusted_level}{level_modifier}" if adjusted_level else row.get("level_with_modifier", "")
        updated_row = dict(row)
        updated_row["rubric_after_penalty_percent"] = round(corrected, 2)
        updated_row["anchor_adjustment_points"] = round(delta, 2)
        updated_row["anchor_calibration_active"] = "true"
        updated_row["adjusted_level"] = adjusted_level
        updated_row["adjusted_letter"] = adjusted_letter
        updated_row["level_with_modifier"] = level_with_modifier
        updated_row["_level_order"] = _level_order_value(adjusted_level, level_bands)
        updated.append(updated_row)
    report = {
        "active": True,
        "applied": len(updated),
        "fit_method": str(patch.get("fit_method", "") or ""),
        "movement_count": movement_count,
        "mean_delta": round(float(patch.get("mean_delta", 0.0) or 0.0), 6),
    }
    return updated, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to marking_config.json")
    parser.add_argument("--pass1", default="assessments/pass1_individual", help="Pass1 directory")
    parser.add_argument("--pass2", default="assessments/pass2_comparative", help="Pass2 directory")
    parser.add_argument("--conventions", default="processing/conventions_report.csv", help="Conventions report")
    parser.add_argument("--output", default="outputs/consensus_scores.csv", help="Consensus CSV")
    parser.add_argument("--allow-missing-data", action="store_true", help="Allow missing data (not recommended)")
    parser.add_argument("--calibration-bias", default="outputs/calibration_bias.json", help="Calibration bias JSON")
    parser.add_argument("--rubric-criteria", default="config/rubric_criteria.json", help="Rubric criteria JSON")
    parser.add_argument("--scope-key", default="", help="Optional calibration scope key (e.g. grade_6_7|literary_analysis)")
    parser.add_argument("--class-metadata", default="inputs/class_metadata.json", help="Class metadata JSON")
    parser.add_argument("--grade-profiles", default="config/grade_level_profiles.json", help="Grade level profiles JSON")
    parser.add_argument("--routing", default="config/llm_routing.json", help="Routing config JSON")
    parser.add_argument("--boundary-report", default="outputs/boundary_calibration_report.json", help="Boundary calibration report JSON")
    parser.add_argument("--portfolio-report", default="outputs/portfolio_mode_report.json", help="Portfolio scoring mode report JSON")
    parser.add_argument("--anchor-calibration", default="outputs/cohort_anchor_calibration.json", help="Local anchor calibration patch JSON")
    args = parser.parse_args()
    config = load_config(Path(args.config), logger)
    scope = load_scope_context(Path(args.class_metadata), Path(args.grade_profiles), Path(args.routing))
    pass1 = read_pass1(Path(args.pass1), logger)
    pass2 = read_pass2(Path(args.pass2), logger)
    conventions = read_conventions_report(Path(args.conventions), logger)
    pass1, portfolio_report = apply_portfolio_mode(pass1, config, scope)
    student_ids = set()
    for assessor in pass1:
        for score in assessor.get("scores", []):
            student_ids.add(score["student_id"])
    for ranking in pass2:
        student_ids.update(ranking["ranking"])
    student_ids.update(conventions.keys())
    student_ids = sorted(student_ids)
    logger.info(f"Found {len(student_ids)} unique students")
    num_assessors_pass1 = len(pass1)
    num_assessors_pass2 = len(pass2)
    logger.info(f"Pass 1 assessors: {num_assessors_pass1}")
    logger.info(f"Pass 2 assessors: {num_assessors_pass2}")
    errors = []
    if num_assessors_pass1 < 3:
        errors.append(f"Insufficient Pass 1 assessors: found {num_assessors_pass1}, need at least 3")
    if num_assessors_pass2 < 3:
        errors.append(f"Insufficient Pass 2 assessors: found {num_assessors_pass2}, need at least 3")
    for sid in student_ids:
        pass1_count = sum(1 for assessor in pass1 
                         if any(s["student_id"] == sid for s in assessor.get("scores", [])))
        if pass1_count < num_assessors_pass1:
            errors.append(f"Student '{sid}': missing Pass 1 scores from {num_assessors_pass1 - pass1_count} assessor(s)")
        pass2_count = sum(1 for ranking in pass2 if sid in ranking["ranking"])
        if pass2_count < num_assessors_pass2:
            errors.append(f"Student '{sid}': missing Pass 2 ranking from {num_assessors_pass2 - pass2_count} assessor(s)")
        if sid not in conventions:
            errors.append(f"Student '{sid}': missing conventions scan data")
    if errors:
        logger.error(f"Data completeness check FAILED with {len(errors)} error(s):")
        for error in errors[:20]:  # Show first 20 errors
            logger.error(f"  - {error}")
        if len(errors) > 20:
            logger.error(f"  ... and {len(errors) - 20} more errors")
        if not args.allow_missing_data:
            logger.error("ABORTING: Use --allow-missing-data to proceed anyway (not recommended)")
            return 1
        else:
            logger.warning("Proceeding with missing data (grades may be unfair)")
    else:
        logger.info("✓ Data completeness check PASSED")
    rubric_points_possible = config.get("rubric", {}).get("points_possible")
    criteria_cfg = load_rubric_criteria(Path(args.rubric_criteria))
    criteria_points_possible = total_points(criteria_cfg) if criteria_cfg else None
    if rubric_points_possible is None and criteria_points_possible:
        rubric_points_possible = criteria_points_possible
    bias_path = Path(args.calibration_bias)
    bias_data = {}
    if bias_path.exists():
        bias_data = json.loads(bias_path.read_text(encoding="utf-8"))
    bias_map = bias_data.get("assessors", {}) if isinstance(bias_data, dict) else {}
    scope_key = args.scope_key or config.get("calibration", {}).get("scope_key")
    rubric_by_student = {sid: [] for sid in student_ids}
    rubric_weights_by_student = {sid: [] for sid in student_ids}
    assessor_weights = {}
    draft_penalties_by_student = {sid: [] for sid in student_ids}
    draft_floor_by_student = {sid: False for sid in student_ids}
    draft_severity_by_student = {sid: "none" for sid in student_ids}
    severity_order = {"none": 0, "low": 1, "medium": 2, "high": 3}

    for assessor in pass1:
        points_possible = assessor.get("rubric_points_possible") or rubric_points_possible
        if rubric_points_possible is None and points_possible is not None:
            rubric_points_possible = points_possible
        assessor_id = assessor.get("assessor_id", "")
        bias_entry = resolve_bias_entry(bias_map, assessor_id, scope_key)
        assessor_weight = 1.0
        if isinstance(bias_entry, dict):
            assessor_weight = max(0.2, float(bias_entry.get("weight", 1.0) or 1.0))
        assessor_weights[assessor_id] = assessor_weight
        for score in assessor.get("scores", []):
            total = score.get("rubric_total_points")
            if total is None:
                criteria = score.get("criteria_points", {})
                total = sum(v for v in criteria.values() if isinstance(v, (int, float)))
            cap = rubric_points_possible or 100.0
            total = apply_bias_correction(float(total), bias_entry, cap)
            sid = score["student_id"]
            rubric_by_student[sid].append(float(total))
            rubric_weights_by_student[sid].append(assessor_weight)
            draft_penalty = _safe_float(score.get("draft_completion_penalty_points"), 0.0)
            if draft_penalty > 0.0:
                draft_penalties_by_student[sid].append(draft_penalty)
            if _safe_bool(score.get("draft_completion_floor_applied")):
                draft_floor_by_student[sid] = True
            severity = str(score.get("draft_completion_severity") or "none").strip().lower()
            if severity_order.get(severity, 0) > severity_order.get(draft_severity_by_student[sid], 0):
                draft_severity_by_student[sid] = severity

    if rubric_points_possible is None:
        all_scores = [v for values in rubric_by_student.values() for v in values]
        rubric_points_possible = max(all_scores) if all_scores else 1
    logger.info(f"Rubric points possible: {rubric_points_possible}")
    rankings_by_student = {sid: [] for sid in student_ids}
    borda_points = {sid: 0 for sid in student_ids}
    num_students = len(student_ids)
    ranking_weight_sum = 0.0

    for ranking in pass2:
        order = ranking["ranking"]
        rid = ranking.get("assessor_id", "")
        bias_entry = resolve_bias_entry(bias_map, rid, scope_key)
        rank_weight = 1.0
        if isinstance(bias_entry, dict):
            rank_weight = max(0.2, float(bias_entry.get("weight", assessor_weights.get(rid, 1.0)) or 1.0))
        ranking_weight_sum += rank_weight
        for idx, sid in enumerate(order):
            if sid not in borda_points:  # pragma: no cover - defensive, should not occur
                logger.warning(f"Student '{sid}' in ranking but not in master list")
                continue
            points = (num_students - idx - 1) * rank_weight
            borda_points[sid] += points
            rankings_by_student[sid].append(idx + 1)

    max_borda = (num_students - 1) * (ranking_weight_sum or 1.0) if num_students > 1 else 1
    irr = calculate_irr_metrics(rubric_by_student, rankings_by_student, num_assessors_pass1, num_assessors_pass2)
    logger.info(f"Inter-rater reliability metrics:")
    logger.info(f"  Rubric ICC (approx): {irr['rubric_icc']:.3f} (>0.7 = good, >0.9 = excellent)")
    logger.info(f"  Rank Kendall's W: {irr['rank_kendall_w']:.3f} (>0.7 = good agreement)")
    logger.info(f"  Mean rubric SD: {irr['mean_rubric_sd']:.2f}")
    logger.info(f"  Mean rank SD: {irr['mean_rank_sd']:.2f}")
    weights = config.get("weights", {})
    if scope.get("is_portfolio"):
        portfolio_weights = config.get("portfolio_mode", {}).get("weights", {})
        weights = {
            "rubric": portfolio_weights.get("rubric", weights.get("rubric", 0.70)),
            "conventions": portfolio_weights.get("conventions", weights.get("conventions", 0.15)),
            "comparative": portfolio_weights.get("comparative", weights.get("comparative", 0.15)),
        }
    rubric_w = weights.get("rubric", 0.70)
    conv_w = weights.get("conventions", 0.15)
    comp_w = weights.get("comparative", 0.15)
    rubric_center = config.get("consensus", {}).get("rubric_central_tendency", "median")
    conventions_config = config.get("conventions", {})
    mistake_rate_threshold = conventions_config.get("mistake_rate_threshold", 0.07)
    max_level_drop = conventions_config.get("max_level_drop", 1)
    missing_data_mistake_rate_percent = conventions_config.get("missing_data_mistake_rate_percent", 100.0)
    if scope.get("is_portfolio"):
        portfolio_cfg = config.get("portfolio_mode", {})
        mistake_rate_threshold += (_safe_float(portfolio_cfg.get("conventions_threshold_bonus_percent"), 0.0) / 100.0)
        max_level_drop = float(max_level_drop) * max(0.0, _safe_float(portfolio_cfg.get("max_level_drop_scale"), 1.0))
    modifier_bands = conventions_config.get(
        "modifier_bands",
        [
            {"max_mistake_rate_percent": 2.0, "modifier": "+"},
            {"max_mistake_rate_percent": 4.0, "modifier": ""},
            {"max_mistake_rate_percent": 6.0, "modifier": "-"},
            {"max_mistake_rate_percent": 100.0, "modifier": "--"},
        ],
    )
    modifier_bands = sorted(modifier_bands, key=lambda b: b["max_mistake_rate_percent"])
    level_bands = get_level_bands(config)
    logger.info(f"Weighting: rubric={rubric_w}, conventions={conv_w}, comparative={comp_w}")
    logger.info(f"Conventions penalty: mistake_rate_threshold={mistake_rate_threshold}, max_level_drop={max_level_drop}")
    logger.info(f"Level bands: {', '.join([b['level'] for b in level_bands])}")
    if portfolio_report.get("enabled"):
        logger.info(
            "Portfolio mode normalized %s assessor score(s)",
            portfolio_report.get("applied", 0),
        )
    rows = []
    conventions_penalties_applied = 0
    for sid in student_ids:
        rubric_scores = rubric_by_student.get(sid, [])
        rubric_weights = rubric_weights_by_student.get(sid, [])
        rubric_mean_points = weighted_central(rubric_scores, rubric_weights, rubric_center)
        rubric_sd_points = stdev(rubric_scores)
        rubric_mean_percent = (rubric_mean_points / rubric_points_possible) * 100 if rubric_points_possible else 0.0

        conv_row = conventions.get(sid)
        if conv_row is None:
            mistake_rate = float(missing_data_mistake_rate_percent)
        else:
            mistake_rate = float(conv_row.get("mistake_rate_percent", 0.0) or 0.0)

        borda = borda_points.get(sid, 0)
        borda_percent = (borda / max_borda) if max_borda else 0.0

        base_band = get_level_band(rubric_mean_percent, level_bands)
        base_level = base_band["level"] if base_band else ""
        base_letter = base_band["letter"] if base_band else ""

        level_modifier = level_modifier_from_mistake_rate(mistake_rate, modifier_bands)

        conv_component = max(0.0, 1.0 - (mistake_rate / 100.0))
        conventions_penalty_applied = False
        rubric_after_penalty = rubric_mean_percent
        threshold_percent = mistake_rate_threshold * 100.0
        if mistake_rate > threshold_percent:
            excess = max(0.0, mistake_rate - threshold_percent)
            scaled_drop = float(max_level_drop) * min(1.0, excess / max(threshold_percent, 1.0))
            rubric_after_penalty = apply_level_drop_penalty(rubric_mean_percent, level_bands, scaled_drop)
            conventions_penalty_applied = True
            conventions_penalties_applied += 1
            logger.info(
                f"Student '{sid}': conventions penalty applied "
                f"(mistake_rate={mistake_rate:.1f}% > threshold={threshold_percent:.1f}%, "
                f"level_drop={scaled_drop:.2f}), rubric reduced from {rubric_mean_percent:.1f}% to {rubric_after_penalty:.1f}%"
            )
        composite = (rubric_w * (rubric_after_penalty / 100.0)) + (conv_w * conv_component) + (comp_w * borda_percent)

        rank_sd = stdev(rankings_by_student.get(sid, []))
        portfolio_summary = portfolio_report.get("student_summaries", {}).get(sid, {})

        flags = []
        if rubric_sd_points >= config.get("consensus", {}).get("rubric_sd_threshold", 0.8):
            flags.append("rubric_sd")
        if rank_sd >= config.get("consensus", {}).get("rank_disagreement_threshold", 3):
            flags.append("rank_sd")
        if sid not in conventions:
            flags.append("missing_conventions")
        if any(sid not in r.get("ranking", []) for r in pass2):
            flags.append("missing_rank")
        if not rubric_scores:
            flags.append("missing_rubric")
        if portfolio_summary.get("note_votes", 0):
            flags.append("portfolio_mode")
        if conventions_penalty_applied:
            flags.append("conventions_penalty")
        draft_penalty_points = max(draft_penalties_by_student.get(sid, []) or [0.0])
        draft_floor_applied = bool(draft_floor_by_student.get(sid, False))
        draft_severity = str(draft_severity_by_student.get(sid, "none") or "none")
        if draft_penalty_points > 0.0:
            flags.append("draft_completion_penalty")
        if draft_floor_applied:
            flags.append("draft_completion_floor")

        adjusted_band = get_level_band(rubric_after_penalty, level_bands)
        adjusted_level = adjusted_band["level"] if adjusted_band else ""
        adjusted_letter = adjusted_band["letter"] if adjusted_band else ""

        level_with_modifier = ""
        if adjusted_level:
            if adjusted_level.endswith("+") and level_modifier in ("", "+"):
                level_with_modifier = adjusted_level
            else:
                level_with_modifier = f"{adjusted_level}{level_modifier}"

        rows.append(
            {
                "student_id": sid,
                "rubric_mean_percent": round(rubric_mean_percent, 2),
                "rubric_after_penalty_percent": round(rubric_after_penalty, 2),
                "rubric_sd_points": round(rubric_sd_points, 2),
                "conventions_mistake_rate_percent": round(mistake_rate, 2),
                "borda_points": round(borda, 4),
                "borda_percent": round(borda_percent, 4),
                "composite_score": round(composite, 4),
                "rank_sd": round(rank_sd, 2),
                "base_level": base_level,
                "base_letter": base_letter,
                "adjusted_level": adjusted_level,
                "adjusted_letter": adjusted_letter,
                "level_modifier": level_modifier,
                "level_with_modifier": level_with_modifier,
                "portfolio_note_estimate": portfolio_summary.get("note_estimate_mean", ""),
                "portfolio_note_level": portfolio_summary.get("note_canonical_level", ""),
                "portfolio_note_votes": portfolio_summary.get("note_votes", 0),
                "portfolio_piece_count_mean": portfolio_summary.get("piece_count_mean", ""),
                "portfolio_piece_overall_mean": portfolio_summary.get("piece_overall_mean", ""),
                "portfolio_piece_median_mean": portfolio_summary.get("piece_median_mean", ""),
                "portfolio_piece_lower_half_mean": portfolio_summary.get("piece_lower_half_mean", ""),
                "portfolio_piece_upper_half_mean": portfolio_summary.get("piece_upper_half_mean", ""),
                "portfolio_piece_top70_mean": portfolio_summary.get("piece_top70_mean", ""),
                "portfolio_piece_top80_mean": portfolio_summary.get("piece_top80_mean", ""),
                "portfolio_piece_lt60_mean": portfolio_summary.get("piece_lt60_mean", ""),
                "draft_completion_penalty_points": round(draft_penalty_points, 2),
                "draft_completion_floor_applied": "true" if draft_floor_applied else "false",
                "draft_completion_severity": draft_severity,
                "anchor_adjustment_points": 0.0,
                "anchor_calibration_active": "false",
                "flags": ";".join(flags),
                "_level_order": float(adjusted_band.get("min", -1.0) if adjusted_band else (base_band.get("min", -1.0) if base_band else -1.0)),
                "_composite_bucket": round(composite, 3),
                "_borda_bucket": round(borda, 3),
            }
        )
    
    if conventions_penalties_applied > 0:
        logger.warning(f"Conventions penalty applied to {conventions_penalties_applied} student(s)")

    rows, portfolio_scale_report = apply_portfolio_scale_calibration(rows, config, scope, level_bands)
    if portfolio_report.get("enabled"):
        portfolio_report["scale_calibration"] = portfolio_scale_report
    write_portfolio_report(Path(args.portfolio_report), portfolio_report)
    if portfolio_scale_report.get("applied", 0):
        logger.info(
            "Portfolio ordinal-scale calibration adjusted %s student(s)",
            portfolio_scale_report.get("applied", 0),
        )

    anchor_patch = load_json(Path(args.anchor_calibration))
    rows, anchor_report = apply_anchor_patch(rows, anchor_patch, level_bands)
    if anchor_report.get("active", False):
        logger.info(
            "Anchor calibration adjusted %s student(s) using %s",
            anchor_report.get("movement_count", 0),
            anchor_report.get("fit_method", "global_shift"),
        )
    else:
        logger.info("Anchor calibration inactive")

    rows, boundary_report = apply_boundary_calibration(rows, config, scope)
    if anchor_report.get("active", False):
        boundary_report["anchor_calibration"] = anchor_report
    write_report(Path(args.boundary_report), boundary_report)
    if boundary_report.get("movement_count", 0):
        logger.info(
            "Boundary calibration applied to %s student(s) for scope grade=%s genre=%s",
            boundary_report.get("movement_count", 0),
            boundary_report.get("scope", {}).get("grade_level"),
            boundary_report.get("scope", {}).get("genre"),
        )
    else:
        logger.info("Boundary calibration made no score adjustments")

    logger.info("Sorting by composite score (weighted: rubric + conventions + comparative)")
    rows_sorted = sorted(
        rows,
        key=lambda r: (
            -r["_level_order"],  # PRIMARY: keep adjusted levels in band order
            -r["_composite_bucket"],  # Tie-break 1: composite score, damped against tiny drift
            -r["_borda_bucket"],      # Tie-break 2: comparative ranking
            -r["rubric_after_penalty_percent"],  # Tie-break 3: rubric after penalty
            r["conventions_mistake_rate_percent"],  # Tie-break 4: conventions (ascending)
            r["student_id"].lower(),  # Tie-break 5: alphabetical
        ),
    )

    for idx, row in enumerate(rows_sorted, start=1):
        row.pop("_level_order", None)
        row.pop("_composite_bucket", None)
        row.pop("_borda_bucket", None)
        row["seed_rank"] = idx
        row["consensus_rank"] = idx
    logger.info(f"Consensus ranking established for {len(rows_sorted)} students")
    out_path = Path(args.output)
    write_consensus_csv(rows_sorted, out_path)
    logger.info(f"✓ Consensus scores written to {out_path}")
    ranked_md = out_path.parent / "ranked_list.md"
    write_ranked_list(rows_sorted, ranked_md)
    logger.info(f"✓ Ranked list written to {ranked_md}")
    recon_path = Path("assessments/pass3_reconcile/disagreements.md")
    disagreements = write_disagreements(rows_sorted, recon_path)
    logger.info(f"✓ Disagreements written to {recon_path} ({len(disagreements)} flagged)")
    irr_path = out_path.parent / "irr_metrics.json"
    irr_full = write_irr_metrics(
        irr,
        irr_path,
        len(student_ids),
        num_assessors_pass1,
        num_assessors_pass2,
        rubric_points_possible,
        len(disagreements),
        conventions_penalties_applied,
    )
    logger.info(f"✓ IRR metrics written to {irr_path}")
    logger.info("")
    logger.info("="*60)
    logger.info("SUMMARY")
    logger.info("="*60)
    logger.info(f"Students processed: {len(student_ids)}")
    logger.info(f"Students flagged for review: {len(disagreements)}")
    logger.info(f"Conventions penalties: {conventions_penalties_applied}")
    logger.info(f"Rubric ICC: {irr['rubric_icc']:.3f} ({irr_full['interpretation']['rubric_icc']})")
    logger.info(f"Rank agreement (Kendall's W): {irr['rank_kendall_w']:.3f} ({irr_full['interpretation']['rank_agreement']})")
    logger.info("="*60)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
