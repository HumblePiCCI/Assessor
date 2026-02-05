import json
import logging
from pathlib import Path

import pytest

from scripts import aggregate_helpers as ah
from tests.conftest import write_json


def test_load_config_and_level_bands(tmp_path):
    logger = logging.getLogger("test")
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({"levels": {"bands": [{"level": "X", "min": 1, "max": 2, "letter": "Z"}]}}))
    cfg = ah.load_config(cfg_path, logger)
    assert cfg["levels"]["bands"][0]["level"] == "X"

    assert ah.get_level_bands(cfg)[0]["level"] == "X"
    assert ah.get_level_bands({})[0]["level"] == "1"
    cfg2 = ah.load_config(cfg_path, None)
    assert cfg2["levels"]["bands"][0]["level"] == "X"


def test_read_pass1_validations(tmp_path):
    logger = logging.getLogger("test")
    pass1_dir = tmp_path / "p1"
    pass1_dir.mkdir()
    # Missing fields
    bad = pass1_dir / "bad.json"
    bad.write_text(json.dumps({"scores": []}))
    with pytest.raises(ValueError):
        ah.read_pass1(pass1_dir, logger)

    bad.write_text("{not-json")
    with pytest.raises(json.JSONDecodeError):
        ah.read_pass1(pass1_dir, logger)

    good = pass1_dir / "good.json"
    good.write_text(json.dumps({"assessor_id": "a", "scores": [{"student_id": " s1 "}, {"student_id": 123}] }))
    data = ah.read_pass1(pass1_dir, logger)
    assert data[0]["assessor_id"] == "a"
    assert data[0]["scores"][0]["student_id"] == "s1"
    assert data[0]["scores"][1]["student_id"] == 123

    bad_scores = pass1_dir / "bad_scores.json"
    bad_scores.write_text(json.dumps({"assessor_id": "b"}))
    data2 = ah.read_pass1(pass1_dir, logger)
    assert any(item["assessor_id"] == "a" for item in data2)


def test_read_pass2_and_conventions(tmp_path):
    logger = logging.getLogger("test")
    pass2_dir = tmp_path / "p2"
    pass2_dir.mkdir()
    (pass2_dir / "subdir").mkdir()
    file = pass2_dir / "rank.txt"
    file.write_text("# comment\n\ns1 \ns2\n")
    empty_file = pass2_dir / "empty.txt"
    empty_file.write_text("# only comments\n\n", encoding="utf-8")
    rankings = ah.read_pass2(pass2_dir, logger)
    assert rankings[0]["ranking"] == ["s1", "s2"]

    missing = ah.read_conventions_report(tmp_path / "missing.csv", logger)
    assert missing == {}

    csv_path = tmp_path / "c.csv"
    csv_path.write_text("student_id,mistake_rate_percent\n s1 ,1.0\n")
    data = ah.read_conventions_report(csv_path, logger)
    assert data["s1"]["mistake_rate_percent"] == "1.0"


def test_stats_and_levels():
    assert ah.mean([]) == 0.0
    assert ah.stdev([]) == 0.0
    assert ah.stdev([1, 1]) == 0.0

    bands = ah.get_level_bands({})
    assert ah.get_level_band(None, bands) is None
    assert ah.get_level_band(55, bands)["level"] == "1"
    assert ah.get_level_band(10, bands)["level"] == "1"
    assert ah.get_level_band(95, bands)["level"] == "4+"
    assert ah.get_level_band(150, bands)["level"] == "4+"
    assert ah.level_modifier_from_mistake_rate(3.0, [{"max_mistake_rate_percent": 2, "modifier": "+"}, {"max_mistake_rate_percent": 5, "modifier": "-"}]) == "-"
    assert ah.level_modifier_from_mistake_rate(10.0, [{"max_mistake_rate_percent": 2, "modifier": "+"}]) == ""
    assert ah.apply_level_drop_penalty(80, bands, 1) == 70
    assert ah.apply_level_drop_penalty(None, bands, 1) is None


def test_calculate_irr_metrics():
    rubric = {"s1": [10, 10], "s2": [5, 6]}
    rankings = {"s1": [1, 2], "s2": [2, 1]}
    irr = ah.calculate_irr_metrics(rubric, rankings, 2, 2)
    assert "rubric_icc" in irr
    assert "rank_kendall_w" in irr

    irr2 = ah.calculate_irr_metrics({}, {}, 0, 0)
    assert irr2["rubric_icc"] == 0.0
    assert irr2["rank_kendall_w"] == 0.0


def test_write_json_helper(tmp_path):
    path = write_json(tmp_path / "file.json", {"a": 1})
    assert path.exists()
