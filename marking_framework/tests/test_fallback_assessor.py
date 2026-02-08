import scripts.fallback_assessor as fa


def test_deterministic_score_profile_and_bounds():
    text = "Dear Principal. First, we should recycle. Second, we should compost. Sincerely, Student."
    a = fa.deterministic_score(text, "A")
    b = fa.deterministic_score(text, "B")
    c = fa.deterministic_score(text, "C")
    assert 0 <= a <= 100
    assert 0 <= b <= 100
    assert 0 <= c <= 100
    assert len({a, b, c}) >= 2


def test_deterministic_pass1_item_with_criteria():
    text = "Dear Principal. First, we should recycle. Sincerely, Student."
    item = fa.deterministic_pass1_item("s1", text, "A", ["K1", "K2", "T1"])
    assert item["student_id"] == "s1"
    assert isinstance(item["rubric_total_points"], float)
    assert set(item["criteria_points"].keys()) == {"K1", "K2", "T1"}
    assert item["notes"]


def test_deterministic_pass1_item_without_criteria_and_level_mapping():
    item = fa.deterministic_pass1_item("s1", "", "Z", None)
    assert item["criteria_points"] == {}
    assert fa.deterministic_level(95) == "4+"
    assert fa.deterministic_level(85) == "4"
    assert fa.deterministic_level(75) == "3"
    assert fa.deterministic_level(65) == "2"
    assert fa.deterministic_level(55) == "1"


def test_level_rank_mapping():
    assert fa._level_rank(None) is None
    assert fa._level_rank(54.0) == 0
    assert fa._level_rank(64.0) == 1
    assert fa._level_rank(75.0) == 2
    assert fa._level_rank(84.0) == 3
    assert fa._level_rank(95.0) == 4


def test_exemplar_target_branches_and_token_set():
    assert fa._token_set("a bb ccc") == set()
    target, overlap = fa._exemplar_target("text", None)
    assert target is None and overlap == 0.0
    target, overlap = fa._exemplar_target("a bb", {"level_1": "sample"})
    assert target is None and overlap == 0.0
    target, overlap = fa._exemplar_target(
        "alpha beta gamma",
        {"level_1": "    ", "level_2": "alpha beta", "level_3": "delta epsilon"},
    )
    assert target == 64.0
    assert overlap > 0
    target2, overlap2 = fa._exemplar_target(
        "alpha beta gamma",
        {"level_2": "alpha beta gamma", "level_4": "alpha"},
    )
    assert target2 == 64.0
    assert overlap2 >= overlap


def test_deterministic_score_with_exemplar_blend_paths():
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu."
    low_text = (
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima "
        "mike november oscar papa quebec romeo sierra tango uniform victor whiskey"
    )
    low = fa.deterministic_score(low_text, "A", {"level_2": "alpha omega"})  # overlap < 0.08
    high = fa.deterministic_score(text, "A", {"level_4": text})  # overlap >= 0.08
    assert low != high

    mid_text = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima."
    slight_ref = "alpha bravo mike november oscar papa quebec romeo sierra tango uniform."
    slight = fa.deterministic_score(mid_text, "A", {"level_1": slight_ref})  # overlap ~0.1
    mid_ref = "alpha bravo charlie delta mike november oscar papa quebec romeo sierra tango."
    med = fa.deterministic_score(mid_text, "A", {"level_2": mid_ref})  # overlap ~0.25
    high_ref = "alpha bravo charlie delta echo foxtrot golf yankee zulu victor uniform xray."
    higher = fa.deterministic_score(mid_text, "A", {"level_3": high_ref})  # overlap ~0.43
    assert len({slight, med, higher}) >= 2


def test_exemplar_target_skips_empty_reference_token_sets():
    target, overlap = fa._exemplar_target("alpha beta", {"level_1": "to be or", "level_2": "alpha beta"})
    assert target == 64.0
    assert overlap > 0.0


def test_structure_target_and_boundary_adjust_branches():
    empty_target, empty_conf = fa._structure_target("alpha beta gamma", None)
    assert empty_target is None and empty_conf == 0.0

    invalid_target, invalid_conf = fa._structure_target(
        "alpha beta gamma",
        {"unknown": "alpha beta", "level_2": "   "},
    )
    assert invalid_target is None and invalid_conf == 0.0

    target, conf = fa._structure_target(
        "alpha beta gamma delta",
        {"level_2": "alpha beta gamma delta", "level_4": "alpha"},
    )
    assert target == fa.level_to_percent("2")
    assert 0.0 <= conf <= 1.0

    down = fa._boundary_adjust(60.4, 59.0)
    up = fa._boundary_adjust(59.8, 61.0)
    no_hint = fa._boundary_adjust(72.5, None)
    assert down < 60.0
    assert up > 60.0
    assert no_hint == 72.5


def test_boundary_adjust_near_miss_uplift_requires_confidence():
    uplifted = fa._boundary_adjust(57.2, 58.9, 0.7)
    not_uplifted = fa._boundary_adjust(57.2, 58.9, 0.3)
    wrong_hint = fa._boundary_adjust(57.2, 55.0, 0.9)
    assert uplifted > 60.0
    assert not_uplifted < 60.0
    assert wrong_hint < 60.0


def test_weighted_structure_target_branches():
    target, conf = fa._weighted_structure_target("alpha beta gamma", None)
    assert target is None and conf == 0.0

    target, conf = fa._weighted_structure_target(
        "alpha beta gamma",
        {"level_1": " ", "level_2": "   "},
    )
    assert target is None and conf == 0.0

    target, conf = fa._weighted_structure_target(
        "alpha beta gamma",
        {"level_1": "   ", "level_2": "alpha beta gamma", "level_4": "delta epsilon zeta"},
    )
    assert target is not None
    assert 0.0 <= conf <= 1.0

    # Nearby-level filtering should ignore non-adjacent top candidates.
    target, conf = fa._weighted_structure_target(
        "alpha bravo charlie delta",
        {
            "level_4_plus": "alpha bravo charlie delta",
            "level_4": "alpha bravo charlie",
            "level_2": "alpha bravo",
        },
    )
    assert target is not None
    assert target > fa.level_to_percent("4")
    assert 0.0 <= conf <= 1.0


def test_normalize_criteria_to_overall_converges():
    assert fa._normalize_criteria_to_overall({}, 68.0) == {}
    normalized = fa._normalize_criteria_to_overall({"K1": 55.0, "K2": 70.0, "C2": 45.0}, 68.0)
    mean_value = sum(normalized.values()) / len(normalized)
    assert round(mean_value, 1) == 68.0
    assert all(0.0 <= value <= 100.0 for value in normalized.values())
    pinned = fa._normalize_criteria_to_overall({"K1": 100.0}, 150.0)
    assert pinned["K1"] == 100.0


def test_criterion_score_branch_matrix():
    overall, content, org, style, conv = 70.0, 80.0, 60.0, 50.0, 40.0
    assert fa._criterion_score("C1", overall, content, org, style, conv) == 68.0
    assert fa._criterion_score("C2", overall, content, org, style, conv) == 59.5
    assert fa._criterion_score("C3", overall, content, org, style, conv) == 66.0
    assert fa._criterion_score("A1", overall, content, org, style, conv) == 72.0
    assert fa._criterion_score("LA1", overall, content, org, style, conv) == 68.0
    assert fa._criterion_score("LA2", overall, content, org, style, conv) == 72.0
    assert fa._criterion_score("LA3", overall, content, org, style, conv) == 66.0
    assert fa._criterion_score("IR1", overall, content, org, style, conv) == 64.0
    assert fa._criterion_score("IR2", overall, content, org, style, conv) == 68.0
    assert fa._criterion_score("UNKNOWN", overall, content, org, style, conv) == 70.0


def test_deterministic_score_lexical_compatibility_and_blend_band():
    text = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima."
    mid_overlap_ref = (
        "alpha bravo mike november oscar papa quebec romeo sierra tango "
        "uniform victor whiskey xray yankee zulu"
    )  # overlap ratio in [0.08, 0.14)
    same_level = fa.deterministic_score(text, "A", {"level_3": mid_overlap_ref})
    assert 0.0 <= same_level <= 100.0

    # Incompatible lexical target (far from structure target) should be ignored.
    compatible = fa.deterministic_score(
        text,
        "A",
        {
            "level_4_plus": text,
            "level_4": "alpha bravo charlie delta",
            "level_2": "alpha bravo charlie",  # high overlap but non-adjacent to top anchor
        },
    )
    incompatible_only = fa.deterministic_score(
        text,
        "A",
        {
            "level_2": text,
            "level_1": "alpha bravo charlie",
        },
    )
    assert compatible > incompatible_only


def test_weighted_structure_target_handles_none_rank(monkeypatch):
    original = fa._level_rank

    def fake_level_rank(percent):
        if percent == fa.level_to_percent("4+"):
            return None
        return original(percent)

    monkeypatch.setattr(fa, "_level_rank", fake_level_rank)
    target, conf = fa._weighted_structure_target(
        "alpha bravo charlie delta",
        {
            "level_4_plus": "alpha bravo charlie delta",
            "level_4": "alpha bravo charlie",
            "level_3": "alpha bravo",
        },
    )
    assert target is not None
    assert 0.0 <= conf <= 1.0


def test_weighted_structure_target_keeps_full_top_when_nearby_empty(monkeypatch):
    calls = {"count": 0}
    original = fa._level_rank

    def fake_level_rank(percent):
        calls["count"] += 1
        if calls["count"] == 1:
            return original(percent)
        return 99

    monkeypatch.setattr(fa, "_level_rank", fake_level_rank)
    target, conf = fa._weighted_structure_target(
        "alpha bravo charlie delta",
        {
            "level_4_plus": "alpha bravo charlie delta",
            "level_4": "alpha bravo charlie",
            "level_3": "alpha bravo",
        },
    )
    assert target is not None
    assert 0.0 <= conf <= 1.0


def test_weighted_structure_target_fills_none_item_rank_with_best(monkeypatch):
    calls = {"count": 0}

    def fake_level_rank(_percent):
        calls["count"] += 1
        if calls["count"] == 1:
            return 2
        return None

    monkeypatch.setattr(fa, "_level_rank", fake_level_rank)
    target, conf = fa._weighted_structure_target(
        "alpha bravo charlie delta",
        {
            "level_4_plus": "alpha bravo charlie delta",
            "level_4": "alpha bravo charlie",
            "level_3": "alpha bravo",
        },
    )
    assert target is not None
    assert 0.0 <= conf <= 1.0
