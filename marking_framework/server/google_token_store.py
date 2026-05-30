#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from server.runtime_context import identity_token, strict_auth_enabled


STATE_TTL_MINUTES = 15
TOKEN_STORE_SCHEMA_VERSION = 1


class GoogleTokenStoreError(ValueError):
    def __init__(self, message: str, *, code: str = "google_token_store_error"):
        super().__init__(message)
        self.code = code


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def canonical_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _token(value: str, fallback: str) -> str:
    raw = str(value or fallback or "").strip() or fallback
    return identity_token(raw)


def _scope_key(project: dict | None, scope_id: str | None = None) -> str:
    if scope_id:
        return str(scope_id).strip() or "workspace"
    project = project or {}
    return str(project.get("scope_key") or project.get("id") or "workspace").strip() or "workspace"


def _teacher_hash(email: str | None, teacher_id: str | None) -> str:
    value = str(email or teacher_id or "").strip().lower()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24] if value else ""


def _safe_redirect_after(value: str) -> str:
    value = str(value or "").strip()
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


class GoogleTokenStore:
    """Private local OAuth state/token store.

    This intentionally lives under server/data, which is ignored by git. The
    keyed envelope is a local-development guard, not a district secret-store
    replacement; strict production launch still needs an approved secret store.
    """

    def __init__(self, base_dir: Path, *, encryption_key: str | None = None, strict_mode: bool | None = None):
        self.base_dir = Path(base_dir)
        self.root = self.base_dir / "data" / "google_oauth"
        self.root.mkdir(parents=True, exist_ok=True)
        self.encryption_key = encryption_key if encryption_key is not None else os.environ.get("GOOGLE_TOKEN_ENCRYPTION_KEY", "")
        self.strict_mode = strict_auth_enabled(self.base_dir.parent) if strict_mode is None else bool(strict_mode)

    def _identity_dir(self, identity: dict, project: dict | None = None, scope_id: str | None = None) -> Path:
        tenant = _token(str(identity.get("tenant_id", "") or ""), "local-dev-tenant")
        teacher = _token(str(identity.get("teacher_id", "") or ""), "local-dev-teacher")
        project_token = _token(_scope_key(project, scope_id), "workspace")
        path = self.root / tenant / teacher / project_token
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _states_dir(self) -> Path:
        path = self.root / "states"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _token_path(self, identity: dict, project: dict | None = None, scope_id: str | None = None) -> Path:
        return self._identity_dir(identity, project, scope_id) / "token.json"

    def _envelope_key(self) -> bytes:
        return hashlib.sha256(str(self.encryption_key or "").encode("utf-8")).digest()

    def _seal(self, payload: dict) -> dict:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        if not self.encryption_key:
            if self.strict_mode:
                raise GoogleTokenStoreError(
                    "GOOGLE_TOKEN_ENCRYPTION_KEY is required before storing Google OAuth tokens in strict runtime mode.",
                    code="token_encryption_required",
                )
            return {
                "encoding": "local_dev_plaintext",
                "payload": payload,
                "payload_hash": canonical_hash(payload),
            }
        key = self._envelope_key()
        nonce = secrets.token_bytes(16)
        stream = hashlib.sha256(key + nonce).digest()
        sealed = bytes(byte ^ stream[idx % len(stream)] for idx, byte in enumerate(raw))
        mac = hmac.new(key, nonce + sealed, hashlib.sha256).hexdigest()
        return {
            "encoding": "local_key_envelope_v1",
            "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
            "payload": base64.urlsafe_b64encode(sealed).decode("ascii"),
            "mac": mac,
            "payload_hash": hashlib.sha256(raw).hexdigest(),
        }

    def _open(self, envelope: dict) -> dict:
        encoding = str(envelope.get("encoding", "") or "")
        if encoding == "local_dev_plaintext":
            payload = envelope.get("payload", {})
            return payload if isinstance(payload, dict) else {}
        if encoding != "local_key_envelope_v1":
            return {}
        if not self.encryption_key:
            return {}
        key = self._envelope_key()
        try:
            nonce = base64.urlsafe_b64decode(str(envelope.get("nonce", "") or "").encode("ascii"))
            sealed = base64.urlsafe_b64decode(str(envelope.get("payload", "") or "").encode("ascii"))
        except Exception:
            return {}
        expected = hmac.new(key, nonce + sealed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, str(envelope.get("mac", "") or "")):
            return {}
        stream = hashlib.sha256(key + nonce).digest()
        raw = bytes(byte ^ stream[idx % len(stream)] for idx, byte in enumerate(sealed))
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def create_state(
        self,
        identity: dict,
        project: dict | None,
        *,
        scopes: list[str],
        redirect_after: str = "",
    ) -> dict:
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(24)
        code_verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES)).isoformat()
        payload = {
            "schema_version": TOKEN_STORE_SCHEMA_VERSION,
            "state": state,
            "nonce": nonce,
            "code_verifier": code_verifier,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "tenant_id": str(identity.get("tenant_id", "") or ""),
            "teacher_id": str(identity.get("teacher_id", "") or ""),
            "project_scope": _scope_key(project),
            "project": {
                "id": str((project or {}).get("id", "") or "workspace"),
                "name": str((project or {}).get("name", "") or "Workspace"),
                "scope_key": _scope_key(project),
            },
            "scopes": sorted(set(str(scope).strip() for scope in scopes if str(scope).strip())),
            "redirect_after": _safe_redirect_after(redirect_after),
            "created_at": now_iso(),
            "expires_at": expires_at,
        }
        _write_json(self._states_dir() / f"{hashlib.sha256(state.encode('utf-8')).hexdigest()}.json", payload)
        return payload

    def consume_state(self, state: str, identity: dict | None = None) -> dict:
        state = str(state or "").strip()
        if not state:
            raise GoogleTokenStoreError("Missing OAuth state.", code="missing_oauth_state")
        path = self._states_dir() / f"{hashlib.sha256(state.encode('utf-8')).hexdigest()}.json"
        payload = _load_json(path)
        if path.exists():
            path.unlink()
        if not payload:
            raise GoogleTokenStoreError("OAuth state is unknown or already consumed.", code="invalid_oauth_state")
        if parse_iso(payload.get("expires_at")) and parse_iso(payload.get("expires_at")) < datetime.now(timezone.utc):
            raise GoogleTokenStoreError("OAuth state expired.", code="expired_oauth_state")
        if identity:
            tenant = str(identity.get("tenant_id", "") or "")
            teacher = str(identity.get("teacher_id", "") or "")
            if tenant and tenant != payload.get("tenant_id"):
                raise GoogleTokenStoreError("OAuth state tenant mismatch.", code="oauth_state_tenant_mismatch")
            if teacher and teacher != payload.get("teacher_id"):
                raise GoogleTokenStoreError("OAuth state teacher mismatch.", code="oauth_state_teacher_mismatch")
        return payload

    def save_token(self, identity: dict, project: dict | None, token_payload: dict, *, granted_scopes: list[str] | None = None) -> dict:
        token_payload = dict(token_payload or {})
        expires_in = token_payload.get("expires_in")
        expires_at = token_payload.get("expires_at")
        if expires_at is None and expires_in not in (None, ""):
            try:
                expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))).isoformat()
            except (TypeError, ValueError):
                expires_at = ""
        email = str(token_payload.get("teacher_email", "") or token_payload.get("email", "") or "")
        teacher_id = str(identity.get("teacher_id", "") or "")
        public = {
            "connected": True,
            "teacher_display_email": email,
            "teacher_identity_hash": _teacher_hash(email, teacher_id),
            "granted_scopes": sorted(set(granted_scopes or token_payload.get("scope", "").split())),
            "expires_at": str(expires_at or ""),
            "updated_at": now_iso(),
        }
        secret = {
            "access_token": token_payload.get("access_token", ""),
            "refresh_token": token_payload.get("refresh_token", ""),
            "token_type": token_payload.get("token_type", "Bearer"),
            "expires_at": public["expires_at"],
            "scope": " ".join(public["granted_scopes"]),
            "id_token": token_payload.get("id_token", ""),
        }
        envelope = {
            "schema_version": TOKEN_STORE_SCHEMA_VERSION,
            "stored_at": now_iso(),
            "tenant_id": str(identity.get("tenant_id", "") or ""),
            "teacher_id": teacher_id,
            "project_scope": _scope_key(project),
            "public": public,
            "secret": self._seal(secret),
        }
        _write_json(self._token_path(identity, project), envelope)
        return public

    def load_token(self, identity: dict, project: dict | None = None, scope_id: str | None = None) -> dict:
        envelope = _load_json(self._token_path(identity, project, scope_id))
        if not envelope:
            return {}
        secret = self._open(envelope.get("secret", {}) if isinstance(envelope.get("secret"), dict) else {})
        if not secret:
            return {}
        public = envelope.get("public", {}) if isinstance(envelope.get("public"), dict) else {}
        return {**secret, "public": public}

    def status(self, identity: dict, project: dict | None = None, scope_id: str | None = None) -> dict:
        envelope = _load_json(self._token_path(identity, project, scope_id))
        public = dict(envelope.get("public", {}) if isinstance(envelope.get("public"), dict) else {})
        secret_meta = envelope.get("secret", {}) if isinstance(envelope.get("secret"), dict) else {}
        secret = self._open(secret_meta) if secret_meta else {}
        connected = bool(public.get("connected")) and bool(envelope)
        expires = parse_iso(public.get("expires_at"))
        expired = bool(expires and expires <= datetime.now(timezone.utc))
        refresh_available = bool(secret.get("refresh_token"))
        if expired and not refresh_available:
            connected = False
        return {
            "connected": connected,
            "expired": expired,
            "refresh_available": refresh_available,
            "granted_scopes": list(public.get("granted_scopes", []) or []),
            "expires_at": str(public.get("expires_at", "") or ""),
            "teacher_display_email": str(public.get("teacher_display_email", "") or ""),
            "teacher_identity_hash": str(public.get("teacher_identity_hash", "") or ""),
            "updated_at": str(public.get("updated_at", "") or ""),
            "storage": {
                "path": "server/data/google_oauth",
                "encoding": str(secret_meta.get("encoding", "") or "none"),
                "strict_mode": self.strict_mode,
                "encryption_key_configured": bool(self.encryption_key),
                "production_ready": bool(self.strict_mode and self.encryption_key),
            },
        }

    def clear_token(self, identity: dict, project: dict | None = None, scope_id: str | None = None) -> bool:
        path = self._token_path(identity, project, scope_id)
        existed = path.exists()
        if existed:
            path.unlink()
        return existed
