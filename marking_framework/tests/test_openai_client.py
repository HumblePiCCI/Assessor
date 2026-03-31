import json
import os
from io import BytesIO
from pathlib import Path

import pytest

import scripts.openai_client as oc


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
    key = oc._cache_key({"mode": "openai", "url": url, "payload": payload})
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
    monkeypatch.setattr(oc.shutil, "which", lambda _: "/usr/bin/codex")

    prompt = oc._messages_to_prompt([{"role": "user", "content": "hi"}])
    key = oc._cache_key({"mode": "codex_local", "model": "gpt-5.2", "prompt": prompt, "text_format": None})
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
    key = oc._cache_key({"mode": "openai", "url": url, "payload": payload})
    cache_path = Path(os.environ["LLM_CACHE_DIR"]) / f"{key}.json"
    assert cache_path.exists()


def test_responses_create_writes_cache_codex(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CACHE", "1")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    routing = {"mode": "openai", "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"}}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setenv("LLM_MODE", "codex_local")
    monkeypatch.setattr(oc.shutil, "which", lambda _: "/usr/bin/codex")

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
    key = oc._cache_key({"mode": "codex_local", "model": "gpt-5.2", "prompt": prompt, "text_format": None})
    cache_path = Path(os.environ["LLM_CACHE_DIR"]) / f"{key}.json"
    assert cache_path.exists()

def test_responses_create_codex_success(tmp_path, monkeypatch):
    routing = {"mode": "openai", "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"}}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setenv("LLM_MODE", "codex_local")
    monkeypatch.setattr(oc.shutil, "which", lambda _: "/usr/bin/codex")
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
    assert captured["cmd"][0] == "codex"


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
    monkeypatch.setattr(oc.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError):
        oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))


def test_responses_create_codex_failure(tmp_path, monkeypatch):
    routing = {"mode": "codex_local"}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setattr(oc.shutil, "which", lambda _: "/usr/bin/codex")

    def fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
        return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))


def test_responses_create_codex_missing_assistant(tmp_path, monkeypatch):
    routing = {"mode": "codex_local"}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setattr(oc.shutil, "which", lambda _: "/usr/bin/codex")
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
    monkeypatch.setattr(oc.shutil, "which", lambda _: "/usr/bin/codex")
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


def test_codex_timeout_raises_runtime_error(tmp_path, monkeypatch):
    routing = {"mode": "codex_local"}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setenv("LLM_MODE", "codex_local")
    monkeypatch.setattr(oc.shutil, "which", lambda _: "/usr/bin/codex")

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
    monkeypatch.setattr(oc.shutil, "which", lambda _: "/usr/bin/codex")

    def fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))
