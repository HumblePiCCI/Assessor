import json
from pathlib import Path

import pytest

from scripts import benchmark_main_vs_fallback as bmf


def test_parse_expected_level_variants():
    assert bmf.parse_expected_level("sample_level4_plus") == "4+"
    assert bmf.parse_expected_level("essay-level_3") == "3"
    assert bmf.parse_expected_level("essay level 2 draft") == "2"
    assert bmf.parse_expected_level("no marker here") is None


def test_ensure_dataset_shape(tmp_path):
    inputs = tmp_path / "inputs"
    subs = tmp_path / "submissions"
    inputs.mkdir()
    subs.mkdir()
    got_inputs, got_subs = bmf.ensure_dataset_shape(tmp_path)
    assert got_inputs == inputs
    assert got_subs == subs
    with pytest.raises(ValueError):
        bmf.ensure_dataset_shape(tmp_path / "missing")


def test_pass1_model_usage_ratio(tmp_path):
    pass1 = tmp_path / "pass1"
    pass1.mkdir()
    payload = {
        "scores": [
            {"student_id": "s1", "notes": "Fallback deterministic score for assessor A."},
            {"student_id": "s2", "notes": "Model rationale"},
        ]
    }
    (pass1 / "assessor_A.json").write_text(json.dumps(payload), encoding="utf-8")
    assert bmf.pass1_model_usage_ratio(pass1) == 0.5
    empty = tmp_path / "empty"
    empty.mkdir()
    assert bmf.pass1_model_usage_ratio(empty) == 0.0


def test_evaluate_run(tmp_path):
    run = tmp_path / "run"
    (run / "processing").mkdir(parents=True)
    (run / "outputs").mkdir(parents=True)
    (run / "assessments/pass1").mkdir(parents=True)
    (run / "processing/submission_metadata.json").write_text(
        json.dumps(
            [
                {"student_id": "s1", "display_name": "sample_level1_demo"},
                {"student_id": "s2", "display_name": "sample_level2_demo"},
            ]
        ),
        encoding="utf-8",
    )
    (run / "outputs/consensus_scores.csv").write_text(
        "student_id,adjusted_level,consensus_rank,rubric_after_penalty_percent\n"
        "s1,1,2,55.0\n"
        "s2,2,1,64.0\n",
        encoding="utf-8",
    )
    (run / "assessments/pass1/assessor_A.json").write_text(
        json.dumps({"scores": [{"student_id": "s1", "notes": "Model"}, {"student_id": "s2", "notes": "Model"}]}),
        encoding="utf-8",
    )
    out = bmf.evaluate_run(run)
    assert out["accuracy"] == 1.0
    assert out["model_usage_ratio"] == 1.0
    assert out["students"]["s1"]["expected"] == "1"
