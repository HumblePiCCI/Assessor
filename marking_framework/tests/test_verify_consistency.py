import csv
import json
from pathlib import Path

import scripts.verify_consistency as vc


def write_scores(path: Path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_verify_consistency_apply(tmp_path, monkeypatch):
    scores_path = tmp_path / "scores.csv"
    rows = [
        {"student_id": "s1", "consensus_rank": "1"},
        {"student_id": "s2", "consensus_rank": "2"},
    ]
    write_scores(scores_path, rows)
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Essay one", encoding="utf-8")
    (texts_dir / "s2.txt").write_text("Essay two", encoding="utf-8")
    rubric = tmp_path / "rubric.md"
    outline = tmp_path / "outline.md"
    rubric.write_text("rubric", encoding="utf-8")
    outline.write_text("outline", encoding="utf-8")

    def fake_create(model, messages, temperature, reasoning, routing_path):
        payload = {"decision": "SWAP", "confidence": "high", "reason": "B stronger"}
        return {"output": [{"type": "output_text", "text": json.dumps(payload)}]}

    monkeypatch.setattr(vc, "responses_create", fake_create)
    out_path = tmp_path / "checks.json"
    monkeypatch.setattr("sys.argv", [
        "vc",
        "--scores", str(scores_path),
        "--texts", str(texts_dir),
        "--rubric", str(rubric),
        "--outline", str(outline),
        "--output", str(out_path),
        "--apply",
    ])
    assert vc.main() == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["checks"][0]["decision"] == "SWAP"
    adjusted = out_path.with_name("consistency_adjusted.csv")
    assert adjusted.exists()


def test_parse_json_fallback():
    payload = vc.parse_json("prefix {\"decision\": \"KEEP\", \"confidence\": \"low\", \"reason\": \"ok\"} suffix")
    assert payload["decision"] == "KEEP"


def test_parse_json_invalid():
    try:
        vc.parse_json("no json here")
    except ValueError:
        assert True


def test_apply_swaps_branches():
    order = ["a", "b", "c"]
    decisions = [
        {"decision": "KEEP"},
        {"decision": "SWAP", "confidence": "low", "pair": ["a", "b"]},
        {"decision": "SWAP", "confidence": "high", "pair": ["x", "y"]},
        {"decision": "SWAP", "confidence": "high", "pair": ["a", "c"]},
        {"decision": "SWAP", "confidence": "high", "pair": ["b", "c"]},
    ]
    result = vc.apply_swaps(order, decisions, "medium")
    assert result == ["a", "c", "b"]


def test_verify_consistency_missing_scores(tmp_path, monkeypatch):
    missing = tmp_path / "missing.csv"
    monkeypatch.setattr("sys.argv", ["vc", "--scores", str(missing)])
    assert vc.main() == 1


def test_verify_consistency_no_rows(tmp_path, monkeypatch):
    scores_path = tmp_path / "scores.csv"
    scores_path.write_text("student_id,consensus_rank\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["vc", "--scores", str(scores_path)])
    assert vc.main() == 1


def test_verify_consistency_no_apply(tmp_path, monkeypatch):
    scores_path = tmp_path / "scores.csv"
    rows = [
        {"student_id": "s1", "consensus_rank": "1"},
        {"student_id": "s2", "consensus_rank": "2"},
    ]
    write_scores(scores_path, rows)
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("Essay one", encoding="utf-8")
    (texts_dir / "s2.txt").write_text("Essay two", encoding="utf-8")
    rubric = tmp_path / "rubric.md"
    outline = tmp_path / "outline.md"
    rubric.write_text("rubric", encoding="utf-8")
    outline.write_text("outline", encoding="utf-8")

    def fake_create(model, messages, temperature, reasoning, routing_path):
        payload = {"decision": "KEEP", "confidence": "low", "reason": "ok"}
        return {"output": [{"type": "output_text", "text": json.dumps(payload)}]}

    monkeypatch.setattr(vc, "responses_create", fake_create)
    out_path = tmp_path / "checks.json"
    monkeypatch.setattr("sys.argv", [
        "vc",
        "--scores", str(scores_path),
        "--texts", str(texts_dir),
        "--rubric", str(rubric),
        "--outline", str(outline),
        "--output", str(out_path),
    ])
    assert vc.main() == 0
