#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import csv
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server import review_store


SCHEMA_VERSION = 2
PASSBACK_ORDER = ["no_passback", "csv_export", "draft_grade", "assigned_grade", "return_submission"]
PASSBACK_MODES = set(PASSBACK_ORDER)
LIVE_WRITE_MODES = {"draft_grade", "assigned_grade", "return_submission"}
CLASSROOM_IMPORT_DIRNAME = "classroom_import"
CLASSROOM_IMPORT_MANIFEST = "classroom_import_manifest.json"
CLASSROOM_IMPORT_READY_ERROR = "No current Classroom imports are ready to assess. Resolve sync blockers and resync."
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
    "drive_api_disabled": "Ask the Google Workspace admin to enable the Google Drive API for this OAuth project.",
    "admin_approval_required": "Ask the Google Workspace admin to approve this OAuth app and its read scopes for the pilot teacher.",
    "admin_blocked_app": "Ask the Google Workspace admin to approve the app for the teacher, course, or pilot cohort.",
    "classroom_write_adapter_not_configured": "Keep using CSV export until a verified Classroom write adapter is configured.",
    "full_validation_current_required": "Run background validation against the latest teacher revision before export or passback.",
    "missing_oauth_grant": "Reconnect Google so the app can refresh the teacher's Classroom grant.",
    "oauth_token_expired": "Reconnect Google Classroom; the stored grant could not be used for a live read.",
    "refresh_failed_reconnect_required": "Reconnect Google Classroom; the refresh token was rejected or revoked.",
    "insufficient_scope": "Reconnect with the Classroom and Drive scopes required by the selected workflow.",
    "requires_drive_scope": "Reconnect Google with Drive read access so the app can export or download the selected attachment.",
    "permission_denied": "Confirm the teacher account still has access to this course, assignment, roster, submission, and attachment.",
    "teacher_removed_from_course": "Have a course teacher or admin restore access before retrying reconciliation.",
    "course_archived": "Restore or duplicate the course before linking it to a live assessment run.",
    "resource_not_found": "Refresh the course-work list and relink the assignment.",
    "quota_exhausted": "Retry after quota reset or move the job to the operator retry queue.",
    "google_api_unavailable": "Retry after the Google API outage clears; no stale or partial read was imported.",
    "forms_unsupported": "Ask the student to submit the essay as a Google Doc, DOCX, PDF, text, Markdown, HTML, or RTF attachment.",
    "slides_unsupported": "Ask the student to submit the essay in a supported document format, not Slides.",
    "sheets_unsupported": "Ask the student to submit prose work in a supported document format, not Sheets.",
    "drawing_unsupported": "Ask the student to submit prose work in a supported document format, not Drawings.",
    "ocr_not_configured": "Image-only submissions need manual handling; OCR is not enabled in this slice.",
    "external_link_unsupported": "Ask the student to attach the work directly rather than linking an external site.",
    "youtube_unsupported": "Ask the student to submit written work as an attached document; YouTube attachments are not graded.",
    "partial_unsupported_attachments": "This slice blocks mixed supported/unsupported submissions; resolve or remove unsupported attachments before grading.",
    "file_too_large": "Export or download a smaller text-bearing document, then resync.",
    "no_extractable_text": "Open the attachment and confirm it contains readable text, then resync.",
    "empty_attachment": "Ask the student to resubmit a non-empty document, then resync.",
    "zero_imports_no_supported_submissions": "No supported written submissions were imported. Resolve blockers or choose another written assignment.",
    "no_current_classroom_imports": "Resolve Classroom sync blockers and resync before running assessment.",
    "evidence_packet_required": "Generate the evidence packet before confirming CSV export.",
    "external_writes_disabled": "Use CSV export for this slice; live Classroom writes are deliberately disabled.",
    "preflight_stale_rebuild_required": "Review or validation changed after this preflight. Rebuild CSV preflight before export.",
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
        "sync_history": [],
        "google_auth": {
            "configured": False,
            "connected": False,
            "expired": False,
            "expiring": False,
            "reconnect_required": False,
            "granted_scopes": [],
            "missing_scopes": [],
            "expires_at": "",
            "teacher_display_email": "",
            "teacher_identity_hash": "",
            "remediation": "",
        },
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
        "imported_count": 0,
        "blocked_count": 0,
        "platform_error_count": 0,
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
    merged.setdefault("sync_history", [])
    merged.setdefault("google_auth", {})
    merged["google_auth"].setdefault("connected", False)
    merged["google_auth"].setdefault("configured", False)
    merged["google_auth"].setdefault("expired", False)
    merged["google_auth"].setdefault("expiring", False)
    merged["google_auth"].setdefault("reconnect_required", False)
    merged["google_auth"].setdefault("granted_scopes", [])
    merged["google_auth"].setdefault("missing_scopes", [])
    merged["google_auth"].setdefault("expires_at", "")
    merged["google_auth"].setdefault("teacher_display_email", "")
    merged["google_auth"].setdefault("teacher_identity_hash", "")
    merged["google_auth"].setdefault("remediation", "")
    merged.setdefault("platform_errors", [])
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
    payload = json.loads(json.dumps(state, ensure_ascii=True))
    payload["event_ids"] = list(payload.get("event_ids", [])[-20:])
    submissions = payload.get("submissions", {})
    if isinstance(submissions, dict):
        for submission in submissions.values():
            if not isinstance(submission, dict):
                continue
            submission.pop("extracted_text", None)
            for attachment in submission.get("attachments", []) or []:
                if isinstance(attachment, dict):
                    attachment.pop("text", None)
    auth = payload.get("google_auth", {}) if isinstance(payload.get("google_auth"), dict) else {}
    payload["google_auth"] = {
        "configured": bool(auth.get("configured", False)),
        "connected": bool(auth.get("connected", False)),
        "expired": bool(auth.get("expired", False)),
        "expiring": bool(auth.get("expiring", False)),
        "reconnect_required": bool(auth.get("reconnect_required", False)),
        "granted_scopes": list(auth.get("granted_scopes", []) or []),
        "missing_scopes": list(auth.get("missing_scopes", []) or []),
        "expires_at": str(auth.get("expires_at", "") or ""),
        "teacher_display_email": str(auth.get("teacher_display_email", "") or ""),
        "teacher_identity_hash": str(auth.get("teacher_identity_hash", "") or ""),
        "remediation": str(auth.get("remediation", "") or ""),
    }
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
    google_integration_path = str(payload.get("google_integration_path", "") or payload.get("adapter", "") or "fixture_local").strip()
    if google_integration_path not in {"fixture_local", "live_google"}:
        google_integration_path = "fixture_local"
    return {
        "tenant_id": str((identity or {}).get("tenant_id", "") or ""),
        "teacher_id": str((identity or {}).get("teacher_id", "") or ""),
        "course_id": course_id,
        "course_name": course_name,
        "coursework_id": coursework_id,
        "coursework_title": coursework_title,
        "google_course_state": str(payload.get("google_course_state", "") or payload.get("course_state", "") or ""),
        "coursework_state": str(payload.get("coursework_state", "") or ""),
        "selected_project_id": project_ref(current_project)["id"],
        "selected_rubric_source": str(payload.get("selected_rubric_source", "") or "project_rubric"),
        "google_integration_path": google_integration_path,
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
    provided_blockers = [str(item) for item in raw.get("blockers", []) or [] if str(item).strip()]
    if provided_blockers:
        blockers.extend(provided_blockers)
        support_state = str(raw.get("support_state", "") or "unsupported")
        extraction_status = str(raw.get("extraction_status", "") or "blocked")
    elif text.strip():
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
        "source_file_id_hash": str(raw.get("source_file_id_hash", "") or ""),
        "source_revision_id": str(raw.get("source_revision_id", "") or ""),
        "source_modified_at": str(raw.get("source_modified_at", "") or raw.get("modifiedTime", "") or ""),
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
    if blockers and extracted_text.strip():
        blockers.append("partial_unsupported_attachments")
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
        "google_submission_state": str(raw.get("google_submission_state", "") or raw.get("state", "") or ""),
        "submitted_at": str(raw.get("submitted_at", "") or ""),
        "updated_at": str(raw.get("updated_at", "") or now_iso()),
        "attachments": attachments,
        "attachment_blockers": sorted(set(blockers)),
        "text_hash": text_hash,
        "extracted_text": extracted_text,
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
        elif analysis_state == "blocked":
            summary["blocked_count"] += 1
        summary["attachment_blocker_count"] += len(item.get("attachment_blockers", []) or [])
    submitted_ids = {str(item.get("student_id", "") or "") for item in submissions.values()}
    roster_ids = {str(item.get("student_id", "") or "") for item in roster}
    summary["missing_count"] += len([sid for sid in roster_ids if sid and sid not in submitted_ids])
    latest_sync = (state.get("sync_history", []) or [])[-1] if state.get("sync_history") else {}
    if isinstance(latest_sync, dict):
        summary["imported_count"] = int(latest_sync.get("imported_count", 0) or 0)
        summary["blocked_count"] = max(summary["blocked_count"], int(latest_sync.get("blocked_count", latest_sync.get("blocker_count", 0)) or 0))
    summary["platform_error_count"] = len(state.get("platform_errors", []) or [])
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
    if payload.get("authoritative", False):
        existing_submissions = normalized
    elif normalized:
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


def safe_submission_filename(submission: dict) -> str:
    token = str(submission.get("student_id", "") or submission.get("submission_id", "") or "submission").strip()
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in token)
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return f"{cleaned or short_hash(submission)}.txt"


def classroom_import_dir(root: Path) -> Path:
    return Path(root) / "inputs" / "submissions" / CLASSROOM_IMPORT_DIRNAME


def classroom_import_manifest_path(root: Path) -> Path:
    return Path(root) / "inputs" / CLASSROOM_IMPORT_MANIFEST


def root_relative(root: Path, path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except Exception:
        return str(path)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_classroom_import_manifest(root: Path) -> dict:
    manifest = load_json(classroom_import_manifest_path(root))
    return manifest if manifest.get("source") == "google_classroom_read_only_sync" else {}


def _previous_classroom_import_paths(root: Path) -> list[Path]:
    inputs = Path(root) / "inputs"
    submissions = inputs / "submissions"
    paths: list[Path] = []
    for source in (load_classroom_import_manifest(root), load_json(inputs / "class_metadata.json")):
        for row in source.get("files", []) or source.get("imported_submissions", []) or []:
            if not isinstance(row, dict):
                continue
            rel_path = str(row.get("path", "") or "").strip()
            if not rel_path:
                continue
            candidate = (Path(root) / rel_path).resolve()
            try:
                candidate.relative_to(submissions.resolve())
            except Exception:
                continue
            paths.append(candidate)
    return sorted(set(paths))


def _clear_previous_classroom_imports(root: Path) -> None:
    manifest_path = classroom_import_manifest_path(root)
    if manifest_path.exists():
        manifest_path.unlink()
    import_dir = classroom_import_dir(root)
    if import_dir.exists():
        shutil.rmtree(import_dir)
    for path in _previous_classroom_import_paths(root):
        if path.exists() and path.is_file():
            path.unlink()


def _current_import_files_ready(root: Path, manifest: dict) -> bool:
    if not manifest or not bool(manifest.get("current_import_ready", False)):
        return False
    if int(manifest.get("imported_count", 0) or 0) <= 0:
        return False
    if int(manifest.get("platform_error_count", 0) or 0) > 0:
        return False
    import_root = classroom_import_dir(root).resolve()
    files = manifest.get("files", []) or []
    if len(files) != int(manifest.get("imported_count", 0) or 0):
        return False
    for row in files:
        if not isinstance(row, dict):
            return False
        rel_path = str(row.get("path", "") or "").strip()
        if not rel_path:
            return False
        path = (Path(root) / rel_path).resolve()
        try:
            path.relative_to(import_root)
        except Exception:
            return False
        if not path.exists() or not path.is_file():
            return False
        expected = str(row.get("sha256", "") or "")
        if expected and _file_hash(path) != expected:
            return False
    return True


def classroom_imports_ready(root: Path) -> bool:
    return _current_import_files_ready(root, load_classroom_import_manifest(root))


def classroom_imports_run_directory(root: Path) -> Path:
    return classroom_import_dir(root)


def materialize_read_only_submissions(root: Path, state: dict) -> dict:
    inputs = root / "inputs"
    submissions_dir = inputs / "submissions"
    final_import_dir = classroom_import_dir(root)
    submissions_dir.mkdir(parents=True, exist_ok=True)
    imported = []
    blockers = []
    summary = summarize_state(state)
    for submission in (state.get("submissions", {}) or {}).values():
        if not isinstance(submission, dict):
            continue
        submission_blockers = list(submission.get("attachment_blockers", []) or [])
        classroom_state = str(submission.get("classroom_state", "") or "")
        text = str(submission.get("extracted_text", "") or "")
        if classroom_state != "submitted" or submission_blockers or not text.strip():
            blockers.append(
                {
                    "submission_id": submission.get("submission_id", ""),
                    "student_id": submission.get("student_id", ""),
                    "blockers": submission_blockers or ([classroom_state] if classroom_state != "submitted" else ["no_extractable_text"]),
                }
            )
            continue
        filename = safe_submission_filename(submission)
        path = final_import_dir / filename
        imported.append(
            {
                "submission_id": submission.get("submission_id", ""),
                "student_id": submission.get("student_id", ""),
                "path": f"inputs/submissions/{CLASSROOM_IMPORT_DIRNAME}/{filename}",
                "text_hash": submission.get("text_hash", ""),
                "text": text.strip(),
            }
        )
        submission["analysis_state"] = "scheduled"
    if len(imported) == 0:
        zero_import_error = {
            "code": "zero_imports_no_supported_submissions",
            "message": "No supported written submissions were imported from this Classroom assignment.",
        }
        existing_codes = {
            str(item.get("code", "") or "")
            for item in state.get("platform_errors", []) or []
            if isinstance(item, dict)
        }
        if zero_import_error["code"] not in existing_codes:
            state.setdefault("platform_errors", []).append(zero_import_error)
    platform_error_count = len(state.get("platform_errors", []) or [])
    link = state.get("classroom_link", {}) if isinstance(state.get("classroom_link"), dict) else {}
    snapshot_hash = str(state.get("reconciliation", {}).get("latest_snapshot_hash", "") or "")
    sync_id = short_hash(
        {
            "snapshot_hash": snapshot_hash,
            "course_id_hash": short_hash({"course_id": link.get("course_id", "")}),
            "coursework_id_hash": short_hash({"coursework_id": link.get("coursework_id", "")}),
            "files": [{key: row.get(key, "") for key in ("submission_id", "student_id", "path", "text_hash")} for row in imported],
            "blockers": blockers,
            "platform_errors": state.get("platform_errors", []) or [],
        }
    )
    tmp_dir = submissions_dir / f".{CLASSROOM_IMPORT_DIRNAME}_tmp_{sync_id}"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    manifest_files = []
    for row in imported:
        filename = Path(str(row["path"])).name
        tmp_path = tmp_dir / filename
        tmp_path.write_text(str(row.pop("text", "")).strip() + "\n", encoding="utf-8")
        sha256 = _file_hash(tmp_path)
        manifest_files.append({**row, "sha256": sha256})
    metadata = {
        "source": "google_classroom_read_only_sync",
        "generated_at": now_iso(),
        "assignment": {
            "course_id_hash": short_hash({"course_id": link.get("course_id", "")}),
            "coursework_id_hash": short_hash({"coursework_id": link.get("coursework_id", "")}),
            "course_name": str(link.get("course_name", "") or ""),
            "coursework_title": str(link.get("coursework_title", "") or ""),
            "google_course_state": str(link.get("google_course_state", "") or ""),
            "coursework_state": str(link.get("coursework_state", "") or ""),
        },
        "counts": {
            "roster_count": int(summary.get("roster_count", 0) or 0),
            "submitted_count": int(summary.get("submitted_count", 0) or 0),
            "imported_count": len(imported),
            "blocked_count": len(blockers),
            "missing_count": int(summary.get("missing_count", 0) or 0),
            "reclaimed_count": int(summary.get("reclaimed_count", 0) or 0),
            "returned_count": int(summary.get("returned_count", 0) or 0),
            "platform_error_count": platform_error_count,
        },
        "imported_submission_count": len(imported),
        "attachment_blocker_count": len(blockers),
        "adapter": str(state.get("classroom_link", {}).get("google_integration_path", "") or "fixture_local"),
        "sync_history": list(state.get("sync_history", []) or [])[-5:],
        "classroom_import_manifest": f"inputs/{CLASSROOM_IMPORT_MANIFEST}",
        "current_import_ready": bool(len(imported) > 0 and platform_error_count == 0),
        "sync_id": sync_id,
        "snapshot_hash": snapshot_hash,
        "imported_submissions": manifest_files,
        "external_write_performed": False,
    }
    manifest = {
        "schema_version": 1,
        "source": "google_classroom_read_only_sync",
        "generated_at": metadata["generated_at"],
        "sync_id": sync_id,
        "snapshot_hash": snapshot_hash,
        "course_id_hash": metadata["assignment"]["course_id_hash"],
        "coursework_id_hash": metadata["assignment"]["coursework_id_hash"],
        "import_dir": f"inputs/submissions/{CLASSROOM_IMPORT_DIRNAME}",
        "imported_count": len(imported),
        "blocked_count": len(blockers),
        "platform_error_count": platform_error_count,
        "external_write_performed": False,
        "current_import_ready": bool(len(imported) > 0 and platform_error_count == 0),
        "files": manifest_files,
        "text_hashes": {
            str(row.get("submission_id", "") or row.get("student_id", "")): row.get("text_hash", "")
            for row in manifest_files
        },
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    metadata["classroom_import_manifest_hash"] = manifest["manifest_hash"]
    metadata["current_submission_paths"] = [row["path"] for row in manifest_files]
    _clear_previous_classroom_imports(root)
    final_import_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir.replace(final_import_dir)
    write_json(classroom_import_manifest_path(root), manifest)
    write_json(inputs / "class_metadata.json", metadata)
    return {
        "adapter": str(state.get("classroom_link", {}).get("google_integration_path", "") or "fixture_local"),
        "external_write_performed": False,
        "imported_submission_count": len(imported),
        "blocked_submission_count": len(blockers),
        "imported_count": len(imported),
        "blocked_count": len(blockers),
        "roster_count": int(summary.get("roster_count", 0) or 0),
        "submitted_count": int(summary.get("submitted_count", 0) or 0),
        "missing_count": int(summary.get("missing_count", 0) or 0),
        "reclaimed_count": int(summary.get("reclaimed_count", 0) or 0),
        "returned_count": int(summary.get("returned_count", 0) or 0),
        "platform_error_count": platform_error_count,
        "sync_id": sync_id,
        "snapshot_hash": snapshot_hash,
        "manifest_hash": manifest["manifest_hash"],
        "current_import_ready": manifest["current_import_ready"],
        "imported_submissions": manifest_files,
        "blockers": blockers,
    }


def read_only_sync(base_dir: Path, root: Path, current_project: dict | None, identity: dict | None, payload: dict) -> dict:
    scope_id = review_store.review_scope_id(current_project)
    state = load_state(base_dir, scope_id, current_project, identity)
    if not state.get("classroom_link"):
        course = payload.get("course", {}) if isinstance(payload.get("course", {}), dict) else {}
        coursework = payload.get("coursework", {}) if isinstance(payload.get("coursework", {}), dict) else {}
        link_payload = {
            "course_id": payload.get("course_id") or course.get("id") or "fixture-course",
            "course_name": payload.get("course_name") or course.get("name") or "Read-only Classroom pilot",
            "coursework_id": payload.get("coursework_id") or coursework.get("id") or "fixture-coursework",
            "coursework_title": payload.get("coursework_title") or payload.get("assignment_title") or coursework.get("title") or "Imported assignment",
            "passback_mode": payload.get("passback_mode") or "csv_export",
            "google_integration_path": payload.get("adapter") or payload.get("google_integration_path") or "fixture_local",
            "google_course_state": payload.get("google_course_state") or payload.get("course_state") or "",
            "coursework_state": payload.get("coursework_state") or "",
            "policy": payload.get("policy", {}),
        }
        link_assignment(base_dir, root, current_project, identity, link_payload)
    snapshot = {
        "roster": payload.get("roster", []) or [],
        "submissions": payload.get("submissions", []) or [],
        "authoritative": True,
    }
    bundle = reconcile_snapshot(base_dir, root, current_project, identity, snapshot)
    state = load_state(base_dir, scope_id, current_project, identity)
    state["platform_errors"] = [
        item for item in payload.get("platform_errors", []) or [] if isinstance(item, dict) or str(item).strip()
    ]
    if isinstance(payload.get("google_auth"), dict):
        safe_auth = payload["google_auth"]
        state["google_auth"] = {
            "configured": bool(safe_auth.get("configured", False)),
            "connected": bool(safe_auth.get("connected", False)),
            "expired": bool(safe_auth.get("expired", False)),
            "expiring": bool(safe_auth.get("expiring", False)),
            "reconnect_required": bool(safe_auth.get("reconnect_required", False)),
            "granted_scopes": list(safe_auth.get("granted_scopes", []) or []),
            "missing_scopes": list(safe_auth.get("missing_scopes", []) or []),
            "expires_at": str(safe_auth.get("expires_at", "") or ""),
            "teacher_display_email": str(safe_auth.get("teacher_display_email", "") or ""),
            "teacher_identity_hash": str(safe_auth.get("teacher_identity_hash", "") or ""),
            "remediation": str(safe_auth.get("remediation", "") or ""),
        }
    sync = materialize_read_only_submissions(root, state)
    history = {
        "timestamp": now_iso(),
        "adapter": sync.get("adapter", "fixture_local"),
        "snapshot_hash": canonical_hash(snapshot),
        "sync_id": sync.get("sync_id", ""),
        "classroom_import_manifest_hash": sync.get("manifest_hash", ""),
        "current_import_ready": bool(sync.get("current_import_ready", False)),
        "roster_count": int(sync.get("roster_count", len(snapshot.get("roster", []) or [])) or 0),
        "submitted_count": int(sync.get("submitted_count", 0) or 0),
        "submission_count": len(snapshot.get("submissions", []) or []),
        "imported_count": int(sync.get("imported_count", sync.get("imported_submission_count", 0)) or 0),
        "blocked_count": int(sync.get("blocked_count", sync.get("blocked_submission_count", 0)) or 0),
        "blocker_count": int(sync.get("blocked_count", sync.get("blocked_submission_count", 0)) or 0),
        "missing_count": int(sync.get("missing_count", 0) or 0),
        "reclaimed_count": int(sync.get("reclaimed_count", 0) or 0),
        "returned_count": int(sync.get("returned_count", 0) or 0),
        "platform_error_count": int(sync.get("platform_error_count", len(state.get("platform_errors", []) or [])) or 0),
        "external_write_performed": False,
    }
    state.setdefault("sync_history", []).append(history)
    state["sync_history"] = list(state.get("sync_history", []) or [])[-25:]
    metadata_path = root / "inputs" / "class_metadata.json"
    metadata = load_json(metadata_path)
    if metadata:
        metadata["sync_history"] = list(state.get("sync_history", []) or [])[-5:]
        metadata["latest_sync"] = history
        if isinstance(metadata.get("counts"), dict):
            metadata["counts"].update(
                {
                    "imported_count": history["imported_count"],
                    "blocked_count": history["blocked_count"],
                    "platform_error_count": history["platform_error_count"],
                }
            )
        write_json(metadata_path, metadata)
    state["summary"] = summarize_state(state)
    state["product_state"] = derive_product_state(state, root, current_project, base_dir)
    save_state(base_dir, scope_id, state, root)
    bundle = state_bundle(base_dir, root, current_project, identity)
    bundle["read_sync"] = sync
    return bundle


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
    for error in state.get("platform_errors", []) or []:
        if isinstance(error, dict):
            blockers.append(str(error.get("code", "") or ""))
        else:
            blockers.append(str(error))
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
            "export_artifacts": [
                action.get("export_artifact", {})
                for action in state.get("passback", {}).get("actions", [])
                if isinstance(action, dict) and action.get("export_artifact")
            ],
            "automatic_publication": False,
        },
        "artifact_hashes": artifact_hashes(root),
    }
    stable_packet = json.loads(json.dumps(packet, ensure_ascii=True))
    stable_packet.pop("generated_at", None)
    if isinstance(stable_packet.get("artifact_hashes"), dict):
        stable_packet["artifact_hashes"].pop("classroom_state", None)
    packet["packet_id"] = short_hash(stable_packet)
    write_json(root / "outputs" / "assessment_evidence_packet.json", packet)
    return packet


CSV_EXPORT_FIELDS = [
    "student_display_name",
    "classroom_student_id",
    "safe_student_id",
    "submission_id",
    "assigned_mark",
    "feedback_star1",
    "feedback_star2",
    "feedback_wish",
    "final_review_timestamp",
    "project_id",
    "project_name",
    "course_id",
    "course_name",
    "coursework_id",
    "coursework_title",
]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv_export(base_dir: Path, scope_id: str, action_id: str, preflight: dict) -> dict:
    export_dir = review_store.exports_dir(base_dir, scope_id)
    path = export_dir / f"classroom_csv_export_{action_id}.csv"
    rows = sorted(
        [row for row in preflight.get("diff_rows", []) or [] if isinstance(row, dict)],
        key=lambda row: (str(row.get("student_display_name", "") or row.get("display_name", "") or "").lower(), str(row.get("safe_student_id", "") or row.get("student_id", ""))),
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_EXPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CSV_EXPORT_FIELDS})
    return {
        "path": str(path),
        "filename": path.name,
        "sha256": file_sha256(path),
        "row_count": len(rows),
    }


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


def passback_rows(state: dict, latest_review: dict, mode: str) -> list[dict]:
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
    project = state.get("project", {}) if isinstance(state.get("project"), dict) else {}
    link = state.get("classroom_link", {}) if isinstance(state.get("classroom_link"), dict) else {}
    rows = []
    for mark in latest_review.get("assigned_marks", []) or []:
        if not isinstance(mark, dict) or not mark.get("student_id"):
            continue
        sid = str(mark["student_id"])
        submission = submissions_by_student.get(sid, {})
        feedback = feedback_by_student.get(sid, {})
        rows.append(
            {
                "student_id": sid,
                "safe_student_id": sid,
                "classroom_student_id": submission.get("student_id", sid),
                "submission_id": submission.get("submission_id", ""),
                "display_name": submission.get("display_name", sid),
                "student_display_name": submission.get("display_name", sid),
                "assigned_mark": mark.get("mark"),
                "draft_grade": mark.get("mark") if mode in {"draft_grade", "assigned_grade", "return_submission"} else None,
                "assigned_grade": mark.get("mark") if mode in {"assigned_grade", "return_submission"} else None,
                "return_submission": mode == "return_submission",
                "feedback_ready": bool(feedback),
                "feedback_star1": feedback.get("star1", ""),
                "feedback_star2": feedback.get("star2", ""),
                "feedback_wish": feedback.get("wish", ""),
                "final_review_timestamp": latest_review.get("saved_at", ""),
                "project_id": project.get("id", ""),
                "project_name": project.get("name", ""),
                "course_id": link.get("course_id", ""),
                "course_name": link.get("course_name", ""),
                "coursework_id": link.get("coursework_id", ""),
                "coursework_title": link.get("coursework_title", ""),
                "classroom_state": submission.get("classroom_state", ""),
            }
        )
    return rows


def passback_blockers(state: dict, latest_review: dict, mode: str) -> list[str]:
    blockers = unresolved_blockers(state)
    if latest_review.get("review_state") != "final" or not latest_review.get("review_id"):
        blockers.append("finalized_teacher_review_required")
    if not audit_is_current(state):
        blockers.append("full_validation_current_required")
    if state.get("product_state") not in {"final_ready", "finalized_by_teacher"}:
        blockers.append("final_ready_required")
    configured_mode = state.get("passback", {}).get("mode", "no_passback")
    if mode not in allowed_passback_modes(configured_mode):
        blockers.append("passback_mode_not_allowed")
    policy = state.get("policy", {}) if isinstance(state.get("policy"), dict) else {}
    if mode in LIVE_WRITE_MODES:
        blockers.append("external_writes_disabled")
        blockers.append("classroom_write_adapter_not_configured")
        if policy.get("oauth_scope_posture") not in {"write_ready", "classroom_write_ready", "connected_with_write_scopes"}:
            blockers.append("insufficient_scope")
        if policy.get("app_approval_status") != "approved":
            blockers.append("admin_approval_required")
    return sorted(set(blockers))


def latest_final_review_fingerprint(latest_review: dict) -> dict:
    return {
        "review_id": str(latest_review.get("review_id", "") or ""),
        "saved_at": str(latest_review.get("saved_at", "") or ""),
        "review_state": str(latest_review.get("review_state", "") or ""),
        "payload_hash": canonical_hash(latest_review) if latest_review else "",
    }


def latest_sync_fingerprint(root: Path, state: dict) -> dict:
    latest_sync = (state.get("sync_history", []) or [])[-1] if state.get("sync_history") else {}
    manifest = load_classroom_import_manifest(root)
    return {
        "sync_id": str(latest_sync.get("sync_id", "") or manifest.get("sync_id", "") or ""),
        "timestamp": str(latest_sync.get("timestamp", "") or manifest.get("generated_at", "") or ""),
        "snapshot_hash": str(latest_sync.get("snapshot_hash", "") or manifest.get("snapshot_hash", "") or ""),
        "classroom_import_manifest_hash": str(latest_sync.get("classroom_import_manifest_hash", "") or manifest.get("manifest_hash", "") or ""),
        "imported_count": int(latest_sync.get("imported_count", manifest.get("imported_count", 0)) or 0),
        "blocked_count": int(latest_sync.get("blocked_count", manifest.get("blocked_count", 0)) or 0),
        "platform_error_count": int(latest_sync.get("platform_error_count", manifest.get("platform_error_count", 0)) or 0),
        "current_import_ready": bool(latest_sync.get("current_import_ready", manifest.get("current_import_ready", False))),
    }


def stable_artifact_hashes(root: Path) -> dict:
    hashes = artifact_hashes(root)
    hashes.pop("classroom_state", None)
    return hashes


def preflight_freshness_binding(root: Path, state: dict, latest_review: dict, mode: str, rows: list[dict], evidence_packet_id: str, blockers: list[str]) -> dict:
    audit = state.get("audit", {}) if isinstance(state.get("audit"), dict) else {}
    finalization = state.get("finalization", {}) if isinstance(state.get("finalization"), dict) else {}
    return {
        "latest_human_revision_id": latest_revision_id(state),
        "latest_finalized_review": latest_final_review_fingerprint(latest_review),
        "audit": {
            "audit_revision_id": state_int(audit.get("audit_revision_id", 0)),
            "gate_status": str(audit.get("gate_status", "") or ""),
            "status": str(audit.get("status", "") or ""),
            "audit_artifact_hash": str(audit.get("audit_artifact_hash", "") or ""),
            "blocked_reasons": sorted(str(item) for item in audit.get("blocked_reasons", []) or []),
        },
        "finalization": {
            "finalized_revision_id": state_int(finalization.get("finalized_revision_id", 0)),
            "evidence_packet_id": str(finalization.get("evidence_packet_id", "") or ""),
            "status": str(finalization.get("status", "") or ""),
        },
        "latest_classroom_sync": latest_sync_fingerprint(root, state),
        "attachment_blockers": sorted(
            {
                str(blocker)
                for submission in (state.get("submissions", {}) or {}).values()
                for blocker in submission.get("attachment_blockers", []) or []
            }
        ),
        "platform_errors": sorted(
            str(item.get("code", "") or "") if isinstance(item, dict) else str(item)
            for item in state.get("platform_errors", []) or []
        ),
        "blockers": sorted(set(blockers)),
        "evidence_packet_id": str(evidence_packet_id or ""),
        "artifact_hashes": stable_artifact_hashes(root),
        "export_mode": mode,
        "row_count": len(rows),
        "row_hash": canonical_hash(rows),
    }


def preflight_stale_error() -> ClassroomStateError:
    return ClassroomStateError(
        "Review or sync changed after this preflight. Rebuild CSV preflight before export.",
        code="preflight_stale_rebuild_required",
    )


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
    blockers = passback_blockers(state, latest_review, mode)
    evidence_packet_id = ""
    if not blockers:
        try:
            evidence_packet_id = str(assessment_evidence_packet(base_dir, root, current_project, identity).get("packet_id", "") or "")
        except Exception:
            blockers.append("evidence_packet_required")
    rows = passback_rows(state, latest_review, mode)
    freshness = preflight_freshness_binding(root, state, latest_review, mode, rows, evidence_packet_id, blockers)
    preflight = {
        "preflight_id": "",
        "mode": mode,
        "created_at": now_iso(),
        "blocked": bool(blockers),
        "blockers": sorted(set(blockers)),
        "requires_teacher_confirmation": True,
        "external_write_would_occur": mode in LIVE_WRITE_MODES,
        "external_write_performed": False,
        "evidence_packet_id": evidence_packet_id,
        "row_count": len(rows),
        "row_hash": freshness["row_hash"],
        "freshness_hash": canonical_hash(freshness),
        "freshness": freshness,
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
    if preflight.get("mode") in LIVE_WRITE_MODES or preflight.get("external_write_would_occur"):
        raise ClassroomStateError("Live Classroom writes are unavailable in this local pilot slice.", code="external_writes_disabled")
    mode = normalize_passback_mode(preflight.get("mode"))
    state["summary"] = summarize_state(state)
    state["product_state"] = derive_product_state(state, root, current_project, base_dir)
    review_bundle = review_store.load_review_bundle(base_dir, root, current_project)
    latest_review = review_bundle.get("latest_review", {})
    blockers = passback_blockers(state, latest_review, mode)
    if blockers:
        raise preflight_stale_error()
    try:
        evidence_packet_id = str(assessment_evidence_packet(base_dir, root, current_project, identity).get("packet_id", "") or "")
    except Exception as exc:
        raise preflight_stale_error() from exc
    rows = passback_rows(state, latest_review, mode)
    freshness = preflight_freshness_binding(root, state, latest_review, mode, rows, evidence_packet_id, blockers)
    if preflight.get("freshness_hash") != canonical_hash(freshness) or preflight.get("freshness") != freshness:
        raise preflight_stale_error()
    action = {
        "action_id": short_hash({"preflight_id": preflight_id, "confirmed_at": now_iso()}),
        "preflight_id": preflight_id,
        "mode": mode,
        "confirmed_at": now_iso(),
        "confirmed_by": str((identity or {}).get("teacher_id", "") or state.get("teacher_id", "")),
        "status": "prepared_for_adapter" if preflight.get("external_write_would_occur") else "prepared_for_export",
        "external_write_performed": False,
        "row_count": int(preflight.get("row_count", 0) or 0),
    }
    if preflight.get("mode") == "csv_export":
        artifact = write_csv_export(base_dir, scope_id, action["action_id"], preflight)
        action["export_artifact"] = artifact
        action["download_url"] = f"/projects/classroom/passback/exports/{action['action_id']}"
    state.setdefault("passback", {}).setdefault("actions", []).append(action)
    save_state(base_dir, scope_id, state, root)
    assessment_evidence_packet(base_dir, root, current_project, identity)
    return action
