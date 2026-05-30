import json

import scripts.google_classroom_setup_check as setup_check


def test_google_classroom_setup_check_reports_missing_env_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_check, "_git_ignored", lambda path, repo_root: True)
    report = setup_check.build_setup_report(tmp_path, env={})
    assert report["ok"] is False
    assert set(report["missing"]) == {
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REDIRECT_URI",
    }
    text = setup_check.format_report(report)
    assert "secrets: redacted" in text


def test_google_classroom_setup_check_redacts_configured_values(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_check, "_git_ignored", lambda path, repo_root: True)
    env = {
        "GOOGLE_OAUTH_CLIENT_ID": "client-id-secret",
        "GOOGLE_OAUTH_CLIENT_SECRET": "client-secret-value",
        "GOOGLE_OAUTH_REDIRECT_URI": "http://127.0.0.1:8000/google/auth/callback",
        "GOOGLE_TOKEN_ENCRYPTION_KEY": "token-encryption-secret",
    }
    report = setup_check.build_setup_report(tmp_path, env=env)
    blob = json.dumps(report) + "\n" + setup_check.format_report(report)
    assert report["ok"] is True
    assert report["missing"] == []
    assert report["configured"]["GOOGLE_OAUTH_CLIENT_SECRET"] is True
    assert "client-secret-value" not in blob
    assert "token-encryption-secret" not in blob
