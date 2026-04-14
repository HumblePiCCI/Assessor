import scripts.apply_anchor_calibration as aac


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
