import json
from pathlib import Path

import scripts.calibrate_assessors as calib


def test_calibrate_assessors(tmp_path, monkeypatch):
    exemplars = tmp_path / "exemplars" / "grade_6_7" / "literary_analysis"
    exemplars.mkdir(parents=True)
    (exemplars / "level_1.md").write_text("Essay text", encoding="utf-8")

    calibration = {
        "gold_samples": {
            "grade_6_7": {
                "literary_analysis": [
                    {"file": "level_1.md", "target_level": "1", "target_pct": 54}
                ]
            }
        },
        "bias_correction": {"method": "linear_offset", "repeats": 2},
    }
    calib_path = tmp_path / "calibration.json"
    calib_path.write_text(json.dumps(calibration), encoding="utf-8")

    rubric_path = tmp_path / "rubric.md"
    outline_path = tmp_path / "outline.md"
    rubric_path.write_text("rubric", encoding="utf-8")
    outline_path.write_text("outline", encoding="utf-8")

    routing = {"tasks": {"pass1_assessor": {"model": "gpt-5.2"}}}
    routing_path = tmp_path / "routing.json"
    routing_path.write_text(json.dumps(routing), encoding="utf-8")

    call_count = {"n": 0}

    def fake_create(model, messages, temperature, reasoning, routing_path, text_format=None):
        call_count["n"] += 1
        return {"output": [{"type": "output_text", "text": json.dumps({
            "student_id": "level_1",
            "rubric_total_points": 50,
            "criteria_points": {},
            "notes": "ok"
        })}]}

    monkeypatch.setattr(calib, "responses_create", fake_create)

    out_path = tmp_path / "bias.json"
    monkeypatch.setattr("sys.argv", [
        "calib",
        "--calibration", str(calib_path),
        "--exemplars", str(tmp_path / "exemplars"),
        "--rubric", str(rubric_path),
        "--outline", str(outline_path),
        "--routing", str(routing_path),
        "--assessors", "A",
        "--rubric-criteria", str(tmp_path / "none.json"),
        "--output", str(out_path),
    ])
    assert calib.main() == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    manifest = json.loads((out_path.parent / "calibration_manifest.json").read_text(encoding="utf-8"))
    assert "assessor_A" in data["assessors"]
    assert "global" in data["assessors"]["assessor_A"]
    assert "scopes" in data["assessors"]["assessor_A"]
    assert "stability_sd" in data["assessors"]["assessor_A"]["global"]
    assert "boundary_mae" in data["assessors"]["assessor_A"]["global"]
    assert "rank_stability_sd" in data["assessors"]["assessor_A"]["global"]
    assert manifest["synthetic"] is False
    assert manifest["model_version"] == "gpt-5.2"
    assert call_count["n"] == 2


def test_score_to_percent_points_possible():
    assert calib.score_to_percent(50, 100) == 50.0
    assert calib.scope_key("grade_6_7", "Literary Analysis") == "grade_6_7|literary_analysis"
    rows = list(calib.iter_gold_samples({"gold_samples": {"grade_6_7": {"literary_analysis": [{"file": "x"}]}}}))
    assert rows[0][0] == "grade_6_7"


def test_fit_affine_correction_branches():
    assert calib.fit_affine_correction([])["slope"] == 1.0
    single = calib.fit_affine_correction([(60.0, 70.0)])
    assert single["slope"] == 1.0
    assert single["intercept"] == 10.0
    flat = calib.fit_affine_correction([(60.0, 70.0), (60.0, 65.0)])
    assert flat["slope"] == 1.0
    multi = calib.fit_affine_correction([(50.0, 60.0), (100.0, 95.0)])
    assert 0.6 <= multi["slope"] <= 1.4


def test_map_profile_helpers():
    assert calib.build_map_points([]) == []
    points = calib.build_map_points([(50, 52), (60, 65), (60, 68), (70, 72), (80, 88)], max_points=3)
    assert len(points) <= 3
    assert calib._interpolate([], 42) == 42.0
    assert calib._interpolate([{"x": 60, "y": 70}], 50) == 70
    assert calib._interpolate([{"x": 60, "y": 70}, {"x": 70, "y": 80}], 65) == 75
    assert calib._interpolate([{"x": 60, "y": 70}, {"x": 60, "y": 75}], 60) == 75
    assert calib._interpolate([{"x": 60, "y": 70}, {"x": 80, "y": 90}], 99) == 90
    assert calib._order_metrics([], [], []) == (1.0, 1.0)
    assert calib._order_metrics([1.0], [2.0], ["a"]) == (1.0, 1.0)
    assert calib._stdev([]) == 0.0

    profile_empty = calib.compute_profile([])
    assert profile_empty["samples"] == 0

    profile = calib.compute_profile(
        [
            {"name": "a", "observed": 60, "target": 62, "target_level": "2"},
            {"name": "b", "observed": 74, "target": 75, "target_level": "3"},
            {"name": "c", "observed": 84, "target": 84, "target_level": "4"},
        ]
    )
    assert profile["samples"] == 3
    assert profile["observations"] == 3
    assert "map_points" in profile
    assert "weight" in profile
    assert "repeat_level_consistency" in profile
    mismatch = calib.compute_profile(
        [
            {"name": "x", "observed": 55, "target": 85, "target_level": "1"},
            {"name": "y", "observed": 56, "target": 84, "target_level": "4"},
        ]
    )
    assert mismatch["level_hit_rate"] < 1.0


def test_calibrate_assessors_empty_rubric(tmp_path, monkeypatch):
    calib_path = tmp_path / "calibration.json"
    calib_path.write_text(json.dumps({"gold_samples": {}},), encoding="utf-8")
    rubric_path = tmp_path / "rubric.md"
    outline_path = tmp_path / "outline.md"
    rubric_path.write_text("", encoding="utf-8")
    outline_path.write_text("outline", encoding="utf-8")
    monkeypatch.setattr("sys.argv", [
        "calib",
        "--calibration", str(calib_path),
        "--rubric", str(rubric_path),
        "--outline", str(outline_path),
    ])
    assert calib.main() == 1


def test_calibrate_assessors_missing_sample_skips(tmp_path, monkeypatch):
    calib_path = tmp_path / "calibration.json"
    calib_path.write_text(json.dumps({
        "gold_samples": {
            "grade_6_7": {"literary_analysis": [{"file": "missing.md", "target_level": "1", "target_pct": 55}]}
        }
    }), encoding="utf-8")
    rubric_path = tmp_path / "rubric.md"
    outline_path = tmp_path / "outline.md"
    rubric_path.write_text("rubric", encoding="utf-8")
    outline_path.write_text("outline", encoding="utf-8")
    routing_path = tmp_path / "routing.json"
    routing_path.write_text(json.dumps({"tasks": {"pass1_assessor": {"model": "gpt-5.2"}}}), encoding="utf-8")
    monkeypatch.setattr(calib, "responses_create", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Should not call")))
    out_path = tmp_path / "bias.json"
    monkeypatch.setattr("sys.argv", [
        "calib",
        "--calibration", str(calib_path),
        "--exemplars", str(tmp_path / "exemplars"),
        "--rubric", str(rubric_path),
        "--outline", str(outline_path),
        "--routing", str(routing_path),
        "--assessors", "A",
        "--rubric-criteria", str(tmp_path / "none.json"),
        "--output", str(out_path),
    ])
    assert calib.main() == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["assessors"] == {}


def test_calibrate_assessors_overrides_reqs(tmp_path, monkeypatch):
    exemplars = tmp_path / "exemplars" / "grade_6_7" / "literary_analysis"
    exemplars.mkdir(parents=True)
    (exemplars / "level_1.md").write_text("Essay text", encoding="utf-8")
    (tmp_path / "calibration.json").write_text(json.dumps({
        "gold_samples": {"grade_6_7": {"literary_analysis": [{"file": "level_1.md", "target_level": "1", "target_pct": 54}]}}
    }), encoding="utf-8")
    (tmp_path / "rubric.md").write_text("rubric", encoding="utf-8")
    (tmp_path / "outline.md").write_text("outline", encoding="utf-8")
    (tmp_path / "routing.json").write_text(json.dumps({"tasks": {"pass1_assessor": {"model": "gpt-5.2"}}}), encoding="utf-8")
    criteria_path = tmp_path / "rubric_criteria.json"
    criteria_path.write_text(json.dumps({
        "categories": {"c": {"criteria": [{"id": "K1"}]}},
        "evidence_requirements": {"quote_validation": True, "rationale_min_words": 20},
    }), encoding="utf-8")

    captured = {"reqs": None}

    monkeypatch.setattr(calib, "responses_create", lambda **kwargs: {"output": [{"type": "output_text", "text": json.dumps({"student_id": "level_1", "rubric_total_points": 54, "criteria_points": {"K1": 54}, "notes": "ok"})}]})

    def fake_parse(content, student_id, required_ids, reqs, essay, strict=False):
        captured["reqs"] = dict(reqs)
        return {"student_id": student_id, "rubric_total_points": 54, "criteria_points": {"K1": 54}, "notes": "ok"}

    monkeypatch.setattr(calib, "parse_pass1_item", fake_parse)
    monkeypatch.setattr("sys.argv", [
        "calib",
        "--calibration", str(tmp_path / "calibration.json"),
        "--exemplars", str(tmp_path / "exemplars"),
        "--rubric", str(tmp_path / "rubric.md"),
        "--outline", str(tmp_path / "outline.md"),
        "--routing", str(tmp_path / "routing.json"),
        "--assessors", "A",
        "--rubric-criteria", str(criteria_path),
        "--output", str(tmp_path / "bias.json"),
    ])
    assert calib.main() == 0
    assert captured["reqs"]["quote_validation"] is False
    assert captured["reqs"]["rationale_min_words"] == 0


def test_build_records_points_possible_branch(tmp_path, monkeypatch):
    exemplars = tmp_path / "exemplars" / "grade_6_7" / "literary_analysis"
    exemplars.mkdir(parents=True)
    (exemplars / "level_1.md").write_text("Essay text", encoding="utf-8")
    args = type("Args", (), {"exemplars": str(tmp_path / "exemplars"), "routing": str(tmp_path / "routing.json"), "repeats": 1})
    calibration = {
        "gold_samples": {"grade_6_7": {"literary_analysis": [{"file": "level_1.md", "target_level": "1", "target_pct": 54}]}}
    }
    routing = {"tasks": {"pass1_assessor": {"model": "x"}}}
    rubric = "rubric"
    outline = "outline"
    profiles = {}
    criteria_cfg = None
    monkeypatch.setattr(calib, "responses_create", lambda **kwargs: {"output": [{"type": "output_text", "text": json.dumps({"student_id": "level_1", "rubric_total_points": 8, "criteria_points": {}, "notes": "ok"})}]})
    monkeypatch.setattr(calib, "parse_pass1_item", lambda *a, **k: {"student_id": "level_1", "rubric_total_points": 8, "criteria_points": {}, "notes": "ok"})
    rows = calib.build_records(args, calibration, routing, rubric, outline, profiles, criteria_cfg, 10, ["A"])
    assert rows[0]["observed"] == 80.0


def test_build_records_fallback_on_model_error(tmp_path, monkeypatch):
    exemplars = tmp_path / "exemplars" / "grade_6_7" / "literary_analysis"
    exemplars.mkdir(parents=True)
    (exemplars / "level_1.md").write_text("Essay text", encoding="utf-8")
    args = type("Args", (), {"exemplars": str(tmp_path / "exemplars"), "routing": str(tmp_path / "routing.json"), "repeats": 2})
    calibration = {
        "gold_samples": {"grade_6_7": {"literary_analysis": [{"file": "level_1.md", "target_level": "1", "target_pct": 54}]}}
    }
    routing = {"tasks": {"pass1_assessor": {"model": "x"}}}
    monkeypatch.setattr(calib, "responses_create", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(
        calib,
        "deterministic_pass1_item",
        lambda student_id, text, assessor_id, required_ids, exemplars: {
            "student_id": student_id,
            "rubric_total_points": 42,
            "criteria_points": {},
            "notes": "fallback",
        },
    )
    rows = calib.build_records(args, calibration, routing, "rubric", "outline", {}, None, None, ["A"])
    assert len(rows) == 2
    assert rows[0]["observed"] == 42.0


def test_compute_profile_repeats_collapsed():
    profile = calib.compute_profile(
        [
            {"name": "essay1", "observed": 70, "target": 72, "target_level": "3"},
            {"name": "essay1", "observed": 71, "target": 72, "target_level": "3"},
            {"name": "essay1", "observed": 50, "target": 72, "target_level": "3"},
            {"name": "essay2", "observed": 85, "target": 84, "target_level": "4"},
            {"name": "essay2", "observed": 85, "target": 84, "target_level": "4"},
        ]
    )
    assert profile["samples"] == 2
    assert profile["observations"] == 5
    assert profile["stability_sd"] > 0
    assert profile["repeat_level_consistency"] < 1.0
