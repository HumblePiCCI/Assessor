import json
from pathlib import Path

from scripts.assessor_context import (
    build_grade_context,
    format_exemplars,
    load_class_metadata,
    load_exemplars,
    load_grade_profiles,
    normalize_genre,
    grade_band_for_level,
    resolve_exemplars_dir,
    select_grade_level,
)
from tests.conftest import make_docx


def test_load_grade_profiles_missing(tmp_path):
    assert load_grade_profiles(tmp_path / "missing.json") == {}


def test_load_class_metadata_missing(tmp_path):
    assert load_class_metadata(tmp_path / "missing.json") == {}


def test_select_grade_level():
    assert select_grade_level(7, {}) == 7
    assert select_grade_level(None, {"grade_level": "8"}) == 8
    assert select_grade_level(None, {"grade_level": "bad"}) is None


def test_build_grade_context():
    profiles = {
        "grade_7": {
            "vocabulary_expectations": "A",
            "sentence_complexity": "B",
            "thesis_expectations": "C",
            "evidence_expectations": "D",
        }
    }
    context = build_grade_context(7, profiles)
    assert "Grade 7" in context
    assert "Vocabulary: A" in context
    assert build_grade_context(8, profiles) == ""


def test_normalize_genre():
    assert normalize_genre("Literary Analysis") == "literary_analysis"
    assert normalize_genre("news report") == "news_report"
    assert normalize_genre("custom genre") == "custom_genre"
    assert normalize_genre(None) is None


def test_grade_band_for_level():
    assert grade_band_for_level(6) == "grade_6_7"
    assert grade_band_for_level(9) == "grade_8_10"
    assert grade_band_for_level(12) == "grade_11_12"
    assert grade_band_for_level(5) is None


def test_resolve_exemplars_dir(tmp_path):
    base = tmp_path / "exemplars"
    (base / "grade_6_7" / "literary_analysis").mkdir(parents=True)
    (base / "genres" / "argumentative").mkdir(parents=True)
    assert resolve_exemplars_dir(base, 6, "literary_analysis") == base / "grade_6_7" / "literary_analysis"
    assert resolve_exemplars_dir(base, 9, "argumentative") == base / "genres" / "argumentative"
    assert resolve_exemplars_dir(base, 6, "missing") == base
    assert resolve_exemplars_dir(base, None, None) == base


def test_load_exemplars_and_format(tmp_path):
    exemplars_dir = tmp_path / "exemplars"
    exemplars_dir.mkdir()
    lvl3 = exemplars_dir / "level_3.txt"
    lvl3.write_text("Level 3 sample", encoding="utf-8")
    lvl4 = make_docx(exemplars_dir / "level_4.docx", "Level 4 sample")
    loaded = load_exemplars(exemplars_dir)
    assert loaded["level_3"] == "Level 3 sample"
    assert loaded["level_4"] == "Level 4 sample"
    loaded_excluded = load_exemplars(exemplars_dir, exclude_files={"level_3.txt"})
    assert "level_3" not in loaded_excluded
    formatted = format_exemplars(loaded)
    assert "Level 4" in formatted
    assert "Level 3" in formatted
    assert format_exemplars({}) == ""


def test_load_class_metadata_invalid(tmp_path):
    path = tmp_path / "class_metadata.json"
    path.write_text("not json", encoding="utf-8")
    assert load_class_metadata(path) == {}


def test_load_class_metadata_non_dict(tmp_path):
    path = tmp_path / "class_metadata.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert load_class_metadata(path) == {}


def test_load_exemplars_missing_dir(tmp_path):
    assert load_exemplars(tmp_path / "missing") == {}


def test_load_exemplars_empty_text(tmp_path):
    exemplars_dir = tmp_path / "exemplars"
    exemplars_dir.mkdir()
    (exemplars_dir / "level_1.txt").write_text("", encoding="utf-8")
    assert load_exemplars(exemplars_dir) == {}
