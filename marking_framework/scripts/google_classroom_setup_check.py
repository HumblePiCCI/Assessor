#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Mapping

try:
    from server.google_oauth import DEFAULT_GOOGLE_SCOPES, load_google_oauth_config
    from server.runtime_context import strict_auth_enabled
except ImportError:  # pragma: no cover - supports direct script execution from scripts/
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from server.google_oauth import DEFAULT_GOOGLE_SCOPES, load_google_oauth_config
    from server.runtime_context import strict_auth_enabled


REQUIRED_ENV = (
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_OAUTH_REDIRECT_URI",
)
LOCAL_ENV_FILES = (
    ".env",
    ".env.local",
    ".env.google",
    ".env.google.local",
)
RECOMMENDED_REDIRECT_URIS = (
    "http://127.0.0.1:8000/google/auth/callback",
    "http://localhost:8000/google/auth/callback",
)


def _git_root(base_dir: Path) -> Path:
    try:
        result = subprocess.run(
            ["git", "-C", str(base_dir), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return base_dir
    if result.returncode != 0:
        return base_dir
    return Path((result.stdout or "").strip() or str(base_dir))


def _git_ignored(path: Path, repo_root: Path) -> bool:
    try:
        rel = str(path.resolve().relative_to(repo_root.resolve()))
    except Exception:
        rel = str(path)
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "check-ignore", "--quiet", "--", rel],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        return False
    return result.returncode == 0


def _with_env(env: Mapping[str, str] | None):
    if env is None:
        return load_google_oauth_config()
    original = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update({key: value for key, value in env.items() if value is not None})
        return load_google_oauth_config()
    finally:
        os.environ.clear()
        os.environ.update(original)


def build_setup_report(base_dir: Path | None = None, *, env: Mapping[str, str] | None = None) -> dict:
    base_dir = Path(base_dir or Path(__file__).resolve().parents[1]).resolve()
    server_dir = base_dir / "server"
    repo_root = _git_root(base_dir)
    config = _with_env(env)
    env_source = env if env is not None else os.environ
    secrets_file = str(env_source.get("GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "") or "")
    secrets_path = Path(secrets_file).expanduser() if secrets_file else None
    configured = {
        "GOOGLE_OAUTH_CLIENT_ID": bool(config.get("client_id")),
        "GOOGLE_OAUTH_CLIENT_SECRET": bool(config.get("client_secret")),
        "GOOGLE_OAUTH_REDIRECT_URI": bool(config.get("redirect_uri")),
        "GOOGLE_OAUTH_CLIENT_SECRETS_FILE": bool(secrets_file),
        "GOOGLE_TOKEN_ENCRYPTION_KEY": bool(env_source.get("GOOGLE_TOKEN_ENCRYPTION_KEY", "")),
    }
    missing = [name for name in REQUIRED_ENV if not configured[name]]
    strict_mode = strict_auth_enabled(base_dir)
    env_ignored = {
        name: _git_ignored(base_dir / name, repo_root)
        for name in LOCAL_ENV_FILES
    }
    data_ignored = _git_ignored(server_dir / "data" / "google_oauth" / "token.json", repo_root)
    recommendations = []
    if missing:
        recommendations.append(f"Set missing OAuth values: {', '.join(missing)}.")
    if not all(env_ignored.values()):
        recommendations.append("Keep local .env files ignored before adding secrets.")
    if not data_ignored:
        recommendations.append("Keep server/data/google_oauth ignored before connecting Google.")
    if strict_mode and not configured["GOOGLE_TOKEN_ENCRYPTION_KEY"]:
        recommendations.append("Set GOOGLE_TOKEN_ENCRYPTION_KEY or use an approved secret store before strict runtime.")
    redirect_uri = str(config.get("redirect_uri", "") or "")
    if redirect_uri and redirect_uri not in RECOMMENDED_REDIRECT_URIS:
        recommendations.append("Confirm the redirect URI exactly matches the OAuth client entry in Google Cloud.")
    return {
        "ok": not missing and all(env_ignored.values()) and data_ignored and (not strict_mode or configured["GOOGLE_TOKEN_ENCRYPTION_KEY"]),
        "configured": configured,
        "missing": missing,
        "redirect_uri": redirect_uri,
        "server_callback_url": redirect_uri,
        "recommended_redirect_uris": list(RECOMMENDED_REDIRECT_URIS),
        "required_scopes": list(DEFAULT_GOOGLE_SCOPES),
        "token_store": {
            "path": "server/data/google_oauth",
            "strict_mode": strict_mode,
            "encryption_key_configured": configured["GOOGLE_TOKEN_ENCRYPTION_KEY"],
            "production_ready": bool(strict_mode and configured["GOOGLE_TOKEN_ENCRYPTION_KEY"]),
        },
        "gitignore": {
            "repo_root": str(repo_root),
            "local_env_files": env_ignored,
            "google_token_store": data_ignored,
        },
        "client_secrets_file": {
            "configured": bool(secrets_file),
            "exists": bool(secrets_path and secrets_path.exists()),
            "path": "<configured outside repo>" if secrets_file else "",
        },
        "recommendations": recommendations,
        "secrets_redacted": True,
    }


def format_report(report: dict) -> str:
    lines = [
        "Google Classroom local setup check",
        f"status: {'ok' if report.get('ok') else 'blocked'}",
        f"redirect_uri: {report.get('redirect_uri') or '(missing)'}",
        f"server_callback_url: {report.get('server_callback_url') or '(missing)'}",
        "configured:",
    ]
    for key, value in report.get("configured", {}).items():
        lines.append(f"  - {key}: {'yes' if value else 'missing'}")
    lines.append("required_scopes:")
    for scope in report.get("required_scopes", []):
        lines.append(f"  - {scope}")
    token_store = report.get("token_store", {})
    lines.extend(
        [
            "token_store:",
            f"  - path: {token_store.get('path')}",
            f"  - strict_mode: {token_store.get('strict_mode')}",
            f"  - encryption_key_configured: {token_store.get('encryption_key_configured')}",
            f"  - production_ready: {token_store.get('production_ready')}",
            "gitignore:",
        ]
    )
    for name, value in report.get("gitignore", {}).get("local_env_files", {}).items():
        lines.append(f"  - {name}: {'ignored' if value else 'not ignored'}")
    lines.append(f"  - server/data/google_oauth: {'ignored' if report.get('gitignore', {}).get('google_token_store') else 'not ignored'}")
    if report.get("recommendations"):
        lines.append("next_actions:")
        for item in report["recommendations"]:
            lines.append(f"  - {item}")
    lines.append("secrets: redacted")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local Google Classroom OAuth setup without printing secrets.")
    parser.add_argument("--json", action="store_true", help="Print the redacted machine-readable report.")
    args = parser.parse_args()
    report = build_setup_report()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_report(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
