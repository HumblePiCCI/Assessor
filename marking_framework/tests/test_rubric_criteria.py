import json
from pathlib import Path

from scripts.rubric_criteria import (
    criteria_for_genre,
    criteria_ids,
    criteria_prompt,
    evidence_requirements,
    load_rubric_criteria,
    total_points,
    validate_criteria_evidence,
)


def test_load_rubric_criteria_missing(tmp_path):
    assert load_rubric_criteria(tmp_path / "missing.json") == {}


def test_total_points_and_ids(tmp_path):
    data = {
        "categories": {
            "c1": {"max_points": 10, "criteria": [{"id": "K1", "name": "A"}]},
            "c2": {"max_points": 15, "criteria": [{"id": "K2", "name": "B"}]},
        },
        "genre_specific_criteria": {"narrative": {"additional_criteria": [{"id": "N1"}]}}
    }
    path = tmp_path / "rubric.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = load_rubric_criteria(path)
    assert total_points(loaded) == 25
    assert criteria_ids(loaded, None) == ["K1", "K2"]
    assert criteria_ids(loaded, "narrative") == ["K1", "K2", "N1"]


def test_criteria_prompt_and_evidence():
    criteria = {
        "categories": {
            "c1": {"criteria": [{"id": "K1", "name": "A", "description": "desc", "indicators": {"3": "ok"}}]},
        },
        "evidence_requirements": {"quote_validation": True, "rationale_min_words": 2},
    }
    prompt = criteria_prompt(criteria, None)
    assert "K1" in prompt
    reqs = evidence_requirements(criteria)
    errors = validate_criteria_evidence(
        [{"criterion_id": "K1", "score": 1, "evidence_quote": "x", "rationale": "ok here"}],
        ["K1"],
        reqs,
    )
    assert errors == []
    errors = validate_criteria_evidence([], ["K1"], reqs)
    assert errors


def test_criteria_prompt_empty():
    assert criteria_prompt({}, None) == ""


def test_criteria_prompt_skips_missing_id_and_indicators():
    criteria = {
        "categories": {
            "c1": {"criteria": [{"name": "No id", "description": "skip me"}]},
            "c2": {"criteria": [{"id": "K2", "name": "Has id", "description": "desc", "indicators": ["x"]}]},
        }
    }
    prompt = criteria_prompt(criteria, None)
    assert "No id" not in prompt
    assert "K2" in prompt
    assert "Level" not in prompt


def test_validate_criteria_evidence_errors():
    reqs = {"quote_validation": True, "rationale_min_words": 3}
    items = [
        {"criterion_id": "K1", "score": None, "evidence_quote": "", "rationale": "too short"},
    ]
    errors = validate_criteria_evidence(items, ["K1", "K2"], reqs)
    assert any("Missing evidence for K2" in err for err in errors)
    assert any("Missing evidence quote for K1" in err for err in errors)
    assert any("Rationale too short for K1" in err for err in errors)
    assert any("Missing score for K1" in err for err in errors)


def test_validate_criteria_evidence_alt_id_keys():
    reqs = {"quote_validation": False, "rationale_min_words": 0}
    items = [
        {"criteria": "K1", "score": 1, "evidence_quote": "x", "rationale": "ok"},
        {"criterion": "K2", "score": 2, "evidence_quote": "y", "rationale": "ok"},
        {"criteria_id": "K3", "score": 3, "evidence_quote": "z", "rationale": "ok"},
    ]
    errors = validate_criteria_evidence(items, ["K1", "K2", "K3"], reqs)
    assert errors == []


def test_validate_criteria_evidence_skips_non_dict_and_missing_id():
    reqs = {"quote_validation": False, "rationale_min_words": 0}
    items = [
        "not a dict",
        {"score": 1, "evidence_quote": "x", "rationale": "ok"},
        {"criterion_id": "K1", "score": 2, "evidence_quote": "x", "rationale": "ok"},
    ]
    errors = validate_criteria_evidence(items, ["K1"], reqs)
    assert errors == []


def test_validate_criteria_evidence_no_required_ids():
    assert validate_criteria_evidence([{"criterion_id": "K1"}], [], {}) == []


def test_validate_criteria_evidence_no_quote_validation():
    reqs = {"quote_validation": False, "rationale_min_words": 0}
    items = [{"criterion_id": "K1", "score": 1, "evidence_quote": "", "rationale": "ok"}]
    errors = validate_criteria_evidence(items, ["K1"], reqs)
    assert not any("Missing evidence quote" in err for err in errors)
