import json
from pathlib import Path

import scripts.llm_pairwise_review as lpr
from tests.conftest import make_docx


def test_llm_pairwise_review_generate(tmp_path, monkeypatch):
    pairs_path = tmp_path / "pairs.json"
    pairs = {
        "pairs": [
            {
                "pair_id": 1,
                "left": {"student_id": "s1"},
                "right": {"student_id": "s2"},
                "decision": {"action": "keep", "reason": ""},
            }
        ]
    }
    pairs_path.write_text(json.dumps(pairs), encoding="utf-8")
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Text one", encoding="utf-8")
    (texts_dir / "s2.txt").write_text("Text two", encoding="utf-8")
    outline_docx = make_docx(tmp_path / "outline.docx", "Outline")

    out_path = tmp_path / "llm_input.json"
    monkeypatch.setattr("sys.argv", ["lpr", "--pairs", str(pairs_path), "--texts", str(texts_dir), "--outline", str(outline_docx), "--output", str(out_path)])
    assert lpr.main() == 0
    assert out_path.exists()


def test_llm_pairwise_review_apply(tmp_path, monkeypatch):
    pairs_path = tmp_path / "pairs.json"
    pairs = {"pairs": [{"pair_id": 1, "left": {"student_id": "s1"}, "right": {"student_id": "s2"}, "decision": {"action": "keep", "reason": ""}}]}
    pairs_path.write_text(json.dumps(pairs), encoding="utf-8")

    decisions_path = tmp_path / "out.json"
    decisions = {"pairs": [{"pair_id": 1, "decision": {"action": "swap", "reason": "better", "confidence": "high"}}]}
    decisions_path.write_text(json.dumps(decisions), encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["lpr", "--pairs", str(pairs_path), "--decisions", str(decisions_path), "--apply"])
    assert lpr.main() == 0
    updated = json.loads(pairs_path.read_text(encoding="utf-8"))
    assert updated["pairs"][0]["decision"]["action"] == "swap"


def test_llm_pairwise_review_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["lpr", "--pairs", str(tmp_path / "missing.json")])
    assert lpr.main() == 1


def test_llm_pairwise_review_apply_missing_decisions(tmp_path, monkeypatch):
    pairs_path = tmp_path / "pairs.json"
    pairs_path.write_text(json.dumps({"pairs": []}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["lpr", "--pairs", str(pairs_path), "--decisions", str(tmp_path / "missing.json"), "--apply"])
    assert lpr.main() == 1


def test_llm_pairwise_review_helpers(tmp_path):
    txt = tmp_path / "outline.txt"
    txt.write_text("Outline", encoding="utf-8")
    assert lpr.read_text(txt) == "Outline"
    assert lpr.load_outline(tmp_path / "missing.md") == ""

    list_pairs = tmp_path / "list_pairs.json"
    list_pairs.write_text(json.dumps([{"pair_id": 1}]), encoding="utf-8")
    data = lpr.load_pairs(list_pairs)
    assert "pairs" in data

    truncated = lpr.truncate("abcdef", 3)
    assert truncated.endswith("...")

    original = {"pairs": [{"pair_id": 1, "decision": {"action": "keep"}}]}
    decisions = {"pairs": [{"pair_id": 2, "decision": {"action": "swap"}}]}
    merged = lpr.apply_decisions(original, decisions)
    assert merged["pairs"][0]["decision"]["action"] == "keep"


def test_llm_pairwise_review_docx_empty(tmp_path):
    empty = make_docx(tmp_path / "empty.docx", "")
    assert lpr.extract_docx_text(empty) == ""
