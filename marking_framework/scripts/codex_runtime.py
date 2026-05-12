#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
from pathlib import Path


CODEX_APP_CLI = Path("/Applications/Codex.app/Contents/Resources/codex")
TOKEN_KEYS = {"tokens", "access_token", "refresh_token", "id_token", "account_id"}


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()


def codex_auth_path() -> Path:
    return codex_home() / "auth.json"


def codex_auth_summary() -> dict:
    auth_path = codex_auth_path()
    summary = {
        "path": str(auth_path),
        "auth_has_api_key": False,
        "auth_has_tokens": False,
        "auth_error": "",
    }
    if not auth_path.exists():
        return summary
    try:
        data = json.loads(auth_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        summary["auth_error"] = "Invalid Codex auth file"
        return summary
    if not isinstance(data, dict):
        summary["auth_error"] = "Invalid Codex auth file"
        return summary
    summary["auth_has_api_key"] = bool(data.get("OPENAI_API_KEY"))
    summary["auth_has_tokens"] = any(bool(data.get(key)) for key in TOKEN_KEYS)
    return summary


def _dedupe(paths: list[str]) -> list[str]:
    seen = set()
    out = []
    for raw in paths:
        if not raw:
            continue
        path = str(Path(raw).expanduser())
        try:
            marker = str(Path(path).resolve())
        except OSError:
            marker = path
        if marker in seen:
            continue
        seen.add(marker)
        out.append(path)
    return out


def codex_candidate_paths() -> list[str]:
    env_path = os.environ.get("CODEX_CLI_PATH", "").strip()
    path_codex = shutil.which("codex") or ""
    return _dedupe([env_path, str(CODEX_APP_CLI), path_codex])


def _run_probe(cmd: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def probe_codex_runtime(path: str) -> dict:
    runtime = {
        "available": False,
        "path": path,
        "kind": "",
        "supports_oauth": False,
        "version": "",
        "error": "",
    }
    if not path:
        runtime["error"] = "Codex CLI not found"
        return runtime
    expanded = str(Path(path).expanduser())
    if not Path(expanded).exists() and shutil.which(expanded) is None:
        runtime["error"] = "Codex CLI not found"
        return runtime
    runtime["path"] = expanded
    try:
        version = _run_probe([expanded, "--version"])
        runtime["version"] = ((version.stdout or "") + (version.stderr or "")).strip().splitlines()[0] if ((version.stdout or "") + (version.stderr or "")).strip() else ""
    except Exception as exc:
        runtime["error"] = f"Codex CLI probe failed: {exc}"
        return runtime
    try:
        help_result = _run_probe([expanded, "exec", "--help"])
    except Exception:
        help_result = None
    help_text = ""
    if help_result is not None:
        help_text = ((help_result.stdout or "") + "\n" + (help_result.stderr or "")).lower()
    runtime["available"] = True
    if help_result is not None and help_result.returncode == 0 and "run codex non-interactively" in help_text:
        runtime["kind"] = "exec"
        runtime["supports_oauth"] = True
        return runtime
    runtime["kind"] = "legacy_q"
    runtime["supports_oauth"] = False
    return runtime


def resolve_codex_runtime() -> dict:
    errors = []
    for path in codex_candidate_paths():
        runtime = probe_codex_runtime(path)
        if runtime.get("available"):
            return runtime
        if runtime.get("error"):
            errors.append(runtime["error"])
    return {
        "available": False,
        "path": "",
        "kind": "",
        "supports_oauth": False,
        "version": "",
        "error": errors[0] if errors else "Codex CLI not found",
    }


def codex_status_payload() -> dict:
    runtime = resolve_codex_runtime()
    auth = codex_auth_summary()
    env_has_api_key = bool(os.environ.get("OPENAI_API_KEY"))
    auth_has_api_key = bool(auth.get("auth_has_api_key"))
    auth_has_tokens = bool(auth.get("auth_has_tokens"))
    oauth_ready = bool(runtime.get("available") and runtime.get("supports_oauth") and auth_has_tokens)
    connected = bool(runtime.get("available") and (env_has_api_key or auth_has_api_key or oauth_ready))
    auth_source = ""
    if env_has_api_key:
        auth_source = "env"
    elif auth_has_api_key:
        auth_source = "auth_file_api_key"
    elif oauth_ready:
        auth_source = "codex_oauth"
    reason = ""
    if not runtime.get("available"):
        reason = runtime.get("error") or "Codex CLI not found"
    elif auth.get("auth_error"):
        reason = str(auth["auth_error"])
    elif connected and oauth_ready and auth_source == "codex_oauth":
        reason = "Codex OAuth runtime ready"
    elif connected:
        reason = "Codex CLI ready"
    elif auth_has_tokens and not runtime.get("supports_oauth"):
        reason = "Codex OAuth tokens found, but this CLI needs an API key for local runs"
    else:
        reason = "Codex not connected"
    return {
        "available": bool(runtime.get("available")),
        "connected": connected,
        "auth_source": auth_source,
        "oauth_tokens_present": auth_has_tokens,
        "oauth_supported": bool(runtime.get("supports_oauth")),
        "runtime_kind": runtime.get("kind", ""),
        "runtime_path": runtime.get("path", ""),
        "version": runtime.get("version", ""),
        "reason": reason,
    }
