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
        "bias_correction": {"method": "linear_offset"},
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

    def fake_create(model, messages, temperature, reasoning, routing_path, text_format=None):
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
    assert "assessor_A" in data["assessors"]


def test_score_to_percent_points_possible():
    assert calib.score_to_percent(50, 100) == 50.0


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
