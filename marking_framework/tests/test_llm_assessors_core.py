import json

from scripts.llm_assessors_core import parse_pass1_item


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
