import json
import os
import subprocess

import scripts.codex_runtime as cr


def _fake_cli(path):
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def test_codex_status_uses_oauth_capable_exec_runtime(tmp_path, monkeypatch):
    cli = _fake_cli(tmp_path / "codex")
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(json.dumps({"access_token": "token", "account_id": "acct"}), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_CLI_PATH", cli)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    def fake_probe(cmd, timeout=5.0):
        if cmd[1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="codex-cli 0.130.0-alpha.5\n", stderr="")
        if cmd[1:] == ["exec", "--help"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="Run Codex non-interactively\n", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr(cr, "_run_probe", fake_probe)
    payload = cr.codex_status_payload()
    assert payload["available"] is True
    assert payload["connected"] is True
    assert payload["auth_source"] == "codex_oauth"
    assert payload["oauth_supported"] is True
    assert payload["runtime_kind"] == "exec"


def test_codex_status_rejects_oauth_tokens_on_legacy_q_runtime(tmp_path, monkeypatch):
    cli = _fake_cli(tmp_path / "codex")
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(json.dumps({"tokens": {"access_token": "token"}}), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_CLI_PATH", cli)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    def fake_probe(cmd, timeout=5.0):
        if cmd[1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="0.1.2504301751\n", stderr="")
        if cmd[1:] == ["exec", "--help"]:
            return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="unexpected argument exec")
        raise AssertionError(cmd)

    monkeypatch.setattr(cr, "_run_probe", fake_probe)
    payload = cr.codex_status_payload()
    assert payload["available"] is True
    assert payload["connected"] is False
    assert payload["oauth_tokens_present"] is True
    assert payload["oauth_supported"] is False
    assert "needs an API key" in payload["reason"]


def test_codex_auth_summary_reads_top_level_token_keys(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(json.dumps({"refresh_token": "token"}), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    summary = cr.codex_auth_summary()
    assert summary["auth_has_tokens"] is True
    assert summary["auth_has_api_key"] is False


def test_codex_status_accepts_env_api_key_on_legacy_runtime(tmp_path, monkeypatch):
    cli = _fake_cli(tmp_path / "codex")
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_CLI_PATH", cli)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    def fake_probe(cmd, timeout=5.0):
        if cmd[1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="0.1.2504301751\n", stderr="")
        if cmd[1:] == ["exec", "--help"]:
            return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="unexpected argument exec")
        raise AssertionError(cmd)

    monkeypatch.setattr(cr, "_run_probe", fake_probe)
    payload = cr.codex_status_payload()
    assert payload["connected"] is True
    assert payload["auth_source"] == "env"


def test_codex_status_does_not_treat_generic_provider_key_as_legacy_codex_auth(tmp_path, monkeypatch):
    cli = _fake_cli(tmp_path / "codex")
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_CLI_PATH", cli)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "provider-key")

    def fake_probe(cmd, timeout=5.0):
        if cmd[1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="0.1.2504301751\n", stderr="")
        if cmd[1:] == ["exec", "--help"]:
            return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="unexpected argument exec")
        raise AssertionError(cmd)

    monkeypatch.setattr(cr, "_run_probe", fake_probe)
    payload = cr.codex_status_payload()
    assert payload["connected"] is False
    assert payload["auth_source"] == ""
