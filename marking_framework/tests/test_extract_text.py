import json
from pathlib import Path

import scripts.extract_text as et
from tests.conftest import make_docx


def test_extract_text_main(tmp_path, monkeypatch):
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    make_docx(in_dir / "a.docx", "Docx text")
    (in_dir / "b.txt").write_text("Plain text", encoding="utf-8")
    (in_dir / "skip.bin").write_text("skip", encoding="utf-8")
    (in_dir / "subdir").mkdir()

    out_dir = tmp_path / "out"
    meta_path = tmp_path / "meta.json"
    monkeypatch.setattr("sys.argv", ["et", "--inputs", str(in_dir), "--output", str(out_dir), "--metadata", str(meta_path)])
    assert et.main() == 0

    assert (out_dir / "s001.txt").exists()
    assert (out_dir / "s002.txt").exists()
    assert meta_path.exists()


def test_extract_text_no_metadata(tmp_path, monkeypatch):
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    (in_dir / "a.txt").write_text("Plain text", encoding="utf-8")
    out_dir = tmp_path / "out"
    monkeypatch.setattr("sys.argv", ["et", "--inputs", str(in_dir), "--output", str(out_dir)])
    assert et.main() == 0


def test_extract_text_uses_classroom_roster_display_names(tmp_path, monkeypatch):
    inputs = tmp_path / "inputs"
    in_dir = inputs / "submissions"
    in_dir.mkdir(parents=True)
    (in_dir / "google-user-1.txt").write_text("Plain text", encoding="utf-8")
    (inputs / "class_metadata.json").write_text(
        json.dumps({"roster": [{"student_id": "google-user-1", "display_name": "Jordan Lee"}]}),
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    meta_path = tmp_path / "meta.json"
    monkeypatch.setattr("sys.argv", ["et", "--inputs", str(in_dir), "--output", str(out_dir), "--metadata", str(meta_path)])

    assert et.main() == 0

    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metadata[0]["student_id"] == "s001"
    assert metadata[0]["display_name"] == "Jordan Lee"
    assert metadata[0]["source_file"] == "google-user-1.txt"


def test_extract_docx_empty(tmp_path):
    path = make_docx(tmp_path / "empty.docx", "")
    assert et.extract_docx_text(path) == ""


def test_scrub_personal_headers():
    raw = "\n".join([
        "Name: Student Name",
        "By: Student Name",
        "Student- 7A",
        "",
        "By the end of the story, the character learns a lesson.",
    ])
    scrubbed = et.scrub_personal_headers(raw)
    assert "Name:" not in scrubbed
    assert "By:" not in scrubbed
    assert "By the end of the story" in scrubbed


def test_scrub_reference_tail_cuts_boilerplate():
    raw = "\n".join(
        [
            "My essay opening.",
            "Second paragraph.",
            "Teacher Support:",
            "Click to find out more about this resource.",
        ]
    )
    scrubbed = et.scrub_reference_tail(raw)
    assert scrubbed == "My essay opening.\nSecond paragraph."


def test_scrub_reference_tail_keeps_clean_text():
    raw = "First line.\nSecond line."
    assert et.scrub_reference_tail(raw) == raw
