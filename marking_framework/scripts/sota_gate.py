#!/usr/bin/env python3
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from scripts.gate_profiles import decision_state, highest_passing_profile, profile_rank, resolve_gate_profiles
except ImportError:  # pragma: no cover
    from gate_profiles import decision_state, highest_passing_profile, profile_rank, resolve_gate_profiles  # pragma: no cover


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


def _item_count(payload: dict, key: str) -> int:
    items = payload.get(key)
    return len(items) if isinstance(items, list) else 0


def evidence_packet_metrics(
    committee_candidates_path: Path,
    neighborhood_report_path: Path,
    group_packets_path: Path,
) -> dict:
    candidate_payload = load_json(committee_candidates_path)
    candidate_count = _item_count(candidate_payload, "candidates") + _item_count(candidate_payload, "skipped")
    neighborhood_payload = load_json(neighborhood_report_path)
    neighborhoods = neighborhood_payload.get("neighborhoods") if isinstance(neighborhood_payload.get("neighborhoods"), list) else []
    needs_group_count = sum(
        1
        for item in neighborhoods
        if isinstance(item, dict) and str(item.get("recommended_next_action") or "") == "needs_group_calibration"
    )
    packet_payload = load_json(group_packets_path)
    selected_packets = packet_payload.get("packets") if isinstance(packet_payload.get("packets"), list) else []
    skipped_packets = packet_payload.get("skipped") if isinstance(packet_payload.get("skipped"), list) else []
    config = packet_payload.get("config") if isinstance(packet_payload.get("config"), dict) else {}
    max_packet_students = int(config.get("max_packet_students", 0) or 0)
    max_packets = int(config.get("max_packets", 0) or 0)
    selected_sizes = [
        len(packet.get("student_ids", []))
        for packet in selected_packets
        if isinstance(packet, dict) and isinstance(packet.get("student_ids"), list)
    ]
    max_selected_size = max(selected_sizes, default=0)
    bounded = True
    if max_packet_students > 0 and max_selected_size > max_packet_students:
        bounded = False
    if max_packets > 0 and len(selected_packets) > max_packets:
        bounded = False
    needs_packets = needs_group_count > 0
    needs_group_has_packets = bool(not needs_packets or selected_packets)
    ready = True
    if candidate_count > 0 and (not neighborhood_report_path.exists() or not neighborhood_payload.get("enabled")):
        ready = False
    if needs_packets and (not group_packets_path.exists() or not packet_payload.get("enabled") or not selected_packets):
        ready = False
    if not bounded:
        ready = False
    return {
        "committee_candidate_count": candidate_count,
        "evidence_neighborhood_present": neighborhood_report_path.exists(),
        "evidence_neighborhood_enabled": bool(neighborhood_payload.get("enabled", False)),
        "evidence_neighborhood_count": len(neighborhoods),
        "evidence_needs_group_calibration_count": needs_group_count,
        "evidence_group_packets_present": group_packets_path.exists(),
        "evidence_group_packets_enabled": bool(packet_payload.get("enabled", False)),
        "evidence_group_packets_selected_count": len(selected_packets),
        "evidence_group_packets_skipped_count": len(skipped_packets),
        "evidence_group_packets_max_selected_packet_size": max_selected_size,
        "evidence_group_packets_max_packet_students": max_packet_students,
        "evidence_group_packets_max_packets": max_packets,
        "evidence_group_packets_ready": ready,
        "packetized_neighborhoods_have_bounded_reads": bounded,
        "needs_group_calibration_has_packets": needs_group_has_packets,
    }


def benchmark_mode_summary(report: dict, mode: str) -> dict:
    modes = report.get("modes", {}) if isinstance(report, dict) else {}
    if not isinstance(modes, dict):
        return {}
    payload = modes.get(mode, {})
    summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
    return summary if isinstance(summary, dict) else {}


def _summary_metrics(summary: dict) -> dict:
    stability = summary.get("stability", {}) if isinstance(summary, dict) else {}
    level_variance = float(stability.get("mean_student_level_variance", 0.0) or 0.0) if isinstance(stability, dict) else 0.0
    rank_variance = float(stability.get("mean_student_rank_variance", 0.0) or 0.0) if isinstance(stability, dict) else 0.0
    score_variance = float(stability.get("mean_student_score_variance", 0.0) or 0.0) if isinstance(stability, dict) else 0.0
    return {
        "runs_successful": int(summary.get("runs_successful", 0) or 0),
        "runs_attempted": int(summary.get("runs_attempted", 0) or 0),
        "exact_level_hit_rate": float(summary.get("exact_level_hit_rate_mean", 0.0) or 0.0),
        "within_one_level_hit_rate": float(summary.get("within_one_level_hit_rate_mean", 0.0) or 0.0),
        "score_band_mae": float(summary.get("score_band_mae_mean", 0.0) or 0.0),
        "mean_rank_displacement": float(summary.get("mean_rank_displacement_mean", 0.0) or 0.0),
        "kendall_tau": float(summary.get("kendall_tau_mean", 0.0) or 0.0),
        "pairwise_order_agreement": float(summary.get("pairwise_order_agreement_mean", 0.0) or 0.0),
        "model_usage_ratio": float(summary.get("model_usage_ratio_mean", 0.0) or 0.0),
        "cost_usd": float(summary.get("cost_usd_mean", 0.0) or 0.0),
        "latency_seconds": float(summary.get("latency_seconds_mean", 0.0) or 0.0),
        "mean_student_level_variance": level_variance,
        "mean_student_rank_variance": rank_variance,
        "mean_student_score_variance": score_variance,
        "mean_student_level_sd": level_variance ** 0.5,
        "mean_student_rank_sd": rank_variance ** 0.5,
        "mean_student_score_sd": score_variance ** 0.5,
    }


def _weighted_summary_metrics(summary: dict, runs_attempted: int = 0, runs_successful: int | None = None) -> dict:
    if runs_successful is None:
        runs_successful = runs_attempted
    return {
        "runs_successful": int(summary.get("runs_successful", runs_successful) or 0),
        "runs_attempted": int(summary.get("runs_attempted", runs_attempted) or 0),
        "exact_level_hit_rate": float(summary.get("exact_level_hit_rate_mean", summary.get("exact_level_hit_rate", 0.0)) or 0.0),
        "within_one_level_hit_rate": float(
            summary.get("within_one_level_hit_rate_mean", summary.get("within_one_level_hit_rate", 0.0)) or 0.0
        ),
        "score_band_mae": float(summary.get("score_band_mae_mean", summary.get("score_band_mae", 0.0)) or 0.0),
        "mean_rank_displacement": float(
            summary.get("mean_rank_displacement_mean", summary.get("mean_rank_displacement", 0.0)) or 0.0
        ),
        "kendall_tau": float(summary.get("kendall_tau_mean", summary.get("kendall_tau", 0.0)) or 0.0),
        "pairwise_order_agreement": float(
            summary.get("pairwise_order_agreement_mean", summary.get("pairwise_order_agreement", 0.0)) or 0.0
        ),
        "model_usage_ratio": float(summary.get("model_usage_ratio_mean", summary.get("model_usage_ratio", 0.0)) or 0.0),
        "cost_usd": float(summary.get("cost_usd_mean", summary.get("cost_usd", 0.0)) or 0.0),
        "latency_seconds": float(summary.get("latency_seconds_mean", summary.get("latency_seconds", 0.0)) or 0.0),
        "mean_student_level_variance": 0.0,
        "mean_student_rank_variance": 0.0,
        "mean_student_score_variance": 0.0,
        "mean_student_level_sd": 0.0,
        "mean_student_rank_sd": 0.0,
        "mean_student_score_sd": 0.0,
    }


def _weighted_delta_metrics(delta: dict) -> dict:
    return {
        "exact_level_hit_rate": float(delta.get("exact_level_hit_rate_mean", delta.get("exact_level_hit_rate", 0.0)) or 0.0),
        "within_one_level_hit_rate": float(
            delta.get("within_one_level_hit_rate_mean", delta.get("within_one_level_hit_rate", 0.0)) or 0.0
        ),
        "score_band_mae": float(delta.get("score_band_mae_mean", delta.get("score_band_mae", 0.0)) or 0.0),
        "mean_rank_displacement": float(
            delta.get("mean_rank_displacement_mean", delta.get("mean_rank_displacement", 0.0)) or 0.0
        ),
        "kendall_tau": float(delta.get("kendall_tau_mean", delta.get("kendall_tau", 0.0)) or 0.0),
        "pairwise_order_agreement": float(
            delta.get("pairwise_order_agreement_mean", delta.get("pairwise_order_agreement", 0.0)) or 0.0
        ),
        "model_usage_ratio": float(delta.get("model_usage_ratio_mean", delta.get("model_usage_ratio", 0.0)) or 0.0),
        "cost_usd": float(delta.get("cost_usd_mean", delta.get("cost_usd", 0.0)) or 0.0),
        "latency_seconds": float(delta.get("latency_seconds_mean", delta.get("latency_seconds", 0.0)) or 0.0),
        "mean_student_level_variance": 0.0,
        "mean_student_rank_variance": 0.0,
        "mean_student_score_variance": 0.0,
        "mean_student_level_sd": 0.0,
        "mean_student_rank_sd": 0.0,
        "mean_student_score_sd": 0.0,
    }


def benchmark_comparison_metrics(report_path: Path, candidate_mode: str = "", baseline_mode: str = "") -> dict:
    report = load_json(report_path)
    if not isinstance(report, dict) or not report:
        return {"present": False, "candidate_mode": "", "baseline_mode": "", "candidate": {}, "baseline": {}, "delta": {}}
    for key in ("comparison", "current_comparison"):
        comparison = report.get(key, {})
        if not isinstance(comparison, dict):
            continue
        if "candidate_weighted_summary" not in comparison or "baseline_weighted_summary" not in comparison:
            continue
        report_candidate = str(comparison.get("candidate_mode", "")).strip()
        report_baseline = str(comparison.get("baseline_mode", "")).strip()
        candidate_mode = report_candidate or candidate_mode
        baseline_mode = report_baseline or baseline_mode
        runs_attempted = int(report.get("runs_per_dataset_mode", 0) or 0)
        failed_dataset_count = len(report.get("failed_datasets", [])) if isinstance(report.get("failed_datasets", []), list) else 0
        dataset_count = int(report.get("dataset_count", len(report.get("datasets", [])) if isinstance(report.get("datasets", []), list) else 0) or 0)
        return {
            "present": True,
            "candidate_mode": candidate_mode,
            "baseline_mode": baseline_mode,
            "candidate": _weighted_summary_metrics(comparison.get("candidate_weighted_summary", {}), runs_attempted),
            "baseline": _weighted_summary_metrics(comparison.get("baseline_weighted_summary", {}), runs_attempted),
            "delta": _weighted_delta_metrics(comparison.get("delta", {})),
            "failed_dataset_count": failed_dataset_count,
            "dataset_count": dataset_count,
        }
    comparison = report.get("comparison", {})
    report_candidate = str(comparison.get("candidate_mode", "")).strip()
    report_baseline = str(comparison.get("baseline_mode", "")).strip()
    candidate_mode = candidate_mode or report_candidate
    baseline_mode = baseline_mode or report_baseline
    if not candidate_mode or not baseline_mode:
        return {
            "present": False,
            "candidate_mode": candidate_mode,
            "baseline_mode": baseline_mode,
            "candidate": {},
            "baseline": {},
            "delta": {},
        }
    candidate_summary = benchmark_mode_summary(report, candidate_mode)
    baseline_summary = benchmark_mode_summary(report, baseline_mode)
    if not candidate_summary or not baseline_summary:
        return {
            "present": False,
            "candidate_mode": candidate_mode,
            "baseline_mode": baseline_mode,
            "candidate": {},
            "baseline": {},
            "delta": {},
        }
    candidate = _summary_metrics(candidate_summary)
    baseline = _summary_metrics(baseline_summary)
    delta = {}
    for key in (
        "exact_level_hit_rate",
        "within_one_level_hit_rate",
        "score_band_mae",
        "mean_rank_displacement",
        "kendall_tau",
        "pairwise_order_agreement",
        "model_usage_ratio",
        "cost_usd",
        "latency_seconds",
        "mean_student_level_variance",
        "mean_student_rank_variance",
        "mean_student_score_variance",
        "mean_student_level_sd",
        "mean_student_rank_sd",
        "mean_student_score_sd",
    ):
        delta[key] = round(candidate.get(key, 0.0) - baseline.get(key, 0.0), 6)
    return {
        "present": True,
        "candidate_mode": candidate_mode,
        "baseline_mode": baseline_mode,
        "candidate": candidate,
        "baseline": baseline,
        "delta": delta,
        "failed_dataset_count": len(report.get("failed_datasets", [])) if isinstance(report.get("failed_datasets", []), list) else 0,
        "dataset_count": int(report.get("dataset_count", len(report.get("datasets", [])) if isinstance(report.get("datasets", []), list) else 0) or 0),
    }


def publish_profile_state(payload: dict) -> dict:
    if not isinstance(payload, dict) or not payload:
        return {
            "present": False,
            "ok": False,
            "target_profile": "",
            "highest_attained_profile": "",
            "profile_order": ["dev", "candidate", "release"],
        }
    order = payload.get("profile_order", ["dev", "candidate", "release"])
    if not isinstance(order, list) or not order:
        order = ["dev", "candidate", "release"]
    highest_profile = str(payload.get("highest_attained_profile", "") or "").strip()
    target_profile = str(payload.get("target_profile", "") or "").strip()
    if not highest_profile and bool(payload.get("ok", False)):
        highest_profile = target_profile or "dev"
    return {
        "present": True,
        "ok": bool(payload.get("ok", False)),
        "target_profile": target_profile,
        "highest_attained_profile": highest_profile,
        "profile_order": order,
    }


def evaluate(metrics: dict, thresholds: dict) -> list[str]:
    failures = []
    if thresholds.get("require_publish_gate_ok", True) and not metrics["publish_gate_ok"]:
        failures.append("publish_gate_not_ok")
    if not metrics["publish_gate_present"]:
        failures.append("publish_gate_missing")
    required_publish_profile = str(thresholds.get("min_publish_profile", "") or "").strip()
    if required_publish_profile:
        attained_rank = profile_rank(metrics.get("publish_profile_order", []), metrics.get("publish_highest_attained_profile"))
        required_rank = profile_rank(metrics.get("publish_profile_order", []), required_publish_profile)
        if attained_rank < required_rank:
            failures.append("publish_gate_profile_below_threshold")
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
    if not metrics.get("evidence_group_packets_ready", True):
        failures.append("evidence_group_packets_not_ready")
    if not metrics.get("packetized_neighborhoods_have_bounded_reads", True):
        failures.append("evidence_group_packets_unbounded")
    if not metrics.get("needs_group_calibration_has_packets", True):
        failures.append("evidence_group_packets_missing_for_neighborhood")
    if thresholds.get("require_benchmark_report", False) and not metrics["benchmark_comparison_present"]:
        failures.append("benchmark_report_missing")
    if metrics["benchmark_comparison_present"]:
        if metrics["benchmark_runs_successful"] < int(thresholds.get("benchmark_min_runs_successful", 0)):
            failures.append("benchmark_runs_successful_below_threshold")
        if metrics.get("benchmark_failed_dataset_count", 0) > int(thresholds.get("benchmark_max_failed_datasets", 999999)):
            failures.append("benchmark_failed_datasets_above_threshold")
        if metrics["benchmark_exact_level_hit_rate"] < float(thresholds.get("benchmark_min_exact_level_hit_rate", 0.0)):
            failures.append("benchmark_exact_level_hit_rate_below_threshold")
        if metrics["benchmark_within_one_level_hit_rate"] < float(thresholds.get("benchmark_min_within_one_level_hit_rate", 0.0)):
            failures.append("benchmark_within_one_level_hit_rate_below_threshold")
        if metrics["benchmark_score_band_mae"] > float(thresholds.get("benchmark_max_score_band_mae", 999.0)):
            failures.append("benchmark_score_band_mae_above_threshold")
        if metrics["benchmark_mean_rank_displacement"] > float(thresholds.get("benchmark_max_mean_rank_displacement", 999.0)):
            failures.append("benchmark_mean_rank_displacement_above_threshold")
        if metrics["benchmark_kendall_tau"] < float(thresholds.get("benchmark_min_kendall_tau", -999.0)):
            failures.append("benchmark_kendall_tau_below_threshold")
        if metrics["benchmark_pairwise_order_agreement"] < float(thresholds.get("benchmark_min_pairwise_order_agreement", -999.0)):
            failures.append("benchmark_pairwise_order_below_threshold")
        if metrics["benchmark_model_usage_ratio"] < float(thresholds.get("benchmark_min_model_usage_ratio", -999.0)):
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
        if metrics["benchmark_mean_student_level_sd"] > float(thresholds.get("benchmark_max_mean_student_level_sd", 999999.0)):
            failures.append("benchmark_student_level_sd_above_threshold")
        if metrics["benchmark_mean_student_rank_sd"] > float(thresholds.get("benchmark_max_mean_student_rank_sd", 999999.0)):
            failures.append("benchmark_student_rank_sd_above_threshold")
        if metrics["benchmark_mean_student_score_sd"] > float(thresholds.get("benchmark_max_mean_student_score_sd", 999999.0)):
            failures.append("benchmark_student_score_sd_above_threshold")
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
        if metrics["benchmark_mean_student_level_sd_delta"] > float(thresholds.get("benchmark_max_mean_student_level_sd_delta", 999999.0)):
            failures.append("benchmark_student_level_sd_delta_above_threshold")
        if metrics["benchmark_mean_student_rank_sd_delta"] > float(thresholds.get("benchmark_max_mean_student_rank_sd_delta", 999999.0)):
            failures.append("benchmark_student_rank_sd_delta_above_threshold")
        if metrics["benchmark_mean_student_score_sd_delta"] > float(thresholds.get("benchmark_max_mean_student_score_sd_delta", 999999.0)):
            failures.append("benchmark_student_score_sd_delta_above_threshold")
    return failures


def build_profile_metrics(base_metrics: dict, *, thresholds: dict, benchmark_report_path: Path) -> dict:
    metrics = dict(base_metrics)
    benchmark = benchmark_comparison_metrics(
        benchmark_report_path,
        str(thresholds.get("benchmark_candidate_mode", "")).strip(),
        str(thresholds.get("benchmark_baseline_mode", "")).strip(),
    )
    candidate = benchmark.get("candidate", {})
    baseline = benchmark.get("baseline", {})
    delta = benchmark.get("delta", {})
    metrics.update(
        {
            "benchmark_comparison_present": bool(benchmark.get("present", False)),
            "benchmark_report_present": bool(benchmark.get("present", False)),
            "benchmark_candidate_mode": benchmark.get("candidate_mode", ""),
            "benchmark_baseline_mode": benchmark.get("baseline_mode", ""),
            "benchmark_runs_successful": int(candidate.get("runs_successful", 0) or 0),
            "benchmark_runs_attempted": int(candidate.get("runs_attempted", 0) or 0),
            "benchmark_failed_dataset_count": int(benchmark.get("failed_dataset_count", 0) or 0),
            "benchmark_dataset_count": int(benchmark.get("dataset_count", 0) or 0),
            "benchmark_exact_level_hit_rate": float(candidate.get("exact_level_hit_rate", 0.0) or 0.0),
            "benchmark_within_one_level_hit_rate": float(candidate.get("within_one_level_hit_rate", 0.0) or 0.0),
            "benchmark_score_band_mae": float(candidate.get("score_band_mae", 0.0) or 0.0),
            "benchmark_mean_rank_displacement": float(candidate.get("mean_rank_displacement", 0.0) or 0.0),
            "benchmark_kendall_tau": float(candidate.get("kendall_tau", 0.0) or 0.0),
            "benchmark_pairwise_order_agreement": float(candidate.get("pairwise_order_agreement", 0.0) or 0.0),
            "benchmark_model_usage_ratio": float(candidate.get("model_usage_ratio", 0.0) or 0.0),
            "benchmark_cost_usd": float(candidate.get("cost_usd", 0.0) or 0.0),
            "benchmark_latency_seconds": float(candidate.get("latency_seconds", 0.0) or 0.0),
            "benchmark_mean_student_level_variance": float(candidate.get("mean_student_level_variance", 0.0) or 0.0),
            "benchmark_mean_student_rank_variance": float(candidate.get("mean_student_rank_variance", 0.0) or 0.0),
            "benchmark_mean_student_score_variance": float(candidate.get("mean_student_score_variance", 0.0) or 0.0),
            "benchmark_mean_student_level_sd": float(candidate.get("mean_student_level_sd", 0.0) or 0.0),
            "benchmark_mean_student_rank_sd": float(candidate.get("mean_student_rank_sd", 0.0) or 0.0),
            "benchmark_mean_student_score_sd": float(candidate.get("mean_student_score_sd", 0.0) or 0.0),
            "benchmark_baseline_exact_level_hit_rate": float(baseline.get("exact_level_hit_rate", 0.0) or 0.0),
            "benchmark_baseline_within_one_level_hit_rate": float(baseline.get("within_one_level_hit_rate", 0.0) or 0.0),
            "benchmark_baseline_score_band_mae": float(baseline.get("score_band_mae", 0.0) or 0.0),
            "benchmark_baseline_kendall_tau": float(baseline.get("kendall_tau", 0.0) or 0.0),
            "benchmark_baseline_pairwise_order_agreement": float(baseline.get("pairwise_order_agreement", 0.0) or 0.0),
            "benchmark_exact_level_hit_rate_delta": float(delta.get("exact_level_hit_rate", 0.0) or 0.0),
            "benchmark_within_one_level_hit_rate_delta": float(delta.get("within_one_level_hit_rate", 0.0) or 0.0),
            "benchmark_score_band_mae_delta": float(delta.get("score_band_mae", 0.0) or 0.0),
            "benchmark_mean_rank_displacement_delta": float(delta.get("mean_rank_displacement", 0.0) or 0.0),
            "benchmark_kendall_tau_delta": float(delta.get("kendall_tau", 0.0) or 0.0),
            "benchmark_pairwise_order_agreement_delta": float(delta.get("pairwise_order_agreement", 0.0) or 0.0),
            "benchmark_model_usage_ratio_delta": float(delta.get("model_usage_ratio", 0.0) or 0.0),
            "benchmark_cost_usd_delta": float(delta.get("cost_usd", 0.0) or 0.0),
            "benchmark_latency_seconds_delta": float(delta.get("latency_seconds", 0.0) or 0.0),
            "benchmark_mean_student_level_variance_delta": float(delta.get("mean_student_level_variance", 0.0) or 0.0),
            "benchmark_mean_student_rank_variance_delta": float(delta.get("mean_student_rank_variance", 0.0) or 0.0),
            "benchmark_mean_student_score_variance_delta": float(delta.get("mean_student_score_variance", 0.0) or 0.0),
            "benchmark_mean_student_level_sd_delta": float(delta.get("mean_student_level_sd", 0.0) or 0.0),
            "benchmark_mean_student_rank_sd_delta": float(delta.get("mean_student_rank_sd", 0.0) or 0.0),
            "benchmark_mean_student_score_sd_delta": float(delta.get("mean_student_score_sd", 0.0) or 0.0),
        }
    )
    return metrics


def evaluate_profiles(base_metrics: dict, gate_cfg: dict, *, benchmark_report_path: Path) -> tuple[list[str], str, dict[str, dict]]:
    order, target_profile, profiles = resolve_gate_profiles(gate_cfg, fallback_profile="dev")
    results = {}
    for name in order:
        thresholds = profiles[name]
        metrics = build_profile_metrics(base_metrics, thresholds=thresholds, benchmark_report_path=benchmark_report_path)
        failures = evaluate(metrics, thresholds)
        results[name] = {
            "ok": len(failures) == 0,
            "failures": failures,
            "thresholds": thresholds,
            "metrics": metrics,
        }
    return order, target_profile, results


def write_markdown_report(path: Path, payload: dict) -> None:
    metrics = payload.get("metrics", {})
    profiles = payload.get("profiles", {})
    lines = [
        "# SOTA Gate",
        "",
        f"- **ok**: {payload.get('ok', False)}",
        f"- **target_profile**: {payload.get('target_profile', '')}",
        f"- **highest_attained_profile**: {payload.get('highest_attained_profile', '') or 'none'}",
        f"- **decision_state**: {payload.get('decision_state', '')}",
        "",
        "## Profiles",
    ]
    for name in payload.get("profile_order", []):
        profile = profiles.get(name, {})
        lines.append(f"- **{name}**: {'pass' if profile.get('ok', False) else 'fail'}")
        for failure in profile.get("failures", []):
            lines.append(f"- {name}: {failure}")
    lines.extend(["", "## Metrics"])
    for key in (
        "publish_highest_attained_profile",
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
        "committee_candidate_count",
        "evidence_neighborhood_present",
        "evidence_neighborhood_enabled",
        "evidence_neighborhood_count",
        "evidence_needs_group_calibration_count",
        "evidence_group_packets_present",
        "evidence_group_packets_enabled",
        "evidence_group_packets_selected_count",
        "evidence_group_packets_skipped_count",
        "evidence_group_packets_max_selected_packet_size",
        "evidence_group_packets_max_packet_students",
        "evidence_group_packets_max_packets",
        "evidence_group_packets_ready",
        "packetized_neighborhoods_have_bounded_reads",
        "needs_group_calibration_has_packets",
        "benchmark_candidate_mode",
        "benchmark_baseline_mode",
        "benchmark_failed_dataset_count",
        "benchmark_dataset_count",
        "benchmark_runs_successful",
        "benchmark_exact_level_hit_rate",
        "benchmark_within_one_level_hit_rate",
        "benchmark_score_band_mae",
        "benchmark_kendall_tau",
        "benchmark_pairwise_order_agreement",
        "benchmark_mean_student_level_sd",
        "benchmark_mean_student_rank_sd",
        "benchmark_mean_student_score_sd",
        "benchmark_cost_usd",
        "benchmark_latency_seconds",
        "benchmark_exact_level_hit_rate_delta",
        "benchmark_within_one_level_hit_rate_delta",
        "benchmark_score_band_mae_delta",
        "benchmark_kendall_tau_delta",
        "benchmark_pairwise_order_agreement_delta",
    ):
        lines.append(f"- **{key}**: {metrics.get(key)}")
    failures = payload.get("failures", [])
    if failures:
        lines.extend(["", "## Failures"])
        lines.extend(f"- {item}" for item in failures)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="SOTA readiness gate for assessment quality.")
    parser.add_argument("--publish-gate", default="outputs/publish_gate.json", help="Publish gate JSON")
    parser.add_argument("--pass1", default="assessments/pass1_individual", help="Pass1 assessor directory")
    parser.add_argument("--consistency", default="outputs/consistency_checks.json", help="Consistency checks JSON")
    parser.add_argument("--benchmark-report", default="outputs/benchmark_report.json", help="Optional benchmark report JSON")
    parser.add_argument("--committee-candidates", default="outputs/committee_edge_candidates.json", help="Committee-edge candidates JSON")
    parser.add_argument("--evidence-neighborhood-report", default="outputs/evidence_neighborhood_report.json", help="Evidence neighborhood report JSON")
    parser.add_argument("--evidence-group-packets", default="outputs/evidence_group_calibration_packets.json", help="Evidence group-calibration packets JSON")
    parser.add_argument("--gate-config", default="config/sota_gate.json", help="SOTA thresholds JSON")
    parser.add_argument("--output", default="outputs/sota_gate.json", help="SOTA result JSON")
    args = parser.parse_args()

    gate_cfg = load_json(Path(args.gate_config))
    publish = publish_profile_state(load_json(Path(args.publish_gate)))
    rows = load_pass1_rows(Path(args.pass1))
    consistency_total, swap_rate, low_conf_rate = consistency_metrics(Path(args.consistency))
    mean_sd, p95_sd = assessor_spread(rows)
    evidence_packets = evidence_packet_metrics(
        Path(args.committee_candidates),
        Path(args.evidence_neighborhood_report),
        Path(args.evidence_group_packets),
    )
    base_metrics = {
        "publish_gate_present": publish["present"],
        "publish_gate_ok": publish["ok"],
        "publish_target_profile": publish["target_profile"],
        "publish_highest_attained_profile": publish["highest_attained_profile"],
        "publish_profile_order": publish["profile_order"],
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
        **evidence_packets,
    }
    profile_order, target_profile, profile_results = evaluate_profiles(
        base_metrics,
        gate_cfg,
        benchmark_report_path=Path(args.benchmark_report),
    )
    highest_profile = highest_passing_profile(profile_order, profile_results)
    target_result = profile_results.get(
        target_profile,
        {"ok": False, "failures": ["target_profile_missing"], "thresholds": {}, "metrics": base_metrics},
    )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": bool(target_result.get("ok", False)),
        "target_profile": target_profile,
        "highest_attained_profile": highest_profile,
        "decision_state": decision_state(profile_order, highest_profile),
        "profile_order": profile_order,
        "failures": list(target_result.get("failures", [])),
        "thresholds": target_result.get("thresholds", {}),
        "metrics": target_result.get("metrics", base_metrics),
        "profiles": profile_results,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md = out.with_suffix(".md")
    write_markdown_report(md, payload)
    print(f"Wrote {out}")
    print(f"Wrote {md}")
    return 0 if payload["ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
