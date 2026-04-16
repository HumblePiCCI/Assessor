import json
from pathlib import Path

from scripts.boundary_calibrator import apply_boundary_calibration


ROOT = Path(__file__).resolve().parents[1]


def load_fixture() -> dict:
    path = ROOT / "tests" / "fixtures" / "remaining_misses_2026-04-16.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_config() -> dict:
    return json.loads((ROOT / "config" / "marking_config.json").read_text(encoding="utf-8"))


def test_remaining_misses_source_family_band_projection_regressions():
    config = load_config()
    fixture = load_fixture()
    for case in fixture["cases"]:
        updated, report = apply_boundary_calibration(case["rows"], config, case["scope"])
        row = {item["student_id"]: item for item in updated}[case["student_id"]]
        expected = case["expected_after_fix"]
        score = float(row["rubric_after_penalty_percent"])
        reason = str(row.get("boundary_calibration_reason", ""))
        assert row["adjusted_level"] == expected["level"], case["dataset"]
        if "min_score" in expected:
            assert score >= float(expected["min_score"]), case["dataset"]
        if "max_score" in expected:
            assert score <= float(expected["max_score"]), case["dataset"]
        if expected.get("reason_contains"):
            assert expected["reason_contains"] in reason, case["dataset"]
        if expected.get("forbidden_reason"):
            assert expected["forbidden_reason"] not in reason, case["dataset"]
        assert report["scope"]["source_scale_profile"], case["dataset"]


def test_speech_poor_model_is_capped_below_okay_model():
    config = load_config()
    fixture = load_fixture()
    case = next(item for item in fixture["cases"] if item["dataset"] == "thoughtful_assessment_grade11_12_speech")
    updated, _ = apply_boundary_calibration(case["rows"], config, case["scope"])
    rows = {item["student_id"]: item for item in updated}
    assert float(rows["s003"]["rubric_after_penalty_percent"]) >= 60.0
    assert float(rows["s004"]["rubric_after_penalty_percent"]) <= 59.0


def test_remaining_misses_repeated_run_low_raw_variants():
    config = load_config()
    variants = [
        {
            "name": "book_review_low_top_raw",
            "scope": {
                "grade_level": 2,
                "genre": "literary_analysis",
                "source_family": "thoughtful_learning_assessment_models",
                "cohort_shape": "same_rubric_family_cross_topic",
                "pass1_model_family": "gpt-5.4-mini",
                "pass1_model_version": "gpt-5.4-mini",
            },
            "rows": [
                {"student_id": "s001", "rubric_mean_percent": 65.83, "rubric_after_penalty_percent": 65.83, "adjusted_level": "2", "base_level": "2", "borda_percent": 1.0, "rank_sd": 0.0, "rubric_sd_points": 1.54, "_level_order": 60.0, "_composite_bucket": 0.8, "_borda_bucket": 100.0, "conventions_mistake_rate_percent": 2.0, "flags": ""},
                {"student_id": "s002", "rubric_mean_percent": 64.17, "rubric_after_penalty_percent": 64.17, "adjusted_level": "2", "base_level": "2", "borda_percent": 0.6667, "rank_sd": 0.0, "rubric_sd_points": 3.32, "_level_order": 60.0, "_composite_bucket": 0.7, "_borda_bucket": 66.67, "conventions_mistake_rate_percent": 2.0, "flags": ""},
                {"student_id": "s003", "rubric_mean_percent": 49.09, "rubric_after_penalty_percent": 49.09, "adjusted_level": "1", "base_level": "1", "borda_percent": 0.3333, "rank_sd": 0.0, "rubric_sd_points": 3.43, "_level_order": 50.0, "_composite_bucket": 0.42, "_borda_bucket": 33.33, "conventions_mistake_rate_percent": 2.0, "flags": ""},
                {"student_id": "s004", "rubric_mean_percent": 23.33, "rubric_after_penalty_percent": 23.33, "adjusted_level": "1", "base_level": "1", "borda_percent": 0.0, "rank_sd": 0.0, "rubric_sd_points": 8.86, "_level_order": 50.0, "_composite_bucket": 0.23, "_borda_bucket": 0.0, "conventions_mistake_rate_percent": 2.0, "flags": ""},
            ],
            "expected_levels": {"s001": "4", "s002": "3", "s003": "2", "s004": "1"},
        },
        {
            "name": "persuasive_letter_low_okay_raw",
            "scope": {
                "grade_level": 7,
                "genre": "argumentative",
                "source_family": "thoughtful_learning_assessment_models",
                "cohort_shape": "same_prompt",
                "pass1_model_family": "gpt-5.4-mini",
                "pass1_model_version": "gpt-5.4-mini",
            },
            "rows": [
                {"student_id": "s001", "rubric_mean_percent": 65.25, "rubric_after_penalty_percent": 65.25, "adjusted_level": "2", "base_level": "2", "borda_percent": 1.0, "rank_sd": 0.0, "rubric_sd_points": 7.34, "_level_order": 60.0, "_composite_bucket": 0.8, "_borda_bucket": 100.0, "conventions_mistake_rate_percent": 2.0, "flags": ""},
                {"student_id": "s002", "rubric_mean_percent": 60.23, "rubric_after_penalty_percent": 60.23, "adjusted_level": "2", "base_level": "2", "borda_percent": 0.6667, "rank_sd": 0.0, "rubric_sd_points": 1.35, "_level_order": 60.0, "_composite_bucket": 0.7, "_borda_bucket": 66.67, "conventions_mistake_rate_percent": 2.0, "flags": ""},
                {"student_id": "s004", "rubric_mean_percent": 48.19, "rubric_after_penalty_percent": 47.96, "adjusted_level": "1", "base_level": "1", "borda_percent": 0.3333, "rank_sd": 0.0, "rubric_sd_points": 4.31, "_level_order": 50.0, "_composite_bucket": 0.48, "_borda_bucket": 33.33, "conventions_mistake_rate_percent": 2.0, "flags": ""},
                {"student_id": "s003", "rubric_mean_percent": 23.64, "rubric_after_penalty_percent": 23.64, "adjusted_level": "1", "base_level": "1", "borda_percent": 0.0, "rank_sd": 0.0, "rubric_sd_points": 4.29, "_level_order": 50.0, "_composite_bucket": 0.24, "_borda_bucket": 0.0, "conventions_mistake_rate_percent": 2.0, "flags": ""},
            ],
            "expected_levels": {"s001": "4", "s002": "3", "s003": "2", "s004": "1"},
        },
        {
            "name": "naep_grade8_low_skillful_raw",
            "scope": {
                "grade_level": 8,
                "genre": "informative_letter",
                "source_family": "NAEP / NCES",
                "rubric_family": "NAEP 1998 focused holistic writing scoring",
                "prompt_shared": True,
                "sample_count": 6,
                "scoring_scale_type": "ordinal",
                "scoring_scale_size": 6,
                "pass1_model_family": "gpt-5.4-mini",
                "pass1_model_version": "gpt-5.4-mini",
            },
            "rows": [
                {"student_id": "s001", "rubric_mean_percent": 75.17, "rubric_after_penalty_percent": 75.17, "adjusted_level": "3", "base_level": "3", "borda_percent": 0.7333, "rank_sd": 0.47, "rubric_sd_points": 0.44, "_level_order": 70.0, "_composite_bucket": 0.79, "_borda_bucket": 73.33, "conventions_mistake_rate_percent": 2.0, "flags": ""},
                {"student_id": "s003", "rubric_mean_percent": 65.35, "rubric_after_penalty_percent": 65.35, "adjusted_level": "2", "base_level": "2", "borda_percent": 0.6667, "rank_sd": 0.47, "rubric_sd_points": 2.4, "_level_order": 60.0, "_composite_bucket": 0.7, "_borda_bucket": 66.67, "conventions_mistake_rate_percent": 2.0, "flags": ""},
                {"student_id": "s004", "rubric_mean_percent": 58.98, "rubric_after_penalty_percent": 58.98, "adjusted_level": "1", "base_level": "1", "borda_percent": 0.4, "rank_sd": 0.0, "rubric_sd_points": 1.02, "_level_order": 50.0, "_composite_bucket": 0.59, "_borda_bucket": 40.0, "conventions_mistake_rate_percent": 2.0, "flags": ""},
                {"student_id": "s002", "rubric_mean_percent": 57.75, "rubric_after_penalty_percent": 57.75, "adjusted_level": "1", "base_level": "1", "borda_percent": 1.0, "rank_sd": 0.0, "rubric_sd_points": 3.07, "_level_order": 50.0, "_composite_bucket": 0.58, "_borda_bucket": 100.0, "conventions_mistake_rate_percent": 2.0, "flags": ""},
                {"student_id": "s005", "rubric_mean_percent": 49.55, "rubric_after_penalty_percent": 49.55, "adjusted_level": "1", "base_level": "1", "borda_percent": 0.2, "rank_sd": 0.0, "rubric_sd_points": 6.24, "_level_order": 50.0, "_composite_bucket": 0.5, "_borda_bucket": 20.0, "conventions_mistake_rate_percent": 2.0, "flags": ""},
                {"student_id": "s006", "rubric_mean_percent": 20.21, "rubric_after_penalty_percent": 20.21, "adjusted_level": "1", "base_level": "1", "borda_percent": 0.0, "rank_sd": 0.0, "rubric_sd_points": 15.88, "_level_order": 50.0, "_composite_bucket": 0.2, "_borda_bucket": 0.0, "conventions_mistake_rate_percent": 2.0, "flags": ""},
            ],
            "expected_levels": {"s001": "4", "s002": "4", "s003": "3", "s004": "2", "s005": "1", "s006": "1"},
        },
    ]
    for variant in variants:
        updated, _ = apply_boundary_calibration(variant["rows"], config, variant["scope"])
        levels = {row["student_id"]: row["adjusted_level"] for row in updated}
        assert levels == variant["expected_levels"], variant["name"]


def test_fixture_contains_adjudication_classification_for_each_miss():
    fixture = load_fixture()
    classifications = {case["classification"] for case in fixture["cases"]}
    assert classifications == {
        "source-native translation issue",
        "early-grade evidence interpretation issue",
        "real pipe error",
    }
    for case in fixture["cases"]:
        assert case["gold_notes"]
        assert case["source_family_context"]
        assert case["current_score"] is not None
        assert case["current_predicted_level"]
        assert case["current_rank_displacement"] is not None
        assert case["adjudication"]
