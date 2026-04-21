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
    from scripts.gate_profiles import decision_state, highest_passing_profile, resolve_gate_profiles
except ImportError:  # pragma: no cover
    from aggregate_helpers import get_level_bands  # pragma: no cover
    from assessor_context import grade_band_for_level, load_class_metadata, normalize_genre, select_grade_level  # pragma: no cover
    from calibration_contract import build_run_scope, calibration_manifest_path  # pragma: no cover
    from calibration_gate import inspect_calibration_profile  # pragma: no cover
    from gate_profiles import decision_state, highest_passing_profile, resolve_gate_profiles  # pragma: no cover


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


def benchmark_weighted_summary(report: dict, preferred_mode: str = "") -> tuple[str, dict, int, int, int, int]:
    if not isinstance(report, dict) or not report:
        return "", {}, 0, 0, 0, 0
    for key in ("comparison", "current_comparison"):
        comparison = report.get(key, {})
        if not isinstance(comparison, dict):
            continue
        summary = comparison.get("candidate_weighted_summary", {})
        if not isinstance(summary, dict) or not summary:
            continue
        mode = str(comparison.get("candidate_mode", "") or preferred_mode).strip()
        runs_attempted = int(report.get("runs_per_dataset_mode", summary.get("runs_attempted", 0)) or 0)
        runs_successful = int(summary.get("runs_successful", runs_attempted) or 0)
        failed_dataset_count = len(report.get("failed_datasets", [])) if isinstance(report.get("failed_datasets", []), list) else 0
        dataset_count = int(report.get("dataset_count", len(report.get("datasets", [])) if isinstance(report.get("datasets", []), list) else 0) or 0)
        return mode, summary, runs_successful, runs_attempted, failed_dataset_count, dataset_count
    return "", {}, 0, 0, 0, 0


def benchmark_metrics(report_path: Path, preferred_mode: str = "") -> dict:
    report = load_json(report_path)
    weighted_mode, weighted_summary, weighted_runs_successful, weighted_runs_attempted, failed_dataset_count, dataset_count = benchmark_weighted_summary(
        report, preferred_mode
    )
    if weighted_summary:
        return {
            "present": True,
            "mode": weighted_mode,
            "runs_successful": weighted_runs_successful,
            "runs_attempted": weighted_runs_attempted,
            "exact_level_hit_rate": float(weighted_summary.get("exact_level_hit_rate_mean", weighted_summary.get("exact_level_hit_rate", 0.0)) or 0.0),
            "within_one_level_hit_rate": float(
                weighted_summary.get("within_one_level_hit_rate_mean", weighted_summary.get("within_one_level_hit_rate", 0.0)) or 0.0
            ),
            "score_band_mae": float(weighted_summary.get("score_band_mae_mean", weighted_summary.get("score_band_mae", 0.0)) or 0.0),
            "mean_rank_displacement": float(
                weighted_summary.get("mean_rank_displacement_mean", weighted_summary.get("mean_rank_displacement", 0.0)) or 0.0
            ),
            "kendall_tau": float(weighted_summary.get("kendall_tau_mean", weighted_summary.get("kendall_tau", 0.0)) or 0.0),
            "pairwise_order_agreement": float(
                weighted_summary.get("pairwise_order_agreement_mean", weighted_summary.get("pairwise_order_agreement", 0.0)) or 0.0
            ),
            "model_usage_ratio": float(weighted_summary.get("model_usage_ratio_mean", weighted_summary.get("model_usage_ratio", 0.0)) or 0.0),
            "cost_usd": float(weighted_summary.get("cost_usd_mean", weighted_summary.get("cost_usd", 0.0)) or 0.0),
            "latency_seconds": float(weighted_summary.get("latency_seconds_mean", weighted_summary.get("latency_seconds", 0.0)) or 0.0),
            "mean_student_level_variance": 0.0,
            "mean_student_rank_variance": 0.0,
            "mean_student_score_variance": 0.0,
            "mean_student_level_sd": 0.0,
            "mean_student_rank_sd": 0.0,
            "mean_student_score_sd": 0.0,
            "failed_dataset_count": failed_dataset_count,
            "dataset_count": dataset_count,
        }
    label, summary = benchmark_mode_summary(report, preferred_mode)
    stability = summary.get("stability", {}) if isinstance(summary, dict) else {}
    level_variance = float(stability.get("mean_student_level_variance", 0.0) or 0.0) if isinstance(stability, dict) else 0.0
    rank_variance = float(stability.get("mean_student_rank_variance", 0.0) or 0.0) if isinstance(stability, dict) else 0.0
    score_variance = float(stability.get("mean_student_score_variance", 0.0) or 0.0) if isinstance(stability, dict) else 0.0
    failed_dataset_count = len(report.get("failed_datasets", [])) if isinstance(report.get("failed_datasets", []), list) else 0
    dataset_count = int(report.get("dataset_count", len(report.get("datasets", [])) if isinstance(report.get("datasets", []), list) else 0) or 0)
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
        "mean_student_level_variance": level_variance,
        "mean_student_rank_variance": rank_variance,
        "mean_student_score_variance": score_variance,
        "mean_student_level_sd": level_variance ** 0.5,
        "mean_student_rank_sd": rank_variance ** 0.5,
        "mean_student_score_sd": score_variance ** 0.5,
        "failed_dataset_count": failed_dataset_count,
        "dataset_count": dataset_count,
    }


def pairwise_eval_metrics(report_path: Path) -> dict:
    report = load_json(report_path)
    if not report:
        return {
            "present": False,
            "mode": "",
            "judgments": "",
            "escalated_path": False,
            "pair_count": 0,
            "evaluated_count": 0,
            "accuracy": 0.0,
            "coverage": 0.0,
            "critical_accuracy": 0.0,
            "polish_bias_risk_count": 0,
            "failures": [],
        }
    summary = report.get("summary", {}) if isinstance(report.get("summary"), dict) else {}
    inputs = report.get("inputs", {}) if isinstance(report.get("inputs"), dict) else {}
    polish_bias_risks = report.get("polish_bias_risks", []) if isinstance(report.get("polish_bias_risks"), list) else []
    failures = summary.get("failures", []) if isinstance(summary.get("failures"), list) else []
    judgments = str(inputs.get("judgments", "") or "")
    escalated_path = bool(judgments and "escalated" in Path(judgments).name)
    escalated_path = escalated_path or contains_escalated_pairwise_judgment(report)
    return {
        "present": True,
        "mode": str(report.get("mode", "") or ""),
        "judgments": judgments,
        "escalated_path": escalated_path,
        "pair_count": int(summary.get("pair_count", 0) or 0),
        "evaluated_count": int(summary.get("evaluated_count", 0) or 0),
        "accuracy": float(summary.get("accuracy", 0.0) or 0.0),
        "coverage": float(summary.get("coverage", 0.0) or 0.0),
        "critical_accuracy": float(summary.get("critical_accuracy", 0.0) or 0.0),
        "polish_bias_risk_count": len(polish_bias_risks),
        "failures": [str(item) for item in failures],
    }


def _item_count(payload: dict, key: str) -> int:
    items = payload.get(key)
    return len(items) if isinstance(items, list) else 0


def evidence_packet_metrics(
    committee_candidates_path: Path,
    neighborhood_report_path: Path,
    group_packets_path: Path,
) -> dict:
    candidates_present = committee_candidates_path.exists()
    candidate_payload = load_json(committee_candidates_path)
    candidate_count = _item_count(candidate_payload, "candidates") + _item_count(candidate_payload, "skipped")
    neighborhood_present = neighborhood_report_path.exists()
    neighborhood_payload = load_json(neighborhood_report_path)
    neighborhoods = neighborhood_payload.get("neighborhoods") if isinstance(neighborhood_payload.get("neighborhoods"), list) else []
    needs_group_count = sum(
        1
        for item in neighborhoods
        if isinstance(item, dict) and str(item.get("recommended_next_action") or "") == "needs_group_calibration"
    )
    packets_present = group_packets_path.exists()
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
    read_type_counts = packet_payload.get("read_type_counts") if isinstance(packet_payload.get("read_type_counts"), dict) else {}
    bounded = True
    if max_packet_students > 0 and max_selected_size > max_packet_students:
        bounded = False
    if max_packets > 0 and len(selected_packets) > max_packets:
        bounded = False
    needs_packets = needs_group_count > 0
    ready = True
    if candidate_count > 0 and (not neighborhood_present or not neighborhood_payload.get("enabled")):
        ready = False
    if needs_packets and (not packets_present or not packet_payload.get("enabled") or not selected_packets):
        ready = False
    if not bounded:
        ready = False
    return {
        "committee_candidates_present": candidates_present,
        "committee_candidate_count": candidate_count,
        "evidence_neighborhood_present": neighborhood_present,
        "evidence_neighborhood_enabled": bool(neighborhood_payload.get("enabled", False)),
        "evidence_neighborhood_count": len(neighborhoods),
        "evidence_needs_group_calibration_count": needs_group_count,
        "evidence_group_packets_present": packets_present,
        "evidence_group_packets_enabled": bool(packet_payload.get("enabled", False)),
        "evidence_group_packets_candidate_count": int(packet_payload.get("counts", {}).get("candidate_packets", 0) or 0)
        if isinstance(packet_payload.get("counts"), dict)
        else 0,
        "evidence_group_packets_selected_count": len(selected_packets),
        "evidence_group_packets_skipped_count": len(skipped_packets),
        "evidence_group_packets_read_type_counts": read_type_counts,
        "evidence_group_packets_max_selected_packet_size": max_selected_size,
        "evidence_group_packets_max_packet_students": max_packet_students,
        "evidence_group_packets_max_packets": max_packets,
        "evidence_group_packets_ready": ready,
        "evidence_group_packets_bounded": bounded,
        "evidence_needs_group_calibration_has_packets": bool(not needs_packets or selected_packets),
    }


def contains_escalated_pairwise_judgment(value) -> bool:
    if isinstance(value, dict):
        metadata = value.get("model_metadata") if isinstance(value.get("model_metadata"), dict) else {}
        source = str(metadata.get("adjudication_source") or value.get("adjudication_source") or "").strip()
        if source in {"escalated_adjudication", "committee_edge"}:
            return True
        return any(contains_escalated_pairwise_judgment(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_escalated_pairwise_judgment(item) for item in value)
    return False


def reproducibility_metrics(report_path: Path) -> dict:
    report = load_json(report_path)
    if not report:
        return {
            "present": False,
            "runs_compared": 0,
            "manifest_identical": False,
            "final_outputs_exact_match": False,
            "within_tolerance": False,
            "max_intermediate_metric_delta": 0.0,
            "mismatched_final_artifact_count": 0,
            "mismatched_intermediate_artifact_count": 0,
        }
    summary = report.get("summary", report) if isinstance(report, dict) else {}
    mismatched_final = summary.get("mismatched_final_artifacts", []) if isinstance(summary, dict) else []
    mismatched_intermediate = summary.get("mismatched_intermediate_artifacts", []) if isinstance(summary, dict) else []
    final_exact = bool(summary.get("final_outputs_exact_match", summary.get("exact_match", False)))
    within_tolerance = bool(summary.get("within_tolerance", final_exact))
    return {
        "present": True,
        "runs_compared": int(summary.get("runs_compared", summary.get("manifest_identical_runs", 0)) or 0),
        "manifest_identical": bool(summary.get("manifest_identical", summary.get("manifest_hash_match", False))),
        "final_outputs_exact_match": final_exact,
        "within_tolerance": within_tolerance,
        "max_intermediate_metric_delta": float(summary.get("max_intermediate_metric_delta", 0.0) or 0.0),
        "mismatched_final_artifact_count": len(mismatched_final) if isinstance(mismatched_final, list) else 0,
        "mismatched_intermediate_artifact_count": len(mismatched_intermediate) if isinstance(mismatched_intermediate, list) else 0,
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
    if metrics.get("calibration_scope_samples", 0) < int(thresholds.get("calibration_min_scope_samples", 0)):
        failures.append("calibration_scope_samples_below_threshold")
    if metrics.get("calibration_scope_observations", 0) < int(thresholds.get("calibration_min_scope_observations", 0)):
        failures.append("calibration_scope_observations_below_threshold")
    if thresholds.get("calibration_require_manifest", strict_release) and not metrics.get("calibration_manifest_present", False):
        failures.append("calibration_manifest_missing")
    if thresholds.get("calibration_require_manifest_integrity", strict_release) and not metrics.get("calibration_manifest_integrity_ok", True):
        failures.append("calibration_manifest_integrity_failed")
    if thresholds.get("calibration_require_scope_match", strict_release) and not metrics.get("calibration_scope_match", False):
        failures.append("calibration_scope_mismatch")
    if thresholds.get("calibration_require_production_profile", strict_release) and metrics.get("calibration_synthetic", False):
        failures.append("calibration_synthetic_not_allowed")
    if metrics.get("calibration_generated_age_hours") is not None and metrics.get("calibration_generated_age_hours", 0.0) > float(
        thresholds.get("calibration_max_age_hours", 999999.0)
    ):
        failures.append("calibration_stale")
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
    if thresholds.get("reproducibility_require_report", False) and not metrics.get("reproducibility_report_present", False):
        failures.append("reproducibility_report_missing")
    if metrics.get("reproducibility_report_present", False):
        if metrics.get("reproducibility_runs_compared", 0) < int(thresholds.get("reproducibility_min_runs_compared", 0)):
            failures.append("reproducibility_runs_compared_below_threshold")
        if thresholds.get("reproducibility_require_manifest_identical", False) and not metrics.get("reproducibility_manifest_identical", False):
            failures.append("reproducibility_manifest_mismatch")
        if thresholds.get("reproducibility_require_exact_final_outputs", False) and not metrics.get(
            "reproducibility_final_outputs_exact_match", False
        ):
            failures.append("reproducibility_final_outputs_mismatch")
        if thresholds.get("reproducibility_require_within_tolerance", False) and not metrics.get(
            "reproducibility_within_tolerance", False
        ):
            failures.append("reproducibility_outside_tolerance")
        if metrics.get("reproducibility_max_intermediate_metric_delta", 0.0) > float(
            thresholds.get("reproducibility_max_intermediate_metric_delta", 999999.0)
        ):
            failures.append("reproducibility_intermediate_delta_above_threshold")
    if thresholds.get("require_benchmark_report", False) and not metrics["benchmark_report_present"]:
        failures.append("benchmark_report_missing")
    if metrics["benchmark_report_present"]:
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
        if metrics.get("benchmark_mean_student_level_sd", 0.0) > float(thresholds.get("benchmark_max_mean_student_level_sd", 999999.0)):
            failures.append("benchmark_student_level_sd_above_threshold")
        if metrics.get("benchmark_mean_student_rank_sd", 0.0) > float(thresholds.get("benchmark_max_mean_student_rank_sd", 999999.0)):
            failures.append("benchmark_student_rank_sd_above_threshold")
        if metrics.get("benchmark_mean_student_score_sd", 0.0) > float(thresholds.get("benchmark_max_mean_student_score_sd", 999999.0)):
            failures.append("benchmark_student_score_sd_above_threshold")
    if thresholds.get("require_pairwise_eval_report", False) and not metrics.get("pairwise_eval_present", False):
        failures.append("pairwise_eval_report_missing")
    if metrics.get("pairwise_eval_present", False):
        if metrics.get("pairwise_eval_accuracy", 0.0) < float(thresholds.get("pairwise_eval_min_accuracy", 0.0)):
            failures.append("pairwise_eval_accuracy_below_threshold")
        if metrics.get("pairwise_eval_critical_accuracy", 0.0) < float(thresholds.get("pairwise_eval_min_critical_accuracy", 0.0)):
            failures.append("pairwise_eval_critical_accuracy_below_threshold")
        if metrics.get("pairwise_eval_coverage", 0.0) < float(thresholds.get("pairwise_eval_min_coverage", 0.0)):
            failures.append("pairwise_eval_coverage_below_threshold")
        if metrics.get("pairwise_eval_polish_bias_risk_count", 0) > int(thresholds.get("pairwise_eval_max_polish_bias_risks", 999999)):
            failures.append("pairwise_eval_polish_bias_risks_above_threshold")
        if thresholds.get("pairwise_eval_fail_on_report_failures", False) and metrics.get("pairwise_eval_failures", []):
            failures.append("pairwise_eval_report_failures_present")
    if thresholds.get("pairwise_eval_require_escalated_path", False) and not metrics.get("pairwise_eval_escalated_path", False):
        failures.append("pairwise_eval_escalated_path_missing")
    require_evidence_packets = thresholds.get("require_evidence_group_packets", strict_release)
    if require_evidence_packets:
        if metrics.get("committee_candidate_count", 0) > 0:
            if not metrics.get("evidence_neighborhood_present", False):
                failures.append("evidence_neighborhood_report_missing")
            elif not metrics.get("evidence_neighborhood_enabled", False):
                failures.append("evidence_neighborhood_report_disabled")
        if metrics.get("evidence_needs_group_calibration_count", 0) > 0:
            if not metrics.get("evidence_group_packets_present", False):
                failures.append("evidence_group_packets_missing")
            elif not metrics.get("evidence_group_packets_enabled", False):
                failures.append("evidence_group_packets_disabled")
            if metrics.get("evidence_group_packets_selected_count", 0) <= 0:
                failures.append("evidence_group_packets_empty")
        max_packet_students = int(metrics.get("evidence_group_packets_max_packet_students", 0) or 0)
        if max_packet_students > 0 and metrics.get("evidence_group_packets_max_selected_packet_size", 0) > max_packet_students:
            failures.append("evidence_group_packet_size_above_limit")
        max_packets = int(metrics.get("evidence_group_packets_max_packets", 0) or 0)
        if max_packets > 0 and metrics.get("evidence_group_packets_selected_count", 0) > max_packets:
            failures.append("evidence_group_packet_count_above_limit")
    return failures


def build_profile_metrics(
    base_metrics: dict,
    *,
    thresholds: dict,
    rows: list[dict],
    level_bands: list[dict],
    benchmark_report_path: Path,
    pairwise_eval_report_path: Path,
) -> dict:
    metrics = dict(base_metrics)
    boundary_margin = float(thresholds.get("boundary_margin_percent", 1.0) or 1.0)
    benchmark = benchmark_metrics(benchmark_report_path, str(thresholds.get("benchmark_mode", "")).strip())
    pairwise_eval = pairwise_eval_metrics(pairwise_eval_report_path)
    metrics.update(
        {
            "boundary_count": boundary_count(rows, level_bands, boundary_margin),
            "benchmark_report_present": bool(benchmark.get("present", False)),
            "benchmark_mode": benchmark.get("mode", ""),
            "benchmark_runs_successful": int(benchmark.get("runs_successful", 0) or 0),
            "benchmark_runs_attempted": int(benchmark.get("runs_attempted", 0) or 0),
            "benchmark_failed_dataset_count": int(benchmark.get("failed_dataset_count", 0) or 0),
            "benchmark_dataset_count": int(benchmark.get("dataset_count", 0) or 0),
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
            "benchmark_mean_student_level_sd": float(benchmark.get("mean_student_level_sd", 0.0) or 0.0),
            "benchmark_mean_student_rank_sd": float(benchmark.get("mean_student_rank_sd", 0.0) or 0.0),
            "benchmark_mean_student_score_sd": float(benchmark.get("mean_student_score_sd", 0.0) or 0.0),
            "pairwise_eval_present": bool(pairwise_eval.get("present", False)),
            "pairwise_eval_mode": str(pairwise_eval.get("mode", "") or ""),
            "pairwise_eval_judgments": str(pairwise_eval.get("judgments", "") or ""),
            "pairwise_eval_escalated_path": bool(pairwise_eval.get("escalated_path", False)),
            "pairwise_eval_pair_count": int(pairwise_eval.get("pair_count", 0) or 0),
            "pairwise_eval_evaluated_count": int(pairwise_eval.get("evaluated_count", 0) or 0),
            "pairwise_eval_accuracy": float(pairwise_eval.get("accuracy", 0.0) or 0.0),
            "pairwise_eval_coverage": float(pairwise_eval.get("coverage", 0.0) or 0.0),
            "pairwise_eval_critical_accuracy": float(pairwise_eval.get("critical_accuracy", 0.0) or 0.0),
            "pairwise_eval_polish_bias_risk_count": int(pairwise_eval.get("polish_bias_risk_count", 0) or 0),
            "pairwise_eval_failures": list(pairwise_eval.get("failures", [])),
        }
    )
    return metrics


def evaluate_profiles(
    base_metrics: dict,
    gate_cfg: dict,
    *,
    rows: list[dict],
    level_bands: list[dict],
    benchmark_report_path: Path,
    pairwise_eval_report_path: Path,
) -> tuple[list[str], str, dict[str, dict]]:
    order, target_profile, profiles = resolve_gate_profiles(gate_cfg, fallback_profile="dev")
    results = {}
    for name in order:
        thresholds = profiles[name]
        metrics = build_profile_metrics(
            base_metrics,
            thresholds=thresholds,
            rows=rows,
            level_bands=level_bands,
            benchmark_report_path=benchmark_report_path,
            pairwise_eval_report_path=pairwise_eval_report_path,
        )
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
        "# Publish Gate",
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
        "irr_rank_kendalls_w",
        "irr_mean_rubric_sd",
        "model_coverage",
        "boundary_count",
        "anchor_hit_rate",
        "anchor_level_mae",
        "calibration_scope_samples",
        "calibration_scope_observations",
        "calibration_scope_match",
        "calibration_synthetic",
        "calibration_generated_age_hours",
        "benchmark_mode",
        "benchmark_failed_dataset_count",
        "benchmark_dataset_count",
        "benchmark_runs_successful",
        "benchmark_exact_level_hit_rate",
        "benchmark_within_one_level_hit_rate",
        "benchmark_score_band_mae",
        "benchmark_mean_rank_displacement",
        "benchmark_kendall_tau",
        "benchmark_pairwise_order_agreement",
        "benchmark_model_usage_ratio",
        "benchmark_cost_usd",
        "benchmark_latency_seconds",
        "benchmark_mean_student_level_variance",
        "benchmark_mean_student_rank_variance",
        "benchmark_mean_student_score_variance",
        "benchmark_mean_student_level_sd",
        "benchmark_mean_student_rank_sd",
        "benchmark_mean_student_score_sd",
        "pairwise_eval_present",
        "pairwise_eval_mode",
        "pairwise_eval_judgments",
        "pairwise_eval_escalated_path",
        "pairwise_eval_pair_count",
        "pairwise_eval_evaluated_count",
        "pairwise_eval_accuracy",
        "pairwise_eval_coverage",
        "pairwise_eval_critical_accuracy",
        "pairwise_eval_polish_bias_risk_count",
        "committee_candidate_count",
        "evidence_neighborhood_present",
        "evidence_neighborhood_enabled",
        "evidence_neighborhood_count",
        "evidence_needs_group_calibration_count",
        "evidence_group_packets_present",
        "evidence_group_packets_enabled",
        "evidence_group_packets_selected_count",
        "evidence_group_packets_skipped_count",
        "evidence_group_packets_read_type_counts",
        "evidence_group_packets_max_selected_packet_size",
        "evidence_group_packets_max_packet_students",
        "evidence_group_packets_max_packets",
        "evidence_group_packets_ready",
        "evidence_group_packets_bounded",
        "evidence_needs_group_calibration_has_packets",
        "reproducibility_report_present",
        "reproducibility_runs_compared",
        "reproducibility_manifest_identical",
        "reproducibility_final_outputs_exact_match",
        "reproducibility_within_tolerance",
        "reproducibility_max_intermediate_metric_delta",
    ):
        lines.append(f"- **{key}**: {metrics.get(key)}")
    failures = payload.get("failures", [])
    if failures:
        lines.extend(["", "## Failures"])
        lines.extend(f"- {item}" for item in failures)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    parser.add_argument("--pairwise-eval-report", default="outputs/pairwise_adjudicator_eval.json", help="Optional hard-pair pairwise adjudicator eval JSON")
    parser.add_argument("--reproducibility-report", default="outputs/reproducibility_report.json", help="Optional reproducibility report JSON")
    parser.add_argument("--committee-candidates", default="outputs/committee_edge_candidates.json", help="Committee-edge candidates JSON")
    parser.add_argument("--evidence-neighborhood-report", default="outputs/evidence_neighborhood_report.json", help="Evidence neighborhood report JSON")
    parser.add_argument("--evidence-group-packets", default="outputs/evidence_group_calibration_packets.json", help="Evidence group-calibration packets JSON")
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
    bands = get_level_bands(marking_cfg)
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
    scope_coverage = cal.get("coverage_scope", {}) if isinstance(cal.get("coverage_scope", {}), dict) else {}
    reproducibility = reproducibility_metrics(Path(args.reproducibility_report))
    evidence_packets = evidence_packet_metrics(
        Path(args.committee_candidates),
        Path(args.evidence_neighborhood_report),
        Path(args.evidence_group_packets),
    )

    anchors_total, anchor_hit_rate, anchor_level_mae = anchor_metrics(rows, metadata)
    base_metrics = {
        "rows": len(rows),
        "irr_rank_kendalls_w": float(irr.get("rank_kendall_w", 0.0) or 0.0),
        "irr_mean_rubric_sd": float(irr.get("mean_rubric_sd", 0.0) or 0.0),
        "model_coverage": model_coverage(Path(args.pass1)),
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
        "calibration_scope_samples": int(scope_coverage.get("samples", 0) or 0),
        "calibration_scope_observations": int(scope_coverage.get("observations", 0) or 0),
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
        "reproducibility_report_present": bool(reproducibility.get("present", False)),
        "reproducibility_runs_compared": int(reproducibility.get("runs_compared", 0) or 0),
        "reproducibility_manifest_identical": bool(reproducibility.get("manifest_identical", False)),
        "reproducibility_final_outputs_exact_match": bool(reproducibility.get("final_outputs_exact_match", False)),
        "reproducibility_within_tolerance": bool(reproducibility.get("within_tolerance", False)),
        "reproducibility_max_intermediate_metric_delta": float(reproducibility.get("max_intermediate_metric_delta", 0.0) or 0.0),
        "reproducibility_mismatched_final_artifact_count": int(reproducibility.get("mismatched_final_artifact_count", 0) or 0),
        "reproducibility_mismatched_intermediate_artifact_count": int(
            reproducibility.get("mismatched_intermediate_artifact_count", 0) or 0
        ),
        **evidence_packets,
    }
    profile_order, target_profile, profile_results = evaluate_profiles(
        base_metrics,
        gate_cfg,
        rows=rows,
        level_bands=bands,
        benchmark_report_path=Path(args.benchmark_report),
        pairwise_eval_report_path=Path(args.pairwise_eval_report),
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
