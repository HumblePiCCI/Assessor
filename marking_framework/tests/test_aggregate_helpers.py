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
    dup = pass2_dir / "dup.txt"
    dup.write_text("s1\ns1\ns2\n", encoding="utf-8")
    rankings = ah.read_pass2(pass2_dir, logger)
    assert any(r["ranking"] == ["s1", "s2"] for r in rankings)

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
    assert ah.get_level_band(59.19, bands)["level"] == "1"
    assert ah.get_level_band(69.9, bands)["level"] == "2"
    assert ah.get_level_band(10, bands)["level"] == "1"
    assert ah.get_level_band(95, bands)["level"] == "4+"
    assert ah.get_level_band(150, bands)["level"] == "4+"
    assert ah.level_modifier_from_mistake_rate(3.0, [{"max_mistake_rate_percent": 2, "modifier": "+"}, {"max_mistake_rate_percent": 5, "modifier": "-"}]) == "-"
    assert ah.level_modifier_from_mistake_rate(10.0, [{"max_mistake_rate_percent": 2, "modifier": "+"}]) == ""
    assert ah.apply_level_drop_penalty(80, bands, 1) == 70
    assert ah.apply_level_drop_penalty(None, bands, 1) is None
    assert ah.consensus_central([], "median") == 0.0
    assert ah.consensus_central([1, 9, 3], "median") == 3.0
    assert ah.consensus_central([1, 9], "median") == 5.0
    assert ah.consensus_central([1, 2, 3], "mean") == 2.0
    assert ah.weighted_central([1, 3], [0, 1], "median") == 3.0
    assert ah.weighted_central([1, 3], [0.4, 0.6], "median") == 3.0
    assert ah.weighted_central([1, 3], [1, 3], "mean") == 2.5
    assert ah.weighted_central([1, 3], [], "mean") == 2.0
    assert ah.weighted_central([1, 3], [0, 0], "median") == 2.0
    assert ah.weighted_central([1, 3], [0, 0], "mean") == 2.0
    assert ah.apply_bias_correction(80, {"slope": 1.1, "intercept": -5}, 100) == 83.0
    assert ah.apply_bias_correction(80, {"bias": 10}, 100) == 70.0
    assert ah.apply_bias_correction(80, 10, 100) == 70.0
    weak = {"bias": 10, "level_hit_rate": 0.2, "pairwise_order_agreement": 0.4, "mae": 12.0}
    assert ah.apply_bias_correction(80, weak, 100) == 80.0
    strong = {"bias": 10, "level_hit_rate": 0.9, "pairwise_order_agreement": 0.9, "mae": 2.0}
    assert ah.apply_bias_correction(80, strong, 100) == 70.0
    mapped = ah.apply_bias_correction(65, {"map_points": [{"x": 60, "y": 62}, {"x": 70, "y": 74}]}, 100)
    assert round(mapped, 2) == 68.0

    scoped = {
        "assessor_a": {
            "global": {"bias": 2},
            "scopes": {"grade_6_7|literary_analysis": {"bias": 5}},
        }
    }
    assert ah.resolve_bias_entry(scoped, "assessor_a", "grade_6_7|literary_analysis")["bias"] == 5
    assert ah.resolve_bias_entry(scoped, "assessor_a", "grade_8_10|news_report")["bias"] == 2
    assert ah.resolve_bias_entry({"assessor_a": 3}, "assessor_a", None) == 3
    assert ah.resolve_bias_entry({"assessor_a": {"custom": 1}}, "assessor_a", None) == {"custom": 1}
    no_global = {"assessor_a": {"scopes": {"grade_6_7|literary_analysis": {"bias": 7}}}}
    assert ah.resolve_bias_entry(no_global, "assessor_a", "grade_6_7|literary_analysis")["bias"] == 7

    blended = {
        "assessor_a": {
            "global": {"bias": 2, "weight": 0.8, "samples": 60},
            "scopes": {
                "grade_6_7|literary_analysis": {
                    "bias": 6,
                    "weight": 0.9,
                    "samples": 20,
                    "scope_prior": 8,
                    "map_points": [{"x": 60, "y": 66}],
                }
            },
        }
    }
    entry = ah.resolve_bias_entry(blended, "assessor_a", "grade_6_7|literary_analysis")
    assert 2.0 < entry["bias"] < 6.0
    assert "blend_alpha" in entry
    assert entry["map_points"] == [{"x": 60, "y": 66}]

    blended_with_global_points = {
        "assessor_a": {
            "global": {"weight": 1.0, "map_points": [{"x": 50, "y": 52}]},
            "scopes": {"grade_6_7|literary_analysis": {"mae": 1.5, "samples": 1, "scope_prior": 50, "map_points": [{"x": 60, "y": 66}]}}
        }
    }
    entry2 = ah.resolve_bias_entry(blended_with_global_points, "assessor_a", "grade_6_7|literary_analysis")
    assert entry2["mae"] == 1.5
    assert entry2["map_points"] == [{"x": 50, "y": 52}]

    unsorted_cfg = {"levels": {"bands": [
        {"level": "4+", "min": 90, "max": 100, "letter": "A+"},
        {"level": "1", "min": 50, "max": 59, "letter": "D"},
        {"level": "2", "min": 60, "max": 69, "letter": "C"},
    ]}}
    unsorted_bands = ah.get_level_bands(unsorted_cfg)
    assert [b["level"] for b in unsorted_bands] == ["1", "2", "4+"]


def test_calculate_irr_metrics():
    rubric = {"s1": [10, 10], "s2": [5, 6]}
    rankings = {"s1": [1, 2], "s2": [2, 1]}
    irr = ah.calculate_irr_metrics(rubric, rankings, 2, 2)
    assert "rubric_icc" in irr
    assert "rank_kendall_w" in irr

    irr2 = ah.calculate_irr_metrics({}, {}, 0, 0)
    assert irr2["rubric_icc"] == 0.0
    assert irr2["rank_kendall_w"] == 0.0


def test_piecewise_bias_edge_cases():
    assert ah._piecewise_interpolate(33, []) == 33.0
    points = [{"x": 60, "y": 62}, {"x": 60, "y": 63}, {"x": 80, "y": 90}]
    # Below and above range clamp to edge points.
    assert ah.apply_bias_correction(40, {"map_points": points}, 100) == 63.0
    assert ah.apply_bias_correction(90, {"map_points": points}, 100) == 90.0
    # Duplicate x value keeps the latest anchor.
    assert ah.apply_bias_correction(60, {"map_points": points}, 100) == 63.0
    # Malformed points list falls back to identity.
    assert ah.apply_bias_correction(70, {"map_points": ["bad"]}, 100) == 70.0


def test_write_json_helper(tmp_path):
    path = write_json(tmp_path / "file.json", {"a": 1})
    assert path.exists()
