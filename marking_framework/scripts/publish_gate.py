#!/usr/bin/env python3
import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from scripts.aggregate_helpers import get_level_bands
    from scripts.assessor_context import grade_band_for_level, load_class_metadata, normalize_genre, select_grade_level
    from scripts.calibration_contract import build_run_scope, calibration_manifest_path
    from scripts.calibration_gate import inspect_calibration_profile
except ImportError:  # pragma: no cover
    from aggregate_helpers import get_level_bands  # pragma: no cover
    from assessor_context import grade_band_for_level, load_class_metadata, normalize_genre, select_grade_level  # pragma: no cover
    from calibration_contract import build_run_scope, calibration_manifest_path  # pragma: no cover
    from calibration_gate import inspect_calibration_profile  # pragma: no cover


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def boundary_count(rows: list[dict], level_bands: list[dict], margin: float) -> int:
    if not rows or not level_bands:
        return 0
    mins = sorted(float(b.get("min", 0.0) or 0.0) for b in level_bands)
    boundaries = [v for v in mins[1:]]
    flagged = 0
    for row in rows:
        try:
            score = float(row.get("rubric_after_penalty_percent", 0.0) or 0.0)
        except ValueError:
            continue
        if boundaries and min(abs(score - edge) for edge in boundaries) <= margin:
            flagged += 1
    return flagged


def model_coverage(pass1_dir: Path) -> float:
    files = sorted(pass1_dir.glob("assessor_*.json"))
    total = 0
    model_rows = 0
    for path in files:
        payload = load_json(path)
        for row in payload.get("scores", []):
            total += 1
            notes = str(row.get("notes", ""))
            if "Fallback deterministic score" not in notes:
                model_rows += 1
    return (model_rows / total) if total else 0.0


def anchor_metrics(rows: list[dict], metadata: list[dict]) -> tuple[int, float, float]:
    by_id = {row.get("student_id"): row for row in rows}
    anchors = []
    for entry in metadata:
        sid = entry.get("student_id")
        expected = str(entry.get("gold_level") or entry.get("expected_level") or entry.get("anchor_level") or "").strip()
        if sid in by_id and expected:
            anchors.append((sid, expected, by_id[sid].get("adjusted_level", "")))
    if not anchors:
        return 0, 0.0, 0.0
    level_map = {"1": 1.0, "2": 2.0, "3": 3.0, "4": 4.0, "4+": 5.0}
    hits = sum(1 for _, expected, got in anchors if expected == got)
    deltas = [abs(level_map[expected] - level_map[got]) for _, expected, got in anchors if expected in level_map and got in level_map]
    hit_rate = hits / len(anchors)
    mae = (sum(deltas) / len(deltas)) if deltas else 0.0
    return len(anchors), hit_rate, mae


def scope_from_metadata(class_metadata: Path) -> str:
    data = load_class_metadata(class_metadata)
    grade = select_grade_level(None, data)
    band = grade_band_for_level(grade)
    genre = normalize_genre(data.get("genre") or data.get("assignment_genre"))
    if not band or not genre:
        return ""
    return f"{band}|{genre}"


def run_scope_from_inputs(class_metadata: Path, routing: Path, rubric: Path) -> dict:
    metadata = load_class_metadata(class_metadata)
    routing_payload = load_json(routing)
    return build_run_scope(metadata=metadata, routing=routing_payload, rubric_path=rubric)


def calibration_metrics(
    calibration_bias: Path,
    calibration_manifest: Path | list[str],
    assessor_ids: list[str] | dict | str | None = None,
    run_scope: dict | None = None,
    *,
    routing_path: Path | None = None,
    rubric_path: Path | None = None,
    calibration_set_path: Path | None = None,
    exemplars_path: Path | None = None,
) -> dict:
    if isinstance(calibration_manifest, list):
        legacy_scope = assessor_ids
        assessor_ids = calibration_manifest
        calibration_manifest = calibration_manifest_path(calibration_bias)
        resolved_scope = legacy_scope if isinstance(legacy_scope, dict) else {"key": str(legacy_scope or "")}
    else:
        resolved_scope = run_scope or {}
    if isinstance(assessor_ids, str):
        resolved_scope = {"key": assessor_ids}
        assessor_ids = []
    if isinstance(assessor_ids, dict) and not resolved_scope:
        resolved_scope = assessor_ids
        assessor_ids = []
    assessor_ids = list(assessor_ids or [])
    calibration_manifest = Path(calibration_manifest)
    routing_path = routing_path or Path("config/llm_routing.json")
    rubric_path = rubric_path or Path("inputs/rubric.md")
    calibration_set_path = calibration_set_path or Path("config/calibration_set.json")
    exemplars_path = exemplars_path or Path("inputs/exemplars")
    report = inspect_calibration_profile(
        bias_path=calibration_bias,
        assessor_ids=assessor_ids,
        run_scope=resolved_scope,
        context={
            "manifest_path": calibration_manifest,
            "routing_path": routing_path,
            "rubric_path": rubric_path,
            "calibration_set_path": calibration_set_path,
            "exemplars_path": exemplars_path,
        },
    )
    assessors = load_json(calibration_bias).get("assessors", {})
    values = {
        "level_hit_rate": [],
        "mae": [],
        "pairwise_order_agreement": [],
        "repeat_level_consistency": [],
        "abs_bias": [],
        "boundary_mae": [],
        "rank_stability_sd": [],
        "boundary_pairwise_disagreement": [],
        "boundary_pairwise_disagreement_concentration": [],
    }
    missing = []
    for raw in assessor_ids:
        aid = raw if raw.startswith("assessor_") else f"assessor_{raw}"
        scope_data = assessors.get(aid, {}).get("scopes", {}).get(resolved_scope.get("key", ""), {})
        if not scope_data:
            missing.append(aid)
            continue
        values["level_hit_rate"].append(float(scope_data.get("level_hit_rate", 0.0) or 0.0))
        values["mae"].append(float(scope_data.get("mae", 0.0) or 0.0))
        values["pairwise_order_agreement"].append(float(scope_data.get("pairwise_order_agreement", 0.0) or 0.0))
        values["repeat_level_consistency"].append(float(scope_data.get("repeat_level_consistency", 0.0) or 0.0))
        values["abs_bias"].append(abs(float(scope_data.get("bias", 0.0) or 0.0)))
        values["boundary_mae"].append(float(scope_data.get("boundary_mae", 0.0) or 0.0))
        values["rank_stability_sd"].append(float(scope_data.get("rank_stability_sd", 0.0) or 0.0))
        values["boundary_pairwise_disagreement"].append(float(scope_data.get("boundary_pairwise_disagreement", 0.0) or 0.0))
        values["boundary_pairwise_disagreement_concentration"].append(
            float(scope_data.get("boundary_pairwise_disagreement_concentration", 0.0) or 0.0)
        )
    means = {k: (sum(v) / len(v) if v else 0.0) for k, v in values.items()}
    means["missing_assessors"] = missing
    means["scope"] = resolved_scope.get("key", "")
    means["scope_match"] = bool(report.get("scope_match", False))
    means["scope_mismatch_fields"] = list(report.get("scope_mismatch_fields", []))
    means["manifest_present"] = bool(report.get("manifest_present", False))
    means["manifest_integrity_ok"] = bool(report.get("manifest_integrity_ok", True))
    means["synthetic"] = bool(report.get("synthetic", False))
    means["profile_type"] = str(report.get("profile_type", "") or "")
    means["generated_at"] = str(report.get("generated_at", "") or "")
    means["generated_age_hours"] = report.get("generated_age_hours")
    means["freshness_window_hours"] = report.get("freshness_window_hours")
    means["drift_failures"] = list(report.get("drift_failures", []))
    means["coverage_scope"] = report.get("coverage_scope", {})
    return means


def benchmark_mode_summary(report: dict, preferred_mode: str = "") -> tuple[str, dict]:
    modes = report.get("modes", {}) if isinstance(report, dict) else {}
    if not isinstance(modes, dict) or not modes:
        return "", {}
    ordered_labels = []
    if preferred_mode:
        ordered_labels.append(preferred_mode)
    comparison = report.get("comparison", {}) if isinstance(report, dict) else {}
    candidate_mode = str(comparison.get("candidate_mode", "")).strip()
    if candidate_mode and candidate_mode not in ordered_labels:
        ordered_labels.append(candidate_mode)
    ordered_labels.extend(label for label in sorted(modes) if label not in ordered_labels)
    for label in ordered_labels:
        payload = modes.get(label, {})
        summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
        if isinstance(summary, dict) and summary:
            return label, summary
    return "", {}


def benchmark_metrics(report_path: Path, preferred_mode: str = "") -> dict:
    report = load_json(report_path)
    label, summary = benchmark_mode_summary(report, preferred_mode)
    stability = summary.get("stability", {}) if isinstance(summary, dict) else {}
    return {
        "present": bool(summary),
        "mode": label,
        "runs_successful": int(summary.get("runs_successful", 0) or 0) if summary else 0,
        "runs_attempted": int(summary.get("runs_attempted", 0) or 0) if summary else 0,
        "exact_level_hit_rate": float(summary.get("exact_level_hit_rate_mean", 0.0) or 0.0) if summary else 0.0,
        "within_one_level_hit_rate": float(summary.get("within_one_level_hit_rate_mean", 0.0) or 0.0) if summary else 0.0,
        "score_band_mae": float(summary.get("score_band_mae_mean", 0.0) or 0.0) if summary else 0.0,
        "mean_rank_displacement": float(summary.get("mean_rank_displacement_mean", 0.0) or 0.0) if summary else 0.0,
        "kendall_tau": float(summary.get("kendall_tau_mean", 0.0) or 0.0) if summary else 0.0,
        "pairwise_order_agreement": float(summary.get("pairwise_order_agreement_mean", 0.0) or 0.0) if summary else 0.0,
        "model_usage_ratio": float(summary.get("model_usage_ratio_mean", 0.0) or 0.0) if summary else 0.0,
        "cost_usd": float(summary.get("cost_usd_mean", 0.0) or 0.0) if summary else 0.0,
        "latency_seconds": float(summary.get("latency_seconds_mean", 0.0) or 0.0) if summary else 0.0,
        "mean_student_level_variance": float(stability.get("mean_student_level_variance", 0.0) or 0.0) if isinstance(stability, dict) else 0.0,
        "mean_student_rank_variance": float(stability.get("mean_student_rank_variance", 0.0) or 0.0) if isinstance(stability, dict) else 0.0,
        "mean_student_score_variance": float(stability.get("mean_student_score_variance", 0.0) or 0.0) if isinstance(stability, dict) else 0.0,
    }


def evaluate(metrics: dict, thresholds: dict) -> list[str]:
    failures = []
    release_mode = str(thresholds.get("release_mode", "development") or "development").strip().lower()
    strict_release = release_mode in {"candidate", "release", "production"}
    if metrics["irr_rank_kendalls_w"] < float(thresholds.get("min_rank_kendall_w", 0.0)):
        failures.append("kendall_w_below_threshold")
    if metrics["irr_mean_rubric_sd"] > float(thresholds.get("max_mean_rubric_sd", 999.0)):
        failures.append("rubric_sd_above_threshold")
    if metrics["model_coverage"] < float(thresholds.get("min_model_coverage", 0.0)):
        failures.append("model_coverage_below_threshold")
    if metrics["boundary_count"] > int(thresholds.get("max_boundary_students", 9999)):
        failures.append("too_many_boundary_students")
    anchor_min = thresholds.get("anchor_min_hit_rate")
    anchor_max_mae = thresholds.get("anchor_max_mae")
    if metrics["anchors_total"] > 0 and anchor_min is not None and metrics["anchor_hit_rate"] < float(anchor_min):
        failures.append("anchor_hit_rate_below_threshold")
    if metrics["anchors_total"] > 0 and anchor_max_mae is not None and metrics["anchor_level_mae"] > float(anchor_max_mae):
        failures.append("anchor_mae_above_threshold")
    if metrics["cal_missing_assessors"]:
        failures.append("calibration_scope_missing")
    if thresholds.get("calibration_require_manifest", strict_release) and not metrics.get("calibration_manifest_present", False):
        failures.append("calibration_manifest_missing")
    if thresholds.get("calibration_require_manifest_integrity", strict_release) and not metrics.get("calibration_manifest_integrity_ok", True):
        failures.append("calibration_manifest_integrity_failed")
    if thresholds.get("calibration_require_scope_match", strict_release) and not metrics.get("calibration_scope_match", False):
        failures.append("calibration_scope_mismatch")
    if thresholds.get("calibration_require_production_profile", strict_release) and metrics.get("calibration_synthetic", False):
        failures.append("calibration_synthetic_not_allowed")
    if metrics.get("calibration_drift_failures", []) and thresholds.get("calibration_fail_on_drift", strict_release):
        drift_map = {
            "stale": "calibration_stale",
            "routing_profile_mismatch": "calibration_routing_profile_mismatch",
            "rubric_hash_mismatch": "calibration_rubric_mismatch",
            "exemplar_set_mismatch": "calibration_exemplar_set_mismatch",
            "scope_mismatch": "calibration_scope_mismatch",
            "manifest_integrity": "calibration_manifest_integrity_failed",
            "synthetic": "calibration_synthetic_not_allowed",
        }
        for item in metrics.get("calibration_drift_failures", []):
            code = drift_map.get(str(item), f"calibration_drift_{item}")
            if code not in failures:
                failures.append(code)
    if metrics["cal_level_hit_rate"] < float(thresholds.get("calibration_min_level_hit_rate", 0.0)):
        failures.append("calibration_level_hit_rate_below_threshold")
    if metrics["cal_mae"] > float(thresholds.get("calibration_max_mae", 999.0)):
        failures.append("calibration_mae_above_threshold")
    if metrics["cal_pairwise_order"] < float(thresholds.get("calibration_min_pairwise_order", 0.0)):
        failures.append("calibration_pairwise_below_threshold")
    if metrics["cal_repeat_consistency"] < float(thresholds.get("calibration_min_repeat_level_consistency", 0.0)):
        failures.append("calibration_repeat_consistency_below_threshold")
    if metrics["cal_abs_bias"] > float(thresholds.get("calibration_max_abs_bias", 999.0)):
        failures.append("calibration_abs_bias_above_threshold")
    if metrics.get("cal_boundary_mae", 0.0) > float(thresholds.get("calibration_max_boundary_mae", 999.0)):
        failures.append("calibration_boundary_mae_above_threshold")
    if metrics.get("cal_rank_stability_sd", 0.0) > float(thresholds.get("calibration_max_rank_stability_sd", 999.0)):
        failures.append("calibration_rank_stability_sd_above_threshold")
    if metrics.get("cal_boundary_pairwise_disagreement", 0.0) > float(thresholds.get("calibration_max_boundary_pairwise_disagreement", 999.0)):
        failures.append("calibration_boundary_pairwise_disagreement_above_threshold")
    if metrics.get("cal_boundary_pairwise_disagreement_concentration", 0.0) > float(
        thresholds.get("calibration_max_boundary_pairwise_disagreement_concentration", 999.0)
    ):
        failures.append("calibration_boundary_pairwise_concentration_above_threshold")
    if thresholds.get("require_benchmark_report", False) and not metrics["benchmark_report_present"]:
        failures.append("benchmark_report_missing")
    if metrics["benchmark_report_present"]:
        if metrics["benchmark_runs_successful"] < int(thresholds.get("benchmark_min_runs_successful", 0)):
            failures.append("benchmark_runs_successful_below_threshold")
        if metrics["benchmark_exact_level_hit_rate"] < float(thresholds.get("benchmark_min_exact_level_hit_rate", 0.0)):
            failures.append("benchmark_exact_level_hit_rate_below_threshold")
        if metrics["benchmark_within_one_level_hit_rate"] < float(thresholds.get("benchmark_min_within_one_level_hit_rate", 0.0)):
            failures.append("benchmark_within_one_level_hit_rate_below_threshold")
        if metrics["benchmark_score_band_mae"] > float(thresholds.get("benchmark_max_score_band_mae", 999.0)):
            failures.append("benchmark_score_band_mae_above_threshold")
        if metrics["benchmark_mean_rank_displacement"] > float(thresholds.get("benchmark_max_mean_rank_displacement", 999.0)):
            failures.append("benchmark_mean_rank_displacement_above_threshold")
        if metrics["benchmark_kendall_tau"] < float(thresholds.get("benchmark_min_kendall_tau", 0.0)):
            failures.append("benchmark_kendall_tau_below_threshold")
        if metrics["benchmark_pairwise_order_agreement"] < float(thresholds.get("benchmark_min_pairwise_order_agreement", 0.0)):
            failures.append("benchmark_pairwise_order_below_threshold")
        if metrics["benchmark_model_usage_ratio"] < float(thresholds.get("benchmark_min_model_usage_ratio", 0.0)):
            failures.append("benchmark_model_usage_below_threshold")
        if metrics["benchmark_cost_usd"] > float(thresholds.get("benchmark_max_cost_usd", 999999.0)):
            failures.append("benchmark_cost_above_threshold")
        if metrics["benchmark_latency_seconds"] > float(thresholds.get("benchmark_max_latency_seconds", 999999.0)):
            failures.append("benchmark_latency_above_threshold")
        if metrics["benchmark_mean_student_level_variance"] > float(thresholds.get("benchmark_max_mean_student_level_variance", 999999.0)):
            failures.append("benchmark_student_level_variance_above_threshold")
        if metrics["benchmark_mean_student_rank_variance"] > float(thresholds.get("benchmark_max_mean_student_rank_variance", 999999.0)):
            failures.append("benchmark_student_rank_variance_above_threshold")
        if metrics["benchmark_mean_student_score_variance"] > float(thresholds.get("benchmark_max_mean_student_score_variance", 999999.0)):
            failures.append("benchmark_student_score_variance_above_threshold")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish gate for accuracy-consistency quality.")
    parser.add_argument("--consensus", default="outputs/consensus_scores.csv", help="Consensus CSV")
    parser.add_argument("--submission-metadata", default="processing/submission_metadata.json", help="Submission metadata JSON")
    parser.add_argument("--irr", default="outputs/irr_metrics.json", help="IRR metrics JSON")
    parser.add_argument("--pass1", default="assessments/pass1_individual", help="Pass1 output directory")
    parser.add_argument("--calibration-bias", default="outputs/calibration_bias.json", help="Calibration bias JSON")
    parser.add_argument("--calibration-manifest", default="outputs/calibration_manifest.json", help="Calibration manifest JSON")
    parser.add_argument("--marking-config", default="config/marking_config.json", help="Marking config")
    parser.add_argument("--class-metadata", default="inputs/class_metadata.json", help="Class metadata JSON")
    parser.add_argument("--routing", default="config/llm_routing.json", help="Routing config")
    parser.add_argument("--rubric", default="inputs/rubric.md", help="Rubric file")
    parser.add_argument("--calibration-set", default="config/calibration_set.json", help="Calibration set JSON")
    parser.add_argument("--exemplars", default="inputs/exemplars", help="Exemplars root")
    parser.add_argument("--gate-config", default="config/accuracy_gate.json", help="Accuracy gate JSON config")
    parser.add_argument("--benchmark-report", default="outputs/benchmark_report.json", help="Optional benchmark report JSON")
    parser.add_argument("--assessors", default="A,B,C", help="Assessor IDs")
    parser.add_argument("--output", default="outputs/publish_gate.json", help="Gate result JSON")
    args = parser.parse_args()

    rows = load_rows(Path(args.consensus))
    metadata = load_json(Path(args.submission_metadata))
    if not isinstance(metadata, list):
        metadata = []
    irr = load_json(Path(args.irr)).get("inter_rater_reliability", {})
    marking_cfg = load_json(Path(args.marking_config))
    gate_cfg = load_json(Path(args.gate_config))
    thresholds = gate_cfg.get("thresholds", gate_cfg)
    bands = get_level_bands(marking_cfg)
    boundary_margin = float(thresholds.get("boundary_margin_percent", 1.0) or 1.0)
    run_scope = run_scope_from_inputs(Path(args.class_metadata), Path(args.routing), Path(args.rubric))
    scope = run_scope.get("key", "")
    assessor_ids = [item.strip() for item in args.assessors.split(",") if item.strip()]
    cal_manifest_path = Path(args.calibration_manifest)
    if not cal_manifest_path.exists():
        cal_manifest_path = calibration_manifest_path(Path(args.calibration_bias))
    cal = calibration_metrics(
        Path(args.calibration_bias),
        cal_manifest_path,
        assessor_ids,
        run_scope,
        routing_path=Path(args.routing),
        rubric_path=Path(args.rubric),
        calibration_set_path=Path(args.calibration_set),
        exemplars_path=Path(args.exemplars),
    )
    benchmark = benchmark_metrics(Path(args.benchmark_report), str(thresholds.get("benchmark_mode", "")).strip())

    anchors_total, anchor_hit_rate, anchor_level_mae = anchor_metrics(rows, metadata)
    metrics = {
        "rows": len(rows),
        "irr_rank_kendalls_w": float(irr.get("rank_kendall_w", 0.0) or 0.0),
        "irr_mean_rubric_sd": float(irr.get("mean_rubric_sd", 0.0) or 0.0),
        "model_coverage": model_coverage(Path(args.pass1)),
        "boundary_count": boundary_count(rows, bands, boundary_margin),
        "anchors_total": anchors_total,
        "anchor_hit_rate": anchor_hit_rate,
        "anchor_level_mae": anchor_level_mae,
        "scope": scope,
        "scope_descriptor": run_scope,
        "cal_missing_assessors": cal.get("missing_assessors", []),
        "calibration_manifest_present": bool(cal.get("manifest_present", False)),
        "calibration_manifest_integrity_ok": bool(cal.get("manifest_integrity_ok", True)),
        "calibration_synthetic": bool(cal.get("synthetic", False)),
        "calibration_scope_match": bool(cal.get("scope_match", False)),
        "calibration_scope_mismatch_fields": cal.get("scope_mismatch_fields", []),
        "calibration_profile_type": cal.get("profile_type", ""),
        "calibration_generated_at": cal.get("generated_at", ""),
        "calibration_generated_age_hours": cal.get("generated_age_hours"),
        "calibration_freshness_window_hours": cal.get("freshness_window_hours"),
        "calibration_drift_failures": cal.get("drift_failures", []),
        "cal_level_hit_rate": float(cal.get("level_hit_rate", 0.0) or 0.0),
        "cal_mae": float(cal.get("mae", 0.0) or 0.0),
        "cal_pairwise_order": float(cal.get("pairwise_order_agreement", 0.0) or 0.0),
        "cal_repeat_consistency": float(cal.get("repeat_level_consistency", 0.0) or 0.0),
        "cal_abs_bias": float(cal.get("abs_bias", 0.0) or 0.0),
        "cal_boundary_mae": float(cal.get("boundary_mae", 0.0) or 0.0),
        "cal_rank_stability_sd": float(cal.get("rank_stability_sd", 0.0) or 0.0),
        "cal_boundary_pairwise_disagreement": float(cal.get("boundary_pairwise_disagreement", 0.0) or 0.0),
        "cal_boundary_pairwise_disagreement_concentration": float(
            cal.get("boundary_pairwise_disagreement_concentration", 0.0) or 0.0
        ),
        "benchmark_report_present": bool(benchmark.get("present", False)),
        "benchmark_mode": benchmark.get("mode", ""),
        "benchmark_runs_successful": int(benchmark.get("runs_successful", 0) or 0),
        "benchmark_runs_attempted": int(benchmark.get("runs_attempted", 0) or 0),
        "benchmark_exact_level_hit_rate": float(benchmark.get("exact_level_hit_rate", 0.0) or 0.0),
        "benchmark_within_one_level_hit_rate": float(benchmark.get("within_one_level_hit_rate", 0.0) or 0.0),
        "benchmark_score_band_mae": float(benchmark.get("score_band_mae", 0.0) or 0.0),
        "benchmark_mean_rank_displacement": float(benchmark.get("mean_rank_displacement", 0.0) or 0.0),
        "benchmark_kendall_tau": float(benchmark.get("kendall_tau", 0.0) or 0.0),
        "benchmark_pairwise_order_agreement": float(benchmark.get("pairwise_order_agreement", 0.0) or 0.0),
        "benchmark_model_usage_ratio": float(benchmark.get("model_usage_ratio", 0.0) or 0.0),
        "benchmark_cost_usd": float(benchmark.get("cost_usd", 0.0) or 0.0),
        "benchmark_latency_seconds": float(benchmark.get("latency_seconds", 0.0) or 0.0),
        "benchmark_mean_student_level_variance": float(benchmark.get("mean_student_level_variance", 0.0) or 0.0),
        "benchmark_mean_student_rank_variance": float(benchmark.get("mean_student_rank_variance", 0.0) or 0.0),
        "benchmark_mean_student_score_variance": float(benchmark.get("mean_student_score_variance", 0.0) or 0.0),
    }
    failures = evaluate(metrics, thresholds)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": len(failures) == 0,
        "failures": failures,
        "thresholds": thresholds,
        "metrics": metrics,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md = out.with_suffix(".md")
    lines = ["# Publish Gate", "", f"- **ok**: {payload['ok']}"]
    for key in (
        "irr_rank_kendalls_w", "irr_mean_rubric_sd", "model_coverage", "boundary_count",
        "anchor_hit_rate", "anchor_level_mae", "cal_level_hit_rate", "cal_mae",
        "cal_pairwise_order", "cal_repeat_consistency", "cal_abs_bias", "cal_boundary_mae",
        "cal_rank_stability_sd", "calibration_manifest_present", "calibration_scope_match",
        "calibration_synthetic",
        "benchmark_mode", "benchmark_runs_successful", "benchmark_exact_level_hit_rate",
        "benchmark_within_one_level_hit_rate", "benchmark_score_band_mae",
        "benchmark_mean_rank_displacement", "benchmark_kendall_tau",
        "benchmark_pairwise_order_agreement", "benchmark_model_usage_ratio",
        "benchmark_cost_usd", "benchmark_latency_seconds",
    ):
        lines.append(f"- **{key}**: {metrics.get(key)}")
    if failures:
        lines.extend(["", "## Failures"] + [f"- {item}" for item in failures])
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out}")
    print(f"Wrote {md}")
    return 0 if payload["ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
