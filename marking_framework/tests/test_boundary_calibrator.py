import json
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.boundary_calibrator import apply_boundary_calibration, load_scope_context


def make_config() -> dict:
    return {
        "boundary_calibration": {
            "enabled": True,
            "strong_rank_fraction": 0.4,
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
        },
        "levels": {
            "bands": [
                {"level": "1", "min": 50, "max": 59, "letter": "D"},
                {"level": "2", "min": 60, "max": 69, "letter": "C"},
                {"level": "3", "min": 70, "max": 79, "letter": "B"},
                {"level": "4", "min": 80, "max": 89, "letter": "A"},
                {"level": "4+", "min": 90, "max": 100, "letter": "A+"},
            ]
        },
    }


def write_scope(tmp_path: Path, metadata: dict) -> dict:
    metadata_path = tmp_path / "class_metadata.json"
    profiles_path = tmp_path / "grade_profiles.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    profiles_path.write_text(json.dumps({"grade_2": {}, "grade_3": {}, "grade_6": {}}), encoding="utf-8")
    return load_scope_context(metadata_path, profiles_path)


def test_boundary_calibrator_rescues_severe_collapse(tmp_path):
    scope = write_scope(tmp_path, {"grade_level": 6, "assignment_genre": "argumentative"})
    rows = [
        {
            "student_id": "s1",
            "rubric_mean_percent": 74.0,
            "rubric_after_penalty_percent": 58.0,
            "adjusted_level": "1",
            "adjusted_letter": "D",
            "base_level": "3",
            "base_letter": "B",
            "level_modifier": "",
            "level_with_modifier": "1",
            "borda_percent": 0.91,
            "rank_sd": 0.3,
            "rubric_sd_points": 2.0,
            "flags": "",
            "_level_order": 50.0,
            "_composite_bucket": 0.91,
            "_borda_bucket": 90.0,
            "conventions_mistake_rate_percent": 1.0,
        }
    ]

    updated, report = apply_boundary_calibration(rows, make_config(), scope)
    row = updated[0]
    assert row["adjusted_level"] == "3"
    assert row["rubric_after_penalty_percent"] == 70.0
    assert "severe_collapse_floor" in row["boundary_calibration_reason"]
    assert "severe_collapse_rescue" in row["flags"]
    assert row["level_with_modifier"] == "3"
    assert report["movement_count"] == 1


def test_boundary_calibrator_uplifts_early_grade_narrative_boundary(tmp_path):
    scope = write_scope(tmp_path, {"grade_level": 3, "assignment_genre": "narrative"})
    rows = [
        {
            "student_id": "s1",
            "rubric_mean_percent": 70.5,
            "rubric_after_penalty_percent": 68.5,
            "adjusted_level": "2",
            "adjusted_letter": "C",
            "base_level": "3",
            "base_letter": "B",
            "level_modifier": "+",
            "level_with_modifier": "2+",
            "borda_percent": 0.84,
            "rank_sd": 0.4,
            "rubric_sd_points": 2.1,
            "flags": "",
            "_level_order": 60.0,
            "_composite_bucket": 0.84,
            "_borda_bucket": 84.0,
            "conventions_mistake_rate_percent": 2.0,
        },
        {
            "student_id": "s2",
            "rubric_mean_percent": 63.0,
            "rubric_after_penalty_percent": 63.0,
            "adjusted_level": "2",
            "adjusted_letter": "C",
            "base_level": "2",
            "base_letter": "C",
            "level_modifier": "",
            "level_with_modifier": "2",
            "borda_percent": 0.40,
            "rank_sd": 0.8,
            "rubric_sd_points": 3.0,
            "flags": "",
            "_level_order": 60.0,
            "_composite_bucket": 0.40,
            "_borda_bucket": 40.0,
            "conventions_mistake_rate_percent": 3.0,
        },
    ]

    updated, report = apply_boundary_calibration(rows, make_config(), scope)
    row = next(item for item in updated if item["student_id"] == "s1")
    assert row["adjusted_level"] == "3"
    assert row["rubric_after_penalty_percent"] == 70.0
    assert "early_grade_narrative_boundary" in row["boundary_calibration_reason"]
    assert row["level_with_modifier"] == "3+"
    assert report["scope"]["is_early_grade_narrative"] is True


def test_boundary_calibrator_ignores_portfolio_specific_moves(tmp_path):
    scope = write_scope(
        tmp_path,
        {
            "assessment_unit": "portfolio",
            "grade_numeric_equivalent": 2,
            "genre_form": "mixed writing portfolio",
            "sample_count": 3,
            "scoring_scale": {
                "type": "ordinal",
                "labels": ["WTS", "EXS", "GDS"],
            },
        },
    )
    rows = [
        {
            "student_id": "portfolio_a",
            "rubric_mean_percent": 66.0,
            "rubric_after_penalty_percent": 61.0,
            "adjusted_level": "2",
            "adjusted_letter": "C",
            "base_level": "3",
            "base_letter": "B",
            "level_modifier": "",
            "level_with_modifier": "2",
            "borda_percent": 0.88,
            "rank_sd": 0.5,
            "rubric_sd_points": 2.0,
            "flags": "",
            "_level_order": 60.0,
            "_composite_bucket": 0.88,
            "_borda_bucket": 88.0,
            "conventions_mistake_rate_percent": 1.0,
        },
        {
            "student_id": "portfolio_b",
            "rubric_mean_percent": 60.0,
            "rubric_after_penalty_percent": 60.0,
            "adjusted_level": "2",
            "adjusted_letter": "C",
            "base_level": "2",
            "base_letter": "C",
            "level_modifier": "",
            "level_with_modifier": "2",
            "borda_percent": 0.25,
            "rank_sd": 1.2,
            "rubric_sd_points": 4.0,
            "flags": "",
            "_level_order": 60.0,
            "_composite_bucket": 0.25,
            "_borda_bucket": 25.0,
            "conventions_mistake_rate_percent": 4.0,
        },
    ]

    updated, report = apply_boundary_calibration(rows, make_config(), scope)
    row = next(item for item in updated if item["student_id"] == "portfolio_a")
    assert row["adjusted_level"] == "2"
    assert row["rubric_after_penalty_percent"] == 61.0
    assert row["boundary_calibration_reason"] == ""
    assert report["scope"]["is_portfolio"] is True
    assert report["movement_count"] == 0
    assert scope["is_small_ordinal_portfolio"] is True


def test_boundary_calibrator_does_not_over_promote_low_support_portfolio_rows(tmp_path):
    scope = write_scope(
        tmp_path,
        {
            "assessment_unit": "portfolio",
            "grade_numeric_equivalent": 6,
            "genre_form": "mixed writing portfolio",
        },
    )
    rows = [
        {
            "student_id": "top",
            "rubric_mean_percent": 75.4,
            "rubric_after_penalty_percent": 75.4,
            "adjusted_level": "3",
            "adjusted_letter": "B",
            "base_level": "3",
            "base_letter": "B",
            "level_modifier": "",
            "level_with_modifier": "3",
            "borda_percent": 0.67,
            "rank_sd": 0.8,
            "rubric_sd_points": 0.5,
            "flags": "",
            "_level_order": 70.0,
            "_composite_bucket": 0.80,
            "_borda_bucket": 67.0,
            "conventions_mistake_rate_percent": 2.0,
        },
        {
            "student_id": "mid",
            "rubric_mean_percent": 66.8,
            "rubric_after_penalty_percent": 66.8,
            "adjusted_level": "2",
            "adjusted_letter": "C",
            "base_level": "2",
            "base_letter": "C",
            "level_modifier": "",
            "level_with_modifier": "2",
            "borda_percent": 0.0,
            "rank_sd": 0.0,
            "rubric_sd_points": 4.6,
            "flags": "",
            "_level_order": 60.0,
            "_composite_bucket": 0.20,
            "_borda_bucket": 0.0,
            "conventions_mistake_rate_percent": 1.0,
        },
    ]

    updated, report = apply_boundary_calibration(rows, make_config(), scope)
    top = next(item for item in updated if item["student_id"] == "top")
    mid = next(item for item in updated if item["student_id"] == "mid")
    assert top["adjusted_level"] == "3"
    assert top["boundary_calibration_reason"] == ""
    assert mid["adjusted_level"] == "2"
    assert mid["boundary_calibration_reason"] == ""
    assert report["movement_count"] == 0


def test_boundary_calibrator_applies_naep_source_scale_profile(tmp_path):
    scope = write_scope(
        tmp_path,
        {
            "grade_numeric": 4,
            "genre_form": "narrative",
            "source_family": "NAEP / NCES",
            "rubric_family": "NAEP 1998 focused holistic writing scoring",
            "prompt_shared": True,
            "sample_count": 6,
            "scoring_scale": {
                "type": "ordinal",
                "labels": ["Unsatisfactory", "Insufficient", "Uneven", "Sufficient", "Skillful", "Excellent"],
            },
        },
    )
    config = make_config()
    config["boundary_calibration"]["source_scale_profiles"] = {
        "naep_release_6pt": {
            "match_source_family_contains": ["naep"],
            "scoring_scale_type": "ordinal",
            "scoring_scale_size": 6,
            "require_prompt_shared": True,
            "require_sample_count": 6,
            "require_student_count_match_scale": True,
            "rank_floor_percent_by_rank": [85.0, 80.0, 70.0, 60.0, 55.0, 50.0],
            "rank_ceiling_percent_by_rank": [89.0, 84.0, 79.0, 69.0, 59.0, 54.0],
            "min_current_score_by_rank": [74.0, 70.0, 52.0, 50.0, 50.0, 50.0],
            "min_base_score_by_rank": [78.0, 74.0, 64.0, 58.0, 50.0, 50.0],
            "min_borda_percent_by_rank": [0.75, 0.55, 0.35, 0.15, 0.0, 0.0],
            "max_rank_sd": 1.75,
            "max_rubric_sd_points": 9.0,
            "max_adjustment_percent": 18.0,
        }
    }
    rows = [
        {
            "student_id": "s1",
            "rubric_mean_percent": 79.5,
            "rubric_after_penalty_percent": 76.0,
            "adjusted_level": "3",
            "adjusted_letter": "B",
            "base_level": "4",
            "base_letter": "A",
            "level_modifier": "",
            "level_with_modifier": "3",
            "borda_percent": 0.88,
            "rank_sd": 0.4,
            "rubric_sd_points": 1.8,
            "flags": "",
            "_level_order": 70.0,
            "_composite_bucket": 0.88,
            "_borda_bucket": 88.0,
            "conventions_mistake_rate_percent": 1.0,
        },
        {
            "student_id": "s2",
            "rubric_mean_percent": 66.0,
            "rubric_after_penalty_percent": 55.0,
            "adjusted_level": "1",
            "adjusted_letter": "D",
            "base_level": "3",
            "base_letter": "B",
            "level_modifier": "",
            "level_with_modifier": "1",
            "borda_percent": 0.40,
            "rank_sd": 0.6,
            "rubric_sd_points": 2.5,
            "flags": "",
            "_level_order": 50.0,
            "_composite_bucket": 0.40,
            "_borda_bucket": 40.0,
            "conventions_mistake_rate_percent": 2.0,
        },
        {
            "student_id": "s3",
            "rubric_mean_percent": 61.0,
            "rubric_after_penalty_percent": 61.0,
            "adjusted_level": "2",
            "adjusted_letter": "C",
            "base_level": "2",
            "base_letter": "C",
            "level_modifier": "",
            "level_with_modifier": "2",
            "borda_percent": 0.2,
            "rank_sd": 0.8,
            "rubric_sd_points": 3.0,
            "flags": "",
            "_level_order": 60.0,
            "_composite_bucket": 0.20,
            "_borda_bucket": 20.0,
            "conventions_mistake_rate_percent": 3.0,
        },
        {
            "student_id": "s4",
            "rubric_mean_percent": 58.0,
            "rubric_after_penalty_percent": 58.0,
            "adjusted_level": "1",
            "adjusted_letter": "D",
            "base_level": "1",
            "base_letter": "D",
            "level_modifier": "",
            "level_with_modifier": "1",
            "borda_percent": 0.1,
            "rank_sd": 0.9,
            "rubric_sd_points": 3.5,
            "flags": "",
            "_level_order": 50.0,
            "_composite_bucket": 0.10,
            "_borda_bucket": 10.0,
            "conventions_mistake_rate_percent": 3.5,
        },
        {
            "student_id": "s5",
            "rubric_mean_percent": 54.0,
            "rubric_after_penalty_percent": 54.0,
            "adjusted_level": "1",
            "adjusted_letter": "D",
            "base_level": "1",
            "base_letter": "D",
            "level_modifier": "",
            "level_with_modifier": "1",
            "borda_percent": 0.05,
            "rank_sd": 1.0,
            "rubric_sd_points": 4.0,
            "flags": "",
            "_level_order": 50.0,
            "_composite_bucket": 0.05,
            "_borda_bucket": 5.0,
            "conventions_mistake_rate_percent": 4.0,
        },
        {
            "student_id": "s6",
            "rubric_mean_percent": 51.0,
            "rubric_after_penalty_percent": 51.0,
            "adjusted_level": "1",
            "adjusted_letter": "D",
            "base_level": "1",
            "base_letter": "D",
            "level_modifier": "",
            "level_with_modifier": "1",
            "borda_percent": 0.0,
            "rank_sd": 1.1,
            "rubric_sd_points": 4.4,
            "flags": "",
            "_level_order": 50.0,
            "_composite_bucket": 0.0,
            "_borda_bucket": 0.0,
            "conventions_mistake_rate_percent": 4.2,
        },
    ]

    updated, report = apply_boundary_calibration(rows, config, scope)
    top = next(item for item in updated if item["student_id"] == "s1")
    middle = next(item for item in updated if item["student_id"] == "s2")
    assert top["adjusted_level"] == "4"
    assert top["rubric_after_penalty_percent"] == 85.0
    assert "source_scale_floor:naep_release_6pt" in top["boundary_calibration_reason"]
    assert middle["adjusted_level"] == "3"
    assert middle["rubric_after_penalty_percent"] == 70.0
    assert report["scope"]["source_scale_profile"] == "naep_release_6pt"
    assert report["movement_count"] >= 2


def test_boundary_calibrator_applies_eqao_source_scale_floor_to_third_rank(tmp_path):
    scope = write_scope(
        tmp_path,
        {
            "grade_level": 6,
            "assignment_genre": "argumentative",
            "source_family": "EQAO ORQ",
            "rubric_family": "EQAO open response",
            "prompt_shared": True,
            "sample_count": 4,
            "scoring_scale": {
                "type": "ordinal",
                "labels": ["Level 1", "Level 2", "Level 3", "Level 4"],
                "numeric_mapping": {"Level 1": 1, "Level 2": 2, "Level 3": 3, "Level 4": 4},
            },
        },
    )
    config = make_config()
    config["boundary_calibration"]["source_scale_profiles"] = {
        "eqao_anchor_4pt": {
            "match_source_family_contains": ["eqao"],
            "scoring_scale_type": "ordinal",
            "scoring_scale_size": 4,
            "require_prompt_shared": True,
            "require_sample_count": 4,
            "require_student_count_match_scale": True,
            "rank_strategy": "borda_percent",
            "rank_floor_percent_by_rank": [80.0, 70.0, 60.0, 50.0],
            "rank_ceiling_percent_by_rank": [89.0, 79.0, 69.0, 59.0],
            "min_current_score_by_rank": [58.0, 58.0, 58.0, 50.0],
            "min_base_score_by_rank": [58.0, 58.0, 58.0, 50.0],
            "min_borda_percent_by_rank": [0.75, 0.5, 0.2, 0.0],
            "max_rank_sd": 1.25,
            "max_rubric_sd_points": 8.5,
            "max_adjustment_percent": 14.0,
        }
    }
    rows = [
        {
            "student_id": "s1",
            "rubric_mean_percent": 75.24,
            "rubric_after_penalty_percent": 75.24,
            "adjusted_level": "3",
            "adjusted_letter": "B",
            "base_level": "3",
            "base_letter": "B",
            "level_modifier": "",
            "level_with_modifier": "3",
            "borda_percent": 1.0,
            "rank_sd": 0.0,
            "rubric_sd_points": 7.8,
            "flags": "",
            "_level_order": 70.0,
            "_composite_bucket": 1.0,
            "_borda_bucket": 100.0,
            "conventions_mistake_rate_percent": 12.0,
        },
        {
            "student_id": "s2",
            "rubric_mean_percent": 58.65,
            "rubric_after_penalty_percent": 58.65,
            "adjusted_level": "1",
            "adjusted_letter": "D",
            "base_level": "1",
            "base_letter": "D",
            "level_modifier": "",
            "level_with_modifier": "1",
            "borda_percent": 0.6667,
            "rank_sd": 0.0,
            "rubric_sd_points": 4.23,
            "flags": "",
            "_level_order": 50.0,
            "_composite_bucket": 0.67,
            "_borda_bucket": 66.67,
            "conventions_mistake_rate_percent": 11.0,
        },
        {
            "student_id": "s3",
            "rubric_mean_percent": 58.91,
            "rubric_after_penalty_percent": 58.91,
            "adjusted_level": "1",
            "adjusted_letter": "D",
            "base_level": "1",
            "base_letter": "D",
            "level_modifier": "",
            "level_with_modifier": "1",
            "borda_percent": 0.3333,
            "rank_sd": 0.0,
            "rubric_sd_points": 4.74,
            "flags": "",
            "_level_order": 50.0,
            "_composite_bucket": 0.33,
            "_borda_bucket": 33.33,
            "conventions_mistake_rate_percent": 8.0,
        },
        {
            "student_id": "s4",
            "rubric_mean_percent": 55.53,
            "rubric_after_penalty_percent": 55.53,
            "adjusted_level": "1",
            "adjusted_letter": "D",
            "base_level": "1",
            "base_letter": "D",
            "level_modifier": "",
            "level_with_modifier": "1",
            "borda_percent": 0.0,
            "rank_sd": 0.0,
            "rubric_sd_points": 2.14,
            "flags": "",
            "_level_order": 50.0,
            "_composite_bucket": 0.0,
            "_borda_bucket": 0.0,
            "conventions_mistake_rate_percent": 4.0,
        },
    ]

    updated, report = apply_boundary_calibration(rows, config, scope)
    third_rank = next(item for item in updated if item["student_id"] == "s3")
    assert third_rank["adjusted_level"] == "2"
    assert third_rank["rubric_after_penalty_percent"] == 60.0
    assert "source_scale_floor:eqao_anchor_4pt" in third_rank["boundary_calibration_reason"]
    assert report["scope"]["source_scale_profile"] == "eqao_anchor_4pt"


def test_boundary_calibrator_applies_source_scale_ceiling_for_low_anchor_ranks(tmp_path):
    scope = write_scope(
        tmp_path,
        {
            "grade_level": 12,
            "assignment_genre": "persuasive_response",
            "source_family": "NAEP / NCES",
            "rubric_family": "NAEP 1998 focused holistic writing scoring",
            "prompt_shared": True,
            "sample_count": 6,
            "scoring_scale": {
                "type": "ordinal",
                "labels": ["Unsatisfactory", "Insufficient", "Uneven", "Sufficient", "Skillful", "Excellent"],
            },
        },
    )
    config = make_config()
    config["boundary_calibration"]["source_scale_profiles"] = {
        "naep_release_6pt": {
            "match_source_family_contains": ["naep"],
            "scoring_scale_type": "ordinal",
            "scoring_scale_size": 6,
            "require_prompt_shared": True,
            "require_sample_count": 6,
            "require_student_count_match_scale": True,
            "rank_strategy": "borda_percent",
            "rank_floor_percent_by_rank": [85.0, 80.0, 70.0, 60.0, 55.0, 50.0],
            "rank_ceiling_percent_by_rank": [89.0, 84.0, 79.0, 69.0, 59.0, 54.0],
            "min_current_score_by_rank": [66.0, 68.0, 54.0, 50.0, 50.0, 50.0],
            "min_base_score_by_rank": [69.0, 72.0, 60.0, 54.0, 50.0, 50.0],
            "min_borda_percent_by_rank": [0.75, 0.55, 0.35, 0.15, 0.0, 0.0],
            "max_rank_sd": 1.75,
            "max_rubric_sd_points": 9.0,
            "max_adjustment_percent": 18.0,
        }
    }
    rows = [
        {
            "student_id": "s1",
            "rubric_mean_percent": 85.0,
            "rubric_after_penalty_percent": 85.0,
            "adjusted_level": "4",
            "adjusted_letter": "A",
            "base_level": "4",
            "base_letter": "A",
            "level_modifier": "",
            "level_with_modifier": "4",
            "borda_percent": 1.0,
            "rank_sd": 0.0,
            "rubric_sd_points": 3.0,
            "flags": "",
            "_level_order": 80.0,
            "_composite_bucket": 1.0,
            "_borda_bucket": 100.0,
            "conventions_mistake_rate_percent": 1.0,
        },
        {
            "student_id": "s2",
            "rubric_mean_percent": 80.0,
            "rubric_after_penalty_percent": 80.0,
            "adjusted_level": "4",
            "adjusted_letter": "A",
            "base_level": "4",
            "base_letter": "A",
            "level_modifier": "",
            "level_with_modifier": "4",
            "borda_percent": 0.8,
            "rank_sd": 0.0,
            "rubric_sd_points": 3.5,
            "flags": "",
            "_level_order": 80.0,
            "_composite_bucket": 0.8,
            "_borda_bucket": 80.0,
            "conventions_mistake_rate_percent": 1.0,
        },
        {
            "student_id": "s3",
            "rubric_mean_percent": 70.0,
            "rubric_after_penalty_percent": 70.0,
            "adjusted_level": "3",
            "adjusted_letter": "B",
            "base_level": "3",
            "base_letter": "B",
            "level_modifier": "",
            "level_with_modifier": "3",
            "borda_percent": 0.6,
            "rank_sd": 0.0,
            "rubric_sd_points": 3.0,
            "flags": "",
            "_level_order": 70.0,
            "_composite_bucket": 0.6,
            "_borda_bucket": 60.0,
            "conventions_mistake_rate_percent": 1.0,
        },
        {
            "student_id": "s4",
            "rubric_mean_percent": 65.0,
            "rubric_after_penalty_percent": 65.0,
            "adjusted_level": "2",
            "adjusted_letter": "C",
            "base_level": "2",
            "base_letter": "C",
            "level_modifier": "",
            "level_with_modifier": "2",
            "borda_percent": 0.4,
            "rank_sd": 0.0,
            "rubric_sd_points": 3.0,
            "flags": "",
            "_level_order": 60.0,
            "_composite_bucket": 0.4,
            "_borda_bucket": 40.0,
            "conventions_mistake_rate_percent": 1.0,
        },
        {
            "student_id": "s5",
            "rubric_mean_percent": 61.58,
            "rubric_after_penalty_percent": 61.58,
            "adjusted_level": "2",
            "adjusted_letter": "C",
            "base_level": "2",
            "base_letter": "C",
            "level_modifier": "",
            "level_with_modifier": "2",
            "borda_percent": 0.2,
            "rank_sd": 0.0,
            "rubric_sd_points": 1.98,
            "flags": "",
            "_level_order": 60.0,
            "_composite_bucket": 0.2,
            "_borda_bucket": 20.0,
            "conventions_mistake_rate_percent": 1.98,
        },
        {
            "student_id": "s6",
            "rubric_mean_percent": 54.83,
            "rubric_after_penalty_percent": 54.83,
            "adjusted_level": "1",
            "adjusted_letter": "D",
            "base_level": "1",
            "base_letter": "D",
            "level_modifier": "",
            "level_with_modifier": "1",
            "borda_percent": 0.0,
            "rank_sd": 0.0,
            "rubric_sd_points": 0.39,
            "flags": "",
            "_level_order": 50.0,
            "_composite_bucket": 0.0,
            "_borda_bucket": 0.0,
            "conventions_mistake_rate_percent": 0.0,
        },
    ]

    updated, _ = apply_boundary_calibration(rows, config, scope)
    fifth_rank = next(item for item in updated if item["student_id"] == "s5")
    sixth_rank = next(item for item in updated if item["student_id"] == "s6")
    assert fifth_rank["adjusted_level"] == "1"
    assert fifth_rank["rubric_after_penalty_percent"] == 59.0
    assert "source_scale_ceiling:naep_release_6pt" in fifth_rank["boundary_calibration_reason"]
    assert sixth_rank["adjusted_level"] == "1"
    assert sixth_rank["rubric_after_penalty_percent"] == 54.0
    assert "source_scale_ceiling:naep_release_6pt" in sixth_rank["boundary_calibration_reason"]


def test_boundary_calibrator_imports_as_standalone_module(tmp_path):
    repo_scripts = Path(__file__).resolve().parents[1] / "scripts"
    for filename in (
        "boundary_calibrator.py",
        "aggregate_helpers.py",
        "assessor_context.py",
        "assessor_utils.py",
        "document_extract.py",
        "extract_text.py",
    ):
        shutil.copy(repo_scripts / filename, tmp_path / filename)
    result = subprocess.run(
        [sys.executable, "-c", "import boundary_calibrator; print('ok')"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
