#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi import HTTPException, Request


DEFAULT_TEACHER_HEADER = "x-teacher-id"
DEFAULT_TENANT_HEADER = "x-tenant-id"
DEFAULT_ROLE_HEADER = "x-teacher-role"
DEFAULT_RUNTIME_MODE = "development"
DEFAULT_LOCAL_TENANT = "local-dev-tenant"
DEFAULT_LOCAL_TEACHER = "local-dev-teacher"


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _production_contract(root: Path) -> dict:
    accuracy = load_json(root / "config" / "accuracy_gate.json")
    sota = load_json(root / "config" / "sota_gate.json")
    contract = {}
    if isinstance(accuracy.get("production_contract"), dict):
        contract.update(accuracy["production_contract"])
    if isinstance(sota.get("production_contract"), dict):
        merged = dict(contract)
        merged.update(sota["production_contract"])
        contract = merged
    return contract


def runtime_mode() -> str:
    value = str(os.environ.get("MARKING_RUNTIME_MODE", DEFAULT_RUNTIME_MODE) or DEFAULT_RUNTIME_MODE).strip().lower()
    return value or DEFAULT_RUNTIME_MODE


def strict_auth_enabled(root: Path) -> bool:
    override = str(os.environ.get("MARKING_STRICT_AUTH", "") or "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    return runtime_mode() in {"staging", "production"}


def auth_headers(root: Path) -> dict:
    contract = _production_contract(root)
    auth = contract.get("auth", {}) if isinstance(contract.get("auth"), dict) else {}
    return {
        "teacher": str(auth.get("teacher_header", DEFAULT_TEACHER_HEADER) or DEFAULT_TEACHER_HEADER).strip().lower(),
        "tenant": str(auth.get("tenant_header", DEFAULT_TENANT_HEADER) or DEFAULT_TENANT_HEADER).strip().lower(),
        "role": str(auth.get("role_header", DEFAULT_ROLE_HEADER) or DEFAULT_ROLE_HEADER).strip().lower(),
    }


def launch_contract(root: Path) -> dict:
    contract = _production_contract(root)
    auth = contract.get("auth", {}) if isinstance(contract.get("auth"), dict) else {}
    retention = contract.get("retention", {}) if isinstance(contract.get("retention"), dict) else {}
    observability = contract.get("observability", {}) if isinstance(contract.get("observability"), dict) else {}
    launch = contract.get("launch", {}) if isinstance(contract.get("launch"), dict) else {}
    privacy = contract.get("privacy", {}) if isinstance(contract.get("privacy"), dict) else {}
    rollback = contract.get("rollback", {}) if isinstance(contract.get("rollback"), dict) else {}
    incident = contract.get("incident", {}) if isinstance(contract.get("incident"), dict) else {}
    return {
        "auth": {
            "required_mode": str(auth.get("required_mode", "strict") or "strict"),
            "teacher_header": str(auth.get("teacher_header", DEFAULT_TEACHER_HEADER) or DEFAULT_TEACHER_HEADER),
            "tenant_header": str(auth.get("tenant_header", DEFAULT_TENANT_HEADER) or DEFAULT_TENANT_HEADER),
            "role_header": str(auth.get("role_header", DEFAULT_ROLE_HEADER) or DEFAULT_ROLE_HEADER),
            "project_owner_required": bool(auth.get("project_owner_required", True)),
        },
        "retention": {
            "job_days": int(retention.get("job_days", 14) or 14),
            "artifact_days": int(retention.get("artifact_days", 30) or 30),
            "workspace_days": int(retention.get("workspace_days", 7) or 7),
        },
        "observability": {
            "max_queue_depth_warning": int(observability.get("max_queue_depth_warning", 5) or 5),
            "max_p95_job_latency_seconds": float(observability.get("max_p95_job_latency_seconds", 3600.0) or 3600.0),
        },
        "launch": {
            "required_publish_profile": str(launch.get("required_publish_profile", "release") or "release"),
            "required_sota_profile": str(launch.get("required_sota_profile", "release") or "release"),
            "required_benchmark_dataset_count": int(launch.get("required_benchmark_dataset_count", 3) or 3),
            "required_calibration_freshness_hours": float(launch.get("required_calibration_freshness_hours", 168.0) or 168.0),
            "required_privacy_posture": str(launch.get("required_privacy_posture", "governed_finalized_anonymized") or "governed_finalized_anonymized"),
        },
        "privacy": {
            "required_posture": str(privacy.get("required_posture", "governed_finalized_anonymized") or "governed_finalized_anonymized"),
            "aggregate_feedback_policy": str(privacy.get("aggregate_feedback_policy", "opt_in_or_policy_compliant") or "opt_in_or_policy_compliant"),
            "delete_tombstone_days": int(privacy.get("delete_tombstone_days", 365) or 365),
        },
        "rollback": {
            "max_release_age_hours": float(rollback.get("max_release_age_hours", 168.0) or 168.0),
            "require_manifest_hash": bool(rollback.get("require_manifest_hash", True)),
            "require_git_sha": bool(rollback.get("require_git_sha", True)),
            "invalidate_cache_on_rollback": bool(rollback.get("invalidate_cache_on_rollback", True)),
        },
        "incident": {
            "require_runbook": bool(incident.get("require_runbook", True)),
            "require_gate_summary": bool(incident.get("require_gate_summary", True)),
            "max_recent_gate_failures": int(incident.get("max_recent_gate_failures", 5) or 5),
        },
    }


def identity_token(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def local_identity(root: Path) -> dict:
    return {
        "tenant_id": DEFAULT_LOCAL_TENANT,
        "teacher_id": DEFAULT_LOCAL_TEACHER,
        "role": "admin",
        "auth_mode": "development",
        "strict_auth": False,
        "tenant_token": identity_token(DEFAULT_LOCAL_TENANT),
        "teacher_token": identity_token(DEFAULT_LOCAL_TEACHER),
        "project_owner_required": False,
        "headers": auth_headers(root),
    }


def resolve_request_identity(request: Request | None, root: Path) -> dict:
    headers = auth_headers(root)
    strict = strict_auth_enabled(root)
    if request is None:
        identity = local_identity(root)
        identity["strict_auth"] = strict
        identity["auth_mode"] = runtime_mode()
        identity["project_owner_required"] = strict
        return identity

    if not strict:
        teacher = str(request.headers.get(headers["teacher"], "") or "").strip() or DEFAULT_LOCAL_TEACHER
        tenant = str(request.headers.get(headers["tenant"], "") or "").strip() or DEFAULT_LOCAL_TENANT
        role = str(request.headers.get(headers["role"], "") or "").strip().lower() or ("admin" if teacher == DEFAULT_LOCAL_TEACHER else "teacher")
    else:
        teacher = str(request.headers.get(headers["teacher"], "") or "").strip()
        tenant = str(request.headers.get(headers["tenant"], "") or "").strip()
        role = str(request.headers.get(headers["role"], "") or "teacher").strip().lower()
        if not teacher or not tenant:
            raise HTTPException(
                status_code=401,
                detail=f"Missing production identity headers: {headers['teacher']} and {headers['tenant']}",
            )
    return {
        "tenant_id": tenant,
        "teacher_id": teacher,
        "role": role or "teacher",
        "auth_mode": runtime_mode(),
        "strict_auth": strict,
        "tenant_token": identity_token(tenant),
        "teacher_token": identity_token(teacher),
        "project_owner_required": strict,
        "headers": headers,
    }


def identity_can_access(owner: dict | None, identity: dict | None) -> bool:
    if not owner:
        return True
    if not identity:
        return False
    owner_tenant = str(owner.get("tenant_id", "") or "").strip()
    owner_teacher = str(owner.get("teacher_id", "") or "").strip()
    if not owner_tenant and not owner_teacher:
        return True
    if str(identity.get("tenant_id", "") or "").strip() != owner_tenant:
        return False
    if str(identity.get("role", "") or "").strip().lower() == "admin":
        return True
    return str(identity.get("teacher_id", "") or "").strip() == owner_teacher


def require_admin(identity: dict) -> None:
    if str(identity.get("role", "") or "").strip().lower() == "admin":
        return
    raise HTTPException(status_code=403, detail="Admin role required")


def project_owner(identity: dict) -> dict:
    return {
        "tenant_id": str(identity.get("tenant_id", "") or ""),
        "teacher_id": str(identity.get("teacher_id", "") or ""),
        "role": str(identity.get("role", "") or "teacher"),
        "tenant_token": str(identity.get("tenant_token", "") or ""),
        "teacher_token": str(identity.get("teacher_token", "") or ""),
    }
