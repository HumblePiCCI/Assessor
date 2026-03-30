#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

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
    project_id = str((current_project or {}).get("id", "") or "").strip()
    return project_id or "workspace"


def reviews_root(base_dir: Path) -> Path:
    path = base_dir / "data" / "reviews"
    path.mkdir(parents=True, exist_ok=True)
    return path


def analytics_root(base_dir: Path) -> Path:
    path = base_dir / "data" / "review_analytics"
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


def analytics_log_path(base_dir: Path) -> Path:
    return analytics_root(base_dir) / "anonymized_feedback.jsonl"


def analytics_salt(base_dir: Path) -> str:
    salt_path = analytics_root(base_dir) / "salt.txt"
    if salt_path.exists():
        return salt_path.read_text(encoding="utf-8").strip()
    salt = uuid.uuid4().hex
    salt_path.write_text(salt, encoding="utf-8")
    return salt


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
        try:
            desired_rank = int((raw or {}).get("desired_rank")) if (raw or {}).get("desired_rank") not in (None, "", "null") else None
        except (TypeError, ValueError):
            desired_rank = None
        if not any([level_override, evidence_quality, evidence_comment, desired_rank is not None]):
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
                "uncertainty_flags": sorted(uncertainty),
            }
        )
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


def _redact_text(text: str, replacements: list[str]) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    for candidate in sorted({item for item in replacements if item}, key=len, reverse=True):
        value = re.sub(re.escape(candidate), "[student]", value, flags=re.IGNORECASE)
    value = re.sub(r"https?://\S+", "[url]", value)
    value = re.sub(r"\b[\w.+-]+@[\w.-]+\.\w+\b", "[email]", value)
    value = re.sub(r"\b\d{4,}\b", "[number]", value)
    value = re.sub(r'"[^"]+"', "[quote]", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:500]


def anonymized_entries(base_dir: Path, scope_id: str, record: dict, students: dict[str, dict]) -> list[dict]:
    salt = analytics_salt(base_dir)

    def hashed(value: str) -> str:
        return hashlib.sha256(f"{salt}:{scope_id}:{value}".encode("utf-8")).hexdigest()[:16]

    entries = []
    replacements = []
    for item in students.values():
        replacements.extend(
            [
                str(item.get("student_id", "") or ""),
                str(item.get("display_name", "") or ""),
                Path(str(item.get("source_file", "") or "")).stem,
            ]
        )
    version_context = record.get("version_context", {})
    pipeline_hash = str(version_context.get("pipeline_manifest", {}).get("manifest_hash", "") or "")
    calibration_hash = str(version_context.get("calibration_manifest", {}).get("sha256", "") or "")
    artifact_set_hash = str(version_context.get("final_artifact_set", {}).get("artifact_set_hash", "") or "")
    project_hash = hashed(scope_id)
    for student in record.get("students", []):
        entries.append(
            {
                "review_id": record.get("review_id"),
                "saved_at": record.get("saved_at"),
                "project_hash": project_hash,
                "student_hash": hashed(student.get("student_id", "")),
                "action_type": "student_review",
                "machine_level": student.get("machine_level", ""),
                "level_override": student.get("level_override", ""),
                "machine_rank": student.get("machine_rank"),
                "desired_rank": student.get("desired_rank"),
                "evidence_quality": student.get("evidence_quality", ""),
                "comment_redacted": _redact_text(student.get("evidence_comment", ""), replacements),
                "uncertainty_flags": list(student.get("uncertainty_flags", []) or []),
                "pipeline_manifest_hash": pipeline_hash,
                "calibration_manifest_hash": calibration_hash,
                "artifact_set_hash": artifact_set_hash,
            }
        )
    for pair in record.get("pairwise", []):
        entries.append(
            {
                "review_id": record.get("review_id"),
                "saved_at": record.get("saved_at"),
                "project_hash": project_hash,
                "student_hash": hashed(pair.get("preferred_student_id", "")),
                "action_type": "pairwise_adjudication",
                "preferred_student_hash": hashed(pair.get("preferred_student_id", "")),
                "other_student_hash": hashed(pair.get("lower_student_id", "")),
                "reversed_machine_order": bool(pair.get("reversed_machine_order", False)),
                "confidence": pair.get("confidence", ""),
                "rationale_redacted": _redact_text(pair.get("rationale", ""), replacements),
                "uncertainty_flags": list(pair.get("uncertainty_flags", []) or []),
                "pipeline_manifest_hash": pipeline_hash,
                "calibration_manifest_hash": calibration_hash,
                "artifact_set_hash": artifact_set_hash,
            }
        )
    return entries


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


def load_review_bundle(base_dir: Path, root: Path, current_project: dict | None) -> dict:
    scope_id = review_scope_id(current_project)
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
    analytics_log = analytics_log_path(base_dir)
    return {
        "scope_id": scope_id,
        "project": current_project or {"id": scope_id, "name": "Workspace"},
        "draft_review": draft,
        "latest_review": latest,
        "latest_delta": load_json(latest_delta_path(base_dir, scope_id)),
        "local_learning_profile": profile,
        "local_teacher_prior": prior,
        "replay_exports": replay,
        "anonymized_aggregate": {
            "path": str(analytics_log),
            "record_count": line_count(analytics_log),
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
    record = {
        "review_state": "draft" if stage != "final" else "final",
        "review_id": uuid.uuid4().hex if stage == "final" else "",
        "scope_id": scope_id,
        "saved_at": now_iso(),
        "project": current_project or {"id": scope_id, "name": "Workspace"},
        "review_notes": review_notes,
        "students": normalized_students,
        "pairwise": normalized_pairwise,
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
    analytics_path = analytics_log_path(base_dir)
    analytics_path.parent.mkdir(parents=True, exist_ok=True)
    with analytics_path.open("a", encoding="utf-8") as handle:
        for item in anonymized_entries(base_dir, scope_id, record, students):
            handle.write(json.dumps(item, ensure_ascii=True) + "\n")
    bundle = load_review_bundle(base_dir, root, current_project)
    materialize_workspace_review_state(root, bundle)
    return bundle


def delete_review_scope(base_dir: Path, scope_id: str) -> None:
    target = reviews_root(base_dir) / scope_id
    if target.exists():
        for path in sorted(target.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        target.rmdir()


def review_scope_summary(base_dir: Path, scope_id: str) -> dict:
    bundle = load_review_bundle(base_dir, base_dir.parent, {"id": scope_id, "name": scope_id})
    latest = bundle.get("latest_review", {})
    profile = bundle.get("local_learning_profile", {})
    return {
        "latest_saved_at": latest.get("saved_at", ""),
        "student_review_count": int(profile.get("student_review_count", 0) or 0),
        "pairwise_adjudication_count": int(profile.get("pairwise_adjudication_count", 0) or 0),
    }
