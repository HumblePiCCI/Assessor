import json
from pathlib import Path

from scripts.portfolio_aggregation import (
    apply_portfolio_mode,
    apply_portfolio_scale_calibration,
    parse_portfolio_note_signal,
)


def make_config() -> dict:
    return {
        "portfolio_mode": {
            "enabled": True,
            "note_clamp_threshold": 4.0,
            "conventions_threshold_bonus_percent": 5.0,
            "max_level_drop_scale": 0.35,
            "weights": {
                "rubric": 0.78,
                "conventions": 0.17,
                "comparative": 0.05,
            },
        }
    }


def test_parse_portfolio_note_signal_explicit_levels():
    assert parse_portfolio_note_signal("Overall working towards expected standard.").get("estimate") == 2.0
    assert parse_portfolio_note_signal("Overall: Working Towards / low-Expected range.").get("estimate") == 2.3
    assert parse_portfolio_note_signal("Overall working at the expected standard.").get("estimate") == 3.0
    assert parse_portfolio_note_signal("Overall working at/near greater depth.").get("estimate") == 3.6


def test_apply_portfolio_mode_clamps_scores_to_note_band():
    pass1 = [
        {
            "assessor_id": "assessor_A",
            "scores": [
                {
                    "student_id": "s001",
                    "rubric_total_points": 39.15,
                    "notes": "Strong KS1 portfolio with clear control across multiple purposes and overall above expected standard.",
                },
                {
                    "student_id": "s002",
                    "rubric_total_points": 79.41,
                    "notes": "Overall working towards/low expected standard across the portfolio.",
                },
            ],
        }
    ]
    scope = {"is_portfolio": True, "grade_level": 2, "genre": "portfolio", "assessment_unit": "portfolio"}
    updated, report = apply_portfolio_mode(pass1, make_config(), scope)
    scores = {row["student_id"]: row for row in updated[0]["scores"]}

    assert scores["s001"]["rubric_total_points"] == 80.0
    assert scores["s001"]["portfolio_note_level"] == "4"
    assert scores["s002"]["rubric_total_points"] == 74.0
    assert scores["s002"]["portfolio_note_level"] == "3"
    assert report["applied"] == 2
    assert report["student_summaries"]["s001"]["note_canonical_level"] == "4"


def test_apply_portfolio_mode_disabled_when_not_portfolio():
    pass1 = [{"assessor_id": "assessor_A", "scores": [{"student_id": "s001", "rubric_total_points": 55, "notes": "Working towards"}]}]
    updated, report = apply_portfolio_mode(pass1, make_config(), {"is_portfolio": False})
    assert updated == pass1
    assert report["enabled"] is False


def test_portfolio_scale_calibration_does_not_promote_bottom_bucket_to_three():
    config = {
        "portfolio_mode": {
            "ordinal_scale_calibration": {
                "enabled": True,
                "top_fraction": 0.25,
                "bottom_fraction": 0.25,
                "early_grade_top_min_percent": 72.0,
                "early_grade_middle_min_percent": 63.25,
                "bottom_max_percent": 70.0,
                "max_rank_sd": 1.5,
                "band_floor_offset_percent": 1.5,
            }
        }
    }
    scope = {"is_small_ordinal_portfolio": True, "grade_level": 2}
    level_bands = [
        {"level": "1", "min": 50, "max": 59, "letter": "D"},
        {"level": "2", "min": 60, "max": 69, "letter": "C"},
        {"level": "3", "min": 70, "max": 79, "letter": "B"},
        {"level": "4", "min": 80, "max": 89, "letter": "A"},
    ]
    rows = [
        {
            "student_id": "s1",
            "adjusted_level": "4",
            "adjusted_letter": "A",
            "rubric_after_penalty_percent": 82.0,
            "rubric_mean_percent": 82.0,
            "rank_sd": 0.1,
            "portfolio_note_votes": 3,
            "_level_order": 80.0,
            "_composite_bucket": 0.9,
            "_borda_bucket": 90.0,
            "conventions_mistake_rate_percent": 4.0,
        },
        {
            "student_id": "s2",
            "adjusted_level": "2",
            "adjusted_letter": "C",
            "rubric_after_penalty_percent": 64.0,
            "rubric_mean_percent": 64.0,
            "rank_sd": 0.1,
            "portfolio_note_votes": 3,
            "_level_order": 60.0,
            "_composite_bucket": 0.5,
            "_borda_bucket": 50.0,
            "conventions_mistake_rate_percent": 8.0,
        },
        {
            "student_id": "s3",
            "adjusted_level": "2",
            "adjusted_letter": "C",
            "rubric_after_penalty_percent": 63.5,
            "rubric_mean_percent": 63.5,
            "rank_sd": 0.1,
            "portfolio_note_votes": 3,
            "_level_order": 60.0,
            "_composite_bucket": 0.1,
            "_borda_bucket": 10.0,
            "conventions_mistake_rate_percent": 14.0,
        },
    ]

    updated, report = apply_portfolio_scale_calibration(rows, config, scope, level_bands)
    rows_by_id = {row["student_id"]: row for row in updated}
    assert rows_by_id["s2"]["adjusted_level"] == "3"
    assert rows_by_id["s2"]["portfolio_scale_adjusted"] == "true"
    assert rows_by_id["s3"]["adjusted_level"] == "2"
    assert rows_by_id["s3"].get("portfolio_scale_adjusted", "false") != "true"
    assert report["applied"] == 1
