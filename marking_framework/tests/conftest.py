import json
import zipfile
from pathlib import Path

import pytest


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


@pytest.fixture(autouse=True)
def _isolate_llm_cache(tmp_path, monkeypatch):
    # Tests should never share on-disk LLM cache state.
    monkeypatch.setenv("LLM_CACHE", "0")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))


def make_docx(path: Path, text: str):
    xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{WORD_NS}">
  <w:body>
    <w:p><w:r><w:t>{text}</w:t></w:r></w:p>
  </w:body>
</w:document>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)
    return path


def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
