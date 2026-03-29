#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_pass1_rows(pass1_dir: Path) -> list[dict]:
    rows = []
    for path in sorted(pass1_dir.glob("assessor_*.json")):
        payload = load_json(path)
        assessor_id = str(payload.get("assessor_id") or path.stem)
        for item in payload.get("scores", []):
            row = dict(item)
            row["assessor_id"] = assessor_id
            rows.append(row)
    return rows


def model_coverage(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    model_rows = 0
    for row in rows:
        notes = str(row.get("notes", ""))
        if "Fallback deterministic score" not in notes:
            model_rows += 1
    return model_rows / len(rows)


def score_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    valid = 0
    for row in rows:
        try:
            if float(row.get("rubric_total_points", 0.0) or 0.0) > 0.0:
                valid += 1
        except (TypeError, ValueError):
            continue
    return valid / len(rows)


def criteria_coverage(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    hit = 0
    for row in rows:
        points = row.get("criteria_points")
        if isinstance(points, dict) and points:
            hit += 1
    return hit / len(rows)


def evidence_coverage(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    hit = 0
    for row in rows:
        evidence = row.get("criteria_evidence")
        if isinstance(evidence, list) and evidence:
            hit += 1
    return hit / len(rows)


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / len(values)
    return variance ** 0.5


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


def assessor_spread(rows: list[dict]) -> tuple[float, float]:
    scores = {}
    for row in rows:
        sid = str(row.get("student_id", "")).strip()
        if not sid:
            continue
        try:
            score = float(row.get("rubric_total_points", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        scores.setdefault(sid, []).append(score)
    sds = [_stdev(items) for items in scores.values() if len(items) > 1]
    if not sds:
        return 0.0, 0.0
    return sum(sds) / len(sds), _percentile(sds, 0.95)


def consistency_metrics(path: Path) -> tuple[int, float, float]:
    payload = load_json(path)
    checks = payload.get("checks", []) if isinstance(payload, dict) else []
    if not checks:
        return 0, 0.0, 0.0
    swaps = 0
    low = 0
    for item in checks:
        decision = str(item.get("decision", "")).upper()
        if decision == "SWAP":
            swaps += 1
        confidence = str(item.get("confidence", "")).lower()
        if confidence == "low":
            low += 1
    total = len(checks)
    return total, swaps / total, low / total


def benchmark_mode_summary(report: dict, mode: str) -> dict:
    modes = report.get("modes", {}) if isinstance(report, dict) else {}
    if not isinstance(modes, dict):
        return {}
    payload = modes.get(mode, {})
    summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
    return summary if isinstance(summary, dict) else {}


def benchmark_comparison_metrics(report_path: Path, candidate_mode: str = "", baseline_mode: str = "") -> dict:
    report = load_json(report_path)
    if not isinstance(report, dict) or not report:
        return {"present": False, "candidate_mode": "", "baseline_mode": "", "delta": {}}
    comparison = report.get("comparison", {})
    report_candidate = str(comparison.get("candidate_mode", "")).strip()
    report_baseline = str(comparison.get("baseline_mode", "")).strip()
    candidate_mode = candidate_mode or report_candidate
    baseline_mode = baseline_mode or report_baseline
    if not candidate_mode or not baseline_mode:
        return {"present": False, "candidate_mode": candidate_mode, "baseline_mode": baseline_mode, "delta": {}}
    candidate_summary = benchmark_mode_summary(report, candidate_mode)
    baseline_summary = benchmark_mode_summary(report, baseline_mode)
    if not candidate_summary or not baseline_summary:
        return {"present": False, "candidate_mode": candidate_mode, "baseline_mode": baseline_mode, "delta": {}}
    delta = {
        "exact_level_hit_rate": round(candidate_summary.get("exact_level_hit_rate_mean", 0.0) - baseline_summary.get("exact_level_hit_rate_mean", 0.0), 6),
        "within_one_level_hit_rate": round(candidate_summary.get("within_one_level_hit_rate_mean", 0.0) - baseline_summary.get("within_one_level_hit_rate_mean", 0.0), 6),
        "score_band_mae": round(candidate_summary.get("score_band_mae_mean", 0.0) - baseline_summary.get("score_band_mae_mean", 0.0), 6),
        "mean_rank_displacement": round(candidate_summary.get("mean_rank_displacement_mean", 0.0) - baseline_summary.get("mean_rank_displacement_mean", 0.0), 6),
        "kendall_tau": round(candidate_summary.get("kendall_tau_mean", 0.0) - baseline_summary.get("kendall_tau_mean", 0.0), 6),
        "pairwise_order_agreement": round(candidate_summary.get("pairwise_order_agreement_mean", 0.0) - baseline_summary.get("pairwise_order_agreement_mean", 0.0), 6),
        "model_usage_ratio": round(candidate_summary.get("model_usage_ratio_mean", 0.0) - baseline_summary.get("model_usage_ratio_mean", 0.0), 6),
        "cost_usd": round(candidate_summary.get("cost_usd_mean", 0.0) - baseline_summary.get("cost_usd_mean", 0.0), 6),
        "latency_seconds": round(candidate_summary.get("latency_seconds_mean", 0.0) - baseline_summary.get("latency_seconds_mean", 0.0), 6),
        "mean_student_level_variance": round(
            candidate_summary.get("stability", {}).get("mean_student_level_variance", 0.0)
            - baseline_summary.get("stability", {}).get("mean_student_level_variance", 0.0),
            6,
        ),
        "mean_student_rank_variance": round(
            candidate_summary.get("stability", {}).get("mean_student_rank_variance", 0.0)
            - baseline_summary.get("stability", {}).get("mean_student_rank_variance", 0.0),
            6,
        ),
        "mean_student_score_variance": round(
            candidate_summary.get("stability", {}).get("mean_student_score_variance", 0.0)
            - baseline_summary.get("stability", {}).get("mean_student_score_variance", 0.0),
            6,
        ),
    }
    return {"present": True, "candidate_mode": candidate_mode, "baseline_mode": baseline_mode, "delta": delta}


def evaluate(metrics: dict, thresholds: dict) -> list[str]:
    failures = []
    if thresholds.get("require_publish_gate_ok", True) and not metrics["publish_gate_ok"]:
        failures.append("publish_gate_not_ok")
    if not metrics["publish_gate_present"]:
        failures.append("publish_gate_missing")
    if metrics["assessor_files"] < int(thresholds.get("min_assessor_files", 0)):
        failures.append("assessor_count_below_threshold")
    if metrics["model_coverage"] < float(thresholds.get("min_model_coverage", 0.0)):
        failures.append("model_coverage_below_threshold")
    if metrics["nonzero_score_rate"] < float(thresholds.get("min_nonzero_score_rate", 0.0)):
        failures.append("nonzero_score_rate_below_threshold")
    if metrics["criteria_coverage"] < float(thresholds.get("min_criteria_coverage", 0.0)):
        failures.append("criteria_coverage_below_threshold")
    if metrics["evidence_coverage"] < float(thresholds.get("min_evidence_coverage", 0.0)):
        failures.append("evidence_coverage_below_threshold")
    if metrics["mean_assessor_sd"] > float(thresholds.get("max_mean_assessor_sd", 999.0)):
        failures.append("mean_assessor_sd_above_threshold")
    if metrics["p95_assessor_sd"] > float(thresholds.get("max_p95_assessor_sd", 999.0)):
        failures.append("p95_assessor_sd_above_threshold")
    if metrics["consistency_swap_rate"] > float(thresholds.get("max_consistency_swap_rate", 1.0)):
        failures.append("consistency_swap_rate_above_threshold")
    if metrics["consistency_low_confidence_rate"] > float(thresholds.get("max_consistency_low_confidence_rate", 1.0)):
        failures.append("consistency_low_confidence_rate_above_threshold")
    if thresholds.get("require_benchmark_report", False) and not metrics["benchmark_comparison_present"]:
        failures.append("benchmark_report_missing")
    if metrics["benchmark_comparison_present"]:
        if metrics["benchmark_exact_level_hit_rate_delta"] < float(thresholds.get("benchmark_min_exact_level_hit_rate_delta", -999.0)):
            failures.append("benchmark_exact_level_hit_rate_delta_below_threshold")
        if metrics["benchmark_within_one_level_hit_rate_delta"] < float(thresholds.get("benchmark_min_within_one_level_hit_rate_delta", -999.0)):
            failures.append("benchmark_within_one_level_hit_rate_delta_below_threshold")
        if metrics["benchmark_score_band_mae_delta"] > float(thresholds.get("benchmark_max_score_band_mae_delta", 999.0)):
            failures.append("benchmark_score_band_mae_delta_above_threshold")
        if metrics["benchmark_mean_rank_displacement_delta"] > float(thresholds.get("benchmark_max_mean_rank_displacement_delta", 999.0)):
            failures.append("benchmark_mean_rank_displacement_delta_above_threshold")
        if metrics["benchmark_kendall_tau_delta"] < float(thresholds.get("benchmark_min_kendall_tau_delta", -999.0)):
            failures.append("benchmark_kendall_tau_delta_below_threshold")
        if metrics["benchmark_pairwise_order_agreement_delta"] < float(thresholds.get("benchmark_min_pairwise_order_agreement_delta", -999.0)):
            failures.append("benchmark_pairwise_order_delta_below_threshold")
        if metrics["benchmark_model_usage_ratio_delta"] < float(thresholds.get("benchmark_min_model_usage_ratio_delta", -999.0)):
            failures.append("benchmark_model_usage_delta_below_threshold")
        if metrics["benchmark_cost_usd_delta"] > float(thresholds.get("benchmark_max_cost_usd_delta", 999999.0)):
            failures.append("benchmark_cost_delta_above_threshold")
        if metrics["benchmark_latency_seconds_delta"] > float(thresholds.get("benchmark_max_latency_seconds_delta", 999999.0)):
            failures.append("benchmark_latency_delta_above_threshold")
        if metrics["benchmark_mean_student_level_variance_delta"] > float(thresholds.get("benchmark_max_mean_student_level_variance_delta", 999999.0)):
            failures.append("benchmark_student_level_variance_delta_above_threshold")
        if metrics["benchmark_mean_student_rank_variance_delta"] > float(thresholds.get("benchmark_max_mean_student_rank_variance_delta", 999999.0)):
            failures.append("benchmark_student_rank_variance_delta_above_threshold")
        if metrics["benchmark_mean_student_score_variance_delta"] > float(thresholds.get("benchmark_max_mean_student_score_variance_delta", 999999.0)):
            failures.append("benchmark_student_score_variance_delta_above_threshold")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="SOTA readiness gate for assessment quality.")
    parser.add_argument("--publish-gate", default="outputs/publish_gate.json", help="Publish gate JSON")
    parser.add_argument("--pass1", default="assessments/pass1_individual", help="Pass1 assessor directory")
    parser.add_argument("--consistency", default="outputs/consistency_checks.json", help="Consistency checks JSON")
    parser.add_argument("--benchmark-report", default="outputs/benchmark_report.json", help="Optional benchmark report JSON")
    parser.add_argument("--gate-config", default="config/sota_gate.json", help="SOTA thresholds JSON")
    parser.add_argument("--output", default="outputs/sota_gate.json", help="SOTA result JSON")
    args = parser.parse_args()

    config = load_json(Path(args.gate_config))
    thresholds = config.get("thresholds", config)

    publish = load_json(Path(args.publish_gate))
    rows = load_pass1_rows(Path(args.pass1))
    consistency_total, swap_rate, low_conf_rate = consistency_metrics(Path(args.consistency))
    mean_sd, p95_sd = assessor_spread(rows)
    benchmark = benchmark_comparison_metrics(
        Path(args.benchmark_report),
        str(thresholds.get("benchmark_candidate_mode", "")).strip(),
        str(thresholds.get("benchmark_baseline_mode", "")).strip(),
    )

    metrics = {
        "publish_gate_present": bool(publish),
        "publish_gate_ok": bool(publish.get("ok", False)) if publish else False,
        "assessor_files": len(list(Path(args.pass1).glob("assessor_*.json"))),
        "pass1_rows": len(rows),
        "model_coverage": model_coverage(rows),
        "nonzero_score_rate": score_rate(rows),
        "criteria_coverage": criteria_coverage(rows),
        "evidence_coverage": evidence_coverage(rows),
        "mean_assessor_sd": mean_sd,
        "p95_assessor_sd": p95_sd,
        "consistency_checks": consistency_total,
        "consistency_swap_rate": swap_rate,
        "consistency_low_confidence_rate": low_conf_rate,
        "benchmark_comparison_present": bool(benchmark.get("present", False)),
        "benchmark_candidate_mode": benchmark.get("candidate_mode", ""),
        "benchmark_baseline_mode": benchmark.get("baseline_mode", ""),
        "benchmark_exact_level_hit_rate_delta": float(benchmark.get("delta", {}).get("exact_level_hit_rate", 0.0) or 0.0),
        "benchmark_within_one_level_hit_rate_delta": float(benchmark.get("delta", {}).get("within_one_level_hit_rate", 0.0) or 0.0),
        "benchmark_score_band_mae_delta": float(benchmark.get("delta", {}).get("score_band_mae", 0.0) or 0.0),
        "benchmark_mean_rank_displacement_delta": float(benchmark.get("delta", {}).get("mean_rank_displacement", 0.0) or 0.0),
        "benchmark_kendall_tau_delta": float(benchmark.get("delta", {}).get("kendall_tau", 0.0) or 0.0),
        "benchmark_pairwise_order_agreement_delta": float(benchmark.get("delta", {}).get("pairwise_order_agreement", 0.0) or 0.0),
        "benchmark_model_usage_ratio_delta": float(benchmark.get("delta", {}).get("model_usage_ratio", 0.0) or 0.0),
        "benchmark_cost_usd_delta": float(benchmark.get("delta", {}).get("cost_usd", 0.0) or 0.0),
        "benchmark_latency_seconds_delta": float(benchmark.get("delta", {}).get("latency_seconds", 0.0) or 0.0),
        "benchmark_mean_student_level_variance_delta": float(benchmark.get("delta", {}).get("mean_student_level_variance", 0.0) or 0.0),
        "benchmark_mean_student_rank_variance_delta": float(benchmark.get("delta", {}).get("mean_student_rank_variance", 0.0) or 0.0),
        "benchmark_mean_student_score_variance_delta": float(benchmark.get("delta", {}).get("mean_student_score_variance", 0.0) or 0.0),
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
    lines = ["# SOTA Gate", "", f"- **ok**: {payload['ok']}"]
    for key in (
        "assessor_files",
        "pass1_rows",
        "model_coverage",
        "nonzero_score_rate",
        "criteria_coverage",
        "evidence_coverage",
        "mean_assessor_sd",
        "p95_assessor_sd",
        "consistency_checks",
        "consistency_swap_rate",
        "consistency_low_confidence_rate",
        "benchmark_candidate_mode",
        "benchmark_baseline_mode",
        "benchmark_exact_level_hit_rate_delta",
        "benchmark_within_one_level_hit_rate_delta",
        "benchmark_score_band_mae_delta",
        "benchmark_mean_rank_displacement_delta",
        "benchmark_kendall_tau_delta",
        "benchmark_pairwise_order_agreement_delta",
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
