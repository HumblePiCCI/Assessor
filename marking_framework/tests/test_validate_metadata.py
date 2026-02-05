import json
from pathlib import Path

import scripts.validate_metadata as vm


def test_validate_metadata_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["vm", "--path", str(tmp_path / "missing.json")])
    assert vm.main() == 0


def test_validate_metadata_invalid_json(tmp_path, monkeypatch):
    path = tmp_path / "meta.json"
    path.write_text("{bad", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["vm", "--path", str(path)])
    assert vm.main() == 1


def test_validate_metadata_warnings_and_errors(tmp_path, monkeypatch):
    path = tmp_path / "meta.json"
    path.write_text(json.dumps({"grade_level": "bad", "total_students": -1}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["vm", "--path", str(path), "--strict"])
    assert vm.main() == 1


def test_validate_metadata_success(tmp_path, monkeypatch):
    submissions = tmp_path / "submissions"
    submissions.mkdir()
    (submissions / "a.txt").write_text("x", encoding="utf-8")
    path = tmp_path / "meta.json"
    path.write_text(json.dumps({"grade_level": 7, "total_students": 1, "class_name": "X"}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["vm", "--path", str(path), "--submissions", str(submissions)])
    assert vm.main() == 0


def test_validate_metadata_non_dict(tmp_path, monkeypatch):
    path = tmp_path / "meta.json"
    path.write_text(json.dumps(["not", "dict"]), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["vm", "--path", str(path)])
    assert vm.main() == 1


def test_validate_metadata_grade_level_out_of_range(tmp_path, monkeypatch):
    path = tmp_path / "meta.json"
    path.write_text(json.dumps({"grade_level": 13}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["vm", "--path", str(path)])
    assert vm.main() == 1


def test_validate_metadata_total_students_mismatch_warning(tmp_path, monkeypatch):
    submissions = tmp_path / "submissions"
    submissions.mkdir()
    (submissions / "a.txt").write_text("x", encoding="utf-8")
    path = tmp_path / "meta.json"
    path.write_text(json.dumps({"grade_level": 7, "total_students": 2}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["vm", "--path", str(path), "--submissions", str(submissions)])
    assert vm.main() == 0


def test_count_submissions_missing_dir(tmp_path):
    assert vm.count_submissions(tmp_path / "missing") == 0


def test_validate_metadata_no_grade_level(tmp_path, monkeypatch):
    path = tmp_path / "meta.json"
    path.write_text(json.dumps({"total_students": 0}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["vm", "--path", str(path)])
    assert vm.main() == 0


def test_validate_metadata_total_students_not_int(tmp_path, monkeypatch):
    path = tmp_path / "meta.json"
    path.write_text(json.dumps({"grade_level": 7, "total_students": "bad"}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["vm", "--path", str(path)])
    assert vm.main() == 1
