#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server import review_store


SCHEMA_VERSION = 1
PASSBACK_ORDER = ["no_passback", "csv_export", "draft_grade", "assigned_grade", "return_submission"]
PASSBACK_MODES = set(PASSBACK_ORDER)
LIVE_WRITE_MODES = {"draft_grade", "assigned_grade", "return_submission"}
TEXT_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "text/html",
    "application/rtf",
}
SUPPORTED_FILE_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}
GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document"
UNSUPPORTED_GOOGLE_MIME_TYPES = {
    "application/vnd.google-apps.form": "forms_unsupported",
    "application/vnd.google-apps.presentation": "slides_unsupported",
    "application/vnd.google-apps.spreadsheet": "sheets_unsupported",
    "application/vnd.google-apps.drawing": "drawing_unsupported",
}
CLASSROOM_REMEDIES = {
    "classroom_api_disabled": "Ask the Google Workspace admin to enable the Classroom API for this domain.",
    "admin_approval_required": "Ask the Google Workspace admin to approve live Classroom writes before passback.",
    "admin_blocked_app": "Ask the Google Workspace admin to approve the app for the teacher, course, or pilot cohort.",
    "classroom_write_adapter_not_configured": "Keep using CSV export until a verified Classroom write adapter is configured.",
    "full_validation_current_required": "Run background validation against the latest teacher revision before export or passback.",
    "missing_oauth_grant": "Reconnect Google so the app can refresh the teacher's Classroom grant.",
    "insufficient_scope": "Reconnect with the Classroom and Drive scopes required by the selected workflow.",
    "teacher_removed_from_course": "Have a course teacher or admin restore access before retrying reconciliation.",
    "course_archived": "Restore or duplicate the course before linking it to a live assessment run.",
    "resource_not_found": "Refresh the course-work list and relink the assignment.",
    "quota_exhausted": "Retry after quota reset or move the job to the operator retry queue.",
}


class ClassroomStateError(ValueError):
    def __init__(self, message: str, *, code: str = "classroom_state_error"):
        super().__init__(message)
        self.code = code


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def canonical_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def short_hash(payload: Any, length: int = 24) -> str:
    return canonical_hash(payload)[:length]


def classroom_root(base_dir: Path) -> Path:
    path = base_dir / "data" / "classroom"
    path.mkdir(parents=True, exist_ok=True)
    return path


def scope_dir(base_dir: Path, scope_id: str) -> Path:
    path = classroom_root(base_dir) / scope_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_path(base_dir: Path, scope_id: str) -> Path:
    return scope_dir(base_dir, scope_id) / "classroom_state.json"


def project_ref(current_project: dict | None) -> dict:
    project = current_project or {}
    return {
        "id": str(project.get("id", "") or "workspace"),
        "name": str(project.get("name", "") or "Workspace"),
        "scope_key": str(project.get("scope_key", "") or project.get("id", "") or "workspace"),
    }


def default_state(scope_id: str, current_project: dict | None, identity: dict | None = None) -> dict:
    identity = identity or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "scope_id": scope_id,
        "project": project_ref(current_project),
        "tenant_id": str(identity.get("tenant_id", "") or ""),
        "teacher_id": str(identity.get("teacher_id", "") or ""),
        "created_at": now_iso(),
        "updated_at": "",
        "product_state": "blocked",
        "classroom_link": {},
        "policy": default_policy(identity),
        "registration": default_registration(),
        "roster": [],
        "submissions": {},
        "event_log": [],
        "event_ids": [],
        "event_counters": {"accepted": 0, "duplicate": 0, "ignored": 0},
        "reconciliation": {
            "latest_reconciliation_at": "",
            "latest_snapshot_hash": "",
            "missed_event_replay_required": False,
            "duplicate_or_out_of_order_count": 0,
        },
        "summary": empty_summary(),
        "human_revisions": [],
        "latest_human_revision_id": 0,
        "audit": {
            "status": "not_started",
            "audit_revision_id": 0,
            "completed_at": "",
            "gate_status": "not_run",
            "blocked_reasons": [],
        },
        "finalization": {
            "finalized_by_teacher_at": "",
            "finalized_revision_id": 0,
            "evidence_packet_id": "",
            "status": "not_finalized",
        },
        "passback": {
            "mode": "no_passback",
            "preflights": {},
            "actions": [],
        },
        "platform_errors": [],
    }


def empty_summary() -> dict:
    return {
        "roster_count": 0,
        "submitted_count": 0,
        "missing_count": 0,
        "reclaimed_count": 0,
        "returned_count": 0,
        "updated_count": 0,
        "attachment_blocker_count": 0,
        "ready_for_analysis_count": 0,
        "scheduled_analysis_count": 0,
        "stale_analysis_count": 0,
    }


def default_policy(identity: dict | None = None) -> dict:
    identity = identity or {}
    return {
        "policy_state": "operator_supervised_pilot" if not identity.get("strict_auth") else "missing_policy",
        "app_approval_status": "operator_supervised_pilot" if not identity.get("strict_auth") else "missing_admin_approval",
        "oauth_scope_posture": "not_connected",
        "classroom_write_adapter_status": "not_configured",
        "provider_allowlist_status": "not_evaluated",
        "retention_policy_status": "not_evaluated",
        "external_writes_enabled": False,
        "read_only_first": True,
        "jurisdiction_profile": "",
    }


def default_registration() -> dict:
    return {
        "registration_state": "not_registered",
        "push_registration_id": "",
        "registration_expiry": "",
        "renewal_required": False,
        "pubsub_delivery_status": "not_configured",
        "dead_letter_count": 0,
        "replay_state": "not_started",
    }


def load_state(base_dir: Path, scope_id: str, current_project: dict | None = None, identity: dict | None = None) -> dict:
    existing = load_json(state_path(base_dir, scope_id))
    if not existing:
        return default_state(scope_id, current_project, identity)
    merged = default_state(scope_id, current_project or existing.get("project"), identity)
    merged.update(existing)
    merged["schema_version"] = SCHEMA_VERSION
    merged["project"] = project_ref(current_project or existing.get("project"))
    merged.setdefault("policy", default_policy(identity))
    merged.setdefault("registration", default_registration())
    merged.setdefault("summary", empty_summary())
    merged.setdefault("passback", {"mode": "no_passback", "preflights": {}, "actions": []})
    merged.setdefault("audit", {})
    merged["audit"].setdefault("status", "not_started")
    merged["audit"].setdefault("audit_revision_id", 0)
    merged["audit"].setdefault("gate_status", "not_run")
    merged.setdefault("finalization", {"finalized_by_teacher_at": "", "evidence_packet_id": ""})
    merged["finalization"].setdefault("finalized_revision_id", 0)
    merged["finalization"].setdefault(
        "status",
        "current" if merged["finalization"].get("finalized_by_teacher_at") else "not_finalized",
    )
    return merged


def save_state(base_dir: Path, scope_id: str, state: dict, root: Path | None = None) -> dict:
    state["updated_at"] = now_iso()
    write_json(state_path(base_dir, scope_id), state)
    if root is not None:
        materialize_workspace_state(root, state)
    return state


def materialize_workspace_state(root: Path, state: dict) -> None:
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    write_json(outputs / "classroom_state.json", public_state(state))


def public_state(state: dict) -> dict:
    payload = dict(state)
    payload["event_ids"] = list(payload.get("event_ids", [])[-20:])
    passback = dict(payload.get("passback", {}))
    preflights = passback.get("preflights", {})
    if isinstance(preflights, dict):
        passback["preflights"] = {
            key: preflights[key]
            for key in sorted(preflights.keys())[-5:]
        }
    payload["passback"] = passback
    return payload


def normalize_passback_mode(mode: str | None) -> str:
    normalized = str(mode or "no_passback").strip().lower()
    if normalized not in PASSBACK_MODES:
        raise ClassroomStateError(f"Unsupported passback mode: {mode}", code="invalid_passback_mode")
    return normalized


def allowed_passback_modes(configured_mode: str) -> set[str]:
    configured_mode = normalize_passback_mode(configured_mode)
    index = PASSBACK_ORDER.index(configured_mode)
    return set(PASSBACK_ORDER[1 : index + 1])


def normalize_link_payload(payload: dict, current_project: dict | None, identity: dict | None) -> dict:
    course_id = str(payload.get("course_id", "") or "").strip()
    coursework_id = str(payload.get("coursework_id", "") or "").strip()
    course_name = str(payload.get("course_name", "") or payload.get("course_title", "") or course_id).strip()
    coursework_title = str(payload.get("coursework_title", "") or payload.get("assignment_title", "") or coursework_id).strip()
    if not course_id:
        raise ClassroomStateError("course_id is required", code="missing_course_id")
    if not coursework_id:
        raise ClassroomStateError("coursework_id is required", code="missing_coursework_id")
    passback_mode = normalize_passback_mode(payload.get("passback_mode"))
    policy = default_policy(identity)
    raw_policy = payload.get("policy", {})
    if isinstance(raw_policy, dict):
        for key in policy:
            if key in raw_policy:
                policy[key] = raw_policy[key]
    return {
        "tenant_id": str((identity or {}).get("tenant_id", "") or ""),
        "teacher_id": str((identity or {}).get("teacher_id", "") or ""),
        "course_id": course_id,
        "course_name": course_name,
        "coursework_id": coursework_id,
        "coursework_title": coursework_title,
        "selected_project_id": project_ref(current_project)["id"],
        "selected_rubric_source": str(payload.get("selected_rubric_source", "") or "project_rubric"),
        "google_integration_path": str(payload.get("google_integration_path", "") or "standalone_oauth_classroom_api"),
        "roster_sync_state": "pending",
        "attachment_support_state": "pending",
        "passback_mode": passback_mode,
        "latest_reconciliation_at": "",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }, policy


def link_assignment(base_dir: Path, root: Path, current_project: dict | None, identity: dict | None, payload: dict) -> dict:
    scope_id = review_store.review_scope_id(current_project)
    state = load_state(base_dir, scope_id, current_project, identity)
    link, policy = normalize_link_payload(payload, current_project, identity)
    state["classroom_link"] = link
    state["policy"] = policy
    state["registration"] = default_registration()
    state["passback"]["mode"] = link["passback_mode"]
    state["product_state"] = "collecting"
    save_state(base_dir, scope_id, state, root)
    return state_bundle(base_dir, root, current_project, identity)


def normalize_roster(raw_roster: list[dict]) -> list[dict]:
    roster = []
    seen = set()
    for raw in raw_roster or []:
        if not isinstance(raw, dict):
            continue
        student_id = str(raw.get("student_id", "") or raw.get("user_id", "") or raw.get("id", "") or "").strip()
        if not student_id or student_id in seen:
            continue
        seen.add(student_id)
        roster.append(
            {
                "student_id": student_id,
                "display_name": str(raw.get("display_name", "") or raw.get("name", "") or student_id).strip(),
                "course_role": str(raw.get("course_role", "") or "student"),
                "classroom_user_id": str(raw.get("classroom_user_id", "") or raw.get("user_id", "") or ""),
            }
        )
    return roster


def normalize_attachment(raw: dict) -> dict:
    raw = raw or {}
    attachment_id = str(raw.get("attachment_id", "") or raw.get("id", "") or raw.get("drive_file_id", "") or "").strip()
    title = str(raw.get("title", "") or raw.get("file_name", "") or attachment_id or "attachment").strip()
    mime_type = str(raw.get("mime_type", "") or raw.get("mimeType", "") or "").strip().lower()
    attachment_type = str(raw.get("type", "") or raw.get("attachment_type", "") or "").strip().lower()
    text = str(raw.get("text", "") or raw.get("extracted_text", "") or "")
    export_mime_type = str(raw.get("export_mime_type", "") or raw.get("exportMimeType", "") or "").strip().lower()
    blockers: list[str] = []
    support_state = "supported"
    extraction_status = "pending_extraction"
    if text.strip():
        extraction_status = "extractable_text_available"
    elif mime_type in TEXT_MIME_TYPES:
        extraction_status = "pending_extraction"
    elif mime_type in SUPPORTED_FILE_MIME_TYPES:
        extraction_status = "pending_extraction"
    elif mime_type == GOOGLE_DOC_MIME_TYPE or attachment_type in {"google_doc", "drive_file"}:
        if export_mime_type:
            extraction_status = "pending_export"
        else:
            support_state = "requires_drive_scope"
            extraction_status = "blocked"
            blockers.append("requires_drive_scope")
    elif mime_type in UNSUPPORTED_GOOGLE_MIME_TYPES:
        support_state = "unsupported"
        extraction_status = "blocked"
        blockers.append(UNSUPPORTED_GOOGLE_MIME_TYPES[mime_type])
    elif mime_type.startswith("image/") or attachment_type == "image":
        support_state = "needs_manual_review"
        extraction_status = "blocked"
        blockers.append("ocr_not_configured")
    elif attachment_type in {"external_link", "link"}:
        support_state = "unsupported"
        extraction_status = "blocked"
        blockers.append("external_link_unsupported")
    elif not mime_type and not attachment_type and not text.strip():
        support_state = "unsupported"
        extraction_status = "blocked"
        blockers.append("empty_attachment")
    else:
        support_state = "unsupported"
        extraction_status = "blocked"
        blockers.append("unsupported_attachment_type")
    file_hash = str(raw.get("file_hash", "") or raw.get("sha256", "") or "")
    if not file_hash and text:
        file_hash = canonical_hash({"text": text})
    return {
        "attachment_id": attachment_id or short_hash({"title": title, "mime_type": mime_type, "text": text}),
        "title": title,
        "mime_type": mime_type,
        "type": attachment_type,
        "support_state": support_state,
        "extraction_status": extraction_status,
        "unsupported_reason": blockers[0] if blockers else "",
        "blockers": blockers,
        "file_hash": file_hash,
        "export_mime_type": export_mime_type,
        "text_hash": canonical_hash({"text": text}) if text.strip() else "",
        "text": text,
    }


def normalize_submission(raw: dict, existing: dict | None = None) -> dict:
    raw = raw or {}
    existing = existing or {}
    submission_id = str(raw.get("submission_id", "") or raw.get("id", "") or raw.get("student_id", "") or "").strip()
    student_id = str(raw.get("student_id", "") or raw.get("user_id", "") or submission_id).strip()
    classroom_state = str(raw.get("classroom_state", "") or raw.get("state", "") or "submitted").strip().lower()
    display_name = str(raw.get("display_name", "") or raw.get("student_name", "") or student_id).strip()
    attachments = [normalize_attachment(item) for item in raw.get("attachments", []) or [] if isinstance(item, dict)]
    direct_text = str(raw.get("text", "") or raw.get("extracted_text", "") or "")
    text_parts = [direct_text] if direct_text.strip() else []
    text_parts.extend(str(item.get("text", "") or "") for item in attachments if str(item.get("text", "") or "").strip())
    extracted_text = "\n\n".join(part.strip() for part in text_parts if part.strip())
    blockers = []
    for attachment in attachments:
        blockers.extend(attachment.get("blockers", []) or [])
    if classroom_state in {"missing", "reclaimed", "returned"}:
        analysis_state = classroom_state
    elif blockers:
        analysis_state = "blocked"
    elif extracted_text.strip():
        text_hash = canonical_hash({"text": extracted_text})
        prior_hash = str(existing.get("text_hash", "") or "")
        prior_analysis = str(existing.get("analysis_state", "") or "")
        analysis_state = "current" if prior_hash == text_hash and prior_analysis in {"current", "analyzed"} else "scheduled"
    else:
        text_hash = ""
        analysis_state = "blocked"
        blockers.append("no_extractable_text")
    text_hash = canonical_hash({"text": extracted_text}) if extracted_text.strip() else ""
    return {
        "submission_id": submission_id or short_hash({"student_id": student_id, "display_name": display_name}),
        "student_id": student_id,
        "display_name": display_name,
        "classroom_state": classroom_state,
        "submitted_at": str(raw.get("submitted_at", "") or ""),
        "updated_at": str(raw.get("updated_at", "") or now_iso()),
        "attachments": attachments,
        "attachment_blockers": sorted(set(blockers)),
        "text_hash": text_hash,
        "analysis_state": analysis_state,
        "scheduled_reason": "new_or_changed_text" if analysis_state == "scheduled" else "",
        "source_revision_id": str(raw.get("source_revision_id", "") or raw.get("draft_id", "") or ""),
    }


def summarize_state(state: dict) -> dict:
    summary = empty_summary()
    submissions = state.get("submissions", {})
    roster = state.get("roster", []) or []
    summary["roster_count"] = len(roster)
    if not isinstance(submissions, dict):
        state["submissions"] = {}
        return summary
    for item in submissions.values():
        classroom_state = str(item.get("classroom_state", "") or "")
        analysis_state = str(item.get("analysis_state", "") or "")
        if classroom_state == "submitted":
            summary["submitted_count"] += 1
        elif classroom_state == "missing":
            summary["missing_count"] += 1
        elif classroom_state == "reclaimed":
            summary["reclaimed_count"] += 1
        elif classroom_state == "returned":
            summary["returned_count"] += 1
        if analysis_state == "scheduled":
            summary["scheduled_analysis_count"] += 1
            summary["ready_for_analysis_count"] += 1
        elif analysis_state == "stale":
            summary["stale_analysis_count"] += 1
        elif analysis_state in {"current", "analyzed"}:
            summary["ready_for_analysis_count"] += 1
        summary["attachment_blocker_count"] += len(item.get("attachment_blockers", []) or [])
    submitted_ids = {str(item.get("student_id", "") or "") for item in submissions.values()}
    roster_ids = {str(item.get("student_id", "") or "") for item in roster}
    summary["missing_count"] += len([sid for sid in roster_ids if sid and sid not in submitted_ids])
    return summary


def require_link(state: dict) -> None:
    if not state.get("classroom_link"):
        raise ClassroomStateError("No Classroom assignment is linked to this project.", code="classroom_link_required")


def reconcile_snapshot(base_dir: Path, root: Path, current_project: dict | None, identity: dict | None, payload: dict) -> dict:
    scope_id = review_store.review_scope_id(current_project)
    state = load_state(base_dir, scope_id, current_project, identity)
    require_link(state)
    roster = normalize_roster(payload.get("roster", []) or [])
    if roster:
        state["roster"] = roster
    existing_submissions = state.get("submissions", {}) if isinstance(state.get("submissions"), dict) else {}
    normalized = {}
    for raw in payload.get("submissions", []) or []:
        if not isinstance(raw, dict):
            continue
        submission = normalize_submission(raw, existing_submissions.get(str(raw.get("submission_id", "") or raw.get("id", "") or raw.get("student_id", ""))))
        normalized[submission["submission_id"]] = submission
    if normalized:
        existing_submissions.update(normalized)
    state["submissions"] = existing_submissions
    stamp = now_iso()
    state["reconciliation"]["latest_reconciliation_at"] = stamp
    state["reconciliation"]["latest_snapshot_hash"] = canonical_hash(payload)
    state["classroom_link"]["latest_reconciliation_at"] = stamp
    state["classroom_link"]["roster_sync_state"] = "reconciled"
    state["classroom_link"]["attachment_support_state"] = "blocked" if any(
        item.get("attachment_blockers") for item in existing_submissions.values()
    ) else "ready"
    state["summary"] = summarize_state(state)
    state["product_state"] = derive_product_state(state, root, current_project, base_dir)
    save_state(base_dir, scope_id, state, root)
    return state_bundle(base_dir, root, current_project, identity)


def record_event_hint(base_dir: Path, root: Path, current_project: dict | None, identity: dict | None, payload: dict) -> dict:
    scope_id = review_store.review_scope_id(current_project)
    state = load_state(base_dir, scope_id, current_project, identity)
    require_link(state)
    event_id = str(payload.get("event_id", "") or payload.get("id", "") or "").strip()
    if not event_id:
        event_id = short_hash(payload)
    known_ids = list(state.get("event_ids", []) or [])
    counters = state.setdefault("event_counters", {"accepted": 0, "duplicate": 0, "ignored": 0})
    if event_id in known_ids:
        counters["duplicate"] = int(counters.get("duplicate", 0) or 0) + 1
        state["reconciliation"]["duplicate_or_out_of_order_count"] = int(
            state["reconciliation"].get("duplicate_or_out_of_order_count", 0) or 0
        ) + 1
        save_state(base_dir, scope_id, state, root)
        return state_bundle(base_dir, root, current_project, identity)
    known_ids.append(event_id)
    state["event_ids"] = known_ids[-500:]
    event = {
        "event_id": event_id,
        "event_type": str(payload.get("event_type", "") or "submission_changed"),
        "received_at": now_iso(),
        "course_id": str(payload.get("course_id", "") or ""),
        "coursework_id": str(payload.get("coursework_id", "") or ""),
        "submission_id": str(payload.get("submission_id", "") or ""),
        "hint_hash": canonical_hash(payload),
    }
    state.setdefault("event_log", []).append(event)
    state["event_log"] = list(state.get("event_log", []) or [])[-200:]
    counters["accepted"] = int(counters.get("accepted", 0) or 0) + 1
    if isinstance(payload.get("submission"), dict):
        existing = state.get("submissions", {}) if isinstance(state.get("submissions"), dict) else {}
        submission = normalize_submission(payload["submission"], existing.get(str(payload.get("submission_id", "") or "")))
        existing[submission["submission_id"]] = submission
        state["submissions"] = existing
    state["reconciliation"]["missed_event_replay_required"] = True
    state["summary"] = summarize_state(state)
    state["product_state"] = derive_product_state(state, root, current_project, base_dir)
    save_state(base_dir, scope_id, state, root)
    return state_bundle(base_dir, root, current_project, identity)


def has_link(base_dir: Path, scope_id: str) -> bool:
    return bool(load_json(state_path(base_dir, scope_id)).get("classroom_link"))


def record_human_revision(
    base_dir: Path,
    root: Path,
    current_project: dict | None,
    identity: dict | None,
    *,
    kind: str,
    payload: dict,
    affected_students: list[str] | None = None,
) -> dict | None:
    scope_id = review_store.review_scope_id(current_project)
    if not has_link(base_dir, scope_id):
        return None
    state = load_state(base_dir, scope_id, current_project, identity)
    revision_id = int(state.get("latest_human_revision_id", 0) or 0) + 1
    revision = {
        "human_revision_id": revision_id,
        "kind": kind,
        "actor": {
            "tenant_id": str((identity or {}).get("tenant_id", "") or state.get("tenant_id", "")),
            "teacher_id": str((identity or {}).get("teacher_id", "") or state.get("teacher_id", "")),
            "role": str((identity or {}).get("role", "") or "teacher"),
        },
        "saved_at": now_iso(),
        "payload_hash": canonical_hash(payload),
        "affected_students": sorted(set(affected_students or [])),
    }
    state.setdefault("human_revisions", []).append(revision)
    state["human_revisions"] = list(state.get("human_revisions", []) or [])[-200:]
    state["latest_human_revision_id"] = revision_id
    audit = state.setdefault("audit", {})
    if int(audit.get("audit_revision_id", 0) or 0) < revision_id:
        audit["status"] = "stale"
        audit["gate_status"] = "not_current"
    finalization = state.setdefault("finalization", {})
    if finalization.get("finalized_by_teacher_at") and state_int(finalization.get("finalized_revision_id", 0)) < revision_id:
        finalization["status"] = "stale"
        finalization["stale_after_revision_id"] = revision_id
    state["product_state"] = derive_product_state(state, root, current_project, base_dir)
    save_state(base_dir, scope_id, state, root)
    return revision


def record_review_revision(
    base_dir: Path,
    root: Path,
    current_project: dict | None,
    identity: dict | None,
    payload: dict,
    *,
    stage: str,
) -> dict | None:
    affected = []
    for key in ("students", "assigned_marks", "feedback_drafts"):
        for row in payload.get(key, []) or []:
            if isinstance(row, dict) and row.get("student_id"):
                affected.append(str(row["student_id"]))
    for row in payload.get("pairwise", []) or []:
        if isinstance(row, dict):
            for key in ("student_id", "student_a_id", "other_student_id", "student_b_id", "preferred_student_id"):
                if row.get(key):
                    affected.append(str(row[key]))
    kind = "review_finalized" if stage == "final" else "review_draft_saved"
    return record_human_revision(base_dir, root, current_project, identity, kind=kind, payload=payload, affected_students=affected)


def complete_background_audit(base_dir: Path, root: Path, current_project: dict | None, identity: dict | None, payload: dict) -> dict:
    scope_id = review_store.review_scope_id(current_project)
    state = load_state(base_dir, scope_id, current_project, identity)
    require_link(state)
    latest_revision = int(state.get("latest_human_revision_id", 0) or 0)
    audit_revision = payload.get("audit_revision_id", latest_revision)
    try:
        audit_revision = int(audit_revision)
    except (TypeError, ValueError):
        raise ClassroomStateError("audit_revision_id must be an integer", code="invalid_audit_revision_id") from None
    state["audit"] = {
        "status": "complete" if audit_revision >= latest_revision else "stale",
        "audit_revision_id": audit_revision,
        "completed_at": now_iso(),
        "gate_status": str(payload.get("gate_status", "") or ("pass" if audit_revision >= latest_revision else "not_current")),
        "blocked_reasons": list(payload.get("blocked_reasons", []) or []),
        "audit_artifact_hash": str(payload.get("audit_artifact_hash", "") or ""),
    }
    state["product_state"] = derive_product_state(state, root, current_project, base_dir)
    save_state(base_dir, scope_id, state, root)
    return state_bundle(base_dir, root, current_project, identity)


def dashboard_exists(root: Path) -> bool:
    dashboard = review_store.load_dashboard(root)
    return bool(isinstance(dashboard, dict) and dashboard.get("students"))


def latest_review_is_final(base_dir: Path, root: Path, current_project: dict | None) -> bool:
    latest = review_store.load_review_bundle(base_dir, root, current_project).get("latest_review", {})
    return bool(latest.get("review_state") == "final" and latest.get("review_id"))


def unresolved_blockers(state: dict) -> list[str]:
    blockers = []
    if not state.get("classroom_link"):
        blockers.append("classroom_link_required")
    policy = state.get("policy", {}) if isinstance(state.get("policy"), dict) else {}
    if policy.get("policy_state") in {"missing_policy", "blocked"}:
        blockers.append(str(policy.get("policy_state")))
    for submission in (state.get("submissions", {}) or {}).values():
        for blocker in submission.get("attachment_blockers", []) or []:
            blockers.append(str(blocker))
    audit = state.get("audit", {}) if isinstance(state.get("audit"), dict) else {}
    blockers.extend(str(item) for item in audit.get("blocked_reasons", []) or [])
    return sorted(set(item for item in blockers if item))


def state_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def latest_revision_id(state: dict) -> int:
    return state_int(state.get("latest_human_revision_id", 0))


def audit_is_current(state: dict) -> bool:
    latest_revision = latest_revision_id(state)
    audit = state.get("audit", {}) if isinstance(state.get("audit"), dict) else {}
    return bool(
        latest_revision
        and state_int(audit.get("audit_revision_id", 0)) >= latest_revision
        and audit.get("gate_status") == "pass"
    )


def finalization_is_current(state: dict, blockers: list[str] | None = None) -> bool:
    finalization = state.get("finalization", {}) if isinstance(state.get("finalization"), dict) else {}
    if not finalization.get("finalized_by_teacher_at"):
        return False
    latest_revision = latest_revision_id(state)
    finalized_revision = state_int(finalization.get("finalized_revision_id", 0))
    return bool(
        latest_revision
        and finalized_revision >= latest_revision
        and audit_is_current(state)
        and not (blockers if blockers is not None else unresolved_blockers(state))
    )


def derive_product_state(state: dict, root: Path, current_project: dict | None = None, base_dir: Path | None = None) -> str:
    blockers = unresolved_blockers(state)
    if not state.get("classroom_link"):
        return "blocked"
    if finalization_is_current(state, blockers):
        return "finalized_by_teacher"
    latest_revision = latest_revision_id(state)
    audit_current = audit_is_current(state)
    review_base_dir = base_dir or (Path(root) / "server")
    if latest_review_is_final(review_base_dir, root, current_project) and audit_current and not blockers:
        return "final_ready"
    if latest_revision and not audit_current:
        return "background_validating"
    if dashboard_exists(root):
        return "review_ready" if not blockers else "blocked"
    summary = state.get("summary", {}) or {}
    if int(summary.get("scheduled_analysis_count", 0) or 0) or int(summary.get("ready_for_analysis_count", 0) or 0):
        return "analyzing_submissions" if not blockers else "blocked"
    if state.get("submissions"):
        return "ingesting" if not blockers else "blocked"
    return "collecting"


def refresh_product_state(base_dir: Path, root: Path, current_project: dict | None, identity: dict | None) -> dict:
    scope_id = review_store.review_scope_id(current_project)
    state = load_state(base_dir, scope_id, current_project, identity)
    state["summary"] = summarize_state(state)
    state["product_state"] = derive_product_state(state, root, current_project, base_dir)
    save_state(base_dir, scope_id, state, root)
    return state


def state_bundle(base_dir: Path, root: Path, current_project: dict | None, identity: dict | None = None) -> dict:
    state = refresh_product_state(base_dir, root, current_project, identity)
    review_bundle = review_store.load_review_bundle(base_dir, root, current_project)
    latest_review = review_bundle.get("latest_review", {})
    latest_delta = review_bundle.get("latest_delta", {})
    launch_gates = {
        "teacher_review_finalized": bool(latest_review.get("review_state") == "final" and latest_review.get("review_id")),
        "full_validation_current": audit_is_current(state),
        "attachment_blockers_clear": not any(
            submission.get("attachment_blockers") for submission in (state.get("submissions", {}) or {}).values()
        ),
        "passback_requires_explicit_action": True,
        "external_write_performed": False,
    }
    payload = public_state(state)
    payload["latest_review"] = {
        "review_state": latest_review.get("review_state", ""),
        "review_id": latest_review.get("review_id", ""),
        "saved_at": latest_review.get("saved_at", ""),
        "student_review_count": len(latest_review.get("students", []) or []),
        "assigned_mark_count": len(latest_review.get("assigned_marks", []) or []),
        "feedback_draft_count": len(latest_review.get("feedback_drafts", []) or []),
    }
    payload["latest_delta_summary"] = latest_delta.get("summary", {}) if isinstance(latest_delta, dict) else {}
    payload["launch_gates"] = launch_gates
    payload["blockers"] = unresolved_blockers(state)
    payload["classroom_error_remedies"] = CLASSROOM_REMEDIES
    materialize_workspace_state(root, payload)
    return payload


def artifact_hashes(root: Path) -> dict:
    paths = {
        "dashboard_data": root / "outputs" / "dashboard_data.json",
        "review_feedback_latest": root / "outputs" / "review_feedback_latest.json",
        "review_delta_latest": root / "outputs" / "review_delta_latest.json",
        "grade_curve": root / "outputs" / "grade_curve.csv",
        "final_order": root / "outputs" / "final_order.csv",
        "classroom_state": root / "outputs" / "classroom_state.json",
    }
    result = {}
    for name, path in paths.items():
        if not path.exists() or not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        result[name] = {"path": str(path), "sha256": digest.hexdigest()}
    return result


def assessment_evidence_packet(base_dir: Path, root: Path, current_project: dict | None, identity: dict | None = None) -> dict:
    state = state_bundle(base_dir, root, current_project, identity)
    review_bundle = review_store.load_review_bundle(base_dir, root, current_project)
    latest_review = review_bundle.get("latest_review", {})
    packet = {
        "schema_version": 1,
        "packet_type": "assessment_evidence_packet",
        "generated_at": now_iso(),
        "scope_id": state.get("scope_id", ""),
        "project": state.get("project", {}),
        "classroom_assignment": state.get("classroom_link", {}),
        "product_state": state.get("product_state", ""),
        "launch_gates": state.get("launch_gates", {}),
        "blockers": state.get("blockers", []),
        "submission_hashes": {
            sid: {
                "student_id": submission.get("student_id", ""),
                "text_hash": submission.get("text_hash", ""),
                "attachment_hashes": [item.get("file_hash", "") for item in submission.get("attachments", []) or []],
            }
            for sid, submission in (state.get("submissions", {}) or {}).items()
        },
        "fast_review": {
            "dashboard_ready": dashboard_exists(root),
            "latest_review_state": latest_review.get("review_state", ""),
            "latest_review_id": latest_review.get("review_id", ""),
            "latest_review_saved_at": latest_review.get("saved_at", ""),
        },
        "full_validation": state.get("audit", {}),
        "teacher_revisions": state.get("human_revisions", []),
        "review_delta": review_bundle.get("latest_delta", {}),
        "feedback_review": {
            "feedback_draft_count": len(latest_review.get("feedback_drafts", []) or []),
            "teacher_review_required": True,
        },
        "export_and_passback": {
            "mode": state.get("passback", {}).get("mode", "no_passback"),
            "actions": state.get("passback", {}).get("actions", []),
            "automatic_publication": False,
        },
        "artifact_hashes": artifact_hashes(root),
    }
    packet["packet_id"] = short_hash(packet)
    write_json(root / "outputs" / "assessment_evidence_packet.json", packet)
    return packet


def finalize_by_teacher(base_dir: Path, root: Path, current_project: dict | None, identity: dict | None = None) -> dict:
    scope_id = review_store.review_scope_id(current_project)
    state = load_state(base_dir, scope_id, current_project, identity)
    require_link(state)
    state["summary"] = summarize_state(state)
    state["product_state"] = derive_product_state(state, root, current_project, base_dir)
    if state["product_state"] != "final_ready":
        raise ClassroomStateError("Classroom result is not final_ready.", code="not_final_ready")
    packet = assessment_evidence_packet(base_dir, root, current_project, identity)
    state = load_state(base_dir, scope_id, current_project, identity)
    state["finalization"] = {
        "finalized_by_teacher_at": now_iso(),
        "finalized_revision_id": latest_revision_id(state),
        "evidence_packet_id": packet["packet_id"],
        "status": "current",
    }
    state["product_state"] = "finalized_by_teacher"
    save_state(base_dir, scope_id, state, root)
    return state_bundle(base_dir, root, current_project, identity)


def passback_preflight(base_dir: Path, root: Path, current_project: dict | None, identity: dict | None, payload: dict) -> dict:
    scope_id = review_store.review_scope_id(current_project)
    state = load_state(base_dir, scope_id, current_project, identity)
    require_link(state)
    mode = normalize_passback_mode(payload.get("mode"))
    if mode == "no_passback":
        raise ClassroomStateError("no_passback has no export action.", code="invalid_passback_mode")
    configured_mode = state.get("passback", {}).get("mode", "no_passback")
    if mode not in allowed_passback_modes(configured_mode):
        raise ClassroomStateError(f"{mode} is not allowed by the linked assignment policy.", code="passback_mode_not_allowed")
    state["summary"] = summarize_state(state)
    state["product_state"] = derive_product_state(state, root, current_project, base_dir)
    review_bundle = review_store.load_review_bundle(base_dir, root, current_project)
    latest_review = review_bundle.get("latest_review", {})
    blockers = unresolved_blockers(state)
    if latest_review.get("review_state") != "final" or not latest_review.get("review_id"):
        blockers.append("finalized_teacher_review_required")
    if not audit_is_current(state):
        blockers.append("full_validation_current_required")
    if state.get("product_state") not in {"final_ready", "finalized_by_teacher"}:
        blockers.append("final_ready_required")
    policy = state.get("policy", {}) if isinstance(state.get("policy"), dict) else {}
    if mode in LIVE_WRITE_MODES:
        if not bool(policy.get("external_writes_enabled", False)):
            blockers.append("external_writes_disabled")
        else:
            if policy.get("classroom_write_adapter_status") != "verified":
                blockers.append("classroom_write_adapter_not_configured")
            if policy.get("oauth_scope_posture") not in {"write_ready", "classroom_write_ready", "connected_with_write_scopes"}:
                blockers.append("insufficient_scope")
            if policy.get("app_approval_status") != "approved":
                blockers.append("admin_approval_required")
    submissions_by_student = {
        str(item.get("student_id", "") or ""): item
        for item in (state.get("submissions", {}) or {}).values()
        if item.get("student_id")
    }
    feedback_by_student = {
        str(item.get("student_id", "") or ""): item
        for item in latest_review.get("feedback_drafts", []) or []
        if isinstance(item, dict) and item.get("student_id")
    }
    rows = []
    for mark in latest_review.get("assigned_marks", []) or []:
        if not isinstance(mark, dict) or not mark.get("student_id"):
            continue
        sid = str(mark["student_id"])
        submission = submissions_by_student.get(sid, {})
        rows.append(
            {
                "student_id": sid,
                "submission_id": submission.get("submission_id", ""),
                "display_name": submission.get("display_name", sid),
                "draft_grade": mark.get("mark") if mode in {"draft_grade", "assigned_grade", "return_submission"} else None,
                "assigned_grade": mark.get("mark") if mode in {"assigned_grade", "return_submission"} else None,
                "return_submission": mode == "return_submission",
                "feedback_ready": bool(feedback_by_student.get(sid)),
                "classroom_state": submission.get("classroom_state", ""),
            }
        )
    preflight = {
        "preflight_id": "",
        "mode": mode,
        "created_at": now_iso(),
        "blocked": bool(blockers),
        "blockers": sorted(set(blockers)),
        "requires_teacher_confirmation": True,
        "external_write_would_occur": mode in LIVE_WRITE_MODES,
        "external_write_performed": False,
        "row_count": len(rows),
        "diff_rows": rows,
        "classroom_semantics": {
            "draft_grade_is_not_assigned_grade": True,
            "return_submission_is_separate": True,
            "rubric_scores_writable": False,
        },
    }
    preflight["preflight_id"] = short_hash(preflight)
    state.setdefault("passback", {}).setdefault("preflights", {})[preflight["preflight_id"]] = preflight
    save_state(base_dir, scope_id, state, root)
    return preflight


def confirm_passback(base_dir: Path, root: Path, current_project: dict | None, identity: dict | None, payload: dict) -> dict:
    scope_id = review_store.review_scope_id(current_project)
    state = load_state(base_dir, scope_id, current_project, identity)
    require_link(state)
    preflight_id = str(payload.get("preflight_id", "") or "").strip()
    preflight = (state.get("passback", {}).get("preflights", {}) or {}).get(preflight_id)
    if not preflight:
        raise ClassroomStateError("Unknown passback preflight.", code="preflight_not_found")
    if preflight.get("blocked"):
        raise ClassroomStateError("Blocked passback preflights cannot be confirmed.", code="preflight_blocked")
    if not bool(payload.get("confirmed", False)):
        raise ClassroomStateError("Teacher confirmation is required.", code="teacher_confirmation_required")
    action = {
        "action_id": short_hash({"preflight_id": preflight_id, "confirmed_at": now_iso()}),
        "preflight_id": preflight_id,
        "mode": preflight.get("mode", ""),
        "confirmed_at": now_iso(),
        "confirmed_by": str((identity or {}).get("teacher_id", "") or state.get("teacher_id", "")),
        "status": "prepared_for_adapter" if preflight.get("external_write_would_occur") else "prepared_for_export",
        "external_write_performed": False,
        "row_count": int(preflight.get("row_count", 0) or 0),
    }
    state.setdefault("passback", {}).setdefault("actions", []).append(action)
    save_state(base_dir, scope_id, state, root)
    assessment_evidence_packet(base_dir, root, current_project, identity)
    return action
