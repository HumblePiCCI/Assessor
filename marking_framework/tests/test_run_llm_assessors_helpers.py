import json
import pytest

import scripts.run_llm_assessors as rla
from tests.conftest import make_docx


def test_run_llm_assessors_helpers():
    assert rla.summarize_text("a b c", 10) == "a b c"
    assert rla.summarize_text("a b c", 2).endswith("...")
    with pytest.raises(ValueError):
        rla.json_from_text("no json here")
    prompt = rla.build_pass1_prompt("A", "rubric", "outline", "s1", "essay", "GRADE", "EX")
    assert "GRADE" in prompt
    assert "EX" in prompt
    prompt_no_ex = rla.build_pass1_prompt("A", "rubric", "outline", "s1", "essay", "GRADE", "")
    assert "GRADE" in prompt_no_ex
    assert "EX" not in prompt_no_ex
    prompt_with_criteria = rla.build_pass1_prompt(
        "A",
        "rubric",
        "outline",
        "s1",
        "essay",
        "GRADE",
        "EX",
        "CRIT",
        {"rationale_min_words": 3},
    )
    assert "CRIT" in prompt_with_criteria
    assert "min 3 words" in prompt_with_criteria
    repair = rla.build_pass1_repair_prompt("s1", "raw", True)
    assert "criteria_evidence" in repair
    contextual_repair = rla.build_pass1_repair_prompt("s1", "raw", False, context_prompt="Rubric:\nX\nEssay:\nY")
    assert "Re-score the same submission from scratch" in contextual_repair
    assert "Essay:\nY" in contextual_repair
    pass2_repair = rla.build_pass2_repair_prompt(["s1", "s2"], "raw", [])
    assert "Missing IDs:" not in pass2_repair
    assert rla.ranking_from_scores({"s1": 70, "s2": 90}, ["s1", "s2"]) == ["s2", "s1"]


def test_resolve_pass1_contract_for_instructions_forces_evidence():
    criteria_cfg = {
        "categories": {
            "communication": {
                "criteria": [
                    {"id": "C1", "name": "Expression", "description": "desc"},
                    {"id": "C2", "name": "Conventions", "description": "desc"},
                ]
            }
        },
        "evidence_requirements": {"quote_validation": True, "rationale_min_words": 20},
        "genre_specific_criteria": {
            "instructions": {
                "contract_criteria_ids": ["IN1", "C2"],
                "contract_guidance": ["Score this as executable procedure."],
                "evidence_requirements": {
                    "force_require_evidence": True,
                    "quote_validation": True,
                    "rationale_min_words": 12,
                    "hard_fail_on_evidence_errors": True,
                    "preserve_validation": True,
                },
                "additional_criteria": [{"id": "IN1", "name": "Procedural completeness", "description": "Steps and materials"}],
            }
        },
    }
    contract = rla.resolve_pass1_contract(criteria_cfg, "instructions", False)
    assert contract["require_evidence"] is True
    assert contract["reqs"]["hard_fail_on_evidence_errors"] is True
    assert contract["reqs"]["quote_validation"] is True
    assert contract["reqs"]["rationale_min_words"] == 12
    assert "SCORING CONTRACT:" in contract["criteria_block"]
    assert "executable procedure" in contract["criteria_block"]
    assert contract["required_ids"] == ["C2", "IN1"]
    assert "C1" not in contract["criteria_block"]


def test_resolve_pass1_contract_for_summary_report_prioritizes_summary_quality():
    criteria_cfg = {
        "categories": {
            "communication": {
                "criteria": [
                    {"id": "C1", "name": "Expression", "description": "desc"},
                    {"id": "C2", "name": "Conventions", "description": "desc"},
                    {"id": "C3", "name": "Vocabulary", "description": "desc"},
                ]
            }
        },
        "genre_specific_criteria": {
            "summary_report": {
                "contract_criteria_ids": ["SR1", "SR2", "SR3", "C1", "C2"],
                "contract_guidance": ["Score this as summary writing."],
                "evidence_requirements": {
                    "force_require_evidence": True,
                    "quote_validation": False,
                    "rationale_min_words": 10,
                    "hard_fail_on_evidence_errors": True,
                    "preserve_validation": True,
                },
                "additional_criteria": [
                    {"id": "SR1", "name": "Main idea capture", "description": "desc"},
                    {"id": "SR2", "name": "Concision", "description": "desc"},
                    {"id": "SR3", "name": "Paraphrase", "description": "desc"},
                ],
            }
        },
    }
    contract = rla.resolve_pass1_contract(criteria_cfg, "summary_report", False)
    assert contract["require_evidence"] is True
    assert contract["required_ids"] == ["C1", "C2", "SR1", "SR2", "SR3"]
    assert "summary writing" in contract["criteria_block"]
    assert "C3" not in contract["criteria_block"]
    assert contract["reqs"]["quote_validation"] is False
    assert contract["reqs"]["rationale_min_words"] == 10


def test_build_pass2_student_summaries_uses_summary_specific_assessment_signal():
    entries = rla.build_pass2_student_summaries(
        ["s1"],
        {"s1": "Raw student response excerpt"},
        {
            "s1": {
                "student_id": "s1",
                "rubric_total_points": 74.33,
                "criteria_points": {"SR1": 95, "SR2": 88, "SR3": 88, "C1": 88, "C2": 95},
                "criteria_evidence": [
                    {"criterion_id": "SR1", "score": 84},
                    {"criterion_id": "SR2", "score": 64},
                    {"criterion_id": "SR3", "score": 64},
                    {"criterion_id": "C1", "score": 75},
                    {"criterion_id": "C2", "score": 84},
                ],
                "notes": "Accurate content but copied source detail leaves it not concise enough for a strong summary.",
            }
        },
        "summary_report",
        False,
        240,
    )
    summary = entries[0]["summary"]
    assert "Summary writing score 74.33." in summary
    assert "concision 64" in summary
    assert "too much source detail" in summary
    assert "heavy source lifting" in summary


def test_build_pass2_student_summaries_uses_portfolio_aggregate_signal():
    entries = rla.build_pass2_student_summaries(
        ["s1"],
        {"s1": "Opening the Fridge: raw snippet"},
        {
            "s1": {
                "student_id": "s1",
                "rubric_total_points": 63.88,
                "portfolio_overall_level": "2",
                "portfolio_piece_scores": [
                    {"piece_id": "p01", "title": "Yesterday we went to bishops Wood to", "rubric_total_points": 76.0, "level": "3"},
                    {"piece_id": "p02", "title": "Missing one dragon", "rubric_total_points": 69.0, "level": "2"},
                    {"piece_id": "p03", "title": "Meet Fred. Fred loves to find things.", "rubric_total_points": 61.78, "level": "2"},
                ],
                "notes": "Overall working towards the expected standard across the portfolio.",
            }
        },
        "portfolio",
        True,
        260,
    )
    summary = entries[0]["summary"]
    assert "Portfolio overall score 63.88 (level 2)." in summary
    assert "Piece profile:" in summary
    assert "Yesterday we went to bishops Wood to" in summary


def test_unanimous_portfolio_seed_order_requires_full_agreement():
    scores = {
        "A": {"s1": 80, "s2": 70, "s3": 60},
        "B": {"s1": 81, "s2": 71, "s3": 61},
        "C": {"s1": 82, "s2": 72, "s3": 62},
    }
    assert rla.unanimous_portfolio_seed_order(scores, ["s1", "s2", "s3"]) == ["s1", "s2", "s3"]
    scores["C"] = {"s1": 82, "s2": 60, "s3": 72}
    assert rla.unanimous_portfolio_seed_order(scores, ["s1", "s2", "s3"]) is None


def test_run_llm_assessors_file_helpers(tmp_path):
    path = tmp_path / "out.txt"
    rla.write_text_atomic(path, "x")
    assert path.read_text(encoding="utf-8") == "x"
    (tmp_path / "assessor_A.txt").write_text("x", encoding="utf-8")
    (tmp_path / "assessor_folder").mkdir()
    (tmp_path / "other.txt").write_text("x", encoding="utf-8")
    rla.reset_assessor_outputs(tmp_path)
    assert not (tmp_path / "assessor_A.txt").exists()
    assert (tmp_path / "assessor_folder").exists()
    assert (tmp_path / "other.txt").exists()


def test_run_llm_assessors_preflight_context():
    texts = {"s1": "text"}
    summaries = [{"student_id": "s1", "summary": "sum"}]
    routing = {"tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}}
    pricing = {"models": {"gpt-5.2": {"input_per_million": 1.0, "output_per_million": 1.0}}}
    limits = {"per_call_max_tokens": 1000, "estimates": {"pass1_output_tokens": 1, "pass2_output_tokens": 1}}
    result = rla.preflight_costs(texts, "rubric", "outline", summaries, routing, pricing, limits, "GRADE", "EX")
    assert result["ok"] is True


def test_run_llm_assessors_helper_functions(tmp_path):
    docx_path = make_docx(tmp_path / "a.docx", "Docx text")
    assert rla.extract_docx_text(docx_path) == "Docx text"
    empty_docx = make_docx(tmp_path / "empty.docx", "")
    assert rla.extract_docx_text(empty_docx) == ""
    assert rla.load_file_text(docx_path) == "Docx text"
    pages_path = tmp_path / "rubric.pages"
    pages_path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        rla.load_file_text(pages_path)
    assert rla.load_file_text(tmp_path / "missing.txt") == ""
    assert rla.load_json(tmp_path / "missing.json") == {}
    assert rla.json_from_text("prefix {\"a\": 1} suffix")["a"] == 1
    multi = "{\"a\": 1} junk {\"student_id\": \"s1\", \"rubric_total_points\": 5}"
    assert rla.json_from_text(multi)["student_id"] == "s1"
    broken = "{not json} {\"student_id\": \"s2\", \"rubric_total_points\": 4}"
    assert rla.json_from_text(broken)["student_id"] == "s2"
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    rubric_docx = make_docx(inputs / "rubric.docx", "Rubric Docx")
    outline_txt = inputs / "assignment_outline.txt"
    outline_txt.write_text("Outline", encoding="utf-8")
    resolved_rubric = rla.resolve_input_path(inputs / "rubric.md", "rubric")
    resolved_outline = rla.resolve_input_path(inputs / "assignment_outline.md", "assignment_outline")
    assert resolved_rubric == rubric_docx
    assert resolved_outline == outline_txt
    (inputs / "rubric.pdf").write_text("pdf", encoding="utf-8")
    assert rla.resolve_input_path(inputs / "rubric.pdf", "rubric").suffix == ".pdf"
    missing_path = rla.resolve_input_path(inputs / "nope.md", "nope")
    assert missing_path == inputs / "nope.md"


def test_guard_bias_for_exemplar_scope_reduces_anchor_on_weak_match():
    assert rla.guard_bias_for_exemplar_scope("exact_scope", 5.0, 1, 0.35) == (5.0, 1, 0.35)
    assert rla.guard_bias_for_exemplar_scope("genre_library", 5.0, 1, 0.35) == (8.0, 2, 0.12)
    assert rla.guard_bias_for_exemplar_scope("cross_band", 5.0, 1, 0.35) == (12.0, 2, 0.0)


def test_runtime_rubric_context_prefers_normalized_contract(tmp_path):
    rubric = tmp_path / "rubric.md"
    rubric.write_text("Ideas and analysis\nLevel 4 80-100", encoding="utf-8")
    normalized = tmp_path / "normalized_rubric.json"
    normalized.write_text(
        json.dumps(
            {
                "genre": "literary_analysis",
                "rubric_family": "rubric_a",
                "criteria": [{"name": "Insight", "weight": 1.0, "canonical_label": "Insight"}],
                "scale": {"levels": [{"label": "4", "band_min": 80, "band_max": 100, "descriptor": "excellent"}]},
                "evidence_requirements": {},
                "raw_text": "original rubric text",
            }
        ),
        encoding="utf-8",
    )
    verification = tmp_path / "rubric_verification.json"
    verification.write_text(json.dumps({"status": "confirmed"}), encoding="utf-8")
    context = rla.runtime_rubric_context(rubric, normalized_path=normalized, verification_path=verification)
    assert "VERIFIED RUBRIC CONTRACT" in context["rubric_text"]
    assert "Insight" in context["rubric_text"]


def test_parse_pass1_item_missing_keys():
    with pytest.raises(ValueError):
        rla.parse_pass1_item('{"student_id": "s1"}', "s1")


def test_parse_pass1_item_non_dict():
    with pytest.raises(ValueError):
        rla.parse_pass1_item('["x"]', "s1")


def test_parse_pass1_item_criteria_points_non_dict():
    item = rla.parse_pass1_item('{"student_id": "s1", "rubric_total_points": 5, "criteria_points": [], "notes": "ok"}', "s1")
    assert item["criteria_points"] == {}


def test_parse_pass1_item_evidence_edge_cases():
    raw = json.dumps({
        "student_id": "s1",
        "rubric_total_points": 5,
        "criteria_points": {},
        "criteria_evidence": [
            "not a dict",
            {"criterion_id": "K1", "score": "n/a", "evidence_quote": "hello", "rationale": "ok"},
        ],
        "notes": "ok"
    })
    item = rla.parse_pass1_item(raw, "s1")
    assert item["criteria_points"] == {}


def test_parse_pass1_item_with_evidence_validation():
    raw = json.dumps({
        "student_id": "s1",
        "rubric_total_points": 80,
        "criteria_points": {},
        "criteria_evidence": [
            {"criterion_id": "K1", "level": "3", "score": 80, "evidence_quote": "hello", "rationale": "good enough"}
        ],
        "notes": "ok"
    })
    item = rla.parse_pass1_item(raw, "s1", ["K1"], {"quote_validation": True, "rationale_min_words": 1}, "hello world")
    assert item["criteria_points"]["K1"] == 75.0


def test_parse_pass1_item_invalid_quote():
    raw = json.dumps({
        "student_id": "s1",
        "rubric_total_points": 80,
        "criteria_points": {},
        "criteria_evidence": [
            {"criterion_id": "K1", "level": "3", "score": 80, "evidence_quote": "missing", "rationale": "good enough"}
        ],
        "notes": "ok"
    })
    with pytest.raises(ValueError):
        rla.parse_pass1_item(raw, "s1", ["K1"], {"quote_validation": True, "rationale_min_words": 1}, "hello world")


def test_parse_pass1_item_hard_fails_on_evidence_errors_even_in_lenient_mode():
    raw = json.dumps({
        "student_id": "s1",
        "rubric_total_points": 80,
        "criteria_points": {"K1": 80},
        "criteria_evidence": [],
        "notes": "ok",
    })
    with pytest.raises(ValueError):
        rla.parse_pass1_item(
            raw,
            "s1",
            ["K1"],
            {"quote_validation": True, "rationale_min_words": 1, "hard_fail_on_evidence_errors": True},
            "hello world",
            strict=False,
        )


def test_parse_pass1_item_skips_quote_validation_on_errors():
    raw = json.dumps({
        "student_id": "s1",
        "rubric_total_points": 80,
        "criteria_points": {},
        "criteria_evidence": [
            {"criterion_id": "K1", "level": "3", "score": 80, "evidence_quote": "", "rationale": "ok"}
        ],
        "notes": "ok"
    })
    with pytest.raises(ValueError):
        rla.parse_pass1_item(raw, "s1", ["K1"], {"quote_validation": True, "rationale_min_words": 1}, "hello world")


def test_parse_pass1_item_alt_evidence_keys():
    raw = json.dumps({
        "student_id": "s1",
        "rubric_total_points": 80,
        "criteria_points": {"K1": 3},
        "criteria_evidence": [
            {"criteria_id": "K1", "evidence": "hello", "rationale": "good enough"}
        ],
        "notes": "ok"
    })
    item = rla.parse_pass1_item(raw, "s1", ["K1"], {"quote_validation": True, "rationale_min_words": 1}, "hello world")
    assert item["criteria_points"]["K1"] == 75.0


def test_parse_pass1_item_alt_criterion_key_and_rationale_fill():
    raw = json.dumps({
        "student_id": "s1",
        "rubric_total_points": 80,
        "criteria_points": {"K1": 3},
        "notes": "fallback rationale",
        "criteria_evidence": [
            {"criterion": "K1", "evidence": "hello"}
        ],
    })
    item = rla.parse_pass1_item(raw, "s1", ["K1"], {"quote_validation": False, "rationale_min_words": 2}, "hello world")
    assert item["criteria_points"]["K1"] == 75.0
    assert item["criteria_evidence"][0]["rationale"] == "fallback rationale"


def test_parse_pass1_item_rationale_min_words_uses_notes():
    raw = json.dumps({
        "student_id": "s1",
        "rubric_total_points": 80,
        "criteria_points": {"K1": 3},
        "notes": "fallback rationale here",
        "criteria_evidence": [
            {"criterion_id": "K1", "evidence_quote": "hello", "rationale": "short", "score": 3}
        ],
    })
    item = rla.parse_pass1_item(raw, "s1", ["K1"], {"quote_validation": False, "rationale_min_words": 3}, "hello world")
    assert item["criteria_evidence"][0]["rationale"] == "fallback rationale here"


def test_normalize_ranking_ids_variants():
    known = [
        "Alannah - Ghost essay",
        "Alyssa - ghost essay",
        "Hudson L - Leadership is a great skill to have",
    ]
    lines = ["Alannah", "alyssa - ghost essay", "Leadership skill"]
    assert rla.normalize_ranking_ids(lines, known) == [
        "Alannah - Ghost essay",
        "Alyssa - ghost essay",
        "Hudson L - Leadership is a great skill to have",
    ]


def test_normalize_ranking_ids_duplicate():
    known = ["Sam Essay", "Sam Draft"]
    with pytest.raises(ValueError):
        rla.normalize_ranking_ids(["Sam Essay", "Sam Essay"], known)


def test_normalize_ranking_ids_ambiguous():
    known = ["Sam Essay", "Sam Draft"]
    with pytest.raises(ValueError):
        rla.normalize_ranking_ids(["Sam"], known)


def test_run_llm_assessors_preflight_pass2_over_limit():
    texts = {"s1": "text"}
    routing = {"mode": "openai", "tasks": {"pass1_assessor": {"model": "gpt-5.2"}, "pass2_ranker": {"model": "gpt-5.2"}}}
    pricing = {"models": {"gpt-5.2": {"input_per_million": 1.0, "output_per_million": 1.0}}}
    limits = {"per_call_max_tokens": 50, "estimates": {"pass1_output_tokens": 1, "pass2_output_tokens": 1}}
    summaries = [{"student_id": "s1", "summary": "x" * 1000}]
    result = rla.preflight_costs(texts, "rubric", "outline", summaries, routing, pricing, limits)
    assert result["ok"] is False
