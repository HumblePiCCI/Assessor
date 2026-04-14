#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.select_anchor_candidates import select_anchor_candidates, teacher_anchor_packet
except ImportError:  # pragma: no cover
    from select_anchor_candidates import select_anchor_candidates, teacher_anchor_packet  # pragma: no cover


DEFAULTS = {
    "shadow_mode": True,
    "min_model_coverage": 0.9,
    "anchor_candidate_count": 5,
    "auto_publish_ready": {
        "mean_assessor_sd": 3.0,
        "p95_assessor_sd": 6.0,
        "swap_rate": 0.15,
        "rubric_parse_confidence": 0.85,
    },
    "provisional_review_recommended": {
        "mean_assessor_sd": 5.0,
        "p95_assessor_sd": 10.0,
        "swap_rate": 0.35,
        "rubric_parse_confidence": 0.70,
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data


def load_submission_metadata(path: Path) -> dict[str, dict]:
    data = load_json(path)
    if isinstance(data, list):
        return {
            str(item.get("student_id", "") or ""): item
            for item in data
            if isinstance(item, dict) and item.get("student_id")
        }
    return {}


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def load_live_config(path: Path) -> dict:
    config = load_json(path)
    live = config.get("live_cohort", {}) if isinstance(config, dict) else {}
    merged = json.loads(json.dumps(DEFAULTS))
    if isinstance(live, dict):
        for key, value in live.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key].update(value)
            else:
                merged[key] = value
    return merged


def assessor_spread(rows: list[dict]) -> tuple[float, float]:
    rubric_sds = [num(row.get("rubric_sd_points"), 0.0) for row in rows if row.get("student_id")]
    rubric_sds = [value for value in rubric_sds if value >= 0.0]
    if not rubric_sds:
        return 0.0, 0.0
    ordered = sorted(rubric_sds)
    p95 = ordered[max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95))))]
    return round(sum(ordered) / len(ordered), 6), round(p95, 6)


def model_coverage(pass1_dir: Path) -> float:
    total = 0
    model_rows = 0
    for path in sorted(pass1_dir.glob("assessor_*.json")):
        payload = load_json(path)
        for row in payload.get("scores", []) if isinstance(payload, dict) else []:
            total += 1
            notes = str(row.get("notes", "") or "")
            if "Fallback deterministic score" not in notes:
                model_rows += 1
    return round((model_rows / total) if total else 0.0, 6)


def rubric_parse_confidence(validation_report: dict, verification: dict) -> float:
    confidence = validation_report.get("confidence", {}) if isinstance(validation_report, dict) else {}
    if isinstance(confidence, dict):
        score = confidence.get("score")
        if isinstance(score, (int, float)):
            return round(float(score), 6)
        status = str(confidence.get("status", "") or "").strip().lower()
    else:
        status = ""
    if not status:
        status = str(verification.get("status", "") or "").strip().lower()
    mapping = {
        "high": 0.9,
        "ok": 0.9,
        "confirmed": 0.95,
        "medium": 0.75,
        "warning": 0.72,
        "low": 0.55,
        "error": 0.4,
        "failed": 0.3,
    }
    return mapping.get(status, 0.6)


def gate_pass(gate_payload: dict) -> bool:
    return bool((gate_payload or {}).get("ok", False))


def calibration_type(calibration_manifest: dict) -> str:
    if not isinstance(calibration_manifest, dict) or not calibration_manifest:
        return "missing"
    if calibration_manifest.get("synthetic", False):
        return "synthetic"
    return str(calibration_manifest.get("profile_type", "") or "calibrated")


def evaluate_state(metrics: dict, thresholds: dict) -> tuple[str, list[str]]:
    reasons = []
    auto = thresholds["auto_publish_ready"]
    provisional = thresholds["provisional_review_recommended"]
    hard_anchor = False

    if metrics["model_coverage"] < float(thresholds.get("min_model_coverage", 0.9) or 0.9):
        hard_anchor = True
        reasons.append("model_coverage_below_threshold")
    if metrics["rubric_parse_confidence"] < float(provisional.get("rubric_parse_confidence", 0.7) or 0.7):
        hard_anchor = True
        reasons.append("rubric_parse_confidence_low")
    if metrics["calibration_type"] == "synthetic" and not metrics["scope_grounding_accepted"]:
        hard_anchor = True
        reasons.append("synthetic_only_scope_support")
    if metrics["rubric_family_unknown"] and metrics["calibration_type"] == "synthetic" and not metrics["scope_grounding_accepted"]:
        hard_anchor = True
        reasons.append("rubric_family_unknown_with_synthetic_only_support")

    if hard_anchor:
        return "anchor_calibration_required", reasons

    if (
        metrics["mean_assessor_sd"] <= float(auto.get("mean_assessor_sd", 3.0) or 3.0)
        and metrics["p95_assessor_sd"] <= float(auto.get("p95_assessor_sd", 6.0) or 6.0)
        and metrics["swap_rate"] <= float(auto.get("swap_rate", 0.15) or 0.15)
        and metrics["rubric_parse_confidence"] >= float(auto.get("rubric_parse_confidence", 0.85) or 0.85)
        and metrics["scope_grounding_accepted"]
        and metrics["calibration_type"] != "synthetic"
    ):
        return "auto_publish_ready", ["all_runtime_signals_within_auto_thresholds"]

    if (
        metrics["mean_assessor_sd"] > float(provisional.get("mean_assessor_sd", 5.0) or 5.0)
        or metrics["p95_assessor_sd"] > float(provisional.get("p95_assessor_sd", 10.0) or 10.0)
        or metrics["swap_rate"] > float(provisional.get("swap_rate", 0.35) or 0.35)
    ):
        reasons.append("instability_above_provisional_ceiling")
        return "anchor_calibration_required", reasons

    reasons.append("stability_is_usable_but_not_release_trustworthy")
    return "provisional_review_recommended", reasons


def effective_state(runtime_state: str, *, publish_ok: bool, sota_ok: bool) -> tuple[str, list[str]]:
    reasons = []
    state = runtime_state
    if not publish_ok or not sota_ok:
        reasons.append("publish_or_sota_gate_not_green")
        if runtime_state == "auto_publish_ready":
            state = "provisional_review_recommended"
    return state, reasons


def build_metrics(*, rows: list[dict], consistency_report: dict, publish_gate: dict, sota_gate: dict, scope_grounding: dict, rubric_validation: dict, rubric_verification: dict, calibration_manifest: dict, pass1_dir: Path) -> dict:
    mean_sd, p95_sd = assessor_spread(rows)
    summary = consistency_report.get("summary", {}) if isinstance(consistency_report, dict) else {}
    resolved_scope = scope_grounding.get("resolved_scope", {}) if isinstance(scope_grounding, dict) else {}
    rubric_family = str((resolved_scope or {}).get("rubric_family", "") or "").strip().lower()
    return {
        "mean_assessor_sd": mean_sd,
        "p95_assessor_sd": p95_sd,
        "swap_rate": num(summary.get("swap_rate"), 0.0),
        "boundary_disagreement_concentration": num(summary.get("boundary_disagreement_concentration"), 0.0),
        "pairwise_conflict_density": num(summary.get("pairwise_conflict_density"), 0.0),
        "model_coverage": model_coverage(pass1_dir),
        "rubric_parse_confidence": rubric_parse_confidence(rubric_validation, rubric_verification),
        "scope_grounding_accepted": bool((scope_grounding or {}).get("accepted", False)),
        "scope_familiarity_label": str((scope_grounding or {}).get("familiarity_label", "") or ""),
        "calibration_type": calibration_type(calibration_manifest),
        "publish_ok": gate_pass(publish_gate),
        "sota_ok": gate_pass(sota_gate),
        "rubric_family_unknown": rubric_family in {"", "rubric_unknown"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate live cohort confidence and emit runtime control artifacts.")
    parser.add_argument("--rows", default="outputs/final_order.csv")
    parser.add_argument("--fallback", default="outputs/consensus_scores.csv")
    parser.add_argument("--marking-config", default="config/marking_config.json")
    parser.add_argument("--consistency-report", default="outputs/consistency_report.json")
    parser.add_argument("--publish-gate", default="outputs/publish_gate.json")
    parser.add_argument("--sota-gate", default="outputs/sota_gate.json")
    parser.add_argument("--scope-grounding", default="outputs/scope_grounding.json")
    parser.add_argument("--rubric-validation", default="outputs/rubric_validation_report.json")
    parser.add_argument("--rubric-verification", default="outputs/rubric_verification.json")
    parser.add_argument("--calibration-manifest", default="outputs/calibration_manifest.json")
    parser.add_argument("--pass1", default="assessments/pass1_individual")
    parser.add_argument("--submission-metadata", default="processing/submission_metadata.json")
    parser.add_argument("--output", default="outputs/cohort_confidence.json")
    parser.add_argument("--anchor-output", default="outputs/anchor_candidates.json")
    parser.add_argument("--anchor-packet-output", default="outputs/teacher_anchor_packet.json")
    args = parser.parse_args()

    config = load_live_config(Path(args.marking_config))
    rows = load_rows(Path(args.rows)) or load_rows(Path(args.fallback))
    consistency_report = load_json(Path(args.consistency_report))
    publish_gate = load_json(Path(args.publish_gate))
    sota_gate = load_json(Path(args.sota_gate))
    scope_grounding = load_json(Path(args.scope_grounding))
    rubric_validation = load_json(Path(args.rubric_validation))
    rubric_verification = load_json(Path(args.rubric_verification))
    calibration_manifest = load_json(Path(args.calibration_manifest))
    metadata = load_submission_metadata(Path(args.submission_metadata))
    metrics = build_metrics(
        rows=rows,
        consistency_report=consistency_report if isinstance(consistency_report, dict) else {},
        publish_gate=publish_gate if isinstance(publish_gate, dict) else {},
        sota_gate=sota_gate if isinstance(sota_gate, dict) else {},
        scope_grounding=scope_grounding if isinstance(scope_grounding, dict) else {},
        rubric_validation=rubric_validation if isinstance(rubric_validation, dict) else {},
        rubric_verification=rubric_verification if isinstance(rubric_verification, dict) else {},
        calibration_manifest=calibration_manifest if isinstance(calibration_manifest, dict) else {},
        pass1_dir=Path(args.pass1),
    )
    runtime_state, runtime_reasons = evaluate_state(metrics, config)
    effective_runtime_state, gate_reasons = effective_state(
        runtime_state,
        publish_ok=metrics["publish_ok"],
        sota_ok=metrics["sota_ok"],
    )
    recommended_action = {
        "auto_publish_ready": "ready_for_publish",
        "provisional_review_recommended": "teacher_review_recommended",
        "anchor_calibration_required": "collect_teacher_anchors",
    }[effective_runtime_state]
    payload = {
        "generated_at": now_iso(),
        "shadow_mode": bool(config.get("shadow_mode", True)),
        "blocking_enabled": not bool(config.get("shadow_mode", True)),
        "runtime_state": runtime_state,
        "effective_runtime_state": effective_runtime_state,
        "recommended_action": recommended_action,
        "accepted": effective_runtime_state == "auto_publish_ready",
        "fallback_used": False,
        "fallback_reason": "",
        "reasons": list(dict.fromkeys(runtime_reasons + gate_reasons)),
        "decision_inputs": metrics,
        "thresholds": config,
        "gate_preconditions": {
            "publish_ok": metrics["publish_ok"],
            "sota_ok": metrics["sota_ok"],
        },
        "would_pause_for_anchors": bool(config.get("shadow_mode", True) and effective_runtime_state == "anchor_calibration_required"),
    }

    if recommended_action == "collect_teacher_anchors" and rows:
        anchor_payload = select_anchor_candidates(
            rows,
            config=load_json(Path(args.marking_config)),
            consistency_report=consistency_report if isinstance(consistency_report, dict) else {},
            metadata=metadata,
            candidate_count=max(1, int(config.get("anchor_candidate_count", 5) or 5)),
        )
        Path(args.anchor_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.anchor_output).write_text(json.dumps(anchor_payload, indent=2), encoding="utf-8")
        Path(args.anchor_packet_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.anchor_packet_output).write_text(json.dumps(teacher_anchor_packet(anchor_payload), indent=2), encoding="utf-8")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote cohort confidence to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
