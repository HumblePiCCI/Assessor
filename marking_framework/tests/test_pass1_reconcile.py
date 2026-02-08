from scripts.pass1_reconcile import guard_parameters, reconcile_pass1_item, strip_internal_fields


def test_reconcile_prefers_evidence_when_required_ids_do_not_match():
    item = {
        "student_id": "s1",
        "rubric_total_points": 12,
        "criteria_points": {"CLAIMSUPPORT": 10, "CONVENTIONS": 16},
        "criteria_evidence": [
            {"criterion_id": "claim", "score": 75},
            {"criterion_id": "organization", "score": 74},
            {"criterion_id": "voice", "score": 76},
            {"criterion_id": "conventions", "score": 75},
        ],
        "notes": "",
    }
    out = reconcile_pass1_item(item, ["K1", "K2", "K3", "K4"])
    assert out["rubric_total_points"] == 75.0
    assert out["_criterion_coverage"] == 1.0
    assert out["_score_coherence"] == 0.0


def test_reconcile_prefers_criteria_points_when_high_coverage():
    item = {
        "student_id": "s2",
        "rubric_total_points": 90,
        "criteria_points": {"K1": 70, "K2": 80},
        "criteria_evidence": [],
        "notes": "",
    }
    out = reconcile_pass1_item(item, ["K1", "K2"])
    assert out["rubric_total_points"] == 75.0
    assert out["_criterion_coverage"] == 1.0


def test_reconcile_handles_missing_scores():
    item = {
        "student_id": "s3",
        "rubric_total_points": "n/a",
        "criteria_points": {},
        "criteria_evidence": [],
        "notes": "",
    }
    out = reconcile_pass1_item(item, [])
    assert out["rubric_total_points"] == 0.0
    assert out["_criterion_coverage"] == 1.0
    assert out["_score_coherence"] == 99.0


def test_guard_parameters_relaxes_for_high_quality():
    item = {"_criterion_coverage": 0.9, "_score_coherence": 2.0}
    delta, gap, blend = guard_parameters(item, 5.0, 1, 0.35)
    assert delta == 100.0
    assert gap == 4
    assert blend == 0.0


def test_guard_parameters_partial_quality():
    item = {"_criterion_coverage": 0.6, "_score_coherence": 10.0}
    delta, gap, blend = guard_parameters(item, 5.0, 1, 0.35)
    assert delta == 35.0
    assert gap == 3
    assert blend == 0.1


def test_guard_parameters_defaults_for_low_quality():
    item = {"_criterion_coverage": 0.1, "_score_coherence": 50.0}
    delta, gap, blend = guard_parameters(item, 5.0, 1, 0.35)
    assert delta == 5.0
    assert gap == 1
    assert blend == 0.35


def test_strip_internal_fields():
    item = {"student_id": "s4", "_criterion_coverage": 1.0, "_score_coherence": 0.0, "notes": "ok"}
    out = strip_internal_fields(item)
    assert out == {"student_id": "s4", "notes": "ok"}
