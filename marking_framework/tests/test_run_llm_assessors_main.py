import json
from pathlib import Path

import pytest

import scripts.run_llm_assessors as rla


def write_config(path: Path, data: dict):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_run_llm_assessors_no_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    routing = {"mode": "openai", "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}}
    write_config(tmp_path / "routing.json", routing)
    monkeypatch.setattr("sys.argv", ["rla", "--routing", str(tmp_path / "routing.json")])
    assert rla.main() == 1


def test_run_llm_assessors_empty_rubric(tmp_path, monkeypatch):
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Essay text", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")
    routing = {"mode": "codex_local", "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}}
    write_config(tmp_path / "routing.json", routing)
    monkeypatch.setattr("sys.argv", [
        "rla",
        "--texts", str(texts_dir),
        "--routing", str(tmp_path / "routing.json"),
        "--rubric", str(tmp_path / "rubric.md"),
        "--outline", str(tmp_path / "outline.md"),
        "--rubric-criteria", str(tmp_path / "no_criteria.json"),
    ])
    assert rla.main() == 1


def test_run_llm_assessors_success(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Sample essay text", encoding="utf-8")

    routing = {
        "mode": "openai",
        "tasks": {
            "pass1_assessor": {"model": "gpt-5.2", "reasoning": "low", "temperature": 0.1},
            "pass2_ranker": {"model": "gpt-5.2", "reasoning": "low", "temperature": 0.1},
        },
        "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"},
    }
    pricing = {"models": {"gpt-5.2": {"input_per_million": 1.0, "output_per_million": 1.0}}}
    limits = {"per_call_max_tokens": 8000, "abort_on_limit": False, "per_job_max_usd": 999, "per_student_max_usd": 999, "estimates": {"pass1_output_tokens": 10, "pass2_output_tokens": 10}}

    write_config(tmp_path / "routing.json", routing)
    write_config(tmp_path / "pricing.json", pricing)
    write_config(tmp_path / "limits.json", limits)
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")

    calls = {"count": 0}

    def fake_response(prompt):
        if "Return ONLY valid JSON" in prompt:
            calls["count"] += 1
            if calls["count"] == 1:
                text = "not json"
            else:
                text = json.dumps({"student_id": "s1", "rubric_total_points": 10, "criteria_points": {}, "notes": "ok"})
        else:
            text = "s1"
        return {
            "output": [{"type": "output_text", "text": text}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    def fake_create(model, messages, temperature, reasoning, routing_path, **kwargs):
        return fake_response(messages[0]["content"])

    monkeypatch.setattr(rla, "responses_create", fake_create)

    pass1_out = tmp_path / "pass1"
    pass2_out = tmp_path / "pass2"

    monkeypatch.setattr("sys.argv", [
        "rla",
        "--texts", str(texts_dir),
        "--routing", str(tmp_path / "routing.json"),
        "--pricing", str(tmp_path / "pricing.json"),
        "--cost-limits", str(tmp_path / "limits.json"),
        "--rubric", str(tmp_path / "rubric.md"),
        "--outline", str(tmp_path / "outline.md"),
        "--rubric-criteria", str(tmp_path / "no_criteria.json"),
        "--pass1-out", str(pass1_out),
        "--pass2-out", str(pass2_out),
    ])
    assert rla.main() == 0
    assert (pass1_out / "assessor_A.json").exists()
    assert (pass2_out / "assessor_A.txt").exists()


def test_run_llm_assessors_custom_exemplars(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Sample essay text", encoding="utf-8")
    routing = {
        "mode": "openai",
        "tasks": {
            "pass1_assessor": {"model": "gpt-5.2", "reasoning": "low", "temperature": 0.1},
            "pass2_ranker": {"model": "gpt-5.2", "reasoning": "low", "temperature": 0.1},
        },
    }
    pricing = {"models": {"gpt-5.2": {"input_per_million": 1.0, "output_per_million": 1.0}}}
    limits = {"per_call_max_tokens": 8000, "abort_on_limit": False, "per_job_max_usd": 999, "per_student_max_usd": 999, "estimates": {"pass1_output_tokens": 10, "pass2_output_tokens": 10}}
    write_config(tmp_path / "routing.json", routing)
    write_config(tmp_path / "pricing.json", pricing)
    write_config(tmp_path / "limits.json", limits)
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")

    def fake_response(prompt):
        if "Return ONLY valid JSON" in prompt:
            text = json.dumps({"student_id": "s1", "rubric_total_points": 10, "criteria_points": {}, "notes": "ok"})
        else:
            text = "s1"
        return {"output": [{"type": "output_text", "text": text}], "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr(rla, "responses_create", lambda **kwargs: fake_response(kwargs["messages"][0]["content"]))

    custom_exemplars = tmp_path / "custom_exemplars"
    custom_exemplars.mkdir()
    pass1_out = tmp_path / "pass1"
    pass2_out = tmp_path / "pass2"

    monkeypatch.setattr("sys.argv", [
        "rla",
        "--texts", str(texts_dir),
        "--routing", str(tmp_path / "routing.json"),
        "--pricing", str(tmp_path / "pricing.json"),
        "--cost-limits", str(tmp_path / "limits.json"),
        "--rubric", str(tmp_path / "rubric.md"),
        "--outline", str(tmp_path / "outline.md"),
        "--rubric-criteria", str(tmp_path / "no_criteria.json"),
        "--pass1-out", str(pass1_out),
        "--pass2-out", str(pass2_out),
        "--exemplars", str(custom_exemplars),
    ])
    assert rla.main() == 0


def test_run_llm_assessors_pass2_repair_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Sample essay text", encoding="utf-8")
    (texts_dir / "s2.txt").write_text("More text", encoding="utf-8")
    routing = {
        "mode": "openai",
        "tasks": {
            "pass1_assessor": {"model": "gpt-5.2", "reasoning": "low", "temperature": 0.1},
            "pass2_ranker": {"model": "gpt-5.2", "reasoning": "low", "temperature": 0.1},
        },
    }
    pricing = {"models": {"gpt-5.2": {"input_per_million": 1.0, "output_per_million": 1.0}}}
    limits = {"per_call_max_tokens": 8000, "abort_on_limit": False, "per_job_max_usd": 999, "per_student_max_usd": 999, "estimates": {"pass1_output_tokens": 10, "pass2_output_tokens": 10}}
    write_config(tmp_path / "routing.json", routing)
    write_config(tmp_path / "pricing.json", pricing)
    write_config(tmp_path / "limits.json", limits)
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")

    def fake_create(model, messages, temperature, reasoning, routing_path, **kwargs):
        prompt = messages[0]["content"]
        if "Return ONLY valid JSON" in prompt:
            text = json.dumps({"student_id": "s1", "rubric_total_points": 10, "criteria_points": {}, "notes": "ok"})
        elif "Return ONLY a ranked list" in prompt:
            text = "s2\ns1"
        else:
            text = "s1"
        return {"output": [{"type": "output_text", "text": text}], "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr(rla, "responses_create", fake_create)
    pass1_out = tmp_path / "pass1"
    pass2_out = tmp_path / "pass2"
    monkeypatch.setattr("sys.argv", [
        "rla",
        "--texts", str(texts_dir),
        "--routing", str(tmp_path / "routing.json"),
        "--pricing", str(tmp_path / "pricing.json"),
        "--cost-limits", str(tmp_path / "limits.json"),
        "--rubric", str(tmp_path / "rubric.md"),
        "--outline", str(tmp_path / "outline.md"),
        "--rubric-criteria", str(tmp_path / "no_criteria.json"),
        "--pass1-out", str(pass1_out),
        "--pass2-out", str(pass2_out),
        "--assessors", "A",
    ])
    assert rla.main() == 0
    ranking = (pass2_out / "assessor_A.txt").read_text(encoding="utf-8").strip().splitlines()
    assert ranking == ["s2", "s1"]


def test_run_llm_assessors_pass2_repair_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Sample essay text", encoding="utf-8")
    (texts_dir / "s2.txt").write_text("More text", encoding="utf-8")
    routing = {
        "mode": "openai",
        "tasks": {
            "pass1_assessor": {"model": "gpt-5.2", "reasoning": "low", "temperature": 0.1},
            "pass2_ranker": {"model": "gpt-5.2", "reasoning": "low", "temperature": 0.1},
        },
    }
    pricing = {"models": {"gpt-5.2": {"input_per_million": 1.0, "output_per_million": 1.0}}}
    limits = {"per_call_max_tokens": 8000, "abort_on_limit": False, "per_job_max_usd": 999, "per_student_max_usd": 999, "estimates": {"pass1_output_tokens": 10, "pass2_output_tokens": 10}}
    write_config(tmp_path / "routing.json", routing)
    write_config(tmp_path / "pricing.json", pricing)
    write_config(tmp_path / "limits.json", limits)
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")

    def fake_create(model, messages, temperature, reasoning, routing_path, **kwargs):
        prompt = messages[0]["content"]
        if "Return ONLY valid JSON" in prompt:
            text = json.dumps({"student_id": "s1", "rubric_total_points": 10, "criteria_points": {}, "notes": "ok"})
        elif "Return ONLY a ranked list" in prompt:
            text = "unknown"
        else:
            text = "unknown"
        return {"output": [{"type": "output_text", "text": text}], "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr(rla, "responses_create", fake_create)
    pass1_out = tmp_path / "pass1"
    pass2_out = tmp_path / "pass2"
    monkeypatch.setattr("sys.argv", [
        "rla",
        "--texts", str(texts_dir),
        "--routing", str(tmp_path / "routing.json"),
        "--pricing", str(tmp_path / "pricing.json"),
        "--cost-limits", str(tmp_path / "limits.json"),
        "--rubric", str(tmp_path / "rubric.md"),
        "--outline", str(tmp_path / "outline.md"),
        "--rubric-criteria", str(tmp_path / "no_criteria.json"),
        "--pass1-out", str(pass1_out),
        "--pass2-out", str(pass2_out),
        "--assessors", "A",
    ])
    assert rla.main() == 0
    ranking = (pass2_out / "assessor_A.txt").read_text(encoding="utf-8").strip().splitlines()
    assert ranking == ["s1", "s2"]
    failure_log = tmp_path / "logs" / "llm_failures.jsonl"
    assert failure_log.exists()


def test_run_llm_assessors_pass2_repair_missing_append(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Sample essay text", encoding="utf-8")
    (texts_dir / "s2.txt").write_text("More text", encoding="utf-8")
    routing = {
        "mode": "openai",
        "tasks": {
            "pass1_assessor": {"model": "gpt-5.2", "reasoning": "low", "temperature": 0.1},
            "pass2_ranker": {"model": "gpt-5.2", "reasoning": "low", "temperature": 0.1},
        },
    }
    pricing = {"models": {"gpt-5.2": {"input_per_million": 1.0, "output_per_million": 1.0}}}
    limits = {"per_call_max_tokens": 8000, "abort_on_limit": False, "per_job_max_usd": 999, "per_student_max_usd": 999, "estimates": {"pass1_output_tokens": 10, "pass2_output_tokens": 10}}
    write_config(tmp_path / "routing.json", routing)
    write_config(tmp_path / "pricing.json", pricing)
    write_config(tmp_path / "limits.json", limits)
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")

    def fake_create(model, messages, temperature, reasoning, routing_path, **kwargs):
        prompt = messages[0]["content"]
        if "Return ONLY valid JSON" in prompt:
            text = json.dumps({"student_id": "s1", "rubric_total_points": 10, "criteria_points": {}, "notes": "ok"})
        elif "Return ONLY a ranked list" in prompt:
            text = "s1"
        else:
            text = "s1"
        return {"output": [{"type": "output_text", "text": text}], "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr(rla, "responses_create", fake_create)
    pass1_out = tmp_path / "pass1"
    pass2_out = tmp_path / "pass2"
    monkeypatch.setattr("sys.argv", [
        "rla",
        "--texts", str(texts_dir),
        "--routing", str(tmp_path / "routing.json"),
        "--pricing", str(tmp_path / "pricing.json"),
        "--cost-limits", str(tmp_path / "limits.json"),
        "--rubric", str(tmp_path / "rubric.md"),
        "--outline", str(tmp_path / "outline.md"),
        "--rubric-criteria", str(tmp_path / "no_criteria.json"),
        "--pass1-out", str(pass1_out),
        "--pass2-out", str(pass2_out),
        "--assessors", "A",
    ])
    assert rla.main() == 0
    ranking = (pass2_out / "assessor_A.txt").read_text(encoding="utf-8").strip().splitlines()
    assert ranking == ["s1", "s2"]
    failure_log = tmp_path / "logs" / "llm_failures.jsonl"
    assert failure_log.exists()
def test_run_llm_assessors_invalid_after_retry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Sample essay text", encoding="utf-8")
    routing = {
        "mode": "openai",
        "tasks": {
            "pass1_assessor": {"model": "gpt-5.2", "reasoning": "low", "temperature": 0.1},
            "pass2_ranker": {"model": "gpt-5.2", "reasoning": "low", "temperature": 0.1},
        },
        "openai": {"base_url": "https://api.openai.com/v1", "responses_endpoint": "/responses"},
    }
    pricing = {"models": {"gpt-5.2": {"input_per_million": 1.0, "output_per_million": 1.0}}}
    limits = {"per_call_max_tokens": 8000, "abort_on_limit": False, "per_job_max_usd": 999, "per_student_max_usd": 999, "estimates": {"pass1_output_tokens": 10, "pass2_output_tokens": 10}}
    write_config(tmp_path / "routing.json", routing)
    write_config(tmp_path / "pricing.json", pricing)
    write_config(tmp_path / "limits.json", limits)
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")

    def fake_create(model, messages, temperature, reasoning, routing_path, **kwargs):
        return {"output": [{"type": "output_text", "text": "not json"}], "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr(rla, "responses_create", fake_create)
    pass1_out = tmp_path / "pass1"
    pass2_out = tmp_path / "pass2"
    monkeypatch.setattr("sys.argv", [
        "rla",
        "--texts", str(texts_dir),
        "--routing", str(tmp_path / "routing.json"),
        "--pricing", str(tmp_path / "pricing.json"),
        "--cost-limits", str(tmp_path / "limits.json"),
        "--rubric", str(tmp_path / "rubric.md"),
        "--outline", str(tmp_path / "outline.md"),
        "--rubric-criteria", str(tmp_path / "no_criteria.json"),
        "--pass1-out", str(pass1_out),
        "--pass2-out", str(pass2_out),
        "--assessors", "A",
    ])
    with pytest.raises(ValueError):
        rla.main()
    failure_log = tmp_path / "logs" / "llm_failures.jsonl"
    assert failure_log.exists()
    lines = failure_log.read_text(encoding="utf-8").strip().splitlines()
    assert lines


def test_run_llm_assessors_codex_local_reqs_override(tmp_path, monkeypatch):
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Sample essay text", encoding="utf-8")
    routing = {"mode": "codex_local", "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}}
    write_config(tmp_path / "routing.json", routing)
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")
    criteria_path = tmp_path / "rubric_criteria.json"
    criteria_path.write_text(json.dumps({"evidence_requirements": {"quote_validation": True, "rationale_min_words": 5}}), encoding="utf-8")

    def fake_create(model, messages, temperature, reasoning, routing_path, **kwargs):
        prompt = messages[0]["content"]
        if "Return ONLY valid JSON" in prompt:
            text = json.dumps({
                "student_id": "s1",
                "rubric_total_points": 10,
                "criteria_points": {},
                "notes": "ok"
            })
        else:
            text = "s1"
        return {"output": [{"type": "output_text", "text": text}]}

    monkeypatch.setattr(rla, "responses_create", fake_create)
    pass1_out = tmp_path / "pass1"
    pass2_out = tmp_path / "pass2"
    monkeypatch.setattr("sys.argv", [
        "rla",
        "--texts", str(texts_dir),
        "--routing", str(tmp_path / "routing.json"),
        "--rubric", str(tmp_path / "rubric.md"),
        "--outline", str(tmp_path / "outline.md"),
        "--rubric-criteria", str(criteria_path),
        "--pass1-out", str(pass1_out),
        "--pass2-out", str(pass2_out),
        "--assessors", "A",
    ])
    assert rla.main() == 0
