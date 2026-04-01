import json
from pathlib import Path

from scripts.assessor_context import (
    build_grade_context,
    exemplar_genre_order,
    format_exemplars,
    resolve_exemplar_selection,
    infer_genre_from_text,
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
    assert select_grade_level(None, {"grade_numeric_equivalent": "2"}) == 2
    assert select_grade_level(None, {"grade_numeric": "4"}) == 4
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
    assert normalize_genre("opinion letter") == "argumentative"
    assert normalize_genre("summary report") == "summary_report"
    assert normalize_genre("book review") == "book_review"
    assert normalize_genre("informative letter") == "informative_letter"
    assert normalize_genre("speech") == "speech"
    assert normalize_genre("custom genre") == "custom_genre"
    assert normalize_genre(None) is None


def test_infer_genre_from_text():
    assert infer_genre_from_text("Write clear instructions with materials and safety notes", "") == "instructions"
    assert infer_genre_from_text("Write a summary of the article in your own words", "") == "summary_report"
    assert infer_genre_from_text("Prepare a speech for your classmates", "") == "speech"
    assert infer_genre_from_text("Write a persuasive letter", "convince your principal") == "argumentative"
    assert infer_genre_from_text("Write a news report headline", "") == "news_report"
    assert infer_genre_from_text("Explain facts and details", "") == "informational_report"
    assert infer_genre_from_text("Analyze theme and character", "") == "literary_analysis"
    assert infer_genre_from_text("Free writing", "journal entry") is None


def test_grade_band_for_level():
    assert grade_band_for_level(2) == "grade_1_3"
    assert grade_band_for_level(5) == "grade_4_5"
    assert grade_band_for_level(6) == "grade_6_7"
    assert grade_band_for_level(9) == "grade_8_10"
    assert grade_band_for_level(12) == "grade_11_12"
    assert grade_band_for_level(13) is None


def test_exemplar_genre_order_prefers_mapped_bucket():
    assert exemplar_genre_order("speech")[0] == "argumentative"
    assert exemplar_genre_order("summary_report")[0] == "informational_report"
    assert exemplar_genre_order("book_review")[0] == "literary_analysis"


def test_resolve_exemplars_dir(tmp_path):
    base = tmp_path / "exemplars"
    grade_dir = base / "grade_6_7" / "literary_analysis"
    grade_dir.mkdir(parents=True)
    (grade_dir / "level_3.md").write_text("Level 3 sample", encoding="utf-8")
    genre_dir = base / "genres" / "argumentative"
    genre_dir.mkdir(parents=True)
    (genre_dir / "level_2.md").write_text("Level 2 sample", encoding="utf-8")
    assert resolve_exemplars_dir(base, 6, "literary_analysis") == base / "grade_6_7" / "literary_analysis"
    assert resolve_exemplars_dir(base, 9, "argumentative") == base / "genres" / "argumentative"
    assert resolve_exemplars_dir(base, 6, "missing") == grade_dir
    assert resolve_exemplars_dir(base, None, None) == grade_dir


def test_resolve_exemplar_selection_cross_band_for_early_grade(tmp_path):
    base = tmp_path / "exemplars"
    band_dir = base / "grade_6_7" / "informational_report"
    band_dir.mkdir(parents=True)
    (band_dir / "level_3.md").write_text("Level 3 sample", encoding="utf-8")
    selection = resolve_exemplar_selection(base, 2, "informative_letter")
    assert selection["path"] == band_dir
    assert selection["selected_band"] == "grade_6_7"
    assert selection["selected_genre"] == "informational_report"
    assert selection["match_quality"] == "cross_band"


def test_resolve_exemplars_dir_fallback_with_levels(tmp_path):
    base = tmp_path / "exemplars"
    band_dir = base / "grade_6_7" / "argumentative"
    band_dir.mkdir(parents=True)
    (band_dir / "level_2.md").write_text("Level 2 exemplar", encoding="utf-8")
    global_dir = base / "grade_8_10" / "literary_analysis"
    global_dir.mkdir(parents=True)
    (global_dir / "level_3.md").write_text("Level 3 exemplar", encoding="utf-8")

    # Genre not available in band should fall back to a genre in the same band with exemplars.
    assert resolve_exemplars_dir(base, 7, "news_report") == band_dir
    # Unknown grade should still find a stable default band/genre with exemplars.
    assert resolve_exemplars_dir(base, None, None) == global_dir


def test_resolve_exemplars_dir_prefers_root_when_root_has_levels(tmp_path):
    base = tmp_path / "exemplars"
    base.mkdir(parents=True)
    (base / "level_2.md").write_text("Root level 2 exemplar", encoding="utf-8")
    # Genre folder exists but has no level files, so function should fall back to root exemplars.
    (base / "genres" / "argumentative").mkdir(parents=True)
    assert resolve_exemplars_dir(base, None, "argumentative") == base


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
