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
except ImportError:  # pragma: no cover
    from aggregate_helpers import get_level_bands  # pragma: no cover
    from assessor_context import grade_band_for_level, load_class_metadata, normalize_genre, select_grade_level  # pragma: no cover


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


def calibration_metrics(calibration_bias: Path, assessor_ids: list[str], scope: str) -> dict:
    payload = load_json(calibration_bias)
    assessors = payload.get("assessors", {}) if isinstance(payload, dict) else {}
    values = {
        "level_hit_rate": [],
        "mae": [],
        "pairwise_order_agreement": [],
        "repeat_level_consistency": [],
        "abs_bias": [],
    }
    missing = []
    for raw in assessor_ids:
        aid = raw if raw.startswith("assessor_") else f"assessor_{raw}"
        scope_data = assessors.get(aid, {}).get("scopes", {}).get(scope, {})
        if not scope_data:
            missing.append(aid)
            continue
        values["level_hit_rate"].append(float(scope_data.get("level_hit_rate", 0.0) or 0.0))
        values["mae"].append(float(scope_data.get("mae", 0.0) or 0.0))
        values["pairwise_order_agreement"].append(float(scope_data.get("pairwise_order_agreement", 0.0) or 0.0))
        values["repeat_level_consistency"].append(float(scope_data.get("repeat_level_consistency", 0.0) or 0.0))
        values["abs_bias"].append(abs(float(scope_data.get("bias", 0.0) or 0.0)))
    means = {k: (sum(v) / len(v) if v else 0.0) for k, v in values.items()}
    means["missing_assessors"] = missing
    means["scope"] = scope
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
    parser.add_argument("--marking-config", default="config/marking_config.json", help="Marking config")
    parser.add_argument("--class-metadata", default="inputs/class_metadata.json", help="Class metadata JSON")
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
    scope = scope_from_metadata(Path(args.class_metadata))
    assessor_ids = [item.strip() for item in args.assessors.split(",") if item.strip()]
    cal = calibration_metrics(Path(args.calibration_bias), assessor_ids, scope)
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
        "cal_missing_assessors": cal.get("missing_assessors", []),
        "cal_level_hit_rate": float(cal.get("level_hit_rate", 0.0) or 0.0),
        "cal_mae": float(cal.get("mae", 0.0) or 0.0),
        "cal_pairwise_order": float(cal.get("pairwise_order_agreement", 0.0) or 0.0),
        "cal_repeat_consistency": float(cal.get("repeat_level_consistency", 0.0) or 0.0),
        "cal_abs_bias": float(cal.get("abs_bias", 0.0) or 0.0),
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
        "cal_pairwise_order", "cal_repeat_consistency", "cal_abs_bias",
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
