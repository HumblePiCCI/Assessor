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


def test_run_llm_assessors_explicit_genre_skips_inference(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(rla, "infer_genre_from_text", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not infer")))
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Sample essay text", encoding="utf-8")
    write_config(
        tmp_path / "routing.json",
        {"mode": "openai", "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}},
    )
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")
    criteria_path = tmp_path / "criteria.json"
    criteria_path.write_text(
        json.dumps(
            {
                "categories": {
                    "communication": {
                        "criteria": [{"id": "C1", "name": "Expression", "description": "desc"}]
                    }
                },
                "genre_specific_criteria": {
                    "speech": {
                        "additional_criteria": [{"id": "SP1", "name": "Audience engagement", "description": "desc"}]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    prompts = []

    def fake_create(model, messages, temperature, reasoning, routing_path, **kwargs):
        prompt = messages[0]["content"]
        prompts.append(prompt)
        text = json.dumps({"student_id": "s1", "rubric_total_points": 10, "criteria_points": {}, "notes": "ok"})
        if "Return ONLY valid JSON" not in prompt:
            text = "s1"
        return {"output": [{"type": "output_text", "text": text}], "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr(rla, "responses_create", fake_create)
    pass1_out = tmp_path / "pass1"
    pass2_out = tmp_path / "pass2"
    monkeypatch.setattr(
        "sys.argv",
        [
            "rla",
            "--texts", str(texts_dir),
            "--routing", str(tmp_path / "routing.json"),
            "--rubric", str(tmp_path / "rubric.md"),
            "--outline", str(tmp_path / "outline.md"),
            "--rubric-criteria", str(criteria_path),
            "--pass1-out", str(pass1_out),
            "--pass2-out", str(pass2_out),
            "--assessors", "A",
            "--genre", "speech",
            "--ignore-cost-limits",
        ],
    )
    assert rla.main() == 0
    pass1_prompts = [prompt for prompt in prompts if "Return ONLY valid JSON" in prompt]
    assert any("SP1" in prompt and "Audience engagement" in prompt for prompt in pass1_prompts)


def test_run_llm_assessors_uses_portfolio_metadata_for_criteria(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(
        rla,
        "infer_genre_from_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not infer")),
    )
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Portfolio writing sample", encoding="utf-8")
    write_config(
        tmp_path / "routing.json",
        {"mode": "openai", "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}},
    )
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")
    (tmp_path / "class_metadata.json").write_text(
        json.dumps(
            {
                "assessment_unit": "portfolio",
                "grade_numeric_equivalent": 2,
                "genre_form": "mixed writing portfolio",
            }
        ),
        encoding="utf-8",
    )
    criteria_path = tmp_path / "criteria.json"
    criteria_path.write_text(
        json.dumps(
            {
                "categories": {
                    "communication": {
                        "criteria": [{"id": "C1", "name": "Expression", "description": "desc"}]
                    }
                },
                "genre_specific_criteria": {
                    "portfolio": {
                        "additional_criteria": [{"id": "PF1", "name": "Cross-piece consistency", "description": "desc"}]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    prompts = []

    def fake_create(model, messages, temperature, reasoning, routing_path, **kwargs):
        prompt = messages[0]["content"]
        prompts.append(prompt)
        text = json.dumps({"student_id": "s1", "rubric_total_points": 10, "criteria_points": {}, "notes": "ok"})
        if "Return ONLY valid JSON" not in prompt:
            text = "s1"
        return {"output": [{"type": "output_text", "text": text}], "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr(rla, "responses_create", fake_create)
    pass1_out = tmp_path / "pass1"
    pass2_out = tmp_path / "pass2"
    monkeypatch.setattr(
        "sys.argv",
        [
            "rla",
            "--texts", str(texts_dir),
            "--routing", str(tmp_path / "routing.json"),
            "--rubric", str(tmp_path / "rubric.md"),
            "--outline", str(tmp_path / "outline.md"),
            "--class-metadata", str(tmp_path / "class_metadata.json"),
            "--rubric-criteria", str(criteria_path),
            "--pass1-out", str(pass1_out),
            "--pass2-out", str(pass2_out),
            "--assessors", "A",
            "--ignore-cost-limits",
        ],
    )
    assert rla.main() == 0
    pass1_prompts = [prompt for prompt in prompts if "Return ONLY valid JSON" in prompt]
    assert any("PF1" in prompt and "Cross-piece consistency" in prompt for prompt in pass1_prompts)


def test_run_llm_assessors_scores_portfolio_pieces_and_aggregates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text(
        "Opening the Fridge\nA polished narrative about sneaking downstairs.\n\n"
        "The Applause\nA vivid performance recount with sensory detail.\n\n"
        "How Pointe Shoes Came To Be\nAn explanatory report about ballet shoes.",
        encoding="utf-8",
    )
    write_config(
        tmp_path / "routing.json",
        {"mode": "openai", "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}},
    )
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")
    (tmp_path / "class_metadata.json").write_text(
        json.dumps(
            {
                "assessment_unit": "portfolio",
                "grade_numeric_equivalent": 6,
                "genre_form": "mixed writing portfolio",
            }
        ),
        encoding="utf-8",
    )
    criteria_path = tmp_path / "criteria.json"
    criteria_path.write_text(
        json.dumps(
            {
                "categories": {
                    "communication": {
                        "criteria": [{"id": "C1", "name": "Expression", "description": "desc"}]
                    }
                },
                "genre_specific_criteria": {
                    "portfolio": {
                        "additional_criteria": [{"id": "PF1", "name": "Cross-piece consistency", "description": "desc"}]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    prompts = []

    def fake_create(model, messages, temperature, reasoning, routing_path, **kwargs):
        prompt = messages[0]["content"]
        prompts.append(prompt)
        if "Return ONLY valid JSON" not in prompt:
            return {"output": [{"type": "output_text", "text": "s1"}], "usage": {"input_tokens": 1, "output_tokens": 1}}
        if "s1::p01" in prompt:
            text = json.dumps({"student_id": "s1::p01", "rubric_total_points": 84, "criteria_points": {}, "notes": "Strong narrative"})
        elif "s1::p02" in prompt:
            text = json.dumps({"student_id": "s1::p02", "rubric_total_points": 81, "criteria_points": {}, "notes": "Strong recount"})
        else:
            text = json.dumps({"student_id": "s1::p03", "rubric_total_points": 76, "criteria_points": {}, "notes": "Good report"})
        return {"output": [{"type": "output_text", "text": text}], "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr(rla, "responses_create", fake_create)
    pass1_out = tmp_path / "pass1"
    pass2_out = tmp_path / "pass2"
    portfolio_report = tmp_path / "portfolio_piece_report.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "rla",
            "--texts", str(texts_dir),
            "--routing", str(tmp_path / "routing.json"),
            "--rubric", str(tmp_path / "rubric.md"),
            "--outline", str(tmp_path / "outline.md"),
            "--class-metadata", str(tmp_path / "class_metadata.json"),
            "--rubric-criteria", str(criteria_path),
            "--pass1-out", str(pass1_out),
            "--pass2-out", str(pass2_out),
            "--portfolio-piece-report", str(portfolio_report),
            "--assessors", "A",
            "--ignore-cost-limits",
        ],
    )
    assert rla.main() == 0
    payload = json.loads((pass1_out / "assessor_A.json").read_text(encoding="utf-8"))
    item = payload["scores"][0]
    assert item["student_id"] == "s1"
    assert item["portfolio_piece_count"] == 3
    assert item["portfolio_overall_level"] == "4"
    assert len(item["portfolio_piece_scores"]) == 3
    report = json.loads(portfolio_report.read_text(encoding="utf-8"))
    assert report["enabled"] is True
    assert report["students"]["s1"]["piece_count"] == 3
    piece_prompts = [prompt for prompt in prompts if "Return ONLY valid JSON" in prompt]
    assert any("C1" in prompt for prompt in piece_prompts)
    assert all("PF1" not in prompt for prompt in piece_prompts)
    pass2_prompts = [prompt for prompt in prompts if "Rank the students best to worst." in prompt]
    assert any("Portfolio overall score" in prompt and "Piece profile:" in prompt for prompt in pass2_prompts)


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


def test_run_llm_assessors_uses_unanimous_portfolio_seed_order(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Title A\nStrong first piece.\n\nTitle B\nStrong second piece.", encoding="utf-8")
    (texts_dir / "s2.txt").write_text("Title C\nMiddle piece.\n\nTitle D\nMiddle follow-up.", encoding="utf-8")
    (texts_dir / "s3.txt").write_text("Title E\nWeak piece.\n\nTitle F\nWeak follow-up.", encoding="utf-8")
    write_config(
        tmp_path / "routing.json",
        {"mode": "openai", "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}},
    )
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")
    (tmp_path / "class_metadata.json").write_text(
        json.dumps(
            {
                "assessment_unit": "portfolio",
                "grade_numeric_equivalent": 2,
                "genre_form": "mixed writing portfolio",
            }
        ),
        encoding="utf-8",
    )

    score_map = {
        ("A", "s1::p01"): 84,
        ("A", "s1::p02"): 82,
        ("A", "s2::p01"): 72,
        ("A", "s2::p02"): 70,
        ("A", "s3::p01"): 60,
        ("A", "s3::p02"): 58,
        ("B", "s1::p01"): 85,
        ("B", "s1::p02"): 83,
        ("B", "s2::p01"): 73,
        ("B", "s2::p02"): 71,
        ("B", "s3::p01"): 61,
        ("B", "s3::p02"): 59,
        ("C", "s1::p01"): 86,
        ("C", "s1::p02"): 84,
        ("C", "s2::p01"): 74,
        ("C", "s2::p02"): 72,
        ("C", "s3::p01"): 62,
        ("C", "s3::p02"): 60,
    }

    def fake_create(model, messages, temperature, reasoning, routing_path, **kwargs):
        prompt = messages[0]["content"]
        if "Return ONLY valid JSON" in prompt:
            student_piece = prompt.split("Student ID: ", 1)[1].splitlines()[0].strip()
            assessor = prompt.split("You are Assessor ", 1)[1].split(".", 1)[0].strip()
            score = score_map[(assessor, student_piece)]
            text = json.dumps({"student_id": student_piece, "rubric_total_points": score, "criteria_points": {}, "notes": "ok"})
            return {"output": [{"type": "output_text", "text": text}], "usage": {"input_tokens": 1, "output_tokens": 1}}
        return {"output": [{"type": "output_text", "text": json.dumps({"ranking": ["s3", "s2", "s1"]})}], "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr(rla, "responses_create", fake_create)
    pass1_out = tmp_path / "pass1"
    pass2_out = tmp_path / "pass2"
    monkeypatch.setattr(
        "sys.argv",
        [
            "rla",
            "--texts", str(texts_dir),
            "--routing", str(tmp_path / "routing.json"),
            "--rubric", str(tmp_path / "rubric.md"),
            "--outline", str(tmp_path / "outline.md"),
            "--class-metadata", str(tmp_path / "class_metadata.json"),
            "--rubric-criteria", str(tmp_path / "no_criteria.json"),
            "--pass1-out", str(pass1_out),
            "--pass2-out", str(pass2_out),
            "--assessors", "A,B,C",
            "--ignore-cost-limits",
        ],
    )
    assert rla.main() == 0
    for assessor in ("A", "B", "C"):
        ranking = (pass2_out / f"assessor_{assessor}.txt").read_text(encoding="utf-8").strip().splitlines()
        assert ranking == ["s1", "s2", "s3"]


def test_run_llm_assessors_uses_argumentative_seed_order_for_thoughtful_cross_topic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Argument essay one", encoding="utf-8")
    (texts_dir / "s2.txt").write_text("Argument essay two", encoding="utf-8")
    (texts_dir / "s3.txt").write_text("Argument essay three", encoding="utf-8")
    write_config(
        tmp_path / "routing.json",
        {"mode": "openai", "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}},
    )
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")
    (tmp_path / "class_metadata.json").write_text(
        json.dumps(
            {
                "grade_level": 10,
                "assignment_genre": "argumentative",
                "source_family": "thoughtful_learning_assessment_models",
                "cohort_shape": "same_rubric_family_cross_topic",
            }
        ),
        encoding="utf-8",
    )

    score_map = {
        ("A", "s1"): {"rubric_total_points": 88, "criteria_points": {"AR1": 90, "AR2": 88, "AR3": 76, "C1": 82, "C3": 78}},
        ("A", "s2"): {"rubric_total_points": 79, "criteria_points": {"AR1": 80, "AR2": 74, "AR3": 64, "C1": 76, "C3": 72}},
        ("A", "s3"): {"rubric_total_points": 69, "criteria_points": {"AR1": 66, "AR2": 60, "AR3": 52, "C1": 68, "C3": 68}},
        ("B", "s1"): {"rubric_total_points": 87, "criteria_points": {"AR1": 88, "AR2": 86, "AR3": 78, "C1": 84, "C3": 76}},
        ("B", "s2"): {"rubric_total_points": 80, "criteria_points": {"AR1": 82, "AR2": 76, "AR3": 62, "C1": 78, "C3": 72}},
        ("B", "s3"): {"rubric_total_points": 68, "criteria_points": {"AR1": 64, "AR2": 58, "AR3": 50, "C1": 66, "C3": 66}},
        ("C", "s1"): {"rubric_total_points": 89, "criteria_points": {"AR1": 92, "AR2": 90, "AR3": 78, "C1": 84, "C3": 80}},
        ("C", "s2"): {"rubric_total_points": 81, "criteria_points": {"AR1": 84, "AR2": 78, "AR3": 64, "C1": 78, "C3": 74}},
        ("C", "s3"): {"rubric_total_points": 70, "criteria_points": {"AR1": 68, "AR2": 60, "AR3": 50, "C1": 68, "C3": 68}},
    }

    def fake_create(model, messages, temperature, reasoning, routing_path, **kwargs):
        prompt = messages[0]["content"]
        if "Return ONLY valid JSON" in prompt:
            student_id = prompt.split("Student ID: ", 1)[1].splitlines()[0].strip()
            assessor = prompt.split("You are Assessor ", 1)[1].split(".", 1)[0].strip()
            payload = score_map[(assessor, student_id)]
            text = json.dumps(
                {
                    "student_id": student_id,
                    "rubric_total_points": payload["rubric_total_points"],
                    "criteria_points": payload["criteria_points"],
                    "notes": "Clear claim and well-supported reasoning.",
                }
            )
            return {"output": [{"type": "output_text", "text": text}], "usage": {"input_tokens": 1, "output_tokens": 1}}
        return {"output": [{"type": "output_text", "text": json.dumps({"ranking": ["s3", "s2", "s1"]})}], "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr(rla, "responses_create", fake_create)
    pass1_out = tmp_path / "pass1"
    pass2_out = tmp_path / "pass2"
    monkeypatch.setattr(
        "sys.argv",
        [
            "rla",
            "--texts", str(texts_dir),
            "--routing", str(tmp_path / "routing.json"),
            "--rubric", str(tmp_path / "rubric.md"),
            "--outline", str(tmp_path / "outline.md"),
            "--class-metadata", str(tmp_path / "class_metadata.json"),
            "--rubric-criteria", str(tmp_path / "no_criteria.json"),
            "--pass1-out", str(pass1_out),
            "--pass2-out", str(pass2_out),
            "--assessors", "A,B,C",
            "--ignore-cost-limits",
        ],
    )
    assert rla.main() == 0
    for assessor in ("A", "B", "C"):
        ranking = (pass2_out / f"assessor_{assessor}.txt").read_text(encoding="utf-8").strip().splitlines()
        assert ranking == ["s1", "s2", "s3"]


def test_run_llm_assessors_uses_literary_seed_order_when_scaffold_draft_is_over_scored(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text(
        "Ghost- Final Essay\n\nConsequences Of Our Choices\n\n"
        "Coach chose to forgive Ghost.\n"
        "Explanation 1: Though Coach forgives him he makes him\n"
        "Cite/Detail 2:\n"
        "Reflect on the Theme:\n",
        encoding="utf-8",
    )
    (texts_dir / "s2.txt").write_text(
        "Ghost teaches that choices carry consequences. The essay explains how Brandon's bullying, "
        "the stolen shoes, and Coach's response all push Ghost toward responsibility.",
        encoding="utf-8",
    )
    write_config(
        tmp_path / "routing.json",
        {"mode": "openai", "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}},
    )
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")
    (tmp_path / "class_metadata.json").write_text(
        json.dumps({"grade_level": 7, "genre": "literary_analysis", "generated_by": "bootstrap"}),
        encoding="utf-8",
    )

    def fake_create(model, messages, temperature, reasoning, routing_path, **kwargs):
        prompt = messages[0]["content"]
        if "Return ONLY valid JSON" in prompt:
            student_id = prompt.split("Student ID: ", 1)[1].splitlines()[0].strip()
            if student_id == "s1":
                text = json.dumps(
                    {
                        "student_id": "s1",
                        "rubric_total_points": 84,
                        "criteria_points": {"LA1": 84, "LA2": 82, "LA3": 80, "C1": 78, "C3": 74},
                        "notes": "Relevant theme, but incomplete structure and placeholder text remain.",
                    }
                )
            else:
                text = json.dumps(
                    {
                        "student_id": "s2",
                        "rubric_total_points": 74,
                        "criteria_points": {"LA1": 80, "LA2": 78, "LA3": 82, "C1": 78, "C3": 76},
                        "notes": "Clear thematic thesis, specific textual evidence, and developed literary analysis.",
                    }
                )
            return {"output": [{"type": "output_text", "text": text}], "usage": {"input_tokens": 1, "output_tokens": 1}}
        return {"output": [{"type": "output_text", "text": json.dumps({"ranking": ["s1", "s2"]})}], "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr(rla, "responses_create", fake_create)
    pass1_out = tmp_path / "pass1"
    pass2_out = tmp_path / "pass2"
    monkeypatch.setattr(
        "sys.argv",
        [
            "rla",
            "--texts", str(texts_dir),
            "--routing", str(tmp_path / "routing.json"),
            "--rubric", str(tmp_path / "rubric.md"),
            "--outline", str(tmp_path / "outline.md"),
            "--class-metadata", str(tmp_path / "class_metadata.json"),
            "--rubric-criteria", str(tmp_path / "no_criteria.json"),
            "--pass1-out", str(pass1_out),
            "--pass2-out", str(pass2_out),
            "--assessors", "A,B,C",
            "--ignore-cost-limits",
        ],
    )
    assert rla.main() == 0
    for assessor in ("A", "B", "C"):
        payload = json.loads((pass1_out / f"assessor_{assessor}.json").read_text(encoding="utf-8"))
        scores = {item["student_id"]: item for item in payload["scores"]}
        assert scores["s1"]["draft_completion_floor_applied"] is True
        assert scores["s1"]["rubric_total_points"] < scores["s2"]["rubric_total_points"]
    for assessor in ("A", "B", "C"):
        ranking = (pass2_out / f"assessor_{assessor}.txt").read_text(encoding="utf-8").strip().splitlines()
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


def test_run_llm_assessors_pass2_fallback_uses_scores_and_cleans_stale(tmp_path, monkeypatch):
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

    pass1_out = tmp_path / "pass1"
    pass2_out = tmp_path / "pass2"
    pass1_out.mkdir()
    pass2_out.mkdir()
    (pass2_out / "assessor_A.txt").write_text("stale", encoding="utf-8")

    def fake_create(model, messages, temperature, reasoning, routing_path, **kwargs):
        prompt = messages[0]["content"]
        if "Return ONLY valid JSON" in prompt:
            sid = "s2" if "Student ID: s2" in prompt else "s1"
            score = 90 if sid == "s2" else 60
            text = json.dumps({"student_id": sid, "rubric_total_points": score, "criteria_points": {}, "notes": "ok"})
        else:
            text = "unknown"
        return {"output": [{"type": "output_text", "text": text}], "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr(rla, "responses_create", fake_create)
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
        "--fallback", "none",
    ])
    with pytest.raises(ValueError):
        rla.main()
    failure_log = tmp_path / "logs" / "llm_failures.jsonl"
    assert failure_log.exists()
    lines = failure_log.read_text(encoding="utf-8").strip().splitlines()
    assert lines


def test_run_llm_assessors_deterministic_fallback_on_exception(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Dear Principal. First recycle. Sincerely, Student.", encoding="utf-8")
    routing = {"mode": "openai", "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}}
    write_config(tmp_path / "routing.json", routing)
    write_config(tmp_path / "pricing.json", {"models": {"gpt-5.2": {"input_per_million": 1.0, "output_per_million": 1.0}}})
    write_config(tmp_path / "limits.json", {"per_call_max_tokens": 8000, "abort_on_limit": False, "estimates": {"pass1_output_tokens": 10, "pass2_output_tokens": 10}})
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")
    monkeypatch.setattr(rla, "responses_create", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
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
        "--rubric-criteria", str(tmp_path / "none.json"),
        "--pass1-out", str(pass1_out),
        "--pass2-out", str(pass2_out),
        "--assessors", "A",
        "--fallback", "deterministic",
    ])
    assert rla.main() == 0
    assert (pass1_out / "assessor_A.json").exists()
    ranking = (pass2_out / "assessor_A.txt").read_text(encoding="utf-8").strip().splitlines()
    assert ranking == ["s1"]


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


def test_run_llm_assessors_codex_local_prompt_echo_retries_then_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Sample essay text", encoding="utf-8")
    routing = {
        "mode": "codex_local",
        "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}},
    }
    write_config(tmp_path / "routing.json", routing)
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")

    def fake_create(model, messages, temperature, reasoning, routing_path, **kwargs):
        prompt = messages[0]["content"]
        if "Return ONLY valid JSON" in prompt:
            text = (
                'user: you are assessor A\n'
                'Student ID must be "s1"\n'
                "Previous output:\n"
                "rubric total points: 82\n"
            )
        else:
            text = "s1"
        return {"output": [{"type": "output_text", "text": text}]}

    monkeypatch.setattr(rla, "responses_create", fake_create)
    pass1_out = tmp_path / "pass1"
    pass2_out = tmp_path / "pass2"
    monkeypatch.setattr(
        "sys.argv",
        [
            "rla",
            "--texts",
            str(texts_dir),
            "--routing",
            str(tmp_path / "routing.json"),
            "--rubric",
            str(tmp_path / "rubric.md"),
            "--outline",
            str(tmp_path / "outline.md"),
            "--rubric-criteria",
            str(tmp_path / "none.json"),
            "--pass1-out",
            str(pass1_out),
            "--pass2-out",
            str(pass2_out),
            "--assessors",
            "A",
            "--fallback",
            "deterministic",
        ],
    )
    assert rla.main() == 0
    payload = json.loads((pass1_out / "assessor_A.json").read_text(encoding="utf-8"))
    assert payload["scores"][0]["student_id"] == "s1"
    failure_log = tmp_path / "logs" / "llm_failures.jsonl"
    assert "prompt echo" in failure_log.read_text(encoding="utf-8").lower()


def test_run_llm_assessors_empty_texts_uses_score_order_branch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    routing = {"mode": "openai", "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}}
    write_config(tmp_path / "routing.json", routing)
    write_config(tmp_path / "pricing.json", {"models": {"gpt-5.2": {"input_per_million": 1.0, "output_per_million": 1.0}}})
    write_config(tmp_path / "limits.json", {"per_call_max_tokens": 8000, "abort_on_limit": False, "estimates": {"pass1_output_tokens": 10, "pass2_output_tokens": 10}})
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")

    monkeypatch.setattr(rla, "responses_create", lambda **kwargs: {"output": [{"type": "output_text", "text": ""}], "usage": {}})
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
        "--rubric-criteria", str(tmp_path / "none.json"),
        "--pass1-out", str(pass1_out),
        "--pass2-out", str(pass2_out),
        "--assessors", "A",
    ])
    assert rla.main() == 0


def test_run_llm_assessors_pass2_uses_structured_contract(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Sample essay text", encoding="utf-8")
    write_config(
        tmp_path / "routing.json",
        {"mode": "openai", "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}},
    )
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")
    seen = {"pass1": [], "pass2": []}

    def fake_create(model, messages, temperature, reasoning, routing_path, **kwargs):
        prompt = messages[0]["content"]
        text_format = kwargs.get("text_format")
        if "Score this student" in prompt:
            seen["pass1"].append(text_format)
            text = json.dumps({"student_id": "s1", "rubric_total_points": 10, "criteria_points": {}, "notes": "ok"})
        else:
            seen["pass2"].append(text_format)
            text = json.dumps({"ranking": ["s1"]})
        return {"output": [{"type": "output_text", "text": text}], "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr(rla, "responses_create", fake_create)
    monkeypatch.setattr(
        "sys.argv",
        [
            "rla",
            "--texts", str(texts_dir),
            "--routing", str(tmp_path / "routing.json"),
            "--rubric", str(tmp_path / "rubric.md"),
            "--outline", str(tmp_path / "outline.md"),
            "--rubric-criteria", str(tmp_path / "none.json"),
            "--pass1-out", str(tmp_path / "pass1"),
            "--pass2-out", str(tmp_path / "pass2"),
            "--assessors", "A",
            "--ignore-cost-limits",
        ],
    )
    assert rla.main() == 0
    assert seen["pass1"] and seen["pass2"]
    assert seen["pass1"][0]["schema"]["required"] == ["student_id", "rubric_total_points", "criteria_points", "notes"]
    assert "criteria_evidence" not in seen["pass1"][0]["schema"]["required"]
    assert seen["pass2"][0]["schema"]["required"] == ["ranking"]


def test_run_llm_assessors_require_model_usage_fails_on_full_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Sample essay text", encoding="utf-8")
    write_config(
        tmp_path / "routing.json",
        {"mode": "openai", "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}},
    )
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")

    def fake_create(*_args, **_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(rla, "responses_create", fake_create)
    monkeypatch.setattr(
        "sys.argv",
        [
            "rla",
            "--texts", str(texts_dir),
            "--routing", str(tmp_path / "routing.json"),
            "--rubric", str(tmp_path / "rubric.md"),
            "--outline", str(tmp_path / "outline.md"),
            "--rubric-criteria", str(tmp_path / "none.json"),
            "--pass1-out", str(tmp_path / "pass1"),
            "--pass2-out", str(tmp_path / "pass2"),
            "--assessors", "A",
            "--ignore-cost-limits",
            "--require-model-usage",
        ],
    )
    assert rla.main() == 1


def test_run_llm_assessors_min_coverage_gate_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Sample essay text", encoding="utf-8")
    write_config(
        tmp_path / "routing.json",
        {
            "mode": "openai",
            "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}},
            "quality_gates": {"min_model_coverage": 0.95},
        },
    )
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")

    def fake_create(model, messages, temperature, reasoning, routing_path, **kwargs):
        prompt = messages[0]["content"]
        if "Return ONLY valid JSON" in prompt:
            return {"output": [{"type": "output_text", "text": "not json"}], "usage": {}}
        return {"output": [{"type": "output_text", "text": json.dumps({"ranking": ["s1"]})}], "usage": {}}

    monkeypatch.setattr(rla, "responses_create", fake_create)
    monkeypatch.setattr(
        "sys.argv",
        [
            "rla",
            "--texts", str(texts_dir),
            "--routing", str(tmp_path / "routing.json"),
            "--rubric", str(tmp_path / "rubric.md"),
            "--outline", str(tmp_path / "outline.md"),
            "--rubric-criteria", str(tmp_path / "none.json"),
            "--pass1-out", str(tmp_path / "pass1"),
            "--pass2-out", str(tmp_path / "pass2"),
            "--assessors", "A",
            "--ignore-cost-limits",
        ],
    )
    assert rla.main() == 1


def test_run_llm_assessors_calibration_gate_missing_bias_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Sample essay text", encoding="utf-8")
    write_config(
        tmp_path / "routing.json",
        {
            "mode": "openai",
            "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}},
            "calibration_gate": {"enabled": True, "bias_path": "outputs/calibration_bias.json"},
        },
    )
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")
    (tmp_path / "class_metadata.json").write_text(json.dumps({"grade_level": 8, "genre": "literary_analysis"}), encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "rla",
            "--texts", str(texts_dir),
            "--routing", str(tmp_path / "routing.json"),
            "--rubric", str(tmp_path / "rubric.md"),
            "--outline", str(tmp_path / "outline.md"),
            "--class-metadata", str(tmp_path / "class_metadata.json"),
            "--rubric-criteria", str(tmp_path / "none.json"),
            "--pass1-out", str(tmp_path / "pass1"),
            "--pass2-out", str(tmp_path / "pass2"),
            "--assessors", "A",
            "--ignore-cost-limits",
        ],
    )
    assert rla.main() == 1
