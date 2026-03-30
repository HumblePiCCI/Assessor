#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.calibration_contract import BOUNDARY_LEVEL_EDGES, normalize_scope_input, parse_iso8601
except ImportError:  # pragma: no cover - Support running as a script
    from calibration_contract import BOUNDARY_LEVEL_EDGES, normalize_scope_input, parse_iso8601  # pragma: no cover


DEFAULT_MIN_FINALIZED_REVIEWS = 2
DEFAULT_MIN_STUDENT_DECISIONS = 3
DEFAULT_FRESHNESS_DAYS = 90.0
DEFAULT_MAX_ADJUSTMENT = 0.08
DEFAULT_BOUNDARY_MARGIN = 1.5


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def empty_local_teacher_prior(scope_id: str = "", run_scope: dict | None = None) -> dict:
    normalized_scope = normalize_scope_input(run_scope or {})
    return {
        "scope_id": scope_id,
        "generated_at": now_iso(),
        "active": False,
        "run_scope": normalized_scope,
        "support": {
            "finalized_review_count": 0,
            "student_decision_count": 0,
            "pairwise_decision_count": 0,
            "days_since_latest": None,
            "support_scalar": 0.0,
            "freshness_scalar": 0.0,
        },
        "activation": {
            "min_finalized_reviews": DEFAULT_MIN_FINALIZED_REVIEWS,
            "min_student_decisions": DEFAULT_MIN_STUDENT_DECISIONS,
            "freshness_days": DEFAULT_FRESHNESS_DAYS,
            "reason": "insufficient_finalized_reviews",
        },
        "weights": {
            "boundary_level_bias": 0.0,
            "seed_order_bias": 0.0,
            "max_adjustment": DEFAULT_MAX_ADJUSTMENT,
            "boundary_margin": DEFAULT_BOUNDARY_MARGIN,
        },
        "signals": {
            "boundary_override_rate": 0.0,
            "low_confidence_reversal_rate": 0.0,
            "high_disagreement_pair_count": 0,
            "pairwise_reversal_count": 0,
            "evidence_quality_counts": {},
        },
    }


def latest_run_scope(records: list[dict]) -> dict:
    latest = {}
    latest_saved_at = ""
    for record in records:
        saved_at = str(record.get("saved_at", "") or "")
        if saved_at >= latest_saved_at:
            latest_saved_at = saved_at
            version = record.get("version_context", {}) if isinstance(record.get("version_context"), dict) else {}
            pipeline = version.get("pipeline_manifest", {}) if isinstance(version.get("pipeline_manifest"), dict) else {}
            latest = normalize_scope_input(pipeline.get("run_scope", {}))
    return latest


def _support_scalars(records: list[dict], *, min_finalized_reviews: int, min_student_decisions: int, freshness_days: float) -> tuple[float, float, int | None]:
    if not records:
        return 0.0, 0.0, None
    student_decisions = sum(len(record.get("students", [])) for record in records)
    latest_saved_at = max(str(record.get("saved_at", "") or "") for record in records)
    latest_dt = parse_iso8601(latest_saved_at)
    now = datetime.now(timezone.utc)
    if latest_dt is None:
        days_since_latest = None
        freshness_scalar = 0.0
    else:
        days_since_latest = max(0.0, (now - latest_dt).total_seconds() / 86400.0)
        freshness_scalar = max(0.0, 1.0 - (days_since_latest / max(1.0, float(freshness_days))))
    review_scalar = min(1.0, len(records) / max(1, int(min_finalized_reviews)))
    decision_scalar = min(1.0, student_decisions / max(1, int(min_student_decisions)))
    return round(min(review_scalar, decision_scalar), 6), round(freshness_scalar, 6), int(days_since_latest) if days_since_latest is not None else None


def build_local_teacher_prior(
    scope_id: str,
    records: list[dict],
    *,
    min_finalized_reviews: int = DEFAULT_MIN_FINALIZED_REVIEWS,
    min_student_decisions: int = DEFAULT_MIN_STUDENT_DECISIONS,
    freshness_days: float = DEFAULT_FRESHNESS_DAYS,
) -> dict:
    finalized = [
        dict(record)
        for record in records
        if isinstance(record, dict) and str(record.get("review_state", "final") or "final").strip().lower() == "final"
    ]
    run_scope = latest_run_scope(finalized)
    prior = empty_local_teacher_prior(scope_id=scope_id, run_scope=run_scope)
    prior["activation"]["min_finalized_reviews"] = int(min_finalized_reviews)
    prior["activation"]["min_student_decisions"] = int(min_student_decisions)
    prior["activation"]["freshness_days"] = float(freshness_days)
    if not finalized:
        prior["activation"]["reason"] = "no_finalized_reviews"
        return prior

    student_decisions = sum(len(record.get("students", [])) for record in finalized)
    pairwise_decisions = sum(len(record.get("pairwise", [])) for record in finalized)
    evidence_quality_counts = {}
    boundary_deltas = []
    boundary_review_count = 0
    boundary_override_count = 0
    low_conf_pairs = 0
    low_conf_reversals = 0
    high_disagreement_pairs = 0
    pairwise_reversals = 0
    for record in finalized:
        for student in record.get("students", []):
            quality = str(student.get("evidence_quality", "") or "")
            if quality:
                evidence_quality_counts[quality] = evidence_quality_counts.get(quality, 0) + 1
            flags = set(student.get("uncertainty_flags", []) or [])
            if "boundary_case" in flags:
                boundary_review_count += 1
                if student.get("level_delta") is not None:
                    boundary_deltas.append(float(student.get("level_delta", 0.0) or 0.0))
                if student.get("level_override") and student.get("level_override") != student.get("machine_level"):
                    boundary_override_count += 1
        for pair in record.get("pairwise", []):
            flags = set(pair.get("uncertainty_flags", []) or [])
            if "low_confidence_rerank_move" in flags:
                low_conf_pairs += 1
                if pair.get("reversed_machine_order"):
                    low_conf_reversals += 1
            if "high_disagreement" in flags:
                high_disagreement_pairs += 1
            if pair.get("reversed_machine_order"):
                pairwise_reversals += 1

    support_scalar, freshness_scalar, days_since_latest = _support_scalars(
        finalized,
        min_finalized_reviews=min_finalized_reviews,
        min_student_decisions=min_student_decisions,
        freshness_days=freshness_days,
    )
    boundary_override_rate = round(boundary_override_count / boundary_review_count, 6) if boundary_review_count else 0.0
    low_confidence_reversal_rate = round(low_conf_reversals / low_conf_pairs, 6) if low_conf_pairs else 0.0
    boundary_level_bias = 0.0
    if boundary_deltas:
        boundary_level_bias = round(
            max(-DEFAULT_MAX_ADJUSTMENT, min(DEFAULT_MAX_ADJUSTMENT, (sum(boundary_deltas) / len(boundary_deltas)) * 0.18 * support_scalar * freshness_scalar)),
            6,
        )
    seed_order_bias = 0.0
    if low_confidence_reversal_rate >= 0.5:
        seed_order_bias = round(min(0.06, 0.06 * support_scalar * freshness_scalar), 6)

    active = (
        len(finalized) >= int(min_finalized_reviews)
        and student_decisions >= int(min_student_decisions)
        and freshness_scalar > 0.0
        and (abs(boundary_level_bias) > 0.0 or seed_order_bias > 0.0)
    )
    if active:
        reason = "active"
    elif len(finalized) < int(min_finalized_reviews):
        reason = "insufficient_finalized_reviews"
    elif student_decisions < int(min_student_decisions):
        reason = "insufficient_student_decisions"
    elif freshness_scalar <= 0.0:
        reason = "stale_feedback"
    else:
        reason = "no_actionable_signal"

    prior["generated_at"] = now_iso()
    prior["active"] = bool(active)
    prior["support"] = {
        "finalized_review_count": len(finalized),
        "student_decision_count": student_decisions,
        "pairwise_decision_count": pairwise_decisions,
        "days_since_latest": days_since_latest,
        "support_scalar": support_scalar,
        "freshness_scalar": freshness_scalar,
    }
    prior["activation"]["reason"] = reason
    prior["weights"] = {
        "boundary_level_bias": boundary_level_bias,
        "seed_order_bias": seed_order_bias,
        "max_adjustment": DEFAULT_MAX_ADJUSTMENT,
        "boundary_margin": DEFAULT_BOUNDARY_MARGIN,
    }
    prior["signals"] = {
        "boundary_override_rate": boundary_override_rate,
        "low_confidence_reversal_rate": low_confidence_reversal_rate,
        "high_disagreement_pair_count": high_disagreement_pairs,
        "pairwise_reversal_count": pairwise_reversals,
        "evidence_quality_counts": dict(sorted(evidence_quality_counts.items())),
    }
    return prior


def scope_matches(prior_scope: dict | None, current_scope: dict | None) -> bool:
    prior_payload = normalize_scope_input(prior_scope or {})
    current_payload = normalize_scope_input(current_scope or {})
    if not prior_payload or not current_payload:
        return True
    compared = False
    for key in ("grade_band", "genre", "rubric_family", "model_family"):
        left = str(prior_payload.get(key, "") or "")
        right = str(current_payload.get(key, "") or "")
        if not left or not right:
            continue
        compared = True
        if left != right:
            return False
    if not compared:
        left = str(prior_payload.get("scope_id", "") or prior_payload.get("key", "") or "")
        right = str(current_payload.get("scope_id", "") or current_payload.get("key", "") or "")
        if left and right:
            return left == right
    return True


def boundary_signal(score: float, boundaries: list[float], *, margin: float) -> float:
    if not boundaries:
        boundaries = list(BOUNDARY_LEVEL_EDGES)
    ordered = sorted(float(item) for item in boundaries)
    lower = 0.0
    upper = 100.0
    for edge in ordered:
        if score >= edge:
            lower = edge
            continue
        upper = edge
        break
    upper_gap = abs(upper - score) if upper < 100.0 else float("inf")
    lower_gap = abs(score - lower) if lower > 0.0 else float("inf")
    upper_strength = 0.0 if upper_gap == float("inf") else max(0.0, 1.0 - (upper_gap / max(0.1, margin)))
    lower_strength = 0.0 if lower_gap == float("inf") else max(0.0, 1.0 - (lower_gap / max(0.1, margin)))
    return round(upper_strength - lower_strength, 6)


def compute_teacher_preference_adjustments(
    rows: list[dict],
    per_student: dict[str, dict],
    prior_payload: dict | None,
    *,
    current_scope: dict | None = None,
    boundaries: list[float] | None = None,
) -> tuple[dict[str, float], dict]:
    prior = prior_payload if isinstance(prior_payload, dict) else {}
    adjustments = {str(row.get("student_id", "")): 0.0 for row in rows if row.get("student_id")}
    if not rows:
        return adjustments, {"active": False, "scope_match": True, "students": {}, "reason": "no_rows"}
    if not prior.get("active", False):
        return adjustments, {"active": False, "scope_match": True, "students": {}, "reason": str(prior.get("activation", {}).get("reason", "inactive"))}
    if not scope_matches(prior.get("run_scope", {}), current_scope or {}):
        return adjustments, {"active": False, "scope_match": False, "students": {}, "reason": "scope_mismatch"}

    count = len(rows)
    max_adjustment = float(prior.get("weights", {}).get("max_adjustment", DEFAULT_MAX_ADJUSTMENT) or DEFAULT_MAX_ADJUSTMENT)
    boundary_margin = float(prior.get("weights", {}).get("boundary_margin", DEFAULT_BOUNDARY_MARGIN) or DEFAULT_BOUNDARY_MARGIN)
    boundary_bias = float(prior.get("weights", {}).get("boundary_level_bias", 0.0) or 0.0)
    seed_order_bias = float(prior.get("weights", {}).get("seed_order_bias", 0.0) or 0.0)
    support_scalar = float(prior.get("support", {}).get("support_scalar", 0.0) or 0.0)
    freshness_scalar = float(prior.get("support", {}).get("freshness_scalar", 0.0) or 0.0)
    diagnostics = {}

    for row in rows:
        sid = str(row.get("student_id", "") or "")
        if not sid:
            continue
        student_metrics = per_student.get(sid, {})
        support = float(student_metrics.get("support_weight", 0.0) or 0.0)
        opposition = float(student_metrics.get("opposition_weight", 0.0) or 0.0)
        incident = float(student_metrics.get("incident_weight", 0.0) or 0.0)
        disagreement_gate = 0.0
        if support > 0.0 and opposition > 0.0:
            disagreement_gate = min(support, opposition) / max(support, opposition)
        low_confidence_gate = 0.0
        if 0.0 < incident < 1.0:
            low_confidence_gate = max(0.0, 1.0 - incident)
        score = num(row.get("_rubric_after_penalty_percent"), num(row.get("rubric_after_penalty_percent"), num(row.get("rubric_mean_percent"), 0.0)))
        signed_boundary = boundary_signal(score, boundaries or list(BOUNDARY_LEVEL_EDGES), margin=boundary_margin)
        boundary_gate = abs(signed_boundary)
        uncertainty_gate = min(1.0, max(boundary_gate, disagreement_gate, low_confidence_gate))
        seed_center = 0.0 if count <= 1 else 0.5 - ((int(num(row.get("seed_rank"), 1)) - 1) / max(1, count - 1))
        raw_adjustment = 0.0
        reasons = []
        if uncertainty_gate > 0.0 and abs(boundary_bias) > 0.0 and boundary_gate > 0.0:
            raw_adjustment += signed_boundary * boundary_bias
            reasons.append("boundary_signal")
        if uncertainty_gate > 0.0 and seed_order_bias > 0.0 and low_confidence_gate > 0.0:
            raw_adjustment += seed_center * seed_order_bias * low_confidence_gate
            reasons.append("low_confidence_seed_pull")
        raw_adjustment *= min(1.0, max(0.0, support_scalar * freshness_scalar))
        adjustment = round(max(-max_adjustment, min(max_adjustment, raw_adjustment)), 6)
        adjustments[sid] = adjustment
        diagnostics[sid] = {
            "adjustment": adjustment,
            "uncertainty_gate": round(uncertainty_gate, 6),
            "boundary_signal": signed_boundary,
            "boundary_gate": round(boundary_gate, 6),
            "disagreement_gate": round(disagreement_gate, 6),
            "low_confidence_gate": round(low_confidence_gate, 6),
            "reasons": reasons,
        }
    return adjustments, {"active": True, "scope_match": True, "students": diagnostics, "reason": "active"}


def finalized_records_from_history(history_dir: Path) -> list[dict]:
    records = []
    if not history_dir.exists():
        return records
    for path in sorted(history_dir.glob("*.json")):
        payload = load_json(path)
        if payload:
            records.append(payload)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a scoped local teacher prior from finalized review history.")
    parser.add_argument("--history-dir", required=True, help="Finalized review history directory")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--scope-id", default="workspace", help="Review scope id")
    parser.add_argument("--min-finalized-reviews", type=int, default=DEFAULT_MIN_FINALIZED_REVIEWS)
    parser.add_argument("--min-student-decisions", type=int, default=DEFAULT_MIN_STUDENT_DECISIONS)
    parser.add_argument("--freshness-days", type=float, default=DEFAULT_FRESHNESS_DAYS)
    args = parser.parse_args()

    records = finalized_records_from_history(Path(args.history_dir))
    payload = build_local_teacher_prior(
        args.scope_id,
        records,
        min_finalized_reviews=args.min_finalized_reviews,
        min_student_decisions=args.min_student_decisions,
        freshness_days=args.freshness_days,
    )
    write_json(Path(args.output), payload)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
