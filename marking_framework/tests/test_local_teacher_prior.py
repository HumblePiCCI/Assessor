import scripts.local_teacher_prior as ltp


def _record(saved_at, *, level_delta=None, boundary=False, low_conf_reversal=False, scope=None):
    student = {
        "student_id": "s1",
        "machine_level": "3",
        "level_override": "4" if level_delta else "",
        "level_delta": level_delta,
        "uncertainty_flags": ["boundary_case"] if boundary else [],
        "evidence_quality": "strong",
    }
    pair = {
        "preferred_student_id": "s1",
        "lower_student_id": "s2",
        "reversed_machine_order": low_conf_reversal,
        "uncertainty_flags": ["low_confidence_rerank_move"] if low_conf_reversal else [],
    }
    return {
        "review_state": "final",
        "saved_at": saved_at,
        "students": [student],
        "pairwise": [pair],
        "version_context": {"pipeline_manifest": {"run_scope": scope or {}}},
    }


def test_local_teacher_prior_requires_minimum_support():
    prior = ltp.build_local_teacher_prior(
        "scope-a",
        [_record("2026-03-29T00:00:00+00:00", level_delta=1.0, boundary=True)],
    )
    assert prior["active"] is False
    assert prior["activation"]["reason"] == "insufficient_finalized_reviews"


def test_local_teacher_prior_activates_with_repeated_recent_feedback():
    records = [
        _record(
            "2026-03-29T00:00:00+00:00",
            level_delta=1.0,
            boundary=True,
            low_conf_reversal=True,
            scope={"grade_band": "grade_6_8", "genre": "literary_analysis", "rubric_family": "rubric_a", "model_family": "gpt-5.4"},
        ),
        _record(
            "2026-03-30T00:00:00+00:00",
            level_delta=1.0,
            boundary=True,
            low_conf_reversal=True,
            scope={"grade_band": "grade_6_8", "genre": "literary_analysis", "rubric_family": "rubric_a", "model_family": "gpt-5.4"},
        ),
    ]
    prior = ltp.build_local_teacher_prior("scope-a", records, min_finalized_reviews=2, min_student_decisions=2)
    assert prior["active"] is True
    assert prior["weights"]["boundary_level_bias"] > 0.0
    assert prior["weights"]["seed_order_bias"] > 0.0


def test_teacher_preference_adjustments_respect_scope_and_uncertainty():
    rows = [
        {"student_id": "s1", "seed_rank": 1, "_rubric_after_penalty_percent": 79.9},
        {"student_id": "s2", "seed_rank": 2, "_rubric_after_penalty_percent": 92.0},
    ]
    per_student = {
        "s1": {"support_weight": 0.5, "opposition_weight": 0.45, "incident_weight": 0.9},
        "s2": {"support_weight": 0.0, "opposition_weight": 0.0, "incident_weight": 0.0},
    }
    prior = {
        "active": True,
        "run_scope": {"grade_band": "grade_6_8", "genre": "literary_analysis", "rubric_family": "rubric_a", "model_family": "gpt-5.4"},
        "support": {"support_scalar": 1.0, "freshness_scalar": 1.0},
        "weights": {"boundary_level_bias": 0.08, "seed_order_bias": 0.06, "max_adjustment": 0.08, "boundary_margin": 1.5},
    }
    adjustments, meta = ltp.compute_teacher_preference_adjustments(
        rows,
        per_student,
        prior,
        current_scope={"grade_band": "grade_6_8", "genre": "literary_analysis", "rubric_family": "rubric_a", "model_family": "gpt-5.4"},
        boundaries=[60.0, 70.0, 80.0, 90.0],
    )
    assert meta["active"] is True
    assert adjustments["s1"] > 0.0
    assert adjustments["s2"] == 0.0

    mismatch_adjustments, mismatch_meta = ltp.compute_teacher_preference_adjustments(
        rows,
        per_student,
        prior,
        current_scope={"grade_band": "grade_9_10", "genre": "literary_analysis", "rubric_family": "rubric_a", "model_family": "gpt-5.4"},
        boundaries=[60.0, 70.0, 80.0, 90.0],
    )
    assert mismatch_meta["scope_match"] is False
    assert mismatch_adjustments["s1"] == 0.0
