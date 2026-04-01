import json
from pathlib import Path

from scripts.portfolio_aggregation import apply_portfolio_mode, parse_portfolio_note_signal


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
