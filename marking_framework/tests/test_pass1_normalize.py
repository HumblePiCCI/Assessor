from scripts.pass1_normalize import (
    canonical_criterion_id,
    canonical_token,
    criterion_lookup,
    rescue_pass1_item,
)


def test_canonical_helpers():
    assert canonical_token(" K1. ") == "K1"
    lookup = criterion_lookup(["K1", "T2"])
    assert lookup["K1"] == "K1"
    assert canonical_criterion_id("k1", lookup) == "K1"
    assert canonical_criterion_id("t2-extra", lookup) == "T2"
    assert canonical_criterion_id("", lookup) == ""
    assert canonical_criterion_id("x9", lookup) == "X9"
    assert criterion_lookup(["", "K1"]) == {"K1": "K1"}


def test_rescue_pass1_item_from_levels_and_total():
    raw = "K1: level 3\nT2 level 2\nrubric_total_points: 82"
    item = rescue_pass1_item(raw, "s1", ["K1", "T2"])
    assert item["student_id"] == "s1"
    assert item["criteria_points"]["K1"] == 75.0
    assert item["criteria_points"]["T2"] == 64.0
    assert item["rubric_total_points"] == 82.0


def test_rescue_pass1_item_from_points_average():
    raw = "K1: 78\nT2: 66"
    item = rescue_pass1_item(raw, "s1", ["K1", "T2"])
    assert item["criteria_points"]["K1"] == 78.0
    assert item["criteria_points"]["T2"] == 66.0
    assert item["rubric_total_points"] == 72.0


def test_rescue_pass1_item_empty_when_no_signal():
    item = rescue_pass1_item("unstructured text", "s1", ["K1"])
    assert item["criteria_points"] == {}
    assert item["rubric_total_points"] is None


def test_rescue_pass1_item_skips_out_of_range_score():
    item = rescue_pass1_item("K1: 999", "s1", ["K1"])
    assert item["criteria_points"] == {}
