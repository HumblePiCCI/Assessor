import csv
import json
from pathlib import Path

import scripts.build_dashboard_data as bdd


def write_csv(path: Path, rows, fieldnames):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_build_dashboard_data(tmp_path, monkeypatch):
    fallback = tmp_path / "consensus.csv"
    rows = [{"student_id": "s1", "consensus_rank": "1"}]
    write_csv(fallback, rows, ["student_id", "consensus_rank"])

    grades = tmp_path / "grades.csv"
    write_csv(grades, [{"student_id": "s1", "final_grade": "90", "curve_top": "92", "curve_bottom": "58"}], ["student_id", "final_grade", "curve_top", "curve_bottom"])

    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "s1.txt").write_text("Essay", encoding="utf-8")
    feedback_dir = tmp_path / "feedback"
    feedback_dir.mkdir()
    (feedback_dir / "s1_feedback.md").write_text("Star 1", encoding="utf-8")

    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir()
    meta = inputs_dir / "class_metadata.json"
    meta.write_text(json.dumps({"grade_level": 7}), encoding="utf-8")

    out = tmp_path / "dash.json"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["bdd", "--input", str(tmp_path / "missing.csv"), "--fallback", str(fallback), "--grades", str(grades), "--texts", str(texts), "--feedback", str(feedback_dir), "--output", str(out)])
    assert bdd.main() == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["students"][0]["student_id"] == "s1"
    assert payload["curve_top"] == "92"
    assert payload["students"][0]["feedback_text"] == "Star 1"


def test_build_dashboard_helpers(tmp_path):
    assert bdd.load_csv(tmp_path / "missing.csv") == []
    assert bdd.load_texts(tmp_path / "missing_dir") == {}
    assert bdd.load_feedback_text(tmp_path / "missing_dir", "s1") == ""
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "s1 .txt").write_text("Essay", encoding="utf-8")
    assert bdd.load_texts(texts)["s1"] == "Essay"


def test_load_feedback_missing_file(tmp_path):
    feedback_dir = tmp_path / "feedback"
    feedback_dir.mkdir()
    assert bdd.load_feedback_text(feedback_dir, "s1") == ""


def test_build_dashboard_data_no_rows(tmp_path, monkeypatch):
    out = tmp_path / "dash.json"
    monkeypatch.setattr("sys.argv", ["bdd", "--input", str(tmp_path / "missing.csv"), "--fallback", str(tmp_path / "missing2.csv"), "--output", str(out)])
    assert bdd.main() == 1


def test_build_dashboard_data_no_grades(tmp_path, monkeypatch):
    fallback = tmp_path / "consensus.csv"
    rows = [{"student_id": "s1", "consensus_rank": "1"}]
    write_csv(fallback, rows, ["student_id", "consensus_rank"])
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "s1.txt").write_text("Essay", encoding="utf-8")
    out = tmp_path / "dash.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["bdd", "--input", str(tmp_path / "missing.csv"), "--fallback", str(fallback), "--output", str(out), "--texts", str(texts)])
    assert bdd.main() == 0


def test_build_dashboard_data_primary_input(tmp_path, monkeypatch):
    primary = tmp_path / "primary.csv"
    rows = [{"student_id": "s1", "final_rank": "1"}]
    write_csv(primary, rows, ["student_id", "final_rank"])
    out = tmp_path / "dash.json"
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "s1.txt").write_text("Essay", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["bdd", "--input", str(primary), "--fallback", str(tmp_path / "missing.csv"), "--output", str(out), "--texts", str(texts)])
    assert bdd.main() == 0
