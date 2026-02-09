import csv
import json

import scripts.publish_gate as pg


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_pass1(path, fallback=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    note = "Fallback deterministic score" if fallback else "Model score"
    payload = {
        "assessor_id": "assessor_A",
        "scores": [
            {"student_id": "s001", "rubric_total_points": 84, "notes": note},
            {"student_id": "s002", "rubric_total_points": 74, "notes": note},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_inputs(tmp_path):
    _write_csv(
        tmp_path / "outputs/consensus_scores.csv",
        [
            {
                "student_id": "s001",
                "rubric_after_penalty_percent": "84.0",
                "adjusted_level": "4",
            },
            {
                "student_id": "s002",
                "rubric_after_penalty_percent": "74.0",
                "adjusted_level": "3",
            },
        ],
    )
    (tmp_path / "processing").mkdir(parents=True, exist_ok=True)
    (tmp_path / "processing/submission_metadata.json").write_text(
        json.dumps(
            [
                {"student_id": "s001", "display_name": "anchor_level_4"},
                {"student_id": "s002", "display_name": "anchor_level_3"},
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "outputs/irr_metrics.json").write_text(
        json.dumps({"inter_rater_reliability": {"rank_kendall_w": 0.9, "mean_rubric_sd": 1.0}}),
        encoding="utf-8",
    )
    _write_pass1(tmp_path / "assessments/pass1_individual/assessor_A.json", fallback=False)
    _write_pass1(tmp_path / "assessments/pass1_individual/assessor_B.json", fallback=False)
    _write_pass1(tmp_path / "assessments/pass1_individual/assessor_C.json", fallback=False)
    (tmp_path / "inputs/class_metadata.json").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "inputs/class_metadata.json").write_text(
        json.dumps({"grade_level": 8, "assignment_genre": "argumentative"}),
        encoding="utf-8",
    )
    (tmp_path / "config/marking_config.json").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config/marking_config.json").write_text(
        json.dumps({"levels": {"bands": [
            {"level": "1", "min": 50, "max": 59},
            {"level": "2", "min": 60, "max": 69},
            {"level": "3", "min": 70, "max": 79},
            {"level": "4", "min": 80, "max": 89},
            {"level": "4+", "min": 90, "max": 100},
        ]}}),
        encoding="utf-8",
    )
    (tmp_path / "outputs/calibration_bias.json").write_text(
        json.dumps(
            {
                "assessors": {
                    "assessor_A": {
                        "scopes": {
                            "grade_8_10|argumentative": {
                                "level_hit_rate": 0.9,
                                "mae": 3.0,
                                "pairwise_order_agreement": 0.9,
                                "repeat_level_consistency": 0.95,
                                "bias": 0.5,
                            }
                        }
                    },
                    "assessor_B": {
                        "scopes": {
                            "grade_8_10|argumentative": {
                                "level_hit_rate": 0.9,
                                "mae": 3.0,
                                "pairwise_order_agreement": 0.9,
                                "repeat_level_consistency": 0.95,
                                "bias": 0.5,
                            }
                        }
                    },
                    "assessor_C": {
                        "scopes": {
                            "grade_8_10|argumentative": {
                                "level_hit_rate": 0.9,
                                "mae": 3.0,
                                "pairwise_order_agreement": 0.9,
                                "repeat_level_consistency": 0.95,
                                "bias": 0.5,
                            }
                        }
                    },
                }
            }
        ),
        encoding="utf-8",
    )


def test_publish_gate_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_inputs(tmp_path)
    (tmp_path / "config/accuracy_gate.json").write_text(
        json.dumps(
            {
                "thresholds": {
                    "min_rank_kendall_w": 0.8,
                    "max_mean_rubric_sd": 2.0,
                    "min_model_coverage": 0.9,
                    "boundary_margin_percent": 1.0,
                    "max_boundary_students": 2,
                    "anchor_min_hit_rate": 0.8,
                    "anchor_max_mae": 0.5,
                    "calibration_min_level_hit_rate": 0.8,
                    "calibration_max_mae": 8.0,
                    "calibration_min_pairwise_order": 0.8,
                    "calibration_min_repeat_level_consistency": 0.8,
                    "calibration_max_abs_bias": 6.0,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "publish_gate",
            "--gate-config",
            "config/accuracy_gate.json",
            "--output",
            "outputs/publish_gate.json",
        ],
    )
    assert pg.main() == 0
    result = json.loads((tmp_path / "outputs/publish_gate.json").read_text(encoding="utf-8"))
    assert result["ok"] is True


def test_publish_gate_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_inputs(tmp_path)
    # Force fallback-only notes for coverage failure.
    _write_pass1(tmp_path / "assessments/pass1_individual/assessor_A.json", fallback=True)
    _write_pass1(tmp_path / "assessments/pass1_individual/assessor_B.json", fallback=True)
    _write_pass1(tmp_path / "assessments/pass1_individual/assessor_C.json", fallback=True)
    (tmp_path / "config/accuracy_gate.json").write_text(
        json.dumps(
            {
                "thresholds": {
                    "min_rank_kendall_w": 0.95,
                    "max_mean_rubric_sd": 0.5,
                    "min_model_coverage": 1.0,
                    "boundary_margin_percent": 1.0,
                    "max_boundary_students": 0,
                    "anchor_min_hit_rate": 1.0,
                    "anchor_max_mae": 0.0,
                    "calibration_min_level_hit_rate": 0.95,
                    "calibration_max_mae": 1.0,
                    "calibration_min_pairwise_order": 0.95,
                    "calibration_min_repeat_level_consistency": 0.95,
                    "calibration_max_abs_bias": 0.1,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "publish_gate",
            "--gate-config",
            "config/accuracy_gate.json",
            "--output",
            "outputs/publish_gate.json",
        ],
    )
    assert pg.main() == 2
    result = json.loads((tmp_path / "outputs/publish_gate.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert "model_coverage_below_threshold" in result["failures"]


def test_publish_gate_helper_branches(tmp_path):
    assert pg.load_json(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{broken", encoding="utf-8")
    assert pg.load_json(bad) == {}
    assert pg.load_rows(tmp_path / "missing.csv") == []
    assert pg.parse_expected_level("x_level_4_plus") == "4+"
    assert pg.parse_expected_level("plain") is None
    assert pg.boundary_count([], [], 1.0) == 0
    rows = [{"rubric_after_penalty_percent": "oops"}, {"rubric_after_penalty_percent": "79.5"}]
    bands = [{"min": 50}, {"min": 60}, {"min": 70}, {"min": 80}]
    assert pg.boundary_count(rows, bands, 1.0) == 1
    assert pg.anchor_metrics([], []) == (0, 0.0, 0.0)
    assert pg.scope_from_metadata(tmp_path / "missing-class.json") == ""
    cal = pg.calibration_metrics(tmp_path / "missing-cal.json", ["A"], "grade_8_10|argumentative")
    assert "assessor_A" in cal["missing_assessors"]


def test_publish_gate_evaluate_covers_all_failure_codes():
    metrics = {
        "irr_rank_kendalls_w": 0.1,
        "irr_mean_rubric_sd": 9.0,
        "model_coverage": 0.1,
        "boundary_count": 9,
        "anchors_total": 2,
        "anchor_hit_rate": 0.1,
        "anchor_level_mae": 2.0,
        "cal_missing_assessors": ["assessor_A"],
        "cal_level_hit_rate": 0.1,
        "cal_mae": 20.0,
        "cal_pairwise_order": 0.1,
        "cal_repeat_consistency": 0.1,
        "cal_abs_bias": 20.0,
    }
    thresholds = {
        "min_rank_kendall_w": 0.7,
        "max_mean_rubric_sd": 2.0,
        "min_model_coverage": 0.95,
        "max_boundary_students": 0,
        "anchor_min_hit_rate": 0.8,
        "anchor_max_mae": 0.5,
        "calibration_min_level_hit_rate": 0.8,
        "calibration_max_mae": 8.0,
        "calibration_min_pairwise_order": 0.8,
        "calibration_min_repeat_level_consistency": 0.8,
        "calibration_max_abs_bias": 6.0,
    }
    failures = pg.evaluate(metrics, thresholds)
    assert "kendall_w_below_threshold" in failures
    assert "rubric_sd_above_threshold" in failures
    assert "model_coverage_below_threshold" in failures
    assert "too_many_boundary_students" in failures
    assert "anchor_hit_rate_below_threshold" in failures
    assert "anchor_mae_above_threshold" in failures
    assert "calibration_scope_missing" in failures
    assert "calibration_level_hit_rate_below_threshold" in failures
    assert "calibration_mae_above_threshold" in failures
    assert "calibration_pairwise_below_threshold" in failures
    assert "calibration_repeat_consistency_below_threshold" in failures
    assert "calibration_abs_bias_above_threshold" in failures


def test_publish_gate_main_with_non_list_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_inputs(tmp_path)
    (tmp_path / "processing/submission_metadata.json").write_text(json.dumps({"bad": True}), encoding="utf-8")
    (tmp_path / "inputs/class_metadata.json").write_text(json.dumps({"grade_level": 5}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["publish_gate", "--output", "outputs/publish_gate.json"])
    code = pg.main()
    assert code in (0, 2)
    result = json.loads((tmp_path / "outputs/publish_gate.json").read_text(encoding="utf-8"))
    assert result["metrics"]["scope"] == ""
