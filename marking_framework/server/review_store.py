#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from scripts.aggregate_review_learning import (
    AGGREGATE_SCHEMA_VERSION,
    canonical_hash as aggregate_canonical_hash,
    collection_eligibility,
    default_aggregate_learning_policy,
    eligible_record_path,
    expires_at as aggregate_expires_at,
    hash_identifier,
    list_eligible_records,
    list_tombstones,
    normalize_aggregate_learning_policy,
    normalize_reason_tags,
    now_iso as aggregate_now_iso,
    prune_expired_records,
    reason_count_summary,
    redact_text,
    tombstone_path,
    write_json as write_aggregate_json,
)
from scripts.engagement_gate import evaluate_engagement
from scripts.local_teacher_prior import build_local_teacher_prior, write_json as write_prior_json


LEVEL_MAP = {"1": 1.0, "2": 2.0, "3": 3.0, "4": 4.0, "4+": 5.0}
EVIDENCE_QUALITY = {"strong", "thin", "misaligned", "unclear"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def file_sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def review_scope_id(current_project: dict | None) -> str:
    scope_key = str((current_project or {}).get("scope_key", "") or "").strip()
    if scope_key:
        return scope_key
    project_id = str((current_project or {}).get("id", "") or "").strip()
    return project_id or "workspace"


def reviews_root(base_dir: Path) -> Path:
    path = base_dir / "data" / "reviews"
    path.mkdir(parents=True, exist_ok=True)
    return path


def scope_dir(base_dir: Path, scope_id: str) -> Path:
    path = reviews_root(base_dir) / scope_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def latest_review_path(base_dir: Path, scope_id: str) -> Path:
    return scope_dir(base_dir, scope_id) / "latest_review.json"


def draft_review_path(base_dir: Path, scope_id: str) -> Path:
    return scope_dir(base_dir, scope_id) / "draft_review.json"


def latest_delta_path(base_dir: Path, scope_id: str) -> Path:
    return scope_dir(base_dir, scope_id) / "latest_review_delta.json"


def history_dir(base_dir: Path, scope_id: str) -> Path:
    path = scope_dir(base_dir, scope_id) / "history"
    path.mkdir(parents=True, exist_ok=True)
    return path


def exports_dir(base_dir: Path, scope_id: str) -> Path:
    path = scope_dir(base_dir, scope_id) / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def local_profile_path(base_dir: Path, scope_id: str) -> Path:
    return scope_dir(base_dir, scope_id) / "local_learning_profile.json"


def local_teacher_prior_path(base_dir: Path, scope_id: str) -> Path:
    return scope_dir(base_dir, scope_id) / "local_teacher_prior.json"


def aggregate_learning_summary_path(base_dir: Path, scope_id: str) -> Path:
    return scope_dir(base_dir, scope_id) / "aggregate_learning_summary.json"


def aggregate_learning_policy(current_project: dict | None) -> dict:
    raw = {}
    if isinstance(current_project, dict):
        raw = current_project.get("aggregate_learning", {}) if isinstance(current_project.get("aggregate_learning"), dict) else {}
    return normalize_aggregate_learning_policy(raw or default_aggregate_learning_policy())


def load_dashboard(root: Path) -> dict:
    return load_json(root / "outputs" / "dashboard_data.json")


def student_lookup(dashboard: dict) -> dict[str, dict]:
    students = dashboard.get("students", []) if isinstance(dashboard, dict) else []
    return {str(item.get("student_id")): item for item in students if isinstance(item, dict) and item.get("student_id")}


def review_context(root: Path, dashboard: dict) -> dict:
    pipeline_path = root / "pipeline_manifest.json"
    if not pipeline_path.exists():
        pipeline_path = root / "outputs" / "pipeline_manifest.json"
    calibration_path = root / "outputs" / "calibration_manifest.json"
    pipeline_manifest = load_json(pipeline_path)
    calibration_manifest = load_json(calibration_path)
    final_artifact_paths = {
        "dashboard_data": root / "outputs" / "dashboard_data.json",
        "final_order": root / "outputs" / "final_order.csv",
        "grade_curve": root / "outputs" / "grade_curve.csv",
        "consistency_report": root / "outputs" / "consistency_report.json",
        "pairwise_matrix": root / "outputs" / "pairwise_matrix.json",
    }
    artifact_hashes = {name: file_sha256(path) for name, path in final_artifact_paths.items() if path.exists()}
    return {
        "pipeline_manifest": {
            "path": str(pipeline_path),
            "manifest_hash": str(pipeline_manifest.get("manifest_hash", "") or ""),
            "generated_at": str(pipeline_manifest.get("generated_at", "") or ""),
            "execution_mode": str(pipeline_manifest.get("execution_mode", "") or ""),
            "run_scope": pipeline_manifest.get("run_scope", {}) if isinstance(pipeline_manifest.get("run_scope", {}), dict) else {},
            "sha256": file_sha256(pipeline_path),
        },
        "calibration_manifest": {
            "path": str(calibration_path),
            "model_version": str(calibration_manifest.get("model_version", "") or ""),
            "generated_at": str(calibration_manifest.get("generated_at", "") or ""),
            "sha256": file_sha256(calibration_path),
        },
        "final_artifact_set": {
            "hashes": artifact_hashes,
            "artifact_set_hash": canonical_hash(artifact_hashes) if artifact_hashes else "",
            "rank_source": str(dashboard.get("rank_source", "") or ""),
        },
    }


def level_value(level: str) -> float | None:
    return LEVEL_MAP.get(str(level or "").strip())


def _student_machine_level(student: dict) -> str:
    return str(student.get("level_with_modifier") or student.get("adjusted_level") or student.get("base_level") or "").strip()


def _student_machine_rank(student: dict) -> int | None:
    try:
        return int(student.get("rank", 0) or 0)
    except (TypeError, ValueError):
        return None


def normalize_student_reviews(raw_reviews: list[dict], students: dict[str, dict]) -> list[dict]:
    normalized = []
    for raw in raw_reviews or []:
        sid = str((raw or {}).get("student_id", "") or "").strip()
        if not sid:
            continue
        machine = students.get(sid, {})
        level_override = str((raw or {}).get("level_override", "") or "").strip()
        evidence_quality = str((raw or {}).get("evidence_quality", "") or "").strip().lower()
        if evidence_quality and evidence_quality not in EVIDENCE_QUALITY:
            evidence_quality = "unclear"
        evidence_comment = str((raw or {}).get("evidence_comment", "") or "").strip()
        reason_tags = normalize_reason_tags((raw or {}).get("reason_tags", []))
        try:
            desired_rank = int((raw or {}).get("desired_rank")) if (raw or {}).get("desired_rank") not in (None, "", "null") else None
        except (TypeError, ValueError):
            desired_rank = None
        if not any([level_override, evidence_quality, evidence_comment, desired_rank is not None, reason_tags]):
            continue
        machine_level = _student_machine_level(machine)
        machine_rank = _student_machine_rank(machine)
        level_delta = None
        if level_override and machine_level and level_value(level_override) is not None and level_value(machine_level) is not None:
            level_delta = round(level_value(level_override) - level_value(machine_level), 4)
        normalized.append(
            {
                "student_id": sid,
                "display_name": machine.get("display_name", sid),
                "source_file": machine.get("source_file", ""),
                "machine_level": machine_level,
                "machine_rank": machine_rank,
                "level_override": level_override,
                "level_delta": level_delta,
                "desired_rank": desired_rank,
                "rank_delta": (desired_rank - machine_rank) if desired_rank is not None and machine_rank is not None else None,
                "evidence_quality": evidence_quality,
                "evidence_comment": evidence_comment,
                "reason_tags": reason_tags,
                "uncertainty_flags": list(machine.get("uncertainty_flags", []) or []),
                "uncertainty_reasons": list(machine.get("uncertainty_reasons", []) or []),
            }
        )
    return normalized


def normalize_pairwise_adjudications(raw_pairs: list[dict], students: dict[str, dict]) -> list[dict]:
    normalized = []
    seen = set()
    for raw in raw_pairs or []:
        left = str((raw or {}).get("student_id", "") or (raw or {}).get("student_a_id", "") or "").strip()
        right = str((raw or {}).get("other_student_id", "") or (raw or {}).get("student_b_id", "") or "").strip()
        preferred = str((raw or {}).get("preferred_student_id", "") or "").strip()
        if not left or not right or not preferred or preferred not in {left, right}:
            continue
        pair_key = tuple(sorted((left, right)))
        if pair_key in seen:
            continue
        seen.add(pair_key)
        left_student = students.get(left, {})
        right_student = students.get(right, {})
        left_rank = _student_machine_rank(left_student)
        right_rank = _student_machine_rank(right_student)
        machine_preferred = left if right_rank is None or (left_rank is not None and left_rank <= right_rank) else right
        uncertainty = set(left_student.get("uncertainty_flags", []) or [])
        uncertainty.update(right_student.get("uncertainty_flags", []) or [])
        normalized.append(
            {
                "pair": [left, right],
                "preferred_student_id": preferred,
                "higher_student_id": preferred,
                "lower_student_id": right if preferred == left else left,
                "machine_preferred_student_id": machine_preferred,
                "reversed_machine_order": preferred != machine_preferred,
                "confidence": str((raw or {}).get("confidence", "") or "").strip().lower(),
                "rationale": str((raw or {}).get("rationale", "") or "").strip(),
                "reason_tags": normalize_reason_tags((raw or {}).get("reason_tags", [])),
                "uncertainty_flags": sorted(uncertainty),
            }
        )
    return normalized


def normalize_curve_bound(value) -> float | None:
    try:
        mark = float(value)
    except (TypeError, ValueError):
        return None
    if not 0.0 <= mark <= 100.0:
        return None
    return round(mark, 4)


def normalize_assigned_marks(raw_marks: list[dict], students: dict[str, dict]) -> list[dict]:
    normalized = []
    seen = set()
    for raw in raw_marks or []:
        sid = str((raw or {}).get("student_id", "") or "").strip()
        if not sid or sid in seen or sid not in students:
            continue
        try:
            mark = float((raw or {}).get("mark"))
        except (TypeError, ValueError):
            continue
        if not 0.0 <= mark <= 100.0:
            continue
        seen.add(sid)
        normalized.append({"student_id": sid, "mark": round(mark, 4)})
    return normalized


def normalize_feedback_drafts(raw_feedback: list[dict], students: dict[str, dict]) -> list[dict]:
    normalized = []
    seen = set()
    for raw in raw_feedback or []:
        sid = str((raw or {}).get("student_id", "") or "").strip()
        if not sid or sid in seen or sid not in students:
            continue
        star1 = str((raw or {}).get("star1", "") or "").strip()
        star2 = str((raw or {}).get("star2", "") or "").strip()
        wish = str((raw or {}).get("wish", "") or "").strip()
        if not any([star1, star2, wish]):
            continue
        seen.add(sid)
        normalized.append({"student_id": sid, "star1": star1, "star2": star2, "wish": wish})
    return normalized


def _safe_rank(value, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


def machine_proposal(root: Path, dashboard: dict) -> dict:
    students = dashboard.get("students", []) if isinstance(dashboard, dict) else []
    ordered = sorted(
        [item for item in students if isinstance(item, dict) and item.get("student_id")],
        key=lambda item: (_safe_rank(item.get("rank"), 999999), str(item.get("student_id", "")).lower()),
    )
    rank_source = str(dashboard.get("rank_source", "") or "")
    rank_source_path = Path(rank_source) if rank_source else None
    if rank_source_path and not rank_source_path.is_absolute():
        rank_source_path = (root / rank_source_path).resolve()
    if not rank_source_path or not rank_source_path.exists():
        for candidate in [root / "outputs" / "final_order.csv", root / "outputs" / "consistency_adjusted.csv", root / "outputs" / "consensus_scores.csv"]:
            if candidate.exists():
                rank_source_path = candidate
                break
    version = review_context(root, dashboard)
    return {
        "captured_at": now_iso(),
        "rank_source": str(rank_source_path) if rank_source_path else rank_source,
        "rank_source_hash": file_sha256(rank_source_path) if rank_source_path else "",
        "pipeline_manifest_hash": version.get("pipeline_manifest", {}).get("manifest_hash", ""),
        "artifact_set_hash": version.get("final_artifact_set", {}).get("artifact_set_hash", ""),
        "run_scope": version.get("pipeline_manifest", {}).get("run_scope", {}),
        "students": [
            {
                "student_id": str(item.get("student_id", "") or ""),
                "display_name": item.get("display_name", item.get("student_id", "")),
                "machine_rank": _student_machine_rank(item),
                "machine_level": _student_machine_level(item),
                "uncertainty_flags": list(item.get("uncertainty_flags", []) or []),
                "uncertainty_reasons": list(item.get("uncertainty_reasons", []) or []),
                "rubric_after_penalty_percent": item.get("rubric_after_penalty_percent") or item.get("rubric_mean_percent"),
            }
            for item in ordered
        ],
    }


def build_review_session(root: Path, dashboard: dict, current_project: dict | None, existing: dict | None = None) -> dict:
    session = dict(existing or {})
    existing_machine = session.get("machine_proposal", {}) if isinstance(session.get("machine_proposal"), dict) else {}
    if not existing_machine or not existing_machine.get("students"):
        session["machine_proposal"] = machine_proposal(root, dashboard)
    session.setdefault("session_id", uuid.uuid4().hex)
    session.setdefault("started_at", now_iso())
    session["updated_at"] = now_iso()
    session["project"] = current_project or {"id": review_scope_id(current_project), "name": "Workspace"}
    session["source_rank_artifact_hash"] = str(session.get("machine_proposal", {}).get("rank_source_hash", "") or "")
    return session


def machine_order_from_session(review_session: dict) -> list[str]:
    proposal = review_session.get("machine_proposal", {}) if isinstance(review_session, dict) else {}
    rows = proposal.get("students", []) if isinstance(proposal, dict) else []
    return [str(item.get("student_id", "") or "") for item in rows if str(item.get("student_id", "") or "").strip()]


def final_order_from_review(review_session: dict, students: list[dict], pairwise: list[dict]) -> tuple[list[str], dict[str, int]]:
    order = [sid for sid in machine_order_from_session(review_session) if sid]
    order_index = {sid: idx for idx, sid in enumerate(order)}
    explicit = sorted(
        [item for item in students if item.get("student_id") and item.get("desired_rank") is not None],
        key=lambda item: (
            int(item.get("desired_rank")),
            _safe_rank(item.get("machine_rank"), order_index.get(str(item.get("student_id", "") or ""), 999999) + 1),
            str(item.get("student_id", "")).lower(),
        ),
    )
    for item in explicit:
        sid = str(item.get("student_id", "") or "")
        if sid not in order:
            continue
        desired_rank = max(1, min(len(order), int(item.get("desired_rank"))))
        order.remove(sid)
        target = max(0, min(len(order), desired_rank - 1))
        order.insert(target, sid)
    for pair in sorted(pairwise, key=lambda item: tuple(item.get("pair", []))):
        preferred = str(pair.get("preferred_student_id", "") or "")
        other = str(pair.get("lower_student_id", "") or "")
        if preferred not in order or other not in order or preferred == other:
            continue
        preferred_idx = order.index(preferred)
        other_idx = order.index(other)
        if preferred_idx > other_idx:
            order.remove(preferred)
            insert_at = max(0, order.index(other))
            order.insert(insert_at, preferred)
    return order, {sid: idx for idx, sid in enumerate(order, start=1)}


def derive_review_delta(record: dict) -> dict:
    review_session = record.get("review_session", {}) if isinstance(record.get("review_session"), dict) else {}
    machine_rows = review_session.get("machine_proposal", {}).get("students", []) if isinstance(review_session.get("machine_proposal"), dict) else []
    machine_lookup = {str(item.get("student_id", "") or ""): item for item in machine_rows if item.get("student_id")}
    machine_order = [str(item.get("student_id", "") or "") for item in machine_rows if item.get("student_id")]
    machine_rank_map = {
        sid: _safe_rank(item.get("machine_rank"), idx)
        for idx, (sid, item) in enumerate(((str(item.get("student_id", "") or ""), item) for item in machine_rows if item.get("student_id")), start=1)
    }
    final_order, final_rank_map = final_order_from_review(review_session, record.get("students", []), record.get("pairwise", []))
    touched_ids = {
        str(item.get("student_id", "") or "")
        for item in record.get("students", [])
        if str(item.get("student_id", "") or "").strip()
    }
    touched_ids.update(
        {
            str(item.get("preferred_student_id", "") or "")
            for item in record.get("pairwise", [])
            if str(item.get("preferred_student_id", "") or "").strip()
        }
    )
    touched_ids.update(
        {
            str(item.get("lower_student_id", "") or "")
            for item in record.get("pairwise", [])
            if str(item.get("lower_student_id", "") or "").strip()
        }
    )
    level_overrides = []
    rank_movements = []
    boundary_decisions = []
    for sid in final_order:
        machine = machine_lookup.get(sid, {})
        machine_rank = machine_rank_map.get(sid)
        final_rank = final_rank_map.get(sid)
        student = next((item for item in record.get("students", []) if str(item.get("student_id", "") or "") == sid), {})
        final_level = str(student.get("level_override") or machine.get("machine_level") or "").strip()
        machine_level = str(machine.get("machine_level", "") or "").strip()
        if student.get("level_override") and final_level != machine_level:
            level_overrides.append(
                {
                    "student_id": sid,
                    "machine_level": machine_level,
                    "final_level": final_level,
                    "level_delta": student.get("level_delta"),
                    "uncertainty_flags": list(student.get("uncertainty_flags", []) or machine.get("uncertainty_flags", []) or []),
                }
            )
        if machine_rank is not None and final_rank is not None and machine_rank != final_rank:
            rank_movements.append(
                {
                    "student_id": sid,
                    "machine_rank": machine_rank,
                    "final_rank": final_rank,
                    "rank_delta": final_rank - machine_rank,
                    "explicit_rank_override": student.get("desired_rank") is not None,
                    "touched": sid in touched_ids,
                }
            )
        flags = set(student.get("uncertainty_flags", []) or machine.get("uncertainty_flags", []) or [])
        if "boundary_case" in flags:
            boundary_decisions.append(
                {
                    "student_id": sid,
                    "machine_level": machine_level,
                    "final_level": final_level,
                    "machine_rank": machine_rank,
                    "final_rank": final_rank,
                    "changed_level": final_level != machine_level,
                    "changed_rank": machine_rank != final_rank,
                }
            )

    pairwise_inversions = []
    seen_pairs = set()
    final_index = {sid: idx for idx, sid in enumerate(final_order)}
    for left_index, left in enumerate(machine_order):
        for right in machine_order[left_index + 1 :]:
            if left not in final_index or right not in final_index:
                continue
            if final_index[left] <= final_index[right]:
                continue
            if left not in touched_ids and right not in touched_ids:
                continue
            token = tuple(sorted((left, right)))
            if token in seen_pairs:
                continue
            seen_pairs.add(token)
            pairwise_inversions.append(
                {
                    "pair": [left, right],
                    "machine_higher": left,
                    "final_higher": left if final_index[left] < final_index[right] else right,
                    "final_lower": right if final_index[left] < final_index[right] else left,
                }
            )
    delta = {
        "generated_at": now_iso(),
        "review_id": record.get("review_id", ""),
        "scope_id": record.get("scope_id", ""),
        "session_id": review_session.get("session_id", ""),
        "source_rank_artifact_hash": review_session.get("source_rank_artifact_hash", ""),
        "machine_order": machine_order,
        "final_order": final_order,
        "level_overrides": level_overrides,
        "rank_movements": rank_movements,
        "pairwise_inversions": pairwise_inversions,
        "boundary_decisions": boundary_decisions,
        "summary": {
            "machine_count": len(machine_order),
            "final_count": len(final_order),
            "level_override_count": len(level_overrides),
            "rank_movement_count": len(rank_movements),
            "pairwise_inversion_count": len(pairwise_inversions),
            "boundary_decision_count": len(boundary_decisions),
        },
    }
    delta["delta_hash"] = canonical_hash(
        {
            "machine_order": machine_order,
            "final_order": final_order,
            "level_overrides": level_overrides,
            "rank_movements": rank_movements,
            "pairwise_inversions": pairwise_inversions,
            "boundary_decisions": boundary_decisions,
        }
    )
    return delta


def history_records(base_dir: Path, scope_id: str) -> list[dict]:
    records = []
    for path in sorted(history_dir(base_dir, scope_id).glob("*.json")):
        payload = load_json(path)
        if isinstance(payload, dict) and payload:
            records.append(migrate_review_record(payload))
    return records


def migrate_review_record(payload: dict) -> dict:
    record = dict(payload or {})
    record.setdefault("review_state", "final")
    record.setdefault("saved_at", "")
    record.setdefault("students", [])
    record.setdefault("pairwise", [])
    record.setdefault("review_notes", "")
    record.setdefault("curve_top", None)
    record.setdefault("curve_bottom", None)
    record.setdefault("assigned_marks", [])
    record.setdefault("feedback_drafts", [])
    record.setdefault("version_context", {})
    record.setdefault("review_session", {})
    record.setdefault("review_delta_summary", {})
    return record


def build_local_learning_profile(scope_id: str, records: list[dict]) -> dict:
    level_transitions = {}
    evidence_quality_counts = {}
    rank_deltas = []
    boundary_review_count = 0
    boundary_override_count = 0
    low_conf_pairs = 0
    low_conf_reversals = 0
    high_disagreement_pairs = 0
    pairwise_reversals = 0
    latest_saved_at = ""
    for record in records:
        latest_saved_at = max(latest_saved_at, str(record.get("saved_at", "") or ""))
        for student in record.get("students", []):
            machine_level = str(student.get("machine_level", "") or "")
            override = str(student.get("level_override", "") or "")
            if machine_level and override:
                key = f"{machine_level}->{override}"
                level_transitions[key] = level_transitions.get(key, 0) + 1
            quality = str(student.get("evidence_quality", "") or "")
            if quality:
                evidence_quality_counts[quality] = evidence_quality_counts.get(quality, 0) + 1
            rank_delta = student.get("rank_delta")
            if isinstance(rank_delta, int):
                rank_deltas.append(rank_delta)
            flags = set(student.get("uncertainty_flags", []) or [])
            if "boundary_case" in flags:
                boundary_review_count += 1
                if override and override != machine_level:
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
    mean_rank_delta = round(sum(rank_deltas) / len(rank_deltas), 6) if rank_deltas else 0.0
    boundary_override_rate = round(boundary_override_count / boundary_review_count, 6) if boundary_review_count else 0.0
    low_conf_reversal_rate = round(low_conf_reversals / low_conf_pairs, 6) if low_conf_pairs else 0.0
    return {
        "scope_id": scope_id,
        "review_count": len(records),
        "student_review_count": sum(len(record.get("students", [])) for record in records),
        "pairwise_adjudication_count": sum(len(record.get("pairwise", [])) for record in records),
        "latest_saved_at": latest_saved_at,
        "level_transition_counts": dict(sorted(level_transitions.items())),
        "evidence_quality_counts": dict(sorted(evidence_quality_counts.items())),
        "mean_rank_delta": mean_rank_delta,
        "boundary_override_rate": boundary_override_rate,
        "low_confidence_reversal_rate": low_conf_reversal_rate,
        "high_disagreement_pair_count": high_disagreement_pairs,
        "pairwise_reversal_count": pairwise_reversals,
        "runtime_preferences": {
            "boundary_level_bias": round(
                sum(
                    float(student.get("level_delta", 0.0) or 0.0)
                    for record in records
                    for student in record.get("students", [])
                    if "boundary_case" in set(student.get("uncertainty_flags", []) or []) and student.get("level_delta") is not None
                )
                / max(
                    1,
                    sum(
                        1
                        for record in records
                        for student in record.get("students", [])
                        if "boundary_case" in set(student.get("uncertainty_flags", []) or []) and student.get("level_delta") is not None
                    ),
                ),
                6,
            ),
            "prefer_seed_order_on_low_confidence": low_conf_reversal_rate >= 0.5,
            "teacher_rank_direction": "promote" if mean_rank_delta < 0 else "demote" if mean_rank_delta > 0 else "neutral",
        },
    }


def _redact_text(text: str, replacements: list[str], *, limit: int = 500) -> str:
    return redact_text(text, replacements, limit=limit)


def _reason_codes_from_uncertainty(flags: list[str]) -> list[str]:
    mapped = []
    lookup = {
        "boundary_case": "boundary_case",
        "high_disagreement": "high_disagreement",
        "low_confidence_rerank_move": "low_confidence_move",
    }
    for flag in flags or []:
        code = lookup.get(str(flag or "").strip())
        if code and code not in mapped:
            mapped.append(code)
    return mapped


def _reason_codes_for_student(student: dict) -> list[str]:
    evidence_quality = str(student.get("evidence_quality", "") or "").strip().lower()
    evidence_map = {
        "strong": "evidence_strong",
        "thin": "evidence_thin",
        "misaligned": "evidence_misaligned",
        "unclear": "evidence_unclear",
    }
    codes = list(student.get("reason_tags", []) or [])
    if student.get("level_override") and student.get("level_override") != student.get("machine_level"):
        codes.append("level_override")
    if student.get("rank_delta") not in (None, 0):
        codes.append("rank_reorder")
    mapped = evidence_map.get(evidence_quality)
    if mapped:
        codes.append(mapped)
    codes.extend(_reason_codes_from_uncertainty(list(student.get("uncertainty_flags", []) or [])))
    from_text = []
    low = str(student.get("evidence_comment", "") or "").strip().lower()
    keyword_map = {
        "analysis_depth": ("analysis", "interpret", "depth"),
        "eloquence": ("eloquent", "elegant", "style", "phrasing"),
        "insight": ("insight", "nuance", "perceptive"),
        "completeness": ("complete", "thorough", "fully developed"),
        "concision": ("concise", "succinct", "tighten"),
        "organization": ("organization", "structure", "coherence", "flow"),
        "voice": ("voice", "tone", "authentic"),
        "evidence_fit": ("evidence", "support", "example", "because", "quote"),
    }
    for code, keywords in keyword_map.items():
        if any(keyword in low for keyword in keywords):
            from_text.append(code)
    return sorted({code for code in codes + from_text if code})


def _reason_codes_for_pair(pair: dict) -> list[str]:
    codes = list(pair.get("reason_tags", []) or [])
    if pair.get("reversed_machine_order"):
        codes.append("pairwise_reversal")
    codes.extend(_reason_codes_from_uncertainty(list(pair.get("uncertainty_flags", []) or [])))
    low = str(pair.get("rationale", "") or "").strip().lower()
    keyword_map = {
        "analysis_depth": ("analysis", "interpret", "depth"),
        "eloquence": ("eloquent", "elegant", "style", "phrasing"),
        "insight": ("insight", "nuance", "perceptive"),
        "completeness": ("complete", "thorough", "fully developed"),
        "concision": ("concise", "succinct", "tighten"),
        "organization": ("organization", "structure", "coherence", "flow"),
        "voice": ("voice", "tone", "authentic"),
        "evidence_fit": ("evidence", "support", "example", "because", "quote"),
    }
    for code, keywords in keyword_map.items():
        if any(keyword in low for keyword in keywords):
            codes.append(code)
    return sorted({code for code in codes if code})


def _student_hash(base_dir: Path, scope_id: str, student_id: str) -> str:
    return hash_identifier(base_dir, "student", str(student_id or ""), scope_id=scope_id)


def _replacement_markers(students: dict[str, dict]) -> list[str]:
    replacements = []
    for item in students.values():
        replacements.extend(
            [
                str(item.get("student_id", "") or ""),
                str(item.get("display_name", "") or ""),
                Path(str(item.get("source_file", "") or "")).stem,
            ]
        )
    return replacements


def build_aggregate_learning_record(base_dir: Path, scope_id: str, record: dict, students: dict[str, dict], current_project: dict | None) -> dict | None:
    policy = aggregate_learning_policy(current_project)
    eligible, reason = collection_eligibility(policy)
    if str(record.get("review_state", "") or "") != "final" or not eligible:
        return None

    replacements = _replacement_markers(students)
    version_context = record.get("version_context", {}) if isinstance(record.get("version_context"), dict) else {}
    delta = derive_review_delta(record)
    replay = replay_exports(record)
    review_hash = hash_identifier(base_dir, "review", str(record.get("review_id", "") or ""), scope_id=scope_id)
    project_hash = hash_identifier(base_dir, "project", str(scope_id or "workspace"), scope_id=scope_id)
    scope_hash = hash_identifier(base_dir, "scope", str(scope_id or "workspace"), scope_id=scope_id)
    aggregate_record_id = aggregate_canonical_hash(
        {
            "review_hash": review_hash,
            "delta_hash": str(delta.get("delta_hash", "") or ""),
            "saved_at": str(record.get("saved_at", "") or ""),
            "scope_hash": scope_hash,
        }
    )[:24]
    student_code_map = {}
    student_actions = []
    for student in record.get("students", []):
        sid = str(student.get("student_id", "") or "")
        if not sid:
            continue
        codes = _reason_codes_for_student(student)
        student_code_map[sid] = codes
        student_actions.append(
            {
                "student_hash": _student_hash(base_dir, scope_id, sid),
                "machine_level": student.get("machine_level", ""),
                "final_level": student.get("level_override") or student.get("machine_level", ""),
                "machine_rank": student.get("machine_rank"),
                "desired_rank": student.get("desired_rank"),
                "rank_delta": student.get("rank_delta"),
                "level_delta": student.get("level_delta"),
                "evidence_quality": student.get("evidence_quality", ""),
                "uncertainty_flags": list(student.get("uncertainty_flags", []) or []),
                "reason_tags": list(student.get("reason_tags", []) or []),
                "normalized_reason_codes": codes,
                "comment_secondary": _redact_text(student.get("evidence_comment", ""), replacements),
            }
        )

    pairwise_actions = []
    for pair in record.get("pairwise", []):
        higher = str(pair.get("preferred_student_id", "") or "")
        lower = str(pair.get("lower_student_id", "") or "")
        codes = _reason_codes_for_pair(pair)
        pairwise_actions.append(
            {
                "preferred_student_hash": _student_hash(base_dir, scope_id, higher),
                "other_student_hash": _student_hash(base_dir, scope_id, lower),
                "reversed_machine_order": bool(pair.get("reversed_machine_order", False)),
                "confidence": pair.get("confidence", ""),
                "uncertainty_flags": list(pair.get("uncertainty_flags", []) or []),
                "reason_tags": list(pair.get("reason_tags", []) or []),
                "normalized_reason_codes": codes,
                "rationale_secondary": _redact_text(pair.get("rationale", ""), replacements),
            }
        )

    anonymized_replay = {"benchmark_gold": [], "boundary_challenges": [], "calibration_exemplars": []}
    for row in replay.get("benchmark_gold", []):
        sid = str(row.get("student_id", "") or "")
        anonymized_replay["benchmark_gold"].append(
            {
                "student_id": _student_hash(base_dir, scope_id, sid),
                "gold_level": row.get("gold_level", ""),
                "gold_band_min": row.get("gold_band_min", ""),
                "gold_band_max": row.get("gold_band_max", ""),
                "gold_rank": row.get("gold_rank"),
                "gold_neighbors": [_student_hash(base_dir, scope_id, str(item or "")) for item in row.get("gold_neighbors", []) or [] if str(item or "").strip()],
                "boundary_flag": bool(row.get("boundary_flag", False)),
                "normalized_reason_codes": list(student_code_map.get(sid, [])),
                "adjudication_notes_secondary": _redact_text(row.get("adjudication_notes", ""), replacements),
            }
        )
    for row in replay.get("boundary_challenges", []):
        sid = str(row.get("student_id", "") or "")
        anonymized_replay["boundary_challenges"].append(
            {
                "student_id": _student_hash(base_dir, scope_id, sid),
                "machine_level": row.get("machine_level", ""),
                "teacher_level": row.get("teacher_level", ""),
                "machine_rank": row.get("machine_rank"),
                "teacher_rank": row.get("teacher_rank"),
                "uncertainty_flags": list(row.get("uncertainty_flags", []) or []),
                "normalized_reason_codes": list(student_code_map.get(sid, [])),
                "comment_secondary": _redact_text(row.get("comment", ""), replacements),
            }
        )
    for row in replay.get("calibration_exemplars", []):
        sid = str(row.get("student_id", "") or "")
        machine = students.get(sid, {})
        anonymized_replay["calibration_exemplars"].append(
            {
                "student_id": _student_hash(base_dir, scope_id, sid),
                "target_level": row.get("target_level", ""),
                "evidence_quality": row.get("evidence_quality", ""),
                "normalized_reason_codes": list(student_code_map.get(sid, [])),
                "teacher_comment_secondary": _redact_text(row.get("teacher_comment", ""), replacements),
                "submission_text_redacted": _redact_text(machine.get("text", ""), replacements, limit=4000),
            }
        )

    all_reason_rows = student_actions + pairwise_actions
    secondary_review_notes = _redact_text(record.get("review_notes", ""), replacements)
    record_level_codes = sorted(
        {
            code
            for row in all_reason_rows
            for code in row.get("normalized_reason_codes", []) or []
        }
    )
    local_payload = {
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "aggregate_record_id": aggregate_record_id,
        "review_hash": review_hash,
        "review_state": "final",
        "scope_id": scope_id,
        "scope_hash": scope_hash,
        "project_hash": project_hash,
        "saved_at": str(record.get("saved_at", "") or ""),
        "retention": {
            "retention_days": int(policy.get("retention_days", 365) or 365),
            "expires_at": aggregate_expires_at(str(record.get("saved_at", "") or ""), int(policy.get("retention_days", 365) or 365)),
        },
        "collection_policy": {
            **policy,
            "eligible": True,
            "eligibility_reason": reason,
            "collected_at": aggregate_now_iso(),
        },
        "provenance": {
            "pipeline_manifest_hash": str(version_context.get("pipeline_manifest", {}).get("manifest_hash", "") or ""),
            "calibration_manifest_hash": str(version_context.get("calibration_manifest", {}).get("sha256", "") or ""),
            "artifact_set_hash": str(version_context.get("final_artifact_set", {}).get("artifact_set_hash", "") or ""),
            "source_rank_artifact_hash": str(record.get("review_session", {}).get("source_rank_artifact_hash", "") or ""),
            "run_scope": version_context.get("pipeline_manifest", {}).get("run_scope", {}) if isinstance(version_context.get("pipeline_manifest", {}), dict) else {},
            "delta_hash": str(delta.get("delta_hash", "") or ""),
        },
        "normalized_reason_codes": record_level_codes,
        "normalized_reason_counts": reason_count_summary(all_reason_rows),
        "secondary_evidence": {
            "review_notes_secondary": secondary_review_notes,
        },
        "student_actions": student_actions,
        "pairwise_actions": pairwise_actions,
        "replay_candidates": anonymized_replay,
    }
    return local_payload


def write_aggregate_learning_record(base_dir: Path, scope_id: str, record: dict) -> dict:
    path = eligible_record_path(base_dir, scope_id, str(record.get("aggregate_record_id", "") or ""))
    write_aggregate_json(path, record)
    return {"path": str(path), "aggregate_record_id": record.get("aggregate_record_id", "")}


def aggregate_learning_summary(base_dir: Path, scope_id: str, current_project: dict | None) -> dict:
    policy = aggregate_learning_policy(current_project)
    eligible_rows = list_eligible_records(base_dir, scope_id=scope_id)
    tombstones = list_tombstones(base_dir)
    return {
        "mode": policy.get("mode", "local_only"),
        "policy_reference": policy.get("policy_reference", ""),
        "retention_days": int(policy.get("retention_days", 365) or 365),
        "collection_allowed": bool(policy.get("eligible", False)),
        "collection_reason": str(policy.get("eligibility_reason", "") or ""),
        "scope_record_count": len(eligible_rows),
        "global_record_count": len(list_eligible_records(base_dir)),
        "tombstone_count": len(tombstones),
        "latest_saved_at": max((str(row.get("saved_at", "") or "") for row in eligible_rows), default=""),
    }


def retire_aggregate_scope_records(base_dir: Path, scope_id: str, *, reason: str) -> dict:
    removed = []
    for record in list_eligible_records(base_dir, scope_id=scope_id):
        record_id = str(record.get("aggregate_record_id", "") or "")
        if not record_id:
            continue
        path = eligible_record_path(base_dir, scope_id, record_id)
        if path.exists():
            path.unlink()
        write_aggregate_json(
            tombstone_path(base_dir, record_id),
            {
                "aggregate_record_id": record_id,
                "deleted_at": aggregate_now_iso(),
                "reason": reason,
                "scope_hash": str(record.get("scope_hash", "") or ""),
                "project_hash": str(record.get("project_hash", "") or ""),
            },
        )
        removed.append(record_id)
    return {"removed_count": len(removed), "removed_record_ids": removed}


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def replay_exports(record: dict) -> dict[str, list[dict]]:
    delta = derive_review_delta(record)
    benchmark_rows = {}
    boundary_rows = {}
    calibration_rows = {}
    student_lookup = {str(item.get("student_id", "") or ""): item for item in record.get("students", []) if item.get("student_id")}
    machine_lookup = {
        str(item.get("student_id", "") or ""): item
        for item in record.get("review_session", {}).get("machine_proposal", {}).get("students", [])
        if item.get("student_id")
    }
    final_rank_map = {sid: idx for idx, sid in enumerate(delta.get("final_order", []), start=1)}
    for sid in delta.get("final_order", []):
        student = student_lookup.get(sid, {})
        machine = machine_lookup.get(sid, {})
        benchmark_rows[sid] = {
            "student_id": sid,
            "gold_level": student.get("level_override") or machine.get("machine_level", ""),
            "gold_band_min": "",
            "gold_band_max": "",
            "gold_rank": final_rank_map.get(sid),
            "gold_neighbors": [],
            "boundary_flag": "boundary_case" in set(student.get("uncertainty_flags", []) or machine.get("uncertainty_flags", []) or []),
            "adjudication_notes": student.get("evidence_comment", ""),
        }
        flags = set(student.get("uncertainty_flags", []) or machine.get("uncertainty_flags", []) or [])
        if flags & {"boundary_case", "high_disagreement", "low_confidence_rerank_move"}:
            boundary_rows[sid] = {
                "student_id": sid,
                "display_name": student.get("display_name", machine.get("display_name", sid)),
                "machine_level": student.get("machine_level", machine.get("machine_level", "")),
                "teacher_level": student.get("level_override") or machine.get("machine_level", ""),
                "machine_rank": student.get("machine_rank", machine.get("machine_rank")),
                "teacher_rank": final_rank_map.get(sid),
                "uncertainty_flags": sorted(flags),
                "comment": student.get("evidence_comment", ""),
            }
        if sid in student_lookup and (student.get("level_override") or student.get("evidence_quality") or student.get("evidence_comment")):
            calibration_rows[sid] = {
                "student_id": sid,
                "display_name": student.get("display_name", sid),
                "source_file": student.get("source_file", ""),
                "target_level": student.get("level_override") or student.get("machine_level", ""),
                "evidence_quality": student.get("evidence_quality", ""),
                "teacher_comment": student.get("evidence_comment", ""),
            }
    for pair in delta.get("pairwise_inversions", []):
        higher = str(pair.get("final_higher", "") or "")
        lower = str(pair.get("final_lower", "") or "")
        if higher and higher in benchmark_rows and lower:
            benchmark_rows[higher]["gold_neighbors"].append(lower)
        if lower and lower in benchmark_rows and higher:
            benchmark_rows[lower]["gold_neighbors"].append(higher)
    return {
        "benchmark_gold": sorted(benchmark_rows.values(), key=lambda item: (str(item.get("gold_rank", "")), item.get("student_id", ""))),
        "boundary_challenges": sorted(boundary_rows.values(), key=lambda item: item.get("student_id", "")),
        "calibration_exemplars": sorted(calibration_rows.values(), key=lambda item: item.get("student_id", "")),
    }


def write_replay_exports(base_dir: Path, scope_id: str, record: dict) -> dict:
    exports = replay_exports(record)
    export_dir = exports_dir(base_dir, scope_id)
    benchmark_path = export_dir / "benchmark_gold.jsonl"
    boundary_path = export_dir / "boundary_challenges.jsonl"
    calibration_path = export_dir / "calibration_exemplars.jsonl"
    write_jsonl(benchmark_path, exports["benchmark_gold"])
    write_jsonl(boundary_path, exports["boundary_challenges"])
    write_jsonl(calibration_path, exports["calibration_exemplars"])
    summary = {
        "benchmark_gold_path": str(benchmark_path),
        "benchmark_gold_count": len(exports["benchmark_gold"]),
        "boundary_challenges_path": str(boundary_path),
        "boundary_challenges_count": len(exports["boundary_challenges"]),
        "calibration_exemplars_path": str(calibration_path),
        "calibration_exemplars_count": len(exports["calibration_exemplars"]),
    }
    write_json(export_dir / "export_summary.json", summary)
    return summary


def line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def materialize_workspace_review_state(root: Path, bundle: dict) -> None:
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    write_json(outputs / "review_feedback_draft.json", bundle.get("draft_review", {}))
    write_json(outputs / "review_feedback_latest.json", bundle.get("latest_review", {}))
    write_json(outputs / "review_delta_latest.json", bundle.get("latest_delta", {}))
    write_json(outputs / "local_learning_profile.json", bundle.get("local_learning_profile", {}))
    write_json(outputs / "local_teacher_prior.json", bundle.get("local_teacher_prior", {}))
    write_json(outputs / "review_replay_exports.json", bundle.get("replay_exports", {}))
    write_json(outputs / "aggregate_learning_summary.json", bundle.get("aggregate_learning", {}))
    write_json(outputs / "engagement_signal.json", bundle.get("engagement_signal", {}))


def load_review_bundle(base_dir: Path, root: Path, current_project: dict | None) -> dict:
    scope_id = review_scope_id(current_project)
    prune_expired_records(base_dir, scope_id=scope_id)
    draft_payload = load_json(draft_review_path(base_dir, scope_id))
    draft = (
        migrate_review_record(draft_payload)
        if draft_payload
        else {
            "review_state": "draft",
            "review_id": "",
            "scope_id": scope_id,
            "saved_at": "",
            "project": current_project or {"id": scope_id, "name": "Workspace"},
            "review_notes": "",
            "students": [],
            "pairwise": [],
            "curve_top": None,
            "curve_bottom": None,
            "assigned_marks": [],
            "feedback_drafts": [],
            "version_context": {},
            "review_session": {},
            "review_delta_summary": {},
        }
    )
    latest = migrate_review_record(load_json(latest_review_path(base_dir, scope_id)))
    records = history_records(base_dir, scope_id)
    if latest.get("review_id") and not any(record.get("review_id") == latest.get("review_id") for record in records):
        records.append(latest)
    profile = load_json(local_profile_path(base_dir, scope_id))
    if not profile:
        profile = build_local_learning_profile(scope_id, records)
    prior = load_json(local_teacher_prior_path(base_dir, scope_id))
    if not prior:
        prior = build_local_teacher_prior(scope_id, records)
    export_dir = exports_dir(base_dir, scope_id)
    replay = load_json(export_dir / "export_summary.json")
    if not replay:
        replay = {
            "benchmark_gold_path": str(export_dir / "benchmark_gold.jsonl"),
            "benchmark_gold_count": line_count(export_dir / "benchmark_gold.jsonl"),
            "boundary_challenges_path": str(export_dir / "boundary_challenges.jsonl"),
            "boundary_challenges_count": line_count(export_dir / "boundary_challenges.jsonl"),
            "calibration_exemplars_path": str(export_dir / "calibration_exemplars.jsonl"),
            "calibration_exemplars_count": line_count(export_dir / "calibration_exemplars.jsonl"),
        }
    aggregate_summary = aggregate_learning_summary(base_dir, scope_id, current_project)
    write_json(aggregate_learning_summary_path(base_dir, scope_id), aggregate_summary)
    engagement_signal = load_json(scope_dir(base_dir, scope_id) / "engagement_signal.json")
    return {
        "scope_id": scope_id,
        "project": current_project or {"id": scope_id, "name": "Workspace"},
        "draft_review": draft,
        "latest_review": latest,
        "latest_delta": load_json(latest_delta_path(base_dir, scope_id)),
        "local_learning_profile": profile,
        "local_teacher_prior": prior,
        "replay_exports": replay,
        "aggregate_learning": aggregate_summary,
        "engagement_signal": engagement_signal,
        "anonymized_aggregate": {
            "mode": aggregate_summary.get("mode", "local_only"),
            "collection_allowed": bool(aggregate_summary.get("collection_allowed", False)),
            "collection_reason": aggregate_summary.get("collection_reason", ""),
            "record_count": int(aggregate_summary.get("scope_record_count", 0) or 0),
            "global_record_count": int(aggregate_summary.get("global_record_count", 0) or 0),
            "tombstone_count": int(aggregate_summary.get("tombstone_count", 0) or 0),
        },
    }


def ensure_draft_review(base_dir: Path, root: Path, current_project: dict | None) -> dict:
    scope_id = review_scope_id(current_project)
    path = draft_review_path(base_dir, scope_id)
    existing = migrate_review_record(load_json(path))
    dashboard = load_dashboard(root)
    current_proposal = machine_proposal(root, dashboard)
    existing_session = existing.get("review_session", {}) if isinstance(existing.get("review_session"), dict) else {}
    existing_hash = str(existing_session.get("source_rank_artifact_hash", "") or "")
    current_hash = str(current_proposal.get("rank_source_hash", "") or "")
    if (
        existing.get("review_state") == "draft"
        and existing_session.get("session_id")
        and existing_hash
        and current_hash
        and existing_hash == current_hash
    ):
        return existing
    session = build_review_session(root, dashboard, current_project, existing_session)
    session["machine_proposal"] = current_proposal
    session["source_rank_artifact_hash"] = current_hash
    draft = {
        "review_state": "draft",
        "review_id": "",
        "scope_id": scope_id,
        "saved_at": existing.get("saved_at", ""),
        "project": current_project or {"id": scope_id, "name": "Workspace"},
        "review_notes": existing.get("review_notes", ""),
        "students": existing.get("students", []),
        "pairwise": existing.get("pairwise", []),
        "curve_top": existing.get("curve_top"),
        "curve_bottom": existing.get("curve_bottom"),
        "assigned_marks": existing.get("assigned_marks", []),
        "feedback_drafts": existing.get("feedback_drafts", []),
        "version_context": review_context(root, dashboard),
        "review_session": session,
        "review_delta_summary": {},
    }
    write_json(path, draft)
    return draft


def save_review_bundle(base_dir: Path, root: Path, current_project: dict | None, payload: dict, *, stage: str = "draft") -> dict:
    dashboard = load_dashboard(root)
    students = student_lookup(dashboard)
    scope_id = review_scope_id(current_project)
    existing_draft = ensure_draft_review(base_dir, root, current_project)
    session = build_review_session(root, dashboard, current_project, existing_draft.get("review_session"))
    normalized_students = normalize_student_reviews((payload or {}).get("students", []), students)
    normalized_pairwise = normalize_pairwise_adjudications((payload or {}).get("pairwise", []), students)
    review_notes = str((payload or {}).get("review_notes", "") or "").strip()
    curve_top = normalize_curve_bound((payload or {}).get("curve_top"))
    curve_bottom = normalize_curve_bound((payload or {}).get("curve_bottom"))
    assigned_marks = normalize_assigned_marks((payload or {}).get("assigned_marks", []), students)
    feedback_drafts = normalize_feedback_drafts((payload or {}).get("feedback_drafts", []), students)
    record = {
        "review_state": "draft" if stage != "final" else "final",
        "review_id": uuid.uuid4().hex if stage == "final" else "",
        "scope_id": scope_id,
        "saved_at": now_iso(),
        "project": current_project or {"id": scope_id, "name": "Workspace"},
        "review_notes": review_notes,
        "students": normalized_students,
        "pairwise": normalized_pairwise,
        "curve_top": curve_top,
        "curve_bottom": curve_bottom,
        "assigned_marks": assigned_marks,
        "feedback_drafts": feedback_drafts,
        "version_context": review_context(root, dashboard),
        "review_session": session,
    }
    if stage != "final":
        write_json(draft_review_path(base_dir, scope_id), record)
        bundle = load_review_bundle(base_dir, root, current_project)
        materialize_workspace_review_state(root, bundle)
        return bundle

    delta = derive_review_delta(record)
    record["review_delta_summary"] = delta.get("summary", {})
    latest_path = latest_review_path(base_dir, scope_id)
    history_path = history_dir(base_dir, scope_id) / f"{record['saved_at'].replace(':', '').replace('.', '')}_{record['review_id']}.json"
    write_json(latest_path, record)
    write_json(history_path, record)
    write_json(latest_delta_path(base_dir, scope_id), delta)
    draft_path = draft_review_path(base_dir, scope_id)
    if draft_path.exists():
        draft_path.unlink()
    records = history_records(base_dir, scope_id)
    profile = build_local_learning_profile(scope_id, records)
    write_json(local_profile_path(base_dir, scope_id), profile)
    prior = build_local_teacher_prior(scope_id, records)
    write_prior_json(local_teacher_prior_path(base_dir, scope_id), prior)
    replay = write_replay_exports(base_dir, scope_id, record)
    aggregate_allowed = bool(collection_eligibility(aggregate_learning_policy(current_project))[0])
    engagement_signal = evaluate_engagement(record, collection_allowed=aggregate_allowed)
    write_json(scope_dir(base_dir, scope_id) / "engagement_signal.json", engagement_signal)
    aggregate_record = None
    if engagement_signal.get("retention_state") == "aggregate_candidate":
        aggregate_record = build_aggregate_learning_record(base_dir, scope_id, record, students, current_project)
    if aggregate_record:
        write_aggregate_learning_record(base_dir, scope_id, aggregate_record)
    bundle = load_review_bundle(base_dir, root, current_project)
    materialize_workspace_review_state(root, bundle)
    return bundle


def delete_review_scope(base_dir: Path, scope_id: str) -> None:
    retire_aggregate_scope_records(base_dir, scope_id, reason="scope_deleted")
    target = reviews_root(base_dir) / scope_id
    if target.exists():
        for path in sorted(target.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        target.rmdir()


def review_scope_summary(base_dir: Path, scope_id: str, current_project: dict | None = None) -> dict:
    bundle = load_review_bundle(base_dir, base_dir.parent, current_project or {"id": scope_id, "name": scope_id})
    latest = bundle.get("latest_review", {})
    profile = bundle.get("local_learning_profile", {})
    aggregate_summary = bundle.get("aggregate_learning", {})
    return {
        "latest_saved_at": latest.get("saved_at", ""),
        "student_review_count": int(profile.get("student_review_count", 0) or 0),
        "pairwise_adjudication_count": int(profile.get("pairwise_adjudication_count", 0) or 0),
        "aggregate_collection_mode": aggregate_summary.get("mode", "local_only"),
        "aggregate_record_count": int(aggregate_summary.get("scope_record_count", 0) or 0),
    }
