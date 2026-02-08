import scripts.levels as lv


def test_normalize_level_none_and_invalid():
    assert lv.normalize_level(None) is None
    assert lv.normalize_level({}) is None
    assert lv.normalize_level("") is None
    assert lv.normalize_level("nope") is None


def test_normalize_level_numeric_level_scale():
    assert lv.normalize_level(4.5) == "4+"
    assert lv.normalize_level(4.0) == "4"
    assert lv.normalize_level(3.1) == "3"
    assert lv.normalize_level(2.2) == "2"
    assert lv.normalize_level(1.0) == "1"
    assert lv.normalize_level(0.0) is None


def test_normalize_level_numeric_percent_scale():
    assert lv.normalize_level(95.0) == "4+"
    assert lv.normalize_level(84.0) == "4"
    assert lv.normalize_level(75.0) == "3"
    assert lv.normalize_level(64.0) == "2"
    assert lv.normalize_level(54.0) == "1"
    assert lv.normalize_level(10.0) is None
    assert lv.normalize_level(101.0) is None


def test_normalize_level_string_variants():
    assert lv.normalize_level("Level 3") == "3"
    assert lv.normalize_level("4+") == "4+"
    assert lv.normalize_level("4 plus") == "4+"
    assert lv.normalize_level(" 2 ") == "2"


def test_level_to_percent_and_score_to_percent():
    assert lv.level_to_percent("3") == 75.0
    assert lv.level_to_percent("nope") is None
    assert lv.score_to_percent("x") is None
    assert lv.score_to_percent(3) == 75.0
    assert lv.score_to_percent(64) == 64.0
    assert lv.score_to_percent("4+") == 95.0
    assert lv.score_to_percent("75%") == 75.0
    assert lv.score_to_percent(" Level 2 ") == 64.0
    assert lv.score_to_percent("   ") is None
    assert lv.score_to_percent("-.") is None
    assert lv.score_to_percent(-1) is None
    assert lv.score_to_percent(999) is None


def test_coerce_level_and_score_to_percent_prefers_level():
    level, pct = lv.coerce_level_and_score_to_percent("Level 4", 65)
    assert level == "4"
    assert pct == 84.0


def test_coerce_level_and_score_to_percent_infers_from_score():
    level, pct = lv.coerce_level_and_score_to_percent("", 2)
    assert level == "2"
    assert pct == 64.0


def test_coerce_level_and_score_to_percent_no_values():
    assert lv.coerce_level_and_score_to_percent("", "x") == (None, None)
