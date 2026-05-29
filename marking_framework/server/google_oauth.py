#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from server.google_token_store import GoogleTokenStore, GoogleTokenStoreError, parse_iso


AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

GOOGLE_CLASSROOM_READ_SCOPES = (
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students.readonly",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
)
GOOGLE_DRIVE_READ_SCOPES = (
    "https://www.googleapis.com/auth/drive.readonly",
)
DEFAULT_GOOGLE_SCOPES = (*GOOGLE_CLASSROOM_READ_SCOPES, *GOOGLE_DRIVE_READ_SCOPES)


class GoogleOAuthError(ValueError):
    def __init__(self, message: str, *, code: str = "google_oauth_error", redirect_after: str = ""):
        super().__init__(message)
        self.code = code
        self.redirect_after = redirect_after


class OAuthTransport:
    def post(self, url: str, *, data: dict | None = None, params: dict | None = None, timeout: float = 20.0):
        return httpx.post(url, data=data, params=params, timeout=timeout)


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
        self.token_store = token_store or GoogleTokenStore(self.base_dir)
        self.transport = transport or OAuthTransport()
        self.config = dict(config or load_google_oauth_config())

    def _require_config(self) -> dict:
        client_id = str(self.config.get("client_id", "") or "").strip()
        client_secret = str(self.config.get("client_secret", "") or "").strip()
        redirect_uri = str(self.config.get("redirect_uri", "") or "").strip()
        missing = []
        if not client_id:
            missing.append("GOOGLE_OAUTH_CLIENT_ID")
        if not client_secret:
            missing.append("GOOGLE_OAUTH_CLIENT_SECRET")
        if not redirect_uri:
            missing.append("GOOGLE_OAUTH_REDIRECT_URI")
        if missing:
            raise GoogleOAuthError(
                f"Google OAuth is not configured: {', '.join(missing)}",
                code="google_oauth_not_configured",
            )
        return {"client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri}

    def status(self, identity: dict, project: dict | None = None) -> dict:
        config = self.config
        token_status = self.token_store.status(identity, project)
        return {
            "configured": bool(config.get("client_id") and config.get("client_secret") and config.get("redirect_uri")),
            "connected": bool(token_status.get("connected")),
            "expired": bool(token_status.get("expired")),
            "granted_scopes": list(token_status.get("granted_scopes", []) or []),
            "required_scopes": list(DEFAULT_GOOGLE_SCOPES),
            "missing_scopes": sorted(set(DEFAULT_GOOGLE_SCOPES) - set(token_status.get("granted_scopes", []) or [])),
            "expires_at": str(token_status.get("expires_at", "") or ""),
            "teacher_display_email": str(token_status.get("teacher_display_email", "") or ""),
            "teacher_identity_hash": str(token_status.get("teacher_identity_hash", "") or ""),
            "refresh_available": bool(token_status.get("refresh_available", False)),
            "storage": token_status.get("storage", {}),
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

    def callback(self, *, state: str, code: str, error: str | None = None) -> dict:
        try:
            state_payload = self.token_store.consume_state(state)
        except GoogleTokenStoreError as exc:
            raise GoogleOAuthError(str(exc), code=exc.code) from exc
        redirect_after = str(state_payload.get("redirect_after", "") or "")
        if error:
            raise GoogleOAuthError(f"Google OAuth failed: {error}", code="google_oauth_denied", redirect_after=redirect_after)
        if not code:
            raise GoogleOAuthError("Missing Google OAuth authorization code.", code="missing_oauth_code", redirect_after=redirect_after)
        try:
            config = self._require_config()
        except GoogleOAuthError as exc:
            raise GoogleOAuthError(str(exc), code=exc.code, redirect_after=redirect_after) from exc
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
            raise GoogleOAuthError(str(reason), code="google_oauth_token_exchange_failed", redirect_after=redirect_after)
        identity = {
            "tenant_id": state_payload.get("tenant_id", ""),
            "teacher_id": state_payload.get("teacher_id", ""),
            "strict_auth": False,
        }
        public = self.token_store.save_token(
            identity,
            state_payload.get("project", {}),
            payload,
            granted_scopes=payload.get("scope", " ".join(state_payload.get("scopes", []))).split(),
        )
        return {
            "status": "connected",
            "project": state_payload.get("project", {}),
            "redirect_after": state_payload.get("redirect_after", ""),
            "google_auth": public,
        }

    def refresh_access_token(self, identity: dict, project: dict | None = None) -> dict:
        token = self.token_store.load_token(identity, project)
        if not token:
            raise GoogleOAuthError("Google is not connected for this teacher and project.", code="missing_oauth_grant")
        refresh_token = str(token.get("refresh_token", "") or "")
        if not refresh_token:
            raise GoogleOAuthError("Google refresh token is missing. Reconnect Google.", code="missing_oauth_grant")
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
            raise GoogleOAuthError(str(reason), code="missing_oauth_grant")
        if "refresh_token" not in payload:
            payload["refresh_token"] = refresh_token
        payload["scope"] = payload.get("scope") or token.get("scope") or " ".join(token.get("public", {}).get("granted_scopes", []))
        return self.token_store.save_token(identity, project, payload, granted_scopes=str(payload.get("scope", "")).split())

    def access_token(self, identity: dict, project: dict | None = None) -> str:
        token = self.token_store.load_token(identity, project)
        if not token:
            raise GoogleOAuthError("Google is not connected for this teacher and project.", code="missing_oauth_grant")
        return str(token.get("access_token", "") or "")

    def fresh_access_token(self, identity: dict, project: dict | None = None) -> tuple[str, dict]:
        token = self.token_store.load_token(identity, project)
        if not token:
            raise GoogleOAuthError("Google is not connected for this teacher and project.", code="missing_oauth_grant")
        expires = parse_iso(str(token.get("expires_at", "") or ""))
        if expires and expires <= datetime.now(timezone.utc):
            try:
                self.refresh_access_token(identity, project)
            except GoogleOAuthError as exc:
                raise GoogleOAuthError("Google connection expired. Reconnect Google Classroom.", code=exc.code) from exc
            token = self.token_store.load_token(identity, project)
        access_token = str(token.get("access_token", "") or "")
        if not access_token:
            raise GoogleOAuthError("Google access token is missing. Reconnect Google Classroom.", code="missing_oauth_grant")
        return access_token, self.status(identity, project)

    def disconnect(self, identity: dict, project: dict | None = None) -> dict:
        token = self.token_store.load_token(identity, project)
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
        cleared = self.token_store.clear_token(identity, project)
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
