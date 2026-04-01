import json
import csv
from pathlib import Path

import scripts.aggregate_assessments as agg


def write_pass1(dir_path: Path, assessor_id: str, scores):
    data = {"assessor_id": assessor_id, "scores": scores}
    path = dir_path / f"{assessor_id}.json"
    path.write_text(json.dumps(data), encoding="utf-8")


def write_pass2(dir_path: Path, assessor_id: str, ranking):
    path = dir_path / f"{assessor_id}.txt"
    path.write_text("\n".join(ranking), encoding="utf-8")


def write_conventions(path: Path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_aggregate_assessments_success(tmp_path, monkeypatch):
    # Setup workspace
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)

    config = {
        "weights": {"rubric": 0.7, "conventions": 0.15, "comparative": 0.15},
        "consensus": {"rank_disagreement_threshold": 3, "rubric_sd_threshold": 0.8},
        "rubric": {"points_possible": None},
        "conventions": {"mistake_rate_threshold": 0.07, "max_level_drop": 1, "missing_data_mistake_rate_percent": 100.0},
        "levels": {"bands": [{"level": "1", "min": 50, "max": 59, "letter": "D"}, {"level": "4", "min": 80, "max": 89, "letter": "A"}, {"level": "4+", "min": 90, "max": 100, "letter": "A+"}]},
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(config), encoding="utf-8")

    pass1_dir = tmp_path / "assessments/pass1_individual"
    scores = [
        {"student_id": "s1", "rubric_total_points": 20},
        {"student_id": "s2", "rubric_total_points": 10},
    ]
    for assessor in ["a", "b", "c"]:
        write_pass1(pass1_dir, assessor, scores)

    pass2_dir = tmp_path / "assessments/pass2_comparative"
    for assessor in ["a", "b", "c"]:
        write_pass2(pass2_dir, assessor, ["s1", "s2"])

    conv_path = tmp_path / "processing/conventions_report.csv"
    write_conventions(conv_path, [
        {"student_id": "s1", "word_count": 100, "mistake_rate_percent": 1.0},
        {"student_id": "s2", "word_count": 100, "mistake_rate_percent": 10.0},
    ])

    out_path = tmp_path / "outputs/consensus_scores.csv"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["agg", "--config", str(cfg_path), "--output", str(out_path)])
    assert agg.main() == 0

    assert out_path.exists()
    data = out_path.read_text(encoding="utf-8")
    assert "composite_score" in data
    assert "level_with_modifier" in data
    # Ensure no 4++ for top band with + modifier
    assert "4++" not in data

    irr_path = tmp_path / "outputs/irr_metrics.json"
    assert irr_path.exists()


def test_aggregate_assessments_boundary_calibration_report(tmp_path, monkeypatch):
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)
    (tmp_path / "inputs").mkdir(parents=True)
    (tmp_path / "config").mkdir(parents=True)

    config = {
        "weights": {"rubric": 0.7, "conventions": 0.15, "comparative": 0.15},
        "consensus": {"rank_disagreement_threshold": 3, "rubric_sd_threshold": 0.8},
        "rubric": {"points_possible": 100},
        "conventions": {"mistake_rate_threshold": 0.15, "max_level_drop": 0.5, "missing_data_mistake_rate_percent": 100.0},
        "boundary_calibration": {
            "enabled": True,
            "strong_rank_fraction": 0.5,
            "strong_borda_min": 0.55,
            "max_rank_sd": 1.5,
            "max_rubric_sd_points": 8.0,
            "max_score_adjustment_percent": 6.0,
            "top_boundary_margin_percent": 4.0,
            "severe_gap_levels": 2,
            "severe_collapse_min_rubric_percent": 58.0,
            "severe_collapse_target_floor_percent": 70.0,
            "severe_collapse_max_adjustment_percent": 12.0,
            "early_grade_narrative_boundary_bonus_percent": 2.0,
            "portfolio_boundary_bonus_percent": 1.5,
            "portfolio_min_rubric_percent": 62.0,
            "portfolio_target_floor_percent": 70.0,
        },
        "levels": {
            "bands": [
                {"level": "1", "min": 50, "max": 59, "letter": "D"},
                {"level": "2", "min": 60, "max": 69, "letter": "C"},
                {"level": "3", "min": 70, "max": 79, "letter": "B"},
                {"level": "4", "min": 80, "max": 89, "letter": "A"},
            ]
        },
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / "inputs/class_metadata.json").write_text(
        json.dumps({"grade_level": 3, "assignment_genre": "narrative"}),
        encoding="utf-8",
    )
    (tmp_path / "config/grade_level_profiles.json").write_text(json.dumps({"grade_3": {}}), encoding="utf-8")

    pass1_dir = tmp_path / "assessments/pass1_individual"
    scores_a = [
        {"student_id": "s1", "rubric_total_points": 70},
        {"student_id": "s2", "rubric_total_points": 63},
    ]
    scores_b = [
        {"student_id": "s1", "rubric_total_points": 71},
        {"student_id": "s2", "rubric_total_points": 62},
    ]
    scores_c = [
        {"student_id": "s1", "rubric_total_points": 69},
        {"student_id": "s2", "rubric_total_points": 64},
    ]
    write_pass1(pass1_dir, "a", scores_a)
    write_pass1(pass1_dir, "b", scores_b)
    write_pass1(pass1_dir, "c", scores_c)

    pass2_dir = tmp_path / "assessments/pass2_comparative"
    for assessor in ["a", "b", "c"]:
        write_pass2(pass2_dir, assessor, ["s1", "s2"])

    conv_path = tmp_path / "processing/conventions_report.csv"
    write_conventions(
        conv_path,
        [
            {"student_id": "s1", "word_count": 100, "mistake_rate_percent": 18.0},
            {"student_id": "s2", "word_count": 100, "mistake_rate_percent": 1.0},
        ],
    )

    out_path = tmp_path / "outputs/consensus_scores.csv"
    report_path = tmp_path / "outputs/boundary_report.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "agg",
            "--config",
            str(cfg_path),
            "--output",
            str(out_path),
            "--boundary-report",
            str(report_path),
        ],
    )
    assert agg.main() == 0

    rows = list(csv.DictReader(out_path.open("r", encoding="utf-8")))
    s1 = next(row for row in rows if row["student_id"] == "s1")
    assert s1["adjusted_level"] == "3"
    assert "early_grade_narrative_boundary" in s1["boundary_calibration_reason"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["movement_count"] == 1
    assert report["scope"]["is_early_grade_narrative"] is True


def test_aggregate_assessments_portfolio_mode_normalizes_scores(tmp_path, monkeypatch):
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)
    (tmp_path / "inputs").mkdir(parents=True)
    (tmp_path / "config").mkdir(parents=True)

    config = {
        "weights": {"rubric": 0.7, "conventions": 0.15, "comparative": 0.15},
        "portfolio_mode": {
            "enabled": True,
            "note_clamp_threshold": 4.0,
            "conventions_threshold_bonus_percent": 5.0,
            "max_level_drop_scale": 0.35,
            "weights": {"rubric": 0.78, "conventions": 0.17, "comparative": 0.05},
        },
        "consensus": {"rank_disagreement_threshold": 3, "rubric_sd_threshold": 0.8},
        "rubric": {"points_possible": 100},
        "conventions": {"mistake_rate_threshold": 0.15, "max_level_drop": 0.5, "missing_data_mistake_rate_percent": 100.0},
        "boundary_calibration": {"enabled": False},
        "levels": {
            "bands": [
                {"level": "1", "min": 50, "max": 59, "letter": "D"},
                {"level": "2", "min": 60, "max": 69, "letter": "C"},
                {"level": "3", "min": 70, "max": 79, "letter": "B"},
                {"level": "4", "min": 80, "max": 89, "letter": "A"},
            ]
        },
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / "inputs/class_metadata.json").write_text(
        json.dumps({"assessment_unit": "portfolio", "grade_numeric_equivalent": 2, "genre_form": "mixed writing portfolio"}),
        encoding="utf-8",
    )
    (tmp_path / "config/grade_level_profiles.json").write_text(json.dumps({"grade_2": {}}), encoding="utf-8")

    pass1_dir = tmp_path / "assessments/pass1_individual"
    for assessor, top_score in [("a", 39.15), ("b", 35.71), ("c", 38.52)]:
        write_pass1(
            pass1_dir,
            assessor,
            [
                {
                    "student_id": "s1",
                    "rubric_total_points": top_score,
                    "notes": "Overall working at/near greater depth: a strong portfolio showing varied purposes and above expected standard.",
                },
                {
                    "student_id": "s2",
                    "rubric_total_points": 63.33,
                    "notes": "Overall working towards expected standard.",
                },
            ],
        )

    pass2_dir = tmp_path / "assessments/pass2_comparative"
    for assessor in ["a", "b", "c"]:
        write_pass2(pass2_dir, assessor, ["s1", "s2"])

    conv_path = tmp_path / "processing/conventions_report.csv"
    write_conventions(
        conv_path,
        [
            {"student_id": "s1", "word_count": 1000, "mistake_rate_percent": 8.0},
            {"student_id": "s2", "word_count": 500, "mistake_rate_percent": 16.0},
        ],
    )

    out_path = tmp_path / "outputs/consensus_scores.csv"
    portfolio_report_path = tmp_path / "outputs/portfolio_mode_report.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "agg",
            "--config",
            str(cfg_path),
            "--output",
            str(out_path),
            "--portfolio-report",
            str(portfolio_report_path),
        ],
    )
    assert agg.main() == 0

    rows = list(csv.DictReader(out_path.open("r", encoding="utf-8")))
    s1 = next(row for row in rows if row["student_id"] == "s1")
    assert s1["adjusted_level"] == "4"
    assert s1["portfolio_note_level"] == "4"
    assert s1["portfolio_note_votes"] == "3"
    report = json.loads(portfolio_report_path.read_text(encoding="utf-8"))
    assert report["applied"] == 3
    assert report["student_summaries"]["s1"]["note_canonical_level"] == "4"


def test_aggregate_assessments_applies_small_ordinal_portfolio_scale_calibration(tmp_path, monkeypatch):
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)
    (tmp_path / "inputs").mkdir(parents=True)
    (tmp_path / "config").mkdir(parents=True)

    config = {
        "weights": {"rubric": 0.7, "conventions": 0.15, "comparative": 0.15},
        "portfolio_mode": {
            "enabled": True,
            "note_clamp_threshold": 4.0,
            "conventions_threshold_bonus_percent": 5.0,
            "max_level_drop_scale": 0.35,
            "ordinal_scale_calibration": {
                "enabled": True,
                "top_fraction": 0.25,
                "bottom_fraction": 0.25,
                "early_grade_top_min_percent": 72.0,
                    "early_grade_middle_min_percent": 63.25,
                "bottom_max_percent": 70.0,
                "max_rank_sd": 1.5,
                "band_floor_offset_percent": 1.5,
            },
            "weights": {"rubric": 0.78, "conventions": 0.17, "comparative": 0.05},
        },
        "consensus": {"rank_disagreement_threshold": 3, "rubric_sd_threshold": 0.8},
        "rubric": {"points_possible": 100},
        "conventions": {"mistake_rate_threshold": 0.15, "max_level_drop": 0.5, "missing_data_mistake_rate_percent": 100.0},
        "boundary_calibration": {"enabled": False},
        "levels": {
            "bands": [
                {"level": "1", "min": 50, "max": 59, "letter": "D"},
                {"level": "2", "min": 60, "max": 69, "letter": "C"},
                {"level": "3", "min": 70, "max": 79, "letter": "B"},
                {"level": "4", "min": 80, "max": 89, "letter": "A"},
            ]
        },
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / "inputs/class_metadata.json").write_text(
        json.dumps(
            {
                "assessment_unit": "portfolio",
                "grade_numeric_equivalent": 2,
                "genre_form": "mixed writing portfolio",
                "sample_count": 3,
                "scoring_scale": {
                    "type": "ordinal",
                    "labels": [
                        "Working towards the expected standard",
                        "Working at the expected standard",
                        "Working at greater depth within the expected standard",
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "config/grade_level_profiles.json").write_text(json.dumps({"grade_2": {}}), encoding="utf-8")

    pass1_dir = tmp_path / "assessments/pass1_individual"
    assessor_scores = [
        ("a", {"s1": 73.48, "s2": 63.41, "s3": 62.58}),
        ("b", {"s1": 73.26, "s2": 64.63, "s3": 63.02}),
        ("c", {"s1": 73.53, "s2": 63.85, "s3": 64.34}),
    ]
    for assessor, scores in assessor_scores:
        write_pass1(
            pass1_dir,
            assessor,
            [
                {
                    "student_id": sid,
                    "rubric_total_points": value,
                    "portfolio_overall_level": "3" if sid == "s1" else "2",
                    "portfolio_aggregation": {"overall_level": "3" if sid == "s1" else "2"},
                }
                for sid, value in scores.items()
            ],
        )

    pass2_dir = tmp_path / "assessments/pass2_comparative"
    for assessor in ["a", "b", "c"]:
        write_pass2(pass2_dir, assessor, ["s1", "s2", "s3"])

    conv_path = tmp_path / "processing/conventions_report.csv"
    write_conventions(
        conv_path,
        [
            {"student_id": "s1", "word_count": 1000, "mistake_rate_percent": 8.35},
            {"student_id": "s2", "word_count": 700, "mistake_rate_percent": 15.41},
            {"student_id": "s3", "word_count": 600, "mistake_rate_percent": 20.56},
        ],
    )

    out_path = tmp_path / "outputs/consensus_scores.csv"
    portfolio_report_path = tmp_path / "outputs/portfolio_mode_report.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "agg",
            "--config",
            str(cfg_path),
            "--output",
            str(out_path),
            "--portfolio-report",
            str(portfolio_report_path),
        ],
    )
    assert agg.main() == 0

    rows = {row["student_id"]: row for row in csv.DictReader(out_path.open("r", encoding="utf-8"))}
    assert rows["s1"]["adjusted_level"] == "4"
    assert rows["s1"]["portfolio_scale_adjusted"] == "true"
    assert rows["s2"]["adjusted_level"] == "3"
    assert rows["s2"]["portfolio_scale_adjusted"] == "true"
    assert rows["s3"]["adjusted_level"] == "2"
    report = json.loads(portfolio_report_path.read_text(encoding="utf-8"))
    assert report["scale_calibration"]["applied"] == 2


def test_aggregate_assessments_missing_data(tmp_path, monkeypatch):
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"weights": {}, "consensus": {}, "conventions": {}, "rubric": {}}), encoding="utf-8")

    pass1_dir = tmp_path / "assessments/pass1_individual"
    write_pass1(pass1_dir, "a", [{"student_id": "s1", "rubric_total_points": 1}])
    write_pass1(pass1_dir, "b", [{"student_id": "s1", "rubric_total_points": 1}])

    pass2_dir = tmp_path / "assessments/pass2_comparative"
    write_pass2(pass2_dir, "a", ["s1"])
    # Missing pass2 for assessor b

    conv_path = tmp_path / "processing/conventions_report.csv"
    write_conventions(conv_path, [{"student_id": "s1", "word_count": 10, "mistake_rate_percent": 0.0}])

    out_path = tmp_path / "outputs/consensus_scores.csv"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["agg", "--config", str(cfg_path), "--output", str(out_path)])
    assert agg.main() == 1

    monkeypatch.setattr("sys.argv", ["agg", "--config", str(cfg_path), "--output", str(out_path), "--allow-missing-data"])
    assert agg.main() == 0


def test_aggregate_assessments_missing_conventions_allowed(tmp_path, monkeypatch):
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"weights": {}, "consensus": {}, "conventions": {"missing_data_mistake_rate_percent": 99.0}, "rubric": {}}), encoding="utf-8")

    pass1_dir = tmp_path / "assessments/pass1_individual"
    for assessor in ["a", "b", "c"]:
        write_pass1(pass1_dir, assessor, [{"student_id": "s1", "rubric_total_points": 1}])

    pass2_dir = tmp_path / "assessments/pass2_comparative"
    for assessor in ["assessor_a", "assessor_b", "assessor_c"]:
        write_pass2(pass2_dir, assessor, ["s1"])

    # No conventions report written
    out_path = tmp_path / "outputs/consensus_scores.csv"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["agg", "--config", str(cfg_path), "--output", str(out_path), "--allow-missing-data"])
    assert agg.main() == 0


def test_aggregate_assessments_rubric_points_from_assessor(tmp_path, monkeypatch):
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "weights": {},
                "consensus": {"rubric_central_tendency": "mean"},
                "conventions": {},
                "rubric": {"points_possible": None},
            }
        ),
        encoding="utf-8",
    )

    pass1_dir = tmp_path / "assessments/pass1_individual"
    scores = [{"student_id": "s1", "rubric_total_points": None, "criteria_points": {"c1": 5, "c2": 5}}]
    for assessor in ["a", "b", "c"]:
        data = {"assessor_id": assessor, "rubric_points_possible": 20, "scores": scores}
        (pass1_dir / f"{assessor}.json").write_text(json.dumps(data), encoding="utf-8")

    pass2_dir = tmp_path / "assessments/pass2_comparative"
    for assessor in ["a", "b", "c"]:
        write_pass2(pass2_dir, assessor, ["s1"])

    conv_path = tmp_path / "processing/conventions_report.csv"
    write_conventions(conv_path, [{"student_id": "s1", "word_count": 10, "mistake_rate_percent": 0.0}])

    out_path = tmp_path / "outputs/consensus_scores.csv"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["agg", "--config", str(cfg_path), "--output", str(out_path)])
    assert agg.main() == 0

    rows = out_path.read_text(encoding="utf-8")
    assert "rubric_after_penalty_percent" in rows


def test_aggregate_assessments_many_errors_and_flags(tmp_path, monkeypatch):
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)

    cfg = {
        "weights": {},
        "consensus": {"rubric_sd_threshold": 0.1, "rank_disagreement_threshold": 0.1},
        "conventions": {"mistake_rate_threshold": 0.01, "max_level_drop": 1, "missing_data_mistake_rate_percent": 100.0},
        "rubric": {"points_possible": None},
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    # Pass1: only s1 has scores, with high variance
    pass1_dir = tmp_path / "assessments/pass1_individual"
    scores_a = [{"student_id": "s1", "rubric_total_points": 0}]
    scores_b = [{"student_id": "s1", "rubric_total_points": 100}]
    scores_c = [{"student_id": "s1", "rubric_total_points": 50}]
    write_pass1(pass1_dir, "a", scores_a)
    write_pass1(pass1_dir, "b", scores_b)
    write_pass1(pass1_dir, "c", scores_c)

    # Pass2: rankings with different orders and one missing student to trigger missing_rank
    students = ["s1"] + [f"s{i}" for i in range(2, 13)]
    pass2_dir = tmp_path / "assessments/pass2_comparative"
    write_pass2(pass2_dir, "a", students)
    write_pass2(pass2_dir, "b", students[1:] + ["s1"])  # move s1 to last
    write_pass2(pass2_dir, "c", students[:-1])  # omit s12

    # Conventions: only s1 to trigger missing conventions for others
    conv_path = tmp_path / "processing/conventions_report.csv"
    write_conventions(conv_path, [{"student_id": "s1", "word_count": 100, "mistake_rate_percent": 50.0}])

    out_path = tmp_path / "outputs/consensus_scores.csv"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["agg", "--config", str(cfg_path), "--output", str(out_path), "--allow-missing-data"])
    assert agg.main() == 0

    rows = list(csv.DictReader(out_path.open("r", encoding="utf-8")))
    s1 = next(r for r in rows if r["student_id"] == "s1")
    assert "rubric_sd" in s1["flags"]
    assert "rank_sd" in s1["flags"]
    assert "conventions_penalty" in s1["flags"]


def test_aggregate_assessments_bias_and_criteria_points(tmp_path, monkeypatch):
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)
    (tmp_path / "outputs").mkdir(parents=True)

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "weights": {},
                "consensus": {"rubric_central_tendency": "mean"},
                "conventions": {},
                "rubric": {"points_possible": None},
            }
        ),
        encoding="utf-8",
    )

    criteria_path = tmp_path / "rubric_criteria.json"
    criteria_path.write_text(json.dumps({"categories": {"c1": {"max_points": 100, "criteria": []}}}), encoding="utf-8")

    pass1_dir = tmp_path / "assessments/pass1_individual"
    scores = [{"student_id": "s1", "rubric_total_points": 90}]
    for assessor in ["assessor_a", "assessor_b", "assessor_c"]:
        write_pass1(pass1_dir, assessor, scores)

    pass2_dir = tmp_path / "assessments/pass2_comparative"
    for assessor in ["a", "b", "c"]:
        write_pass2(pass2_dir, assessor, ["s1"])

    conv_path = tmp_path / "processing/conventions_report.csv"
    write_conventions(conv_path, [{"student_id": "s1", "word_count": 10, "mistake_rate_percent": 0.0}])

    bias_path = tmp_path / "outputs/calibration_bias.json"
    bias_path.write_text(
        json.dumps(
            {
                "assessors": {
                    "assessor_a": {
                        "global": {"bias": 10, "weight": 0.6},
                        "scopes": {"grade_6_7|literary_analysis": {"bias": 8, "weight": 0.7}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    out_path = tmp_path / "outputs/consensus_scores.csv"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", [
        "agg",
        "--config", str(cfg_path),
        "--output", str(out_path),
        "--rubric-criteria", str(criteria_path),
        "--calibration-bias", str(bias_path),
        "--scope-key", "grade_6_7|literary_analysis",
    ])
    assert agg.main() == 0
    rows = list(csv.DictReader(out_path.open("r", encoding="utf-8")))
    assert float(rows[0]["rubric_mean_percent"]) < 90.0
    assert len(rows) == 1


def test_aggregate_assessments_no_level_band(tmp_path, monkeypatch):
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"weights": {}, "consensus": {}, "conventions": {}, "rubric": {}}), encoding="utf-8")

    pass1_dir = tmp_path / "assessments/pass1_individual"
    for assessor in ["a", "b", "c"]:
        write_pass1(pass1_dir, assessor, [{"student_id": "s1", "rubric_total_points": 1}])

    pass2_dir = tmp_path / "assessments/pass2_comparative"
    for assessor in ["a", "b", "c"]:
        write_pass2(pass2_dir, assessor, ["s1"])

    conv_path = tmp_path / "processing/conventions_report.csv"
    write_conventions(conv_path, [{"student_id": "s1", "word_count": 10, "mistake_rate_percent": 0.0}])

    out_path = tmp_path / "outputs/consensus_scores.csv"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(agg, "get_level_band", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("sys.argv", ["agg", "--config", str(cfg_path), "--output", str(out_path)])
    assert agg.main() == 0


def test_aggregate_assessments_keeps_higher_level_ahead_of_lower_level(tmp_path, monkeypatch):
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "weights": {"rubric": 0.7, "conventions": 0.15, "comparative": 0.15},
                "consensus": {},
                "conventions": {"mistake_rate_threshold": 0.5, "max_level_drop": 0.0, "missing_data_mistake_rate_percent": 100.0},
                "rubric": {"points_possible": 100},
                "levels": {
                    "bands": [
                        {"level": "3", "min": 70, "max": 79, "letter": "B"},
                        {"level": "4", "min": 80, "max": 89, "letter": "A"},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    pass1_dir = tmp_path / "assessments/pass1_individual"
    for assessor in ["a", "b", "c"]:
        write_pass1(
            pass1_dir,
            assessor,
            [
                {"student_id": "s4", "rubric_total_points": 80},
                {"student_id": "s3", "rubric_total_points": 79},
            ],
        )

    pass2_dir = tmp_path / "assessments/pass2_comparative"
    for assessor in ["a", "b", "c"]:
        write_pass2(pass2_dir, assessor, ["s3", "s4"])

    conv_path = tmp_path / "processing/conventions_report.csv"
    write_conventions(
        conv_path,
        [
            {"student_id": "s4", "word_count": 100, "mistake_rate_percent": 9.0},
            {"student_id": "s3", "word_count": 100, "mistake_rate_percent": 0.0},
        ],
    )

    out_path = tmp_path / "outputs/consensus_scores.csv"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["agg", "--config", str(cfg_path), "--output", str(out_path)])
    assert agg.main() == 0

    rows = list(csv.DictReader(out_path.open("r", encoding="utf-8")))
    assert [row["student_id"] for row in rows] == ["s4", "s3"]


def test_aggregate_assessments_rank_weight_from_calibration(tmp_path, monkeypatch):
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)
    (tmp_path / "outputs").mkdir(parents=True)

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"weights": {}, "consensus": {}, "conventions": {}, "rubric": {}}), encoding="utf-8")

    pass1_dir = tmp_path / "assessments/pass1_individual"
    for assessor in ["assessor_a", "assessor_b", "assessor_c"]:
        write_pass1(pass1_dir, assessor, [{"student_id": "s1", "rubric_total_points": 80}, {"student_id": "s2", "rubric_total_points": 60}])

    pass2_dir = tmp_path / "assessments/pass2_comparative"
    for assessor in ["assessor_a", "assessor_b", "assessor_c"]:
        write_pass2(pass2_dir, assessor, ["s1", "s2"])

    conv_path = tmp_path / "processing/conventions_report.csv"
    write_conventions(conv_path, [
        {"student_id": "s1", "word_count": 10, "mistake_rate_percent": 0.0},
        {"student_id": "s2", "word_count": 10, "mistake_rate_percent": 0.0},
    ])

    bias_path = tmp_path / "outputs/calibration_bias.json"
    bias_path.write_text(
        json.dumps(
            {
                "assessors": {
                    "assessor_a": {"global": {"weight": 0.5}},
                    "assessor_b": {"global": {"weight": 1.0}},
                    "assessor_c": {"global": {"weight": 1.0}},
                }
            }
        ),
        encoding="utf-8",
    )

    out_path = tmp_path / "outputs/consensus_scores.csv"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["agg", "--config", str(cfg_path), "--output", str(out_path), "--calibration-bias", str(bias_path)],
    )
    assert agg.main() == 0
    rows = list(csv.DictReader(out_path.open("r", encoding="utf-8")))
    assert float(rows[0]["borda_points"]) > float(rows[1]["borda_points"])
