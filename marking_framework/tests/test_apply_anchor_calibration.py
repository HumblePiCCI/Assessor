import scripts.apply_anchor_calibration as aac
import pytest


def test_build_anchor_patch_uses_teacher_marks_and_levels():
    rows = [
        {"student_id": "s1", "rubric_after_penalty_percent": "78"},
        {"student_id": "s2", "rubric_after_penalty_percent": "63"},
    ]
    teacher_scores = {
        "anchors": [
            {"student_id": "s1", "teacher_level": "4", "teacher_mark": 84},
            {"student_id": "s2", "teacher_level": "2"},
        ]
    }
    config = {
        "levels": {
            "bands": [
                {"level": "1", "min": 50, "max": 59},
                {"level": "2", "min": 60, "max": 69},
                {"level": "3", "min": 70, "max": 79},
                {"level": "4", "min": 80, "max": 100},
            ]
        }
    }

    patch = aac.build_anchor_patch(rows=rows, teacher_scores=teacher_scores, config=config)

    assert patch["active"] is True
    assert patch["fit_method"] == "piecewise_score_interpolation"
    assert len(patch["interpolation_points"]) == 2
    assert patch["anchors"][0]["target_score"] == 84.0


def test_normalize_teacher_scores_rejects_invalid_mark():
    with pytest.raises(ValueError, match="between 0 and 100"):
        aac.normalize_teacher_scores(
            {"anchors": [{"student_id": "s1", "teacher_level": "4", "teacher_mark": 101}]},
            {"levels": {"bands": [{"level": "1", "min": 50, "max": 59}, {"level": "4", "min": 80, "max": 100}]}},
        )


def test_normalize_teacher_scores_canonicalizes_level_aliases():
    normalized = aac.normalize_teacher_scores(
        {"anchors": [{"student_id": "s1", "teacher_level": "4 plus"}]},
        {"levels": {"bands": [{"level": "1", "min": 50, "max": 59}, {"level": "4+", "min": 90, "max": 100}]}},
    )
    assert normalized["anchors"][0]["teacher_level"] == "4+"


def test_patch_is_rank_evidence_mode_with_pairwise_judgments():
    # Validated 2026-06-11 on blind-marked holdouts: score interpolation on
    # seeds harms mis-ordered cohorts; teacher anchor order as adjudicated
    # rank evidence strictly improves agreement.
    rows = [
        {"student_id": "s1", "rubric_after_penalty_percent": "80"},
        {"student_id": "s2", "rubric_after_penalty_percent": "70"},
        {"student_id": "s3", "rubric_after_penalty_percent": "60"},
    ]
    teacher = {"anchors": [
        {"student_id": "s1", "teacher_mark": 65},
        {"student_id": "s2", "teacher_mark": 85},
        {"student_id": "s3", "teacher_mark": 65},
    ]}
    patch = aac.build_anchor_patch(rows=rows, teacher_scores=teacher, config={})
    assert patch["seed_patch_enabled"] is False
    assert patch["apply_mode"] == "rank_evidence_plus_curve_pins"
    pairs = patch["anchor_pairwise_judgments"]
    # s2 (85) above s1 (65) and s3 (65); s1 vs s3 tie -> no judgment.
    keyed = {tuple(p["pair"]) for p in pairs}
    assert ("s2", "s1") in keyed and ("s2", "s3") in keyed
    assert len(pairs) == 2
    assert all(p["model_metadata"]["adjudication_source"] == "committee_edge" for p in pairs)
