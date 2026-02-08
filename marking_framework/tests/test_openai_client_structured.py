import json

import scripts.openai_client as oc


def test_schema_required_keys_and_contract_hint():
    fmt = {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "required": ["student_id", "rubric_total_points"],
            "properties": {"student_id": {"type": "string"}},
        },
    }
    assert oc._schema_required_keys(fmt) == ["student_id", "rubric_total_points"]
    hint = oc._structured_contract_hint(fmt)
    assert "IMPORTANT OUTPUT CONTRACT" in hint
    assert "student_id" in hint
    assert oc._schema_required_keys(None) == []
    assert oc._schema_required_keys({"type": "json_object"}) == []
    assert oc._structured_contract_hint({"type": "json_schema", "schema": "bad"}) == ""
    assert oc._structured_contract_hint({"type": "json_object"}) == ""


def test_json_candidates_and_coerce_structured_text():
    fmt = {
        "type": "json_schema",
        "schema": {"type": "object", "required": ["student_id", "rubric_total_points"]},
    }
    text = "noise {\"a\":1} middle {\"student_id\":\"s1\",\"rubric_total_points\":85,\"notes\":\"ok\"}"
    candidates = oc._json_candidates(text)
    assert len(candidates) == 2
    canonical = oc._coerce_structured_text(text, fmt)
    assert canonical is not None
    parsed = json.loads(canonical)
    assert parsed["student_id"] == "s1"
    assert parsed["rubric_total_points"] == 85

    missing = oc._coerce_structured_text("{\"student_id\":\"s1\"}", fmt)
    assert missing is None
    assert oc._coerce_structured_text("plain", None) is None
    assert oc._json_candidates("{bad json} {\"student_id\":\"s1\",\"rubric_total_points\":77}")[-1]["student_id"] == "s1"


def test_build_codex_prompt_with_previous_output():
    messages = [{"role": "user", "content": "Grade this."}]
    fmt = {
        "type": "json_schema",
        "schema": {"type": "object", "required": ["student_id"]},
    }
    prompt = oc._build_codex_prompt(messages, fmt, "bad output")
    assert "USER: Grade this." in prompt
    assert "IMPORTANT OUTPUT CONTRACT" in prompt
    assert "Previous output violated the contract" in prompt


def test_responses_create_codex_structured_retry_and_canonical(tmp_path, monkeypatch):
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps({"mode": "codex_local"}), encoding="utf-8")
    monkeypatch.setenv("LLM_MODE", "codex_local")
    monkeypatch.setattr(oc.shutil, "which", lambda _: "/usr/bin/codex")

    calls = {"n": 0, "prompts": []}

    def fake_run(cmd, capture_output=None, text=None, timeout=None):
        calls["n"] += 1
        calls["prompts"].append(cmd[-1])
        if calls["n"] == 1:
            return type("Result", (), {"returncode": 0, "stdout": "not json", "stderr": ""})()
        stdout = "prefix {\"student_id\":\"s1\",\"rubric_total_points\":84,\"criteria_points\":{},\"notes\":\"ok\"} suffix"
        return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)

    fmt = {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "required": ["student_id", "rubric_total_points", "criteria_points", "notes"],
        },
    }
    resp = oc.responses_create(
        "gpt-5.2",
        [{"role": "user", "content": "hi"}],
        routing_path=str(route_path),
        text_format=fmt,
    )
    parsed = json.loads(oc.extract_text(resp))
    assert parsed["student_id"] == "s1"
    assert calls["n"] == 2
    assert "Previous output violated the contract" in calls["prompts"][1]


def test_responses_create_codex_structured_from_raw_without_assistant(tmp_path, monkeypatch):
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps({"mode": "codex_local"}), encoding="utf-8")
    monkeypatch.setenv("LLM_MODE", "codex_local")
    monkeypatch.setattr(oc.shutil, "which", lambda _: "/usr/bin/codex")

    def fake_run(cmd, capture_output=None, text=None, timeout=None):
        stdout = json.dumps({"student_id": "s7", "rubric_total_points": 73, "criteria_points": {}, "notes": "ok"})
        return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)

    fmt = {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "required": ["student_id", "rubric_total_points", "criteria_points", "notes"],
        },
    }
    resp = oc.responses_create(
        "gpt-5.2",
        [{"role": "user", "content": "hi"}],
        routing_path=str(route_path),
        text_format=fmt,
    )
    parsed = json.loads(oc.extract_text(resp))
    assert parsed["student_id"] == "s7"
    assert parsed["rubric_total_points"] == 73


def test_responses_create_codex_structured_cache_hit(tmp_path, monkeypatch):
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps({"mode": "codex_local"}), encoding="utf-8")
    monkeypatch.setenv("LLM_MODE", "codex_local")
    monkeypatch.setenv("LLM_CACHE", "1")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(oc.shutil, "which", lambda _: "/usr/bin/codex")
    fmt = {"type": "json_schema", "schema": {"type": "object", "required": ["student_id"]}}
    normalized = oc._normalized_text_format(fmt)
    prompt = oc._build_codex_prompt([{"role": "user", "content": "hi"}], normalized)
    key = oc._cache_key({"mode": "codex_local", "model": "gpt-5.2", "prompt": prompt, "text_format": normalized})
    path = tmp_path / "cache" / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"output": [{"type": "output_text", "text": "{\"student_id\":\"s1\"}"}], "usage": {}}), encoding="utf-8")
    monkeypatch.setattr(oc.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("cache miss")))
    resp = oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path), text_format=fmt)
    assert json.loads(oc.extract_text(resp))["student_id"] == "s1"


def test_responses_create_codex_structured_from_extracted_path(tmp_path, monkeypatch):
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps({"mode": "codex_local"}), encoding="utf-8")
    monkeypatch.setenv("LLM_MODE", "codex_local")
    monkeypatch.setattr(oc.shutil, "which", lambda _: "/usr/bin/codex")
    fmt = {
        "type": "json_schema",
        "schema": {"type": "object", "required": ["student_id", "rubric_total_points", "criteria_points", "notes"]},
    }

    def fake_run(cmd, capture_output=None, text=None, timeout=None):
        raw = "\n".join([
            json.dumps({"role": "user", "content": [{"type": "input_text", "text": "prompt"}]}),
            json.dumps({"role": "assistant", "content": [{"type": "output_text", "text": "{\"student_id\":\"s9\",\"rubric_total_points\":81,\"criteria_points\":{},\"notes\":\"ok\"}"}]}),
        ])
        return type("Result", (), {"returncode": 0, "stdout": raw, "stderr": ""})()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    resp = oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path), text_format=fmt)
    assert json.loads(oc.extract_text(resp))["student_id"] == "s9"


def test_responses_create_codex_structured_valueerror_repair(tmp_path, monkeypatch):
    route_path = tmp_path / "routing.json"
    route_path.write_text(json.dumps({"mode": "codex_local"}), encoding="utf-8")
    monkeypatch.setenv("LLM_MODE", "codex_local")
    monkeypatch.setattr(oc.shutil, "which", lambda _: "/usr/bin/codex")
    fmt = {"type": "json_schema", "schema": {"type": "object", "required": ["student_id"]}}
    prompts = []
    calls = {"n": 0}

    def fake_run(cmd, capture_output=None, text=None, timeout=None):
        calls["n"] += 1
        prompts.append(cmd[-1])
        if calls["n"] == 1:
            # No assistant event; triggers ValueError path and repair prompt update.
            raw = json.dumps({"role": "user", "content": [{"type": "input_text", "text": "hi"}]})
            return type("Result", (), {"returncode": 0, "stdout": raw, "stderr": ""})()
        raw = json.dumps({"student_id": "s2"})
        return type("Result", (), {"returncode": 0, "stdout": raw, "stderr": ""})()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    resp = oc.responses_create("gpt-5.2", [{"role": "user", "content": "hi"}], routing_path=str(route_path), text_format=fmt)
    assert json.loads(oc.extract_text(resp))["student_id"] == "s2"
    assert calls["n"] == 2
    assert "Previous output violated the contract" in prompts[1]
