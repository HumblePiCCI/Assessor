import json
import os
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

    def fake_urlopen(req):
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

    def fake_urlopen(req):
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return DummyResponse({"output": [{"type": "output_text", "text": "hello"}], "usage": {"input_tokens": 1}})

    monkeypatch.setattr(oc.urllib.request, "urlopen", fake_urlopen)
    oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))
    assert "text" not in captured["payload"]


def test_responses_create_codex_success(tmp_path, monkeypatch):
    routing = {"mode": "openai", "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"}}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setenv("LLM_MODE", "codex_local")
    monkeypatch.setattr(oc.shutil, "which", lambda _: "/usr/bin/codex")
    captured = {}

    def fake_run(cmd, cwd=None, capture_output=None, text=None):
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

    def fake_run(cmd, cwd=None, capture_output=None, text=None):
        return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))


def test_responses_create_codex_missing_assistant(tmp_path, monkeypatch):
    routing = {"mode": "codex_local"}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setattr(oc.shutil, "which", lambda _: "/usr/bin/codex")

    def fake_run(cmd, cwd=None, capture_output=None, text=None):
        raw = json.dumps({"role": "user", "content": [{"type": "input_text", "text": "hi"}]})
        return type("Result", (), {"returncode": 0, "stdout": raw, "stderr": ""})()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path))


def test_responses_create_codex_retry_then_success(tmp_path, monkeypatch):
    routing = {"mode": "codex_local"}
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setattr(oc.shutil, "which", lambda _: "/usr/bin/codex")
    calls = {"count": 0}

    def fake_run(cmd, cwd=None, capture_output=None, text=None):
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
