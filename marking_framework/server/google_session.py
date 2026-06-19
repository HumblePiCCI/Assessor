#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Request

from server.runtime_context import identity_token, project_owner


COOKIE_NAME = "assessor_google_session"
SESSION_TTL_DAYS = 30
GOOGLE_TENANT_ID = "google-oauth"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def sessions_root(base_dir: Path) -> Path:
    path = Path(base_dir) / "data" / "google_sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_path(base_dir: Path, session_id: str) -> Path:
    digest = hashlib.sha256(str(session_id or "").encode("utf-8")).hexdigest()
    return sessions_root(base_dir) / f"{digest}.json"


def google_identity(email: str, identity_hash: str) -> dict:
    hash_value = str(identity_hash or "").strip()
    teacher_id = f"google:{hash_value}" if hash_value else ""
    return {
        "tenant_id": GOOGLE_TENANT_ID,
        "teacher_id": teacher_id,
        "role": "teacher",
        "auth_mode": "google_oauth",
        "strict_auth": True,
        "tenant_token": identity_token(GOOGLE_TENANT_ID),
        "teacher_token": identity_token(teacher_id),
        "project_owner_required": True,
        "google_authenticated": True,
        "google_teacher_identity_hash": hash_value,
        "google_teacher_display_email": str(email or ""),
    }


def anonymous_identity() -> dict:
    return {
        "tenant_id": "google-anonymous",
        "teacher_id": "google-anonymous",
        "role": "anonymous",
        "auth_mode": "google_oauth",
        "strict_auth": True,
        "tenant_token": identity_token("google-anonymous"),
        "teacher_token": identity_token("google-anonymous"),
        "project_owner_required": True,
        "google_authenticated": False,
    }


def create_session(base_dir: Path, google_public: dict) -> tuple[str, dict]:
    email = str((google_public or {}).get("teacher_display_email", "") or "")
    identity_hash = str((google_public or {}).get("teacher_identity_hash", "") or "")
    if not identity_hash:
        raise ValueError("Google identity hash is required for project access.")
    session_id = secrets.token_urlsafe(48)
    identity = google_identity(email, identity_hash)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)).isoformat()
    payload = {
        "schema_version": 1,
        "created_at": now_iso(),
        "expires_at": expires_at,
        "teacher_display_email": email,
        "teacher_identity_hash": identity_hash,
        "identity": project_owner(identity),
    }
    path = session_path(base_dir, session_id)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return session_id, identity


def identity_from_session(base_dir: Path, session_id: str) -> dict | None:
    path = session_path(base_dir, session_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    expires_at = parse_iso(str(payload.get("expires_at", "") or ""))
    if expires_at and expires_at < datetime.now(timezone.utc):
        try:
            path.unlink()
        except OSError:
            pass
        return None
    email = str(payload.get("teacher_display_email", "") or "")
    identity_hash = str(payload.get("teacher_identity_hash", "") or "")
    if not identity_hash:
        return None
    return google_identity(email, identity_hash)


def identity_from_request(base_dir: Path, request: Request | None) -> dict | None:
    if request is None:
        return None
    cookies = getattr(request, "cookies", {}) or {}
    return identity_from_session(base_dir, cookies.get(COOKIE_NAME, ""))


def clear_session(base_dir: Path, request: Request | None) -> bool:
    if request is None:
        return False
    session_id = request.cookies.get(COOKIE_NAME, "")
    if not session_id:
        return False
    path = session_path(base_dir, session_id)
    existed = path.exists()
    if existed:
        path.unlink()
    return existed


def cookie_secure(request: Request | None) -> bool:
    if request is None:
        return False
    forwarded = str(request.headers.get("x-forwarded-proto", "") or "").lower()
    return forwarded == "https" or str(request.url.scheme).lower() == "https"
