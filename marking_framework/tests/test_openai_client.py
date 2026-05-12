import json
import os
from io import BytesIO
from pathlib import Path

import pytest

import scripts.openai_client as oc


def fake_codex_runtime(kind="legacy_q"):
    return {
        "available": True,
        "path": "/usr/bin/codex",
        "kind": kind,
        "supports_oauth": kind == "exec",
        "version": "codex-test",
    }


class DummyResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_responses_create_missing_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    routing = {"mode": "openai", "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"}}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    with pytest.raises(RuntimeError):
        oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))


def test_responses_create_and_extract(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    routing = {"mode": "openai", "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"}}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return DummyResponse({"output": [{"type": "output_text", "text": "hello"}], "usage": {"input_tokens": 1}})

    monkeypatch.setattr(oc.urllib.request, "urlopen", fake_urlopen)
    fmt = {"type": "json_object"}
    resp = oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], temperature=0.1, reasoning="low",
                               routing_path=str(route_path), text_format=fmt)
    assert oc.extract_text(resp) == "hello"
    assert oc.extract_usage(resp)["input_tokens"] == 1
    assert captured["payload"]["text"]["format"] == fmt


def test_responses_create_uses_low_verbosity_for_gpt54_mini_structured(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    routing = {"mode": "openai", "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"}}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return DummyResponse({"output": [{"type": "output_text", "text": "{\"ok\":true}"}], "usage": {"input_tokens": 1}})

    monkeypatch.setattr(oc.urllib.request, "urlopen", fake_urlopen)
    fmt = {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
    }
    oc.responses_create("gpt-5.4-mini", [{"role": "user", "content": "hi"}], routing_path=str(route_path), text_format=fmt)
    assert captured["payload"]["text"]["verbosity"] == "low"


def test_responses_create_without_text_format(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    routing = {"mode": "openai", "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"}}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return DummyResponse({"output": [{"type": "output_text", "text": "hello"}], "usage": {"input_tokens": 1}})

    monkeypatch.setattr(oc.urllib.request, "urlopen", fake_urlopen)
    oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))
    assert "text" not in captured["payload"]


def test_openai_retries_without_temperature_on_unsupported_parameter(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    routing = {"mode": "openai", "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"}}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    calls = {"count": 0}

    def fake_urlopen(req, timeout=None):
        calls["count"] += 1
        payload = json.loads(req.data.decode("utf-8"))
        if calls["count"] == 1:
            assert "temperature" in payload
            body = {
                "error": {
                    "message": "Unsupported parameter: 'temperature' is not supported with this model.",
                    "type": "invalid_request_error",
                    "param": "temperature",
                    "code": None,
                }
            }
            raise oc.urllib.error.HTTPError(req.full_url, 400, "Bad Request", hdrs=None, fp=BytesIO(json.dumps(body).encode("utf-8")))
        assert "temperature" not in payload
        return DummyResponse({"output": [{"type": "output_text", "text": "{\"ok\":true}"}], "usage": {"input_tokens": 1}})

    monkeypatch.setattr(oc.urllib.request, "urlopen", fake_urlopen)
    fmt = {
        "type": "json_schema",
        "name": "ping",
        "schema": {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        "strict": True,
    }
    resp = oc.responses_create(
        "gpt-5.2",
        [{"role": "user", "content": "hi"}],
        temperature=0.0,
        reasoning="medium",
        routing_path=str(route_path),
        text_format=fmt,
    )
    assert calls["count"] == 2
    assert oc.extract_usage(resp)["input_tokens"] == 1


def test_openai_compatibility_retry_does_not_consume_single_retry_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "1")
    routing = {"mode": "openai", "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"}}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    calls = {"count": 0}

    def fake_urlopen(req, timeout=None):
        calls["count"] += 1
        payload = json.loads(req.data.decode("utf-8"))
        if calls["count"] == 1:
            assert "temperature" in payload
            body = {
                "error": {
                    "message": "Unsupported parameter: 'temperature' is not supported with this model.",
                    "type": "invalid_request_error",
                    "param": "temperature",
                    "code": None,
                }
            }
            raise oc.urllib.error.HTTPError(req.full_url, 400, "Bad Request", hdrs=None, fp=BytesIO(json.dumps(body).encode("utf-8")))
        assert "temperature" not in payload
        return DummyResponse({"output": [{"type": "output_text", "text": "ok"}], "usage": {"input_tokens": 3}})

    monkeypatch.setattr(oc.urllib.request, "urlopen", fake_urlopen)
    resp = oc.responses_create(
        "gpt-5.4",
        [{"role": "user", "content": "hi"}],
        temperature=0.0,
        reasoning="high",
        routing_path=str(route_path),
    )
    assert calls["count"] == 2
    assert oc.extract_usage(resp)["input_tokens"] == 3


def test_openai_retries_transient_network_error(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    routing = {"mode": "openai", "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"}}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    calls = {"count": 0}
    sleeps = []

    def fake_urlopen(req, timeout=None):
        calls["count"] += 1
        if calls["count"] < 3:
            raise oc.urllib.error.URLError("dns lookup failed")
        return DummyResponse({"output": [{"type": "output_text", "text": "hello"}], "usage": {"input_tokens": 1}})

    monkeypatch.setattr(oc.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(oc.time, "sleep", lambda seconds: sleeps.append(round(float(seconds), 2)))
    resp = oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))
    assert oc.extract_text(resp) == "hello"
    assert calls["count"] == 3
    assert len(sleeps) == 2


def test_openai_retries_retryable_http_error(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    routing = {"mode": "openai", "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"}}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    calls = {"count": 0}
    sleeps = []

    def fake_urlopen(req, timeout=None):
        calls["count"] += 1
        if calls["count"] == 1:
            body = {"error": {"message": "rate limited", "type": "rate_limit_error"}}
            raise oc.urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", hdrs=None, fp=BytesIO(json.dumps(body).encode("utf-8")))
        return DummyResponse({"output": [{"type": "output_text", "text": "ok"}], "usage": {"input_tokens": 1}})

    monkeypatch.setattr(oc.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(oc.time, "sleep", lambda seconds: sleeps.append(round(float(seconds), 2)))
    resp = oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))
    assert oc.extract_text(resp) == "ok"
    assert calls["count"] == 2
    assert len(sleeps) == 1


def test_responses_create_openai_compatible_chat_provider(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("KIMI_API_KEY", "kimi-test")
    routing = {
        "mode": "openai",
        "api_provider": "kimi",
        "providers": {
            "kimi": {
                "kind": "openai_chat",
                "base_url": "https://kimi.example/v1",
                "chat_completions_endpoint": "/chat/completions",
                "api_key_env": "KIMI_API_KEY",
            }
        },
    }
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return DummyResponse({"choices": [{"message": {"content": "chat-ok"}}], "usage": {"total_tokens": 3}})

    monkeypatch.setattr(oc.urllib.request, "urlopen", fake_urlopen)
    resp = oc.responses_create("kimi-model", [{"role": "user", "content": "hi"}], routing_path=str(route_path))
    assert captured["url"] == "https://kimi.example/v1/chat/completions"
    assert captured["auth"] == "Bearer kimi-test"
    assert captured["payload"]["messages"][0]["content"] == "hi"
    assert oc.extract_text(resp) == "chat-ok"
    assert oc.extract_usage(resp)["total_tokens"] == 3


def test_responses_create_anthropic_provider(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")
    routing = {
        "mode": "openai",
        "api_provider": "anthropic",
        "providers": {
            "anthropic": {
                "kind": "anthropic_messages",
                "base_url": "https://anthropic.example/v1",
                "messages_endpoint": "/messages",
                "api_key_env": "ANTHROPIC_API_KEY",
            }
        },
    }
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["version"] = req.get_header("Anthropic-version")
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return DummyResponse({"content": [{"type": "text", "text": "anthropic-ok"}], "usage": {"input_tokens": 1, "output_tokens": 2}})

    monkeypatch.setattr(oc.urllib.request, "urlopen", fake_urlopen)
    resp = oc.responses_create(
        "claude-test",
        [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "hi"}],
        routing_path=str(route_path),
        max_output_tokens=50,
    )
    assert captured["url"] == "https://anthropic.example/v1/messages"
    assert captured["auth"] == "Bearer anthropic-test"
    assert captured["version"] == "2023-06-01"
    assert captured["payload"]["system"] == "Be brief."
    assert captured["payload"]["messages"][0]["content"] == "hi"
    assert oc.extract_text(resp) == "anthropic-ok"
    assert oc.extract_usage(resp)["output_tokens"] == 2


def test_api_provider_status_uses_generic_override_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "generic-key")
    routing = {
        "mode": "openai",
        "api_provider": "anthropic",
        "providers": {"anthropic": {"kind": "anthropic_messages", "base_url": "https://anthropic.example/v1", "api_key_env": "ANTHROPIC_API_KEY"}},
    }
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    status = oc.api_provider_status(str(route_path))
    assert status["connected"] is True
    assert status["provider"] == "anthropic"
    assert status["auth_source"] == "LLM_API_KEY"


def test_responses_create_uses_cache_openai(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("LLM_CACHE", "1")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    routing = {"mode": "openai", "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"}}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")

    url = "https://api.openai.com/v1/responses"
    payload = {
        "model": "gpt-5.2",
        "input": [{"role": "user", "content": "hi"}],
        "temperature": 0.1,
        "reasoning": {"effort": "low"},
    }
    key = oc._cache_key({"mode": "api", "provider": "openai", "kind": "openai_responses", "url": url, "payload": payload})
    cache_path = Path(os.environ["LLM_CACHE_DIR"]) / f"{key}.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"output": [{"type": "output_text", "text": "cached"}], "usage": {}}), encoding="utf-8")

    monkeypatch.setattr(oc.urllib.request, "urlopen", lambda req: (_ for _ in ()).throw(AssertionError("Should not call")))
    resp = oc.responses_create(
        "gpt-5.2",
        [{"role": "user", "content": "hi"}],
        temperature=0.1,
        reasoning="low",
        routing_path=str(route_path),
    )
    assert resp.get("cached") is True
    assert oc.extract_text(resp) == "cached"


def test_responses_create_uses_cache_codex(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CACHE", "1")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    routing = {"mode": "openai", "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"}}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setenv("LLM_MODE", "codex_local")
    monkeypatch.setattr(oc, "resolve_codex_runtime", lambda: fake_codex_runtime())

    prompt = oc._messages_to_prompt([{"role": "user", "content": "hi"}])
    key = oc._cache_key(oc._codex_cache_payload("gpt-5.2", prompt, None, fake_codex_runtime()))
    cache_path = Path(os.environ["LLM_CACHE_DIR"]) / f"{key}.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"output": [{"type": "output_text", "text": "cached"}], "usage": {}}), encoding="utf-8")

    monkeypatch.setattr(oc.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Should not call")))
    resp = oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))
    assert resp.get("cached") is True
    assert oc.extract_text(resp) == "cached"


def test_cache_get_miss_and_bad_json_and_non_dict(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CACHE", "1")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    assert oc._cache_get("missing") is None
    bad = Path(os.environ["LLM_CACHE_DIR"]) / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert oc._cache_get("bad") is None
    non_dict_key = oc._cache_key({"x": 1})
    non_dict_path = Path(os.environ["LLM_CACHE_DIR"]) / f"{non_dict_key}.json"
    non_dict_path.write_text(json.dumps(["x"]), encoding="utf-8")
    assert oc._cache_get(non_dict_key) is None


def test_cache_put_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CACHE", "1")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    key = oc._cache_key({"a": 1})
    oc._cache_put(key, {"ok": True})
    path = Path(os.environ["LLM_CACHE_DIR"]) / f"{key}.json"
    assert json.loads(path.read_text(encoding="utf-8"))["ok"] is True


def test_responses_create_writes_cache_openai(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("LLM_CACHE", "1")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    routing = {"mode": "openai", "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"}}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")

    def fake_urlopen(req, timeout=None):
        return DummyResponse({"output": [{"type": "output_text", "text": "hello"}], "usage": {"input_tokens": 1}})

    monkeypatch.setattr(oc.urllib.request, "urlopen", fake_urlopen)
    resp = oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], temperature=0.1, reasoning="low",
                               routing_path=str(route_path))
    assert oc.extract_text(resp) == "hello"

    url = "https://api.openai.com/v1/responses"
    payload = {
        "model": "gpt-5.2",
        "input": [{"role": "user", "content": "hi"}],
        "temperature": 0.1,
        "reasoning": {"effort": "low"},
    }
    key = oc._cache_key({"mode": "api", "provider": "openai", "kind": "openai_responses", "url": url, "payload": payload})
    cache_path = Path(os.environ["LLM_CACHE_DIR"]) / f"{key}.json"
    assert cache_path.exists()


def test_responses_create_writes_cache_codex(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CACHE", "1")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    routing = {"mode": "openai", "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"}}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setenv("LLM_MODE", "codex_local")
    monkeypatch.setattr(oc, "resolve_codex_runtime", lambda: fake_codex_runtime())

    def fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
        raw = "\n".join([
            json.dumps({"role": "user", "content": [{"type": "input_text", "text": "hi"}], "type": "message"}),
            json.dumps({"role": "assistant", "content": [{"type": "output_text", "text": "ok"}]}),
        ])
        return type("Result", (), {"returncode": 0, "stdout": raw, "stderr": ""})()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    resp = oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))
    assert oc.extract_text(resp) == "ok"
    prompt = oc._messages_to_prompt([{"role": "user", "content": "hi"}])
    key = oc._cache_key(oc._codex_cache_payload("gpt-5.2", prompt, None, fake_codex_runtime()))
    cache_path = Path(os.environ["LLM_CACHE_DIR"]) / f"{key}.json"
    assert cache_path.exists()

def test_responses_create_codex_success(tmp_path, monkeypatch):
    routing = {"mode": "openai", "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"}}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setenv("LLM_MODE", "codex_local")
    monkeypatch.setattr(oc, "resolve_codex_runtime", lambda: fake_codex_runtime())
    captured = {}

    def fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
        captured["cmd"] = cmd
        content = cmd[-1]
        assert "USER: hi" in content
        raw = "\n".join([
            json.dumps({"role": "user", "content": [{"type": "input_text", "text": "hi"}], "type": "message"}),
            json.dumps({"role": "assistant", "content": [{"type": "output_text", "text": "ok"}]}),
        ])
        return type("Result", (), {"returncode": 0, "stdout": raw, "stderr": ""})()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    resp = oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))
    assert oc.extract_text(resp) == "ok"
    assert oc.extract_usage(resp) == {}
    assert captured["cmd"][0] == "/usr/bin/codex"


def test_responses_create_codex_exec_uses_output_last_message(tmp_path, monkeypatch):
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps({"mode": "codex_local"}), encoding="utf-8")
    monkeypatch.setenv("LLM_MODE", "codex_local")
    monkeypatch.setattr(oc, "resolve_codex_runtime", lambda: fake_codex_runtime("exec"))
    captured = {}

    def fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
        captured["cmd"] = cmd
        output_path = Path(cmd[cmd.index("--output-last-message") + 1])
        output_path.write_text("exec-ok", encoding="utf-8")
        return type("Result", (), {"returncode": 0, "stdout": "noisy logs", "stderr": ""})()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    resp = oc.responses_create("gpt-5.4-mini", [{"role": "user", "content": "hi"}], routing_path=str(route_path))
    assert captured["cmd"][:2] == ["/usr/bin/codex", "exec"]
    assert "--ignore-user-config" in captured["cmd"]
    assert "--output-last-message" in captured["cmd"]
    assert oc.extract_text(resp) == "exec-ok"


def test_codex_output_text_parses_json_lines():
    raw = "\n".join([
        json.dumps({"role": "user", "content": [{"type": "input_text", "text": "hi"}], "type": "message"}),
        json.dumps({"role": "assistant", "content": [{"type": "output_text", "text": "OK"}]}),
    ])
    assert oc._codex_output_text(raw) == "OK"


def test_codex_output_text_passthrough():
    assert oc._codex_output_text("plain response") == "plain response"


def test_codex_output_text_assistant_text_field():
    raw = json.dumps({"role": "assistant", "text": "Direct"})
    assert oc._codex_output_text(raw) == "Direct"


def test_codex_output_text_no_assistant():
    raw = json.dumps({"role": "user", "content": [{"type": "input_text", "text": "hi"}]})
    with pytest.raises(ValueError):
        oc._codex_output_text(raw)


def test_codex_output_text_no_output_text():
    raw = json.dumps({"role": "assistant", "content": [{"type": "other", "text": "x"}]})
    with pytest.raises(ValueError):
        oc._codex_output_text(raw)


def test_codex_output_text_non_list_content():
    raw = json.dumps({"role": "assistant", "content": "oops", "text": "Direct"})
    assert oc._codex_output_text(raw) == "Direct"


def test_codex_output_text_empty_raw():
    assert oc._codex_output_text("") == ""


def test_responses_create_codex_missing(monkeypatch, tmp_path):
    routing = {"mode": "codex_local"}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setattr(oc, "resolve_codex_runtime", lambda: {"available": False, "error": "Codex CLI not found"})
    with pytest.raises(RuntimeError):
        oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))


def test_responses_create_codex_failure(tmp_path, monkeypatch):
    routing = {"mode": "codex_local"}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setattr(oc, "resolve_codex_runtime", lambda: fake_codex_runtime())

    def fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
        return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))


def test_responses_create_codex_missing_assistant(tmp_path, monkeypatch):
    routing = {"mode": "codex_local"}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setattr(oc, "resolve_codex_runtime", lambda: fake_codex_runtime())
    expected_raw = json.dumps({"role": "user", "content": [{"type": "input_text", "text": "hi"}]})

    def fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
        return type("Result", (), {"returncode": 0, "stdout": expected_raw, "stderr": ""})()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    resp = oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))
    assert oc.extract_text(resp) == expected_raw


def test_responses_create_codex_retry_then_success(tmp_path, monkeypatch):
    routing = {"mode": "codex_local"}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setattr(oc, "resolve_codex_runtime", lambda: fake_codex_runtime())
    calls = {"count": 0}

    def fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raw = json.dumps({"role": "user", "content": [{"type": "input_text", "text": "hi"}]})
            return type("Result", (), {"returncode": 0, "stdout": raw, "stderr": ""})()
        raw = "\n".join([
            json.dumps({"role": "user", "content": [{"type": "input_text", "text": "hi"}], "type": "message"}),
            json.dumps({"role": "assistant", "content": [{"type": "output_text", "text": "ok"}]}),
        ])
        return type("Result", (), {"returncode": 0, "stdout": raw, "stderr": ""})()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    resp = oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))
    assert oc.extract_text(resp) == "ok"


def test_extract_text_nested():
    resp = {"output": [{"content": [{"type": "output_text", "text": "nested"}]}]}
    assert oc.extract_text(resp) == "nested"


def test_extract_text_non_list_content():
    resp = {"output": [{"type": "output_text", "text": "hi", "content": "oops"}]}
    assert oc.extract_text(resp) == "hi"


def test_extract_text_empty_list_content():
    resp = {"output": [{"type": "output_text", "text": "hi", "content": []}]}
    assert oc.extract_text(resp) == "hi"


def test_extract_text_no_content_key():
    resp = {"output": [{"type": "output_text", "text": "hi"}]}
    assert oc.extract_text(resp) == "hi"


def test_extract_text_non_text_content():
    resp = {"output": [{"content": [{"type": "other", "text": "x"}]}]}
    assert oc.extract_text(resp) == ""


def test_extract_text_empty():
    assert oc.extract_text({"output": []}) == ""


def test_load_routing(tmp_path):
    path = tmp_path / "routing.json"
    path.write_text('{"openai": {"base_url": "x"}}', encoding="utf-8")
    cfg = oc.load_routing(path)
    assert cfg["openai"]["base_url"] == "x"


def test_timeout_seconds_invalid_env(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "nope")
    assert oc._timeout_seconds() == 180.0


def test_timeout_seconds_negative_env(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "-5")
    assert oc._timeout_seconds() == 180.0


def test_codex_timeout_seconds_defaults_longer(monkeypatch):
    monkeypatch.delenv("CODEX_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
    assert oc._codex_timeout_seconds() == 600.0


def test_codex_timeout_seconds_uses_specific_override(monkeypatch):
    monkeypatch.setenv("CODEX_TIMEOUT_SECONDS", "900")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "120")
    assert oc._codex_timeout_seconds() == 900.0


def test_codex_timeout_seconds_falls_back_to_llm_override(monkeypatch):
    monkeypatch.delenv("CODEX_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "240")
    assert oc._codex_timeout_seconds() == 240.0


def test_codex_timeout_raises_runtime_error(tmp_path, monkeypatch):
    routing = {"mode": "codex_local"}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setenv("LLM_MODE", "codex_local")
    monkeypatch.setattr(oc, "resolve_codex_runtime", lambda: fake_codex_runtime())

    def fake_run(*args, **kwargs):
        raise oc.subprocess.TimeoutExpired(cmd="codex", timeout=1)

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))


def test_codex_empty_output_raises_runtime_error(tmp_path, monkeypatch):
    routing = {"mode": "codex_local"}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setenv("LLM_MODE", "codex_local")
    monkeypatch.setattr(oc, "resolve_codex_runtime", lambda: fake_codex_runtime())

    def fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))
