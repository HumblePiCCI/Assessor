#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from server.google_token_store import GoogleTokenStore, GoogleTokenStoreError, TOKEN_REFRESH_SKEW_SECONDS, parse_iso
from server.google_session import google_identity
from server.local_env import load_local_env


AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
TOKENINFO_ENDPOINT = "https://oauth2.googleapis.com/tokeninfo"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

GOOGLE_IDENTITY_SCOPES = ("openid", "email")
GOOGLE_CLASSROOM_READ_SCOPES = (
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students.readonly",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
)
GOOGLE_DRIVE_READ_SCOPES = (
    "https://www.googleapis.com/auth/drive.readonly",
)
DEFAULT_GOOGLE_SCOPES = (*GOOGLE_IDENTITY_SCOPES, *GOOGLE_CLASSROOM_READ_SCOPES, *GOOGLE_DRIVE_READ_SCOPES)
GOOGLE_ACCOUNT_PROJECT = {"id": "google-account", "name": "Google Account", "scope_key": "google-account"}
GOOGLE_SCOPE_EQUIVALENTS = {
    "email": {
        "https://www.googleapis.com/auth/userinfo.email",
    },
    "https://www.googleapis.com/auth/classroom.coursework.students.readonly": {
        "https://www.googleapis.com/auth/classroom.student-submissions.students.readonly",
    },
}


class GoogleOAuthError(ValueError):
    def __init__(self, message: str, *, code: str = "google_oauth_error"):
        super().__init__(message)
        self.code = code


class OAuthTransport:
    def post(self, url: str, *, data: dict | None = None, params: dict | None = None, timeout: float = 20.0):
        return httpx.post(url, data=data, params=params, timeout=timeout)

    def get(self, url: str, *, params: dict | None = None, timeout: float = 20.0):
        return httpx.get(url, params=params, timeout=timeout)


def _load_client_secrets_file(path: str | None) -> dict:
    if not path:
        return {}
    secrets_path = Path(path).expanduser()
    if not secrets_path.exists():
        return {}
    try:
        payload = json.loads(secrets_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload.get("web", payload.get("installed", payload)) if isinstance(payload.get("web", payload), dict) else {}


def load_google_oauth_config() -> dict:
    secrets = _load_client_secrets_file(os.environ.get("GOOGLE_OAUTH_CLIENT_SECRETS_FILE"))
    redirect_uris = secrets.get("redirect_uris", []) if isinstance(secrets.get("redirect_uris"), list) else []
    redirect_uri = (
        os.environ.get("GOOGLE_OAUTH_REDIRECT_URI")
        or secrets.get("redirect_uri")
        or (redirect_uris[0] if redirect_uris else "")
    )
    return {
        "client_id": os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or secrets.get("client_id") or "",
        "client_secret": os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET") or secrets.get("client_secret") or "",
        "redirect_uri": redirect_uri,
        "client_secrets_file_configured": bool(os.environ.get("GOOGLE_OAUTH_CLIENT_SECRETS_FILE")),
    }


def _response_json(response: Any) -> dict:
    try:
        payload = response.json()
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _status_code(response: Any) -> int:
    try:
        return int(response.status_code)
    except Exception:
        return 0


def _config_missing(config: dict) -> list[str]:
    missing = []
    if not str(config.get("client_id", "") or "").strip():
        missing.append("GOOGLE_OAUTH_CLIENT_ID")
    if not str(config.get("client_secret", "") or "").strip():
        missing.append("GOOGLE_OAUTH_CLIENT_SECRET")
    if not str(config.get("redirect_uri", "") or "").strip():
        missing.append("GOOGLE_OAUTH_REDIRECT_URI")
    return missing


def _required_scope_is_satisfied(required_scope: str, granted_scopes: set[str]) -> bool:
    if required_scope in granted_scopes:
        return True
    return bool(GOOGLE_SCOPE_EQUIVALENTS.get(required_scope, set()) & granted_scopes)


def missing_required_scopes(granted_scopes: list[str]) -> list[str]:
    granted = {str(scope or "").strip() for scope in granted_scopes if str(scope or "").strip()}
    return [scope for scope in DEFAULT_GOOGLE_SCOPES if not _required_scope_is_satisfied(scope, granted)]


def _token_needs_refresh(token: dict) -> bool:
    expires = parse_iso(str(token.get("expires_at", "") or ""))
    if not expires:
        return False
    return expires <= datetime.now(timezone.utc) + timedelta(seconds=TOKEN_REFRESH_SKEW_SECONDS)


def _verified_email_is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() == "true"


def _teacher_hash(email: str) -> str:
    return hashlib.sha256(str(email or "").strip().lower().encode("utf-8")).hexdigest()[:24]


class GoogleOAuthService:
    def __init__(
        self,
        base_dir: Path,
        *,
        token_store: GoogleTokenStore | None = None,
        transport: OAuthTransport | None = None,
        config: dict | None = None,
    ):
        self.base_dir = Path(base_dir)
        if config is None:
            load_local_env(self.base_dir.parent)
        self.token_store = token_store or GoogleTokenStore(self.base_dir)
        self.transport = transport or OAuthTransport()
        self.config = dict(config or load_google_oauth_config())

    def _require_config(self) -> dict:
        client_id = str(self.config.get("client_id", "") or "").strip()
        client_secret = str(self.config.get("client_secret", "") or "").strip()
        redirect_uri = str(self.config.get("redirect_uri", "") or "").strip()
        missing = _config_missing(self.config)
        if missing:
            raise GoogleOAuthError(
                f"Google OAuth is not configured: {', '.join(missing)}",
                code="google_oauth_not_configured",
            )
        return {"client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri}

    def status(self, identity: dict, project: dict | None = None) -> dict:
        config = self.config
        token_status = self.token_store.status(identity, project)
        if project != GOOGLE_ACCOUNT_PROJECT and not token_status.get("connected"):
            token_status = self.token_store.status(identity, GOOGLE_ACCOUNT_PROJECT)
        configured_missing = _config_missing(config)
        configured = not configured_missing
        granted = list(token_status.get("granted_scopes", []) or [])
        missing_scopes = missing_required_scopes(granted)
        remediation = ""
        if not configured:
            remediation = "Set Google OAuth env vars from marking_framework/.env.example, then restart the local server."
        elif missing_scopes and token_status.get("connected"):
            remediation = "Reconnect Google Classroom and approve the missing Classroom/Drive read scopes."
        elif token_status.get("connected") and token_status.get("expired"):
            remediation = "Stored access token is expired; the next live Classroom read will refresh before calling Google."
        elif token_status.get("connected") and token_status.get("expiring"):
            remediation = "Stored access token is near expiry; the next live Classroom read will refresh before calling Google."
        elif not token_status.get("connected"):
            remediation = "Click Connect Google Classroom and sign in with the teacher account."
        return {
            "configured": configured,
            "configured_missing": configured_missing,
            "connected": bool(token_status.get("connected")),
            "expired": bool(token_status.get("expired")),
            "expiring": bool(token_status.get("expiring")),
            "expires_in_seconds": token_status.get("expires_in_seconds"),
            "reconnect_required": False,
            "granted_scopes": granted,
            "required_scopes": list(DEFAULT_GOOGLE_SCOPES),
            "missing_scopes": missing_scopes,
            "expires_at": str(token_status.get("expires_at", "") or ""),
            "teacher_display_email": str(token_status.get("teacher_display_email", "") or ""),
            "teacher_identity_hash": str(token_status.get("teacher_identity_hash", "") or ""),
            "storage": token_status.get("storage", {}),
            "storage_posture": token_status.get("storage", {}),
            "remediation": remediation,
        }

    def start(self, identity: dict, project: dict | None = None, *, redirect_after: str = "", scopes: list[str] | None = None) -> dict:
        config = self._require_config()
        state = self.token_store.create_state(
            identity,
            project,
            scopes=list(scopes or DEFAULT_GOOGLE_SCOPES),
            redirect_after=redirect_after,
        )
        query = {
            "client_id": config["client_id"],
            "redirect_uri": config["redirect_uri"],
            "response_type": "code",
            "scope": " ".join(state["scopes"]),
            "state": state["state"],
            "access_type": "offline",
            "include_granted_scopes": "true",
            "code_challenge": state["code_challenge"],
            "code_challenge_method": state["code_challenge_method"],
            "prompt": "consent",
        }
        return {
            "authorization_url": f"{AUTH_ENDPOINT}?{urlencode(query)}",
            "state_expires_at": state["expires_at"],
            "scopes": state["scopes"],
            "project": state["project"],
        }

    def verify_google_identity(self, id_token: str) -> dict:
        token = str(id_token or "").strip()
        if not token:
            raise GoogleOAuthError("Google sign-in did not return an identity token. Reconnect and approve the email scope.", code="google_identity_required")
        response = self.transport.get(TOKENINFO_ENDPOINT, params={"id_token": token}, timeout=20.0)
        payload = _response_json(response)
        if _status_code(response) >= 400:
            raise GoogleOAuthError("Google identity token could not be verified.", code="google_identity_verification_failed")
        client_id = str(self.config.get("client_id", "") or "")
        audience = payload.get("aud", "")
        audiences = audience if isinstance(audience, list) else [audience]
        if client_id and client_id not in {str(item) for item in audiences}:
            raise GoogleOAuthError("Google identity token audience did not match this OAuth client.", code="google_identity_audience_mismatch")
        issuer = str(payload.get("iss", "") or "")
        if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
            raise GoogleOAuthError("Google identity token issuer was not trusted.", code="google_identity_issuer_mismatch")
        expires = str(payload.get("exp", "") or "")
        if expires:
            try:
                if int(expires) <= int(datetime.now(timezone.utc).timestamp()):
                    raise GoogleOAuthError("Google identity token is expired.", code="google_identity_expired")
            except ValueError as exc:
                raise GoogleOAuthError("Google identity token expiry was invalid.", code="google_identity_invalid") from exc
        email = str(payload.get("email", "") or "").strip().lower()
        if not email or not _verified_email_is_true(payload.get("email_verified", True)):
            raise GoogleOAuthError("A verified Gmail/Google Workspace email is required to access projects.", code="google_verified_email_required")
        return {"email": email}

    def callback(self, *, state: str, code: str, error: str | None = None) -> dict:
        state_payload = self.token_store.consume_state(state)
        if error:
            raise GoogleOAuthError(f"Google OAuth failed: {error}", code="google_oauth_denied")
        if not code:
            raise GoogleOAuthError("Missing Google OAuth authorization code.", code="missing_oauth_code")
        config = self._require_config()
        response = self.transport.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "redirect_uri": config["redirect_uri"],
                "grant_type": "authorization_code",
                "code_verifier": state_payload["code_verifier"],
            },
            timeout=20.0,
        )
        payload = _response_json(response)
        if _status_code(response) >= 400 or "access_token" not in payload:
            reason = payload.get("error_description") or payload.get("error") or "token exchange failed"
            raise GoogleOAuthError(str(reason), code="google_oauth_token_exchange_failed")
        verified_identity = self.verify_google_identity(str(payload.get("id_token", "") or ""))
        payload["teacher_email"] = verified_identity["email"]
        identity = google_identity(verified_identity["email"], _teacher_hash(verified_identity["email"]))
        public = self.token_store.save_token(
            identity,
            state_payload.get("project", {}),
            payload,
            granted_scopes=payload.get("scope", " ".join(state_payload.get("scopes", []))).split(),
        )
        self.token_store.save_token(
            identity,
            GOOGLE_ACCOUNT_PROJECT,
            payload,
            granted_scopes=payload.get("scope", " ".join(state_payload.get("scopes", []))).split(),
        )
        return {
            "status": "connected",
            "project": state_payload.get("project", {}),
            "redirect_after": state_payload.get("redirect_after", ""),
            "google_auth": public,
            "identity": identity,
        }

    def _load_token_with_fallback(self, identity: dict, project: dict | None = None) -> tuple[dict, dict | None]:
        token = self.token_store.load_token(identity, project)
        if token:
            return token, project
        if project != GOOGLE_ACCOUNT_PROJECT:
            token = self.token_store.load_token(identity, GOOGLE_ACCOUNT_PROJECT)
            if token:
                return token, GOOGLE_ACCOUNT_PROJECT
        return {}, project

    def refresh_access_token(self, identity: dict, project: dict | None = None) -> dict:
        token, token_project = self._load_token_with_fallback(identity, project)
        if not token:
            raise GoogleOAuthError("Google is not connected for this teacher and project.", code="missing_oauth_grant")
        refresh_token = str(token.get("refresh_token", "") or "")
        if not refresh_token:
            raise GoogleOAuthError("Google refresh token is missing. Reconnect Google.", code="refresh_failed_reconnect_required")
        config = self._require_config()
        response = self.transport.post(
            TOKEN_ENDPOINT,
            data={
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=20.0,
        )
        payload = _response_json(response)
        if _status_code(response) >= 400 or "access_token" not in payload:
            reason = payload.get("error_description") or payload.get("error") or "token refresh failed"
            raise GoogleOAuthError(str(reason), code="refresh_failed_reconnect_required")
        if "refresh_token" not in payload:
            payload["refresh_token"] = refresh_token
        payload["scope"] = payload.get("scope") or token.get("scope") or " ".join(token.get("public", {}).get("granted_scopes", []))
        public = token.get("public", {}) if isinstance(token.get("public"), dict) else {}
        payload["teacher_email"] = public.get("teacher_display_email", "")
        return self.token_store.save_token(identity, token_project, payload, granted_scopes=str(payload.get("scope", "")).split())

    def access_token(self, identity: dict, project: dict | None = None, *, refresh_if_needed: bool = True) -> str:
        token, token_project = self._load_token_with_fallback(identity, project)
        if not token:
            raise GoogleOAuthError("Google is not connected for this teacher and project.", code="missing_oauth_grant")
        if refresh_if_needed and _token_needs_refresh(token):
            self.refresh_access_token(identity, token_project)
            token, _ = self._load_token_with_fallback(identity, token_project)
        access_token = str(token.get("access_token", "") or "")
        if not access_token:
            raise GoogleOAuthError("Google access token is missing. Reconnect Google.", code="missing_oauth_grant")
        return access_token

    def disconnect(self, identity: dict, project: dict | None = None) -> dict:
        token, token_project = self._load_token_with_fallback(identity, project)
        revoked = False
        revoke_error = ""
        raw_token = str(token.get("refresh_token", "") or token.get("access_token", "") or "")
        if raw_token:
            try:
                response = self.transport.post(REVOKE_ENDPOINT, params={"token": raw_token}, timeout=10.0)
                revoked = _status_code(response) < 400
                if not revoked:
                    revoke_error = str(_response_json(response).get("error", "") or "google_revoke_failed")
            except Exception as exc:
                revoke_error = str(exc)[:120]
        cleared = self.token_store.clear_identity_tokens(identity)
        if not cleared:
            cleared = self.token_store.clear_token(identity, token_project)
        return {
            "status": "disconnected",
            "cleared": bool(cleared),
            "revoked": bool(revoked),
            "revoke_error": revoke_error,
            "connected": False,
        }


def google_oauth_error_payload(exc: Exception) -> dict:
    if isinstance(exc, (GoogleOAuthError, GoogleTokenStoreError)):
        return {"code": exc.code, "message": str(exc)}
    return {"code": "google_oauth_error", "message": str(exc)}
