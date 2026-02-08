from scripts.pass1_guard import stabilize_pass1_item


def test_stabilize_pass1_item_clamps_large_delta_and_shifts_criteria():
    llm_item = {
        "student_id": "s1",
        "rubric_total_points": 95.0,
        "criteria_points": {"K1": 90.0, "C2": 95.0},
        "notes": "x",
    }
    fallback_item = {"student_id": "s1", "rubric_total_points": 70.0, "criteria_points": {}, "notes": "y"}
    out = stabilize_pass1_item(llm_item, fallback_item, max_score_delta=8.0, max_level_gap=1)
    assert out["rubric_total_points"] == 78.0
    assert out["criteria_points"]["K1"] == 73.0
    assert out["criteria_points"]["C2"] == 78.0


def test_stabilize_pass1_item_clamps_level_gap():
    llm_item = {"student_id": "s1", "rubric_total_points": 92.0, "criteria_points": {}, "notes": "x"}
    fallback_item = {"student_id": "s1", "rubric_total_points": 55.0, "criteria_points": {}, "notes": "y"}
    out = stabilize_pass1_item(llm_item, fallback_item, max_score_delta=100.0, max_level_gap=1)
    assert 60.0 <= out["rubric_total_points"] <= 69.99


def test_stabilize_pass1_item_no_change_when_within_limits():
    llm_item = {"student_id": "s1", "rubric_total_points": 74.0, "criteria_points": {"K1": 74.0}, "notes": "x"}
    fallback_item = {"student_id": "s1", "rubric_total_points": 71.0, "criteria_points": {}, "notes": "y"}
    out = stabilize_pass1_item(llm_item, fallback_item, max_score_delta=8.0, max_level_gap=1)
    assert out["rubric_total_points"] == 74.0
    assert out["criteria_points"]["K1"] == 74.0


def test_stabilize_pass1_item_anchor_blend_biases_toward_anchor():
    llm_item = {"student_id": "s1", "rubric_total_points": 90.0, "criteria_points": {}, "notes": "x"}
    fallback_item = {"student_id": "s1", "rubric_total_points": 70.0, "criteria_points": {}, "notes": "y"}
    out = stabilize_pass1_item(llm_item, fallback_item, max_score_delta=100.0, max_level_gap=4, anchor_blend=0.5)
    assert out["rubric_total_points"] == 80.0
