import scripts.curve_reflow as cr


def cohort(marks):
    return [
        {"student_id": f"s{i + 1:02d}", "final_grade": mark}
        for i, mark in enumerate(marks)
    ]


def marks_of(result):
    return [item["mark"] for item in result["marks"]]


def order_of(result):
    return [item["student_id"] for item in result["marks"]]


def test_no_pins_is_identity():
    students = cohort([91, 88, 84, 79, 75, 71, 66, 60])
    result = cr.reflow_marks(students)
    assert marks_of(result) == [91, 88, 84, 79, 75, 71, 66, 60]
    assert order_of(result) == [s["student_id"] for s in students]
    assert not result["reorder_required"]
    assert not result["order_changed"]


def test_single_pin_cascades_between_anchors():
    students = cohort([91, 88, 84, 79, 75, 71, 66, 60])
    result = cr.reflow_marks(students, {"s05": 80.0})
    marks = marks_of(result)
    # Pin honored exactly; extremes hold; everyone between re-flows.
    assert marks[4] == 80
    assert marks[0] == 91
    assert marks[-1] == 60
    # Above the pin marks compress upward but stay between pin and top.
    assert all(80 <= m <= 91 for m in marks[:5])
    # Below the pin marks stretch but stay between bottom and pin.
    assert all(60 <= m <= 80 for m in marks[4:])
    # Order and monotonicity preserved.
    assert marks == sorted(marks, reverse=True)
    assert order_of(result) == [s["student_id"] for s in students]
    assert result["marks"][4]["pinned"] is True


def test_reflow_is_deterministic():
    students = cohort([91, 88, 84, 79, 75, 71, 66, 60])
    a = cr.reflow_marks(students, {"s03": 86.0, "s07": 64.0}, curve_top=95.0)
    b = cr.reflow_marks(students, {"s03": 86.0, "s07": 64.0}, curve_top=95.0)
    assert a == b


def test_unpin_returns_to_machine_curve():
    students = cohort([91, 88, 84, 79, 75, 71, 66, 60])
    pinned = cr.reflow_marks(students, {"s04": 82.0})
    assert marks_of(pinned) != [91, 88, 84, 79, 75, 71, 66, 60]
    unpinned = cr.reflow_marks(students, {})
    assert marks_of(unpinned) == [91, 88, 84, 79, 75, 71, 66, 60]


def test_curve_bounds_rescale_preserving_shape():
    students = cohort([90, 85, 80, 75, 70])
    result = cr.reflow_marks(students, {}, curve_top=96.0, curve_bottom=66.0)
    marks = marks_of(result)
    assert marks[0] == 96
    assert marks[-1] == 66
    # Equal machine spacing stays equal after rescale.
    gaps = [marks[i] - marks[i + 1] for i in range(len(marks) - 1)]
    assert max(gaps) - min(gaps) <= 1


def test_pin_beats_curve_bounds():
    students = cohort([90, 85, 80, 75, 70])
    result = cr.reflow_marks(students, {"s01": 97.0}, curve_top=92.0)
    assert marks_of(result)[0] == 97
    assert result["curve_top"] == 97.0
    assert not result["clamped_pins"]


def test_conflicting_pins_require_reorder_confirmation():
    students = cohort([91, 88, 84, 79, 75, 71, 66, 60])
    # Teacher pins a lower-ranked student above a higher-ranked pin.
    result = cr.reflow_marks(students, {"s03": 80.0, "s06": 85.0})
    assert result["reorder_required"]
    assert not result["order_changed"]
    moves = {m["student_id"]: m for m in result["implied_moves"]}
    assert "s06" in moves
    # Preview clamps the conflicting pin instead of crossing.
    assert result["clamped_pins"][0]["student_id"] == "s06"
    marks = marks_of(result)
    assert marks == sorted(marks, reverse=True)


def test_accepted_reorder_moves_pinned_student():
    students = cohort([91, 88, 84, 79, 75, 71, 66, 60])
    result = cr.reflow_marks(students, {"s03": 80.0, "s06": 85.0}, accept_reorder=True)
    assert result["order_changed"]
    assert not result["reorder_required"]
    order = order_of(result)
    assert order.index("s06") < order.index("s03")
    marks = marks_of(result)
    assert marks == sorted(marks, reverse=True)
    by_sid = {item["student_id"]: item for item in result["marks"]}
    assert by_sid["s06"]["mark"] == 85
    assert by_sid["s03"]["mark"] == 80


def test_anchor_provenance_reported():
    students = cohort([91, 88, 84, 79, 75])
    result = cr.reflow_marks(students, {"s03": 82.0})
    item = result["marks"][1]
    assert item["anchor_above"] == "curve_top"
    assert item["anchor_below"] == "s03"
    below = result["marks"][3]
    assert below["anchor_above"] == "s03"
    assert below["anchor_below"] == "curve_bottom"


def test_band_break_reported_not_enforced():
    students = cohort([91, 75])
    students[1]["adjusted_level"] = "3"
    bands = [{"level": "3", "min": 70, "max": 79}]
    result = cr.reflow_marks(students, {"s02": 85.0}, level_bands=bands)
    item = result["marks"][1]
    assert item["mark"] == 85
    assert item["band_break"] is True


def test_singleton_cohort():
    students = cohort([84])
    assert marks_of(cr.reflow_marks(students)) == [84]
    assert marks_of(cr.reflow_marks(students, {"s01": 90.0})) == [90]


def test_two_students_pin_each():
    students = cohort([88, 70])
    result = cr.reflow_marks(students, {"s01": 90.0, "s02": 65.0})
    assert marks_of(result) == [90, 65]


def test_empty_cohort():
    result = cr.reflow_marks([])
    assert result["marks"] == []
    assert not result["reorder_required"]


def test_missing_machine_grades_fall_back_to_bell():
    students = [{"student_id": f"s{i}"} for i in range(1, 6)]
    result = cr.reflow_marks(students, {}, curve_top=92.0, curve_bottom=58.0)
    marks = marks_of(result)
    assert marks[0] == 92
    assert marks[-1] == 58
    assert marks == sorted(marks, reverse=True)


def test_equal_pins_allow_ties():
    students = cohort([91, 88, 84, 79])
    result = cr.reflow_marks(students, {"s02": 85.0, "s03": 85.0})
    marks = marks_of(result)
    assert marks[1] == 85 and marks[2] == 85
    assert not result["reorder_required"]
    assert marks == sorted(marks, reverse=True)


def test_plateau_stretches_instead_of_following_pin():
    # Integer rounding plateaus (seven students at 68) must spread smoothly
    # between the pin and the next anchor, not jump as a block to the pin.
    students = cohort([68, 68, 68, 68, 68, 68, 68, 67, 67, 64, 64, 58])
    result = cr.reflow_marks(students, {"s01": 85.0})
    marks = marks_of(result)
    assert marks[0] == 85
    assert marks[-1] == 58
    # The plateau spreads downward instead of moving as a block to 85.
    assert marks[6] <= 85 - 2
    assert marks == sorted(marks, reverse=True)
    assert len(set(marks[:7])) >= 3


def test_unrounded_machine_curve_preferred_for_shape():
    students = cohort([80, 80, 79])
    students[0]["final_grade_raw"] = 80.4
    students[1]["final_grade_raw"] = 79.6
    students[2]["final_grade_raw"] = 78.9
    identity = cr.reflow_marks(students)
    # Identity still returns the machine's rounded marks verbatim.
    assert marks_of(identity) == [80, 80, 79]
    pinned = cr.reflow_marks(students, {"s03": 75.0})
    marks = marks_of(pinned)
    assert marks[2] == 75
    assert marks[0] == 80
    assert 75 < marks[1] <= 80


def test_identity_shortcut_returns_machine_marks_verbatim():
    students = cohort([91, 88, 84])
    result = cr.reflow_marks(students)
    assert marks_of(result) == [91, 88, 84]
    assert all(item["anchor_above"] == "machine" for item in result["marks"])
    assert result["anchors"] == []


def test_normalize_pins_filters_unknown_and_invalid():
    students = cohort([91, 88])
    pins = cr.normalize_pins(
        [
            {"student_id": "s01", "mark": 89.5},
            {"student_id": "ghost", "mark": 70},
            {"student_id": "s02", "mark": "bad"},
            {"student_id": "s02", "mark": 120},
        ],
        students,
    )
    assert pins == {"s01": 89.5, "s02": 100.0}
