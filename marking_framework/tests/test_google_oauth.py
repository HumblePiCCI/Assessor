import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from server.google_oauth import DEFAULT_GOOGLE_SCOPES, GoogleOAuthError, GoogleOAuthService
from server.google_token_store import GoogleTokenStore, GoogleTokenStoreError


class Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class OAuthTransport:
    def __init__(self):
        self.posts = []

    def post(self, url, *, data=None, params=None, timeout=20.0):
        self.posts.append({"url": url, "data": data or {}, "params": params or {}})
        if "revoke" in url:
            return Response(200, {})
        return Response(
            200,
            {
                "access_token": "access-secret",
                "refresh_token": "refresh-secret",
                "expires_in": 3600,
                "scope": " ".join(DEFAULT_GOOGLE_SCOPES),
                "token_type": "Bearer",
            },
        )


class FailingRefreshTransport:
    def __init__(self):
        self.posts = []

    def post(self, url, *, data=None, params=None, timeout=20.0):
        self.posts.append({"url": url, "data": data or {}, "params": params or {}})
        return Response(400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})


def identity():
    return {"tenant_id": "tenant-a", "teacher_id": "teacher-a", "strict_auth": False}


def project():
    return {"id": "project-a", "name": "Project A", "scope_key": "scope-a"}


def service(tmp_path, transport=None):
    return GoogleOAuthService(
        tmp_path / "server",
        token_store=GoogleTokenStore(tmp_path / "server"),
        transport=transport or OAuthTransport(),
        config={
            "client_id": "client-id",
            "client_secret": "client-secret",
            "redirect_uri": "http://localhost/google/auth/callback",
        },
    )


def save_expired_token(store, identity_payload=None):
    return store.save_token(
        identity_payload or identity(),
        project(),
        {
            "access_token": "stale-access-secret",
            "refresh_token": "refresh-secret",
            "expires_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
            "scope": " ".join(DEFAULT_GOOGLE_SCOPES),
            "token_type": "Bearer",
        },
        granted_scopes=list(DEFAULT_GOOGLE_SCOPES),
    )


def test_oauth_config_missing_status_is_teacher_friendly_and_redacted(tmp_path):
    svc = GoogleOAuthService(
        tmp_path / "server",
        token_store=GoogleTokenStore(tmp_path / "server"),
        transport=OAuthTransport(),
        config={},
    )
    status = svc.status(identity(), project())
    assert status["configured"] is False
    assert "GOOGLE_OAUTH_CLIENT_ID" in status["configured_missing"]
    assert "Set Google OAuth env vars" in status["remediation"]
    assert "client-secret" not in json.dumps(status)
    with pytest.raises(GoogleOAuthError) as exc:
        svc.start(identity(), project())
    assert exc.value.code == "google_oauth_not_configured"


def test_oauth_start_uses_pkce_state_and_project_binding(tmp_path):
    svc = service(tmp_path)
    started = svc.start(identity(), project(), redirect_after="https://evil.example/<script>")
    parsed = urlparse(started["authorization_url"])
    query = parse_qs(parsed.query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["access_type"] == ["offline"]
    assert query["include_granted_scopes"] == ["true"]
    assert set(query["scope"][0].split()) == set(DEFAULT_GOOGLE_SCOPES)

    state = query["state"][0]
    state_store = GoogleTokenStore(tmp_path / "server")
    valid_state = state_store.consume_state(state, identity())
    assert valid_state["redirect_after"] == "/"

    started = svc.start(identity(), project())
    state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]
    with pytest.raises(GoogleTokenStoreError, match="tenant mismatch"):
        state_store.consume_state(state, {"tenant_id": "wrong", "teacher_id": "teacher-a"})


def test_oauth_callback_status_and_disconnect_never_leak_tokens(tmp_path):
    transport = OAuthTransport()
    svc = service(tmp_path, transport)
    started = svc.start(identity(), project())
    state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]

    connected = svc.callback(state=state, code="auth-code")
    assert connected["status"] == "connected"
    status = svc.status(identity(), project())
    status_blob = json.dumps(status)
    assert status["connected"] is True
    assert "access-secret" not in status_blob
    assert "refresh-secret" not in status_blob

    disconnected = svc.disconnect(identity(), project())
    assert disconnected["connected"] is False
    assert disconnected["cleared"] is True
    assert transport.posts[-1]["params"]["token"] == "refresh-secret"
    assert svc.status(identity(), project())["connected"] is False


def test_access_token_refreshes_expired_token_before_live_google_use(tmp_path):
    transport = OAuthTransport()
    store = GoogleTokenStore(tmp_path / "server")
    save_expired_token(store)
    svc = GoogleOAuthService(
        tmp_path / "server",
        token_store=store,
        transport=transport,
        config={
            "client_id": "client-id",
            "client_secret": "client-secret",
            "redirect_uri": "http://localhost/google/auth/callback",
        },
    )
    initial_status = svc.status(identity(), project())
    assert initial_status["connected"] is True
    assert initial_status["expired"] is True
    assert initial_status["reconnect_required"] is False
    assert svc.access_token(identity(), project()) == "access-secret"
    assert transport.posts[-1]["data"]["grant_type"] == "refresh_token"
    refreshed_status = svc.status(identity(), project())
    assert refreshed_status["connected"] is True
    assert "access-secret" not in json.dumps(refreshed_status)


def test_refresh_failure_requires_reconnect_and_returns_no_stale_access_token(tmp_path):
    store = GoogleTokenStore(tmp_path / "server")
    save_expired_token(store)
    svc = GoogleOAuthService(
        tmp_path / "server",
        token_store=store,
        transport=FailingRefreshTransport(),
        config={
            "client_id": "client-id",
            "client_secret": "client-secret",
            "redirect_uri": "http://localhost/google/auth/callback",
        },
    )
    with pytest.raises(GoogleOAuthError) as exc:
        svc.access_token(identity(), project())
    assert exc.value.code == "refresh_failed_reconnect_required"
