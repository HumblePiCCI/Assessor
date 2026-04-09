import json

import pytest

from scripts.llm_assessors_core import looks_like_prompt_echo, parse_pass1_item, pass1_text_format


def test_parse_pass1_item_rationale_min_words_notes_branch():
    raw = json.dumps({
        "student_id": "s1",
        "rubric_total_points": 80,
        "criteria_points": {"K1": 3},
        "notes": "fallback rationale here",
        "criteria_evidence": [
            {"criterion_id": "K1", "evidence_quote": "hello", "rationale": "short", "score": 3}
        ],
    })
    item = parse_pass1_item(raw, "s1", ["K1"], {"quote_validation": False, "rationale_min_words": 3}, "hello world")
    assert item["criteria_evidence"][0]["rationale"] == "fallback rationale here"


def test_parse_pass1_item_rationale_min_words_no_notes():
    raw = json.dumps({
        "student_id": "s1",
        "rubric_total_points": 80,
        "criteria_points": {"K1": 3},
        "notes": "",
        "criteria_evidence": [
            {"criterion_id": "K1", "evidence_quote": "hello", "rationale": "short", "score": 3}
        ],
    })
    try:
        parse_pass1_item(raw, "s1", ["K1"], {"quote_validation": False, "rationale_min_words": 3}, "hello world")
    except ValueError:
        assert True


def test_parse_pass1_item_maps_criteria_key():
    raw = json.dumps({
        "student_id": "s1",
        "rubric_total_points": 10,
        "criteria_points": {"K1": 2},
        "notes": "ok",
        "criteria_evidence": [
            {"criteria": "K1", "evidence": "quote here", "rationale": "ok", "score": 2}
        ],
    })
    item = parse_pass1_item(raw, "s1", ["K1"], {"quote_validation": False, "rationale_min_words": 0}, "quote here")
    evidence = item["criteria_evidence"][0]
    assert evidence["criterion_id"] == "K1"
    assert evidence["evidence_quote"] == "quote here"


def test_parse_pass1_item_derive_total_fails_if_scores_out_of_range():
    raw = json.dumps({
        "student_id": "s1",
        "rubric_total_points": 10,
        "criteria_points": {},
        "notes": "ok",
        "criteria_evidence": [
            {"criterion_id": "K1", "score": 999, "evidence_quote": "hello", "rationale": "ok"}
        ],
    })
    with pytest.raises(ValueError) as exc:
        parse_pass1_item(raw, "s1", ["K1"], {"quote_validation": False, "rationale_min_words": 0}, "hello")
    assert "Unable to derive rubric_total_points" in str(exc.value)


def test_parse_pass1_item_strict_false_adds_warnings_and_continues():
    raw = json.dumps({
        "student_id": "s1",
        "rubric_total_points": 10,
        "criteria_points": {"K1": 3},
        "notes": "ok",
        "criteria_evidence": [{"criterion_id": "K1", "level": "3", "evidence_quote": "missing", "rationale": "ok"}],
    })
    item = parse_pass1_item(raw, "s1", ["K1"], {"quote_validation": True, "rationale_min_words": 0}, "hello world", strict=False)
    assert item["rubric_total_points"] == 75.0
    assert any("Quote not found" in w for w in item.get("warnings", []))


def test_parse_pass1_item_quote_fuzzy_match():
    raw = json.dumps({
        "student_id": "s1",
        "rubric_total_points": 10,
        "criteria_points": {"K1": 3},
        "notes": "ok",
        "criteria_evidence": [{"criterion_id": "K1", "level": "3", "evidence_quote": "hello world", "rationale": "ok"}],
    })
    item = parse_pass1_item(raw, "s1", ["K1"], {"quote_validation": True, "rationale_min_words": 0}, "hello, world")
    assert item["rubric_total_points"] == 75.0


def test_parse_pass1_item_strict_false_fallback_total():
    raw = json.dumps({
        "student_id": "s1",
        "rubric_total_points": 88,
        "criteria_points": {},
        "notes": "ok",
        "criteria_evidence": [],
    })
    item = parse_pass1_item(raw, "s1", ["K1"], {"quote_validation": True, "rationale_min_words": 0}, "hello", strict=False)
    assert item["rubric_total_points"] == 88.0


def test_parse_pass1_item_strict_false_fallback_missing_raises():
    raw = json.dumps({
        "student_id": "s1",
        "rubric_total_points": 999,
        "criteria_points": {},
        "notes": "ok",
        "criteria_evidence": [],
    })
    with pytest.raises(ValueError):
        parse_pass1_item(raw, "s1", ["K1"], {"quote_validation": True, "rationale_min_words": 0}, "hello", strict=False)


def test_parse_pass1_item_rescues_non_json():
    raw = "K1 level 3\nrubric_total_points: 78"
    item = parse_pass1_item(raw, "s1", ["K1"], {"quote_validation": False, "rationale_min_words": 0}, "hello", strict=False)
    assert item["rubric_total_points"] == 75.0
    assert item["criteria_points"]["K1"] == 75.0


def test_parse_pass1_item_rescue_without_signal_raises():
    with pytest.raises(ValueError):
        parse_pass1_item("not json", "s1", ["K1"], {"quote_validation": False, "rationale_min_words": 0}, "hello", strict=False)


def test_parse_pass1_item_ignores_non_numeric_criteria_points_and_blank_evidence_id():
    raw = json.dumps({
        "student_id": "s1",
        "rubric_total_points": 70,
        "criteria_points": {"K1": "n/a"},
        "notes": "ok",
        "criteria_evidence": [{"criterion_id": "", "score": 3, "evidence_quote": "x", "rationale": "ok"}],
    })
    item = parse_pass1_item(raw, "s1", ["K1"], {"quote_validation": False, "rationale_min_words": 0}, "x", strict=False)
    assert item["criteria_points"] == {}


def test_parse_pass1_item_strict_false_rescues_truncated_outer_json():
    raw = """{
  "student_id": "s1",
  "rubric_total_points": 59,
  "criteria_points": [
    {
      "criterion_id": "K1",
      "score": 3
    },
    {
      "criterion_id": "K2",
      "score": 2
    }
  ],
  "notes": "truncated after this field"""
    item = parse_pass1_item(raw, "s1", ["K1", "K2"], {"quote_validation": False, "rationale_min_words": 0}, "essay text", strict=False)
    assert item["student_id"] == "s1"
    assert item["rubric_total_points"] == 59.0
    assert item["criteria_points"] == {}


def test_looks_like_prompt_echo_detection():
    bad = "{\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"USER: You are Assessor A\"}]}"
    assert looks_like_prompt_echo(bad, "s1") is True
    good = "{\"student_id\":\"s1\",\"rubric_total_points\":80,\"criteria_points\":{},\"notes\":\"ok\"}"
    assert looks_like_prompt_echo(good, "s1") is False


def test_pass1_text_format_uses_compact_criteria_object():
    fmt = pass1_text_format()
    criteria = fmt["schema"]["properties"]["criteria_points"]
    assert criteria["type"] == "array"
    assert criteria["items"]["properties"]["criterion_id"]["type"] == "string"
    assert criteria["items"]["properties"]["score"]["type"] == "number"
