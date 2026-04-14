import scripts.engagement_gate as eg


def test_engagement_gate_keeps_substantive_final_review():
    record = {
        "review_state": "final",
        "saved_at": "2026-04-14T12:05:00+00:00",
        "review_notes": "Teacher reviewed the cohort carefully.",
        "students": [{"student_id": "s1", "level_override": "4", "desired_rank": 1}],
        "pairwise": [],
        "review_session": {"started_at": "2026-04-14T12:00:00+00:00"},
    }
    signal = eg.evaluate_engagement(record, collection_allowed=True)
    assert signal["eligible"] is True
    assert signal["retention_state"] == "aggregate_candidate"


def test_engagement_gate_discards_non_final_reviews():
    signal = eg.evaluate_engagement({"review_state": "draft", "students": [], "pairwise": []}, collection_allowed=True)
    assert signal["eligible"] is False
    assert signal["retention_state"] == "discarded"
