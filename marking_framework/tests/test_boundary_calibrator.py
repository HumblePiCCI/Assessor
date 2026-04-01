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
