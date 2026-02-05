import csv
from pathlib import Path

import scripts.generate_feedback as gf


def write_grades(path: Path):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id", "final_grade"])
        writer.writeheader()
        writer.writerow({"student_id": "s1", "final_grade": "80"})


def test_validate_quote_cases():
    text = "Hello world. This is a test."
    exact = gf.validate_quote("Hello world", text)
    assert exact["valid"] is True and exact["exact_match"] is True

    fuzzy = gf.validate_quote("Hello world this is a test", text)
    assert fuzzy["valid"] is True and fuzzy["fuzzy_match"] is True

    invalid = gf.validate_quote("Not present", text)
    assert invalid["valid"] is False

    long_invalid = gf.validate_quote("This is a long quote that will not match anywhere", text)
    assert long_invalid["valid"] is False


def test_generate_feedback_templates(tmp_path):
    grades = tmp_path / "grades.csv"
    write_grades(grades)
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "s1.txt").write_text("Hello world. This is a test.", encoding="utf-8")
    out_dir = tmp_path / "out"

    gf.generate_feedback_batch(grades, texts, out_dir, validate_only=False)
    out_file = out_dir / "s1_feedback.md"
    assert out_file.exists()
    # Second run should skip existing
    gf.generate_feedback_batch(grades, texts, out_dir, validate_only=False)


def test_generate_feedback_validate(tmp_path):
    grades = tmp_path / "grades.csv"
    write_grades(grades)
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "s1.txt").write_text("Hello world. This is a test.", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    feedback = out_dir / "s1_feedback.md"
    feedback.write_text("> \"Hello world\"\n> \"This is a test\"\n> \"Not present\"\n", encoding="utf-8")

    result = gf.generate_feedback_batch(grades, texts, out_dir, validate_only=True)
    assert result == 1

    # Missing feedback file triggers validation error
    (out_dir / "s1_feedback.md").unlink()
    result2 = gf.generate_feedback_batch(grades, texts, out_dir, validate_only=True)
    assert result2 == 1


def test_generate_feedback_main_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["gf", "--grades", str(tmp_path / "missing.csv")])
    assert gf.main() == 1


def test_generate_feedback_main_success(tmp_path, monkeypatch):
    grades = tmp_path / "grades.csv"
    write_grades(grades)
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "s1.txt").write_text("Hello world. This is a test.", encoding="utf-8")
    out_dir = tmp_path / "out"
    monkeypatch.setattr("sys.argv", ["gf", "--grades", str(grades), "--texts", str(texts), "--output", str(out_dir)])
    assert gf.main() == 0


def test_load_student_text_missing(tmp_path):
    assert gf.load_student_text("s1", tmp_path) == ""


def test_generate_feedback_validate_insufficient_quotes(tmp_path):
    grades = tmp_path / "grades.csv"
    write_grades(grades)
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "s1.txt").write_text("Hello world. This is a test.", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    feedback = out_dir / "s1_feedback.md"
    feedback.write_text("> \"Hello world\"\n> \"This is a test\"\n", encoding="utf-8")
    result = gf.generate_feedback_batch(grades, texts, out_dir, validate_only=True)
    assert result == 1


def test_generate_feedback_validate_fuzzy_ok(tmp_path):
    grades = tmp_path / "grades.csv"
    write_grades(grades)
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "s1.txt").write_text("Hello world. This is a test.", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    feedback = out_dir / "s1_feedback.md"
    feedback.write_text("> \"Hello world this is a test\"\n> \"Hello world\"\n> \"This is a test\"\n", encoding="utf-8")
    result = gf.generate_feedback_batch(grades, texts, out_dir, validate_only=True)
    assert result == 0


def test_generate_feedback_missing_text(tmp_path):
    grades = tmp_path / "grades.csv"
    write_grades(grades)
    texts = tmp_path / "texts"
    texts.mkdir()
    out_dir = tmp_path / "out"
    result = gf.generate_feedback_batch(grades, texts, out_dir, validate_only=False)
    assert result == 1


def test_generate_feedback_main_missing_texts(tmp_path, monkeypatch):
    grades = tmp_path / "grades.csv"
    write_grades(grades)
    monkeypatch.setattr("sys.argv", ["gf", "--grades", str(grades), "--texts", str(tmp_path / "missing")])
    assert gf.main() == 1


def test_generate_feedback_many_errors(tmp_path):
    grades = tmp_path / "grades.csv"
    with grades.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id", "final_grade"])
        writer.writeheader()
        for i in range(21):
            writer.writerow({"student_id": f"s{i}", "final_grade": "80"})
    texts = tmp_path / "texts"
    texts.mkdir()
    out_dir = tmp_path / "out"
    result = gf.generate_feedback_batch(grades, texts, out_dir, validate_only=False)
    assert result == 1
