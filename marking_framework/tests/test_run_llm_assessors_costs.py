import json
from pathlib import Path

import scripts.run_llm_assessors as rla


def write_config(path: Path, data: dict):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_run_llm_assessors_preflight_abort(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("A" * 1000, encoding="utf-8")

    routing = {
        "mode": "openai",
        "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}
    }
    pricing = {"models": {"gpt-5.2": {"input_per_million": 1.0, "output_per_million": 1.0}}}
    limits = {"per_call_max_tokens": 1, "abort_on_limit": True, "estimates": {"pass1_output_tokens": 1, "pass2_output_tokens": 1}}

    write_config(tmp_path / "routing.json", routing)
    write_config(tmp_path / "pricing.json", pricing)
    write_config(tmp_path / "limits.json", limits)

    monkeypatch.setattr("sys.argv", [
        "rla",
        "--texts", str(texts_dir),
        "--routing", str(tmp_path / "routing.json"),
        "--pricing", str(tmp_path / "pricing.json"),
        "--cost-limits", str(tmp_path / "limits.json"),
        "--rubric", str(tmp_path / "rubric.md"),
        "--outline", str(tmp_path / "outline.md"),
        "--rubric-criteria", str(tmp_path / "no_criteria.json"),
    ])
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")
    assert rla.main() == 1


def test_run_llm_assessors_ignore_limits(tmp_path, monkeypatch):
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
    limits = {"per_call_max_tokens": 1, "abort_on_limit": True, "estimates": {"pass1_output_tokens": 1, "pass2_output_tokens": 1}}

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
        "--ignore-cost-limits",
    ])
    assert rla.main() == 0


def test_run_llm_assessors_cost_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Sample essay text", encoding="utf-8")

    routing = {
        "mode": "openai",
        "tasks": {
            "pass1_assessor": {"model": "gpt-5.2", "reasoning": "low", "temperature": 0.1},
            "pass2_ranker": {"model": "gpt-5.2", "reasoning": "low", "temperature": 0.1},
        }
    }
    pricing = {"models": {"gpt-5.2": {"input_per_million": 1000.0, "output_per_million": 1000.0}}}
    limits = {"per_call_max_tokens": 8000, "abort_on_limit": False, "per_student_max_usd": 0.01, "per_job_max_usd": 0.01, "alert_at_percent": 50, "estimates": {"pass1_output_tokens": 10, "pass2_output_tokens": 10}}

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


def test_run_llm_assessors_preflight_fail_no_abort(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("A" * 1000, encoding="utf-8")

    routing = {"mode": "openai", "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}}
    pricing = {"models": {"gpt-5.2": {"input_per_million": 1.0, "output_per_million": 1.0}}}
    limits = {"per_call_max_tokens": 1, "abort_on_limit": False, "estimates": {"pass1_output_tokens": 1, "pass2_output_tokens": 1}}

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
    monkeypatch.setattr("sys.argv", [
        "rla",
        "--texts", str(texts_dir),
        "--routing", str(tmp_path / "routing.json"),
        "--pricing", str(tmp_path / "pricing.json"),
        "--cost-limits", str(tmp_path / "limits.json"),
        "--rubric", str(tmp_path / "rubric.md"),
        "--outline", str(tmp_path / "outline.md"),
        "--rubric-criteria", str(tmp_path / "no_criteria.json"),
        "--pass1-out", str(tmp_path / "pass1"),
        "--pass2-out", str(tmp_path / "pass2"),
    ])
    assert rla.main() == 0


def test_run_llm_assessors_cost_limit_abort_student(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Sample essay text", encoding="utf-8")

    routing = {"mode": "openai", "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}}
    pricing = {"models": {"gpt-5.2": {"input_per_million": 1000.0, "output_per_million": 1000.0}}}
    limits = {"per_call_max_tokens": 8000, "abort_on_limit": True, "per_student_max_usd": 0.00001, "estimates": {"pass1_output_tokens": 10, "pass2_output_tokens": 10}}

    write_config(tmp_path / "routing.json", routing)
    write_config(tmp_path / "pricing.json", pricing)
    write_config(tmp_path / "limits.json", limits)
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")

    monkeypatch.setattr("sys.argv", [
        "rla",
        "--texts", str(texts_dir),
        "--routing", str(tmp_path / "routing.json"),
        "--pricing", str(tmp_path / "pricing.json"),
        "--cost-limits", str(tmp_path / "limits.json"),
        "--rubric", str(tmp_path / "rubric.md"),
        "--outline", str(tmp_path / "outline.md"),
        "--rubric-criteria", str(tmp_path / "no_criteria.json"),
    ])
    assert rla.main() == 1


def test_run_llm_assessors_cost_limit_abort_job(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Sample essay text", encoding="utf-8")

    routing = {"mode": "openai", "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}}
    pricing = {"models": {"gpt-5.2": {"input_per_million": 1000.0, "output_per_million": 1000.0}}}
    limits = {"per_call_max_tokens": 8000, "abort_on_limit": True, "per_job_max_usd": 0.00001, "estimates": {"pass1_output_tokens": 10, "pass2_output_tokens": 10}}

    write_config(tmp_path / "routing.json", routing)
    write_config(tmp_path / "pricing.json", pricing)
    write_config(tmp_path / "limits.json", limits)
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")

    monkeypatch.setattr("sys.argv", [
        "rla",
        "--texts", str(texts_dir),
        "--routing", str(tmp_path / "routing.json"),
        "--pricing", str(tmp_path / "pricing.json"),
        "--cost-limits", str(tmp_path / "limits.json"),
        "--rubric", str(tmp_path / "rubric.md"),
        "--outline", str(tmp_path / "outline.md"),
        "--rubric-criteria", str(tmp_path / "no_criteria.json"),
    ])
    assert rla.main() == 1
