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

    assert (out_dir / "a.txt").exists()
    assert (out_dir / "b.txt").exists()
    assert meta_path.exists()


def test_extract_text_no_metadata(tmp_path, monkeypatch):
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    (in_dir / "a.txt").write_text("Plain text", encoding="utf-8")
    out_dir = tmp_path / "out"
    monkeypatch.setattr("sys.argv", ["et", "--inputs", str(in_dir), "--output", str(out_dir)])
    assert et.main() == 0


def test_extract_docx_empty(tmp_path):
    path = make_docx(tmp_path / "empty.docx", "")
    assert et.extract_docx_text(path) == ""
