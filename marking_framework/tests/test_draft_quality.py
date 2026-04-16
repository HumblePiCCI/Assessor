import scripts.draft_quality as dq


def test_analyze_draft_quality_detects_scaffold_placeholders():
    text = """
    Ghost- Final Essay

    Consequences Of Our Choices

    Coach chose to give Ghost many second chances but made him work for it, which was a consequence for Ghost.
    Explanation 1: Though Coach forgives him he makes him
    Cite/Detail 2:
    Explanation 2:
    Sum-Up the Argument: Many of our choices come with consequences.
    Reflect on the Theme:
    """
    signals = dq.analyze_draft_quality(text, "Basic argument with incomplete structure and limited evidence.")
    assert signals["penalty_points"] >= 34.0
    assert signals["severity"] == "high"
    assert signals["placeholder_line_count"] >= 5
    assert signals["blank_placeholder_count"] >= 2
    assert signals["unfinished_placeholder_clause_count"] >= 1
    assert signals["hard_floor_incomplete"] is True
    assert any("scaffold" in reason for reason in signals["reasons"])


def test_apply_draft_penalty_reduces_score_and_marks_warning():
    item = {
        "student_id": "s1",
        "rubric_total_points": 76.0,
        "criteria_points": {"LA1": 80.0, "LA2": 78.0, "LA3": 74.0},
        "notes": "Incomplete structure with placeholder text.",
    }
    text = "Explanation 1: unfinished\nCite/Detail 2:\nReflect on the Theme:\n"
    updated, signals = dq.apply_draft_penalty(item, text, item["notes"])
    assert signals["penalty_points"] > 0
    assert updated["rubric_total_points"] < 76.0
    assert updated["criteria_points"]["LA1"] < 80.0
    assert "incomplete_scaffold_draft" in updated["warnings"]
    assert "Deterministic draft-completion penalty applied" in updated["notes"]
    assert updated["draft_completion_floor_applied"] is True
