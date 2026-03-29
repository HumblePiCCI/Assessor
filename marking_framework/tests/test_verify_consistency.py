import csv
import json
from pathlib import Path

import scripts.verify_consistency as vc


def write_scores(path: Path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_verify_consistency_collects_normalized_judgments(tmp_path, monkeypatch):
    scores_path = tmp_path / "scores.csv"
    rows = [
        {
            "student_id": "s1",
            "seed_rank": "1",
            "consensus_rank": "1",
            "adjusted_level": "4",
            "rubric_after_penalty_percent": "82.0",
            "composite_score": "0.81",
        },
        {
            "student_id": "s2",
            "seed_rank": "2",
            "consensus_rank": "2",
            "adjusted_level": "4",
            "rubric_after_penalty_percent": "84.0",
            "composite_score": "0.79",
        },
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

    def fake_create(model, messages, temperature, reasoning, routing_path, text_format=None, max_output_tokens=None):
        assert text_format is not None
        assert max_output_tokens == 300
        payload = {"decision": "SWAP", "confidence": "high", "rationale": "B is stronger overall."}
        return {"model": model, "usage": {"input_tokens": 10}, "output": [{"type": "output_text", "text": json.dumps(payload)}]}

    monkeypatch.setattr(vc, "responses_create", fake_create)
    out_path = tmp_path / "checks.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "vc",
            "--scores",
            str(scores_path),
            "--texts",
            str(texts_dir),
            "--rubric",
            str(rubric),
            "--outline",
            str(outline),
            "--output",
            str(out_path),
        ],
    )
    assert vc.main() == 0
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["comparison_window"] == 2
    assert data["checks"][0]["pair"] == ["s1", "s2"]
    assert data["checks"][0]["decision"] == "SWAP"
    assert data["checks"][0]["model_metadata"]["requested_model"] == "gpt-5.2"


def test_verify_consistency_apply_runs_global_reranker(tmp_path, monkeypatch):
    scores_path = tmp_path / "scores.csv"
    rows = [
        {
            "student_id": "s1",
            "seed_rank": "1",
            "consensus_rank": "1",
            "adjusted_level": "4",
            "rubric_after_penalty_percent": "82.0",
            "composite_score": "0.80",
        },
        {
            "student_id": "s2",
            "seed_rank": "2",
            "consensus_rank": "2",
            "adjusted_level": "4",
            "rubric_after_penalty_percent": "83.0",
            "composite_score": "0.79",
        },
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
    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")

    def fake_create(model, messages, temperature, reasoning, routing_path, text_format=None, max_output_tokens=None):
        payload = {"decision": "SWAP", "confidence": "high", "rationale": "B is stronger overall."}
        return {"model": model, "output": [{"type": "output_text", "text": json.dumps(payload)}]}

    monkeypatch.setattr(vc, "responses_create", fake_create)
    out_path = tmp_path / "checks.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "vc",
            "--scores",
            str(scores_path),
            "--texts",
            str(texts_dir),
            "--rubric",
            str(rubric),
            "--outline",
            str(outline),
            "--config",
            str(cfg),
            "--output",
            str(out_path),
            "--rerank-output",
            str(tmp_path / "final_order.csv"),
            "--matrix-output",
            str(tmp_path / "pairwise_matrix.json"),
            "--scores-output",
            str(tmp_path / "rerank_scores.csv"),
            "--report-output",
            str(tmp_path / "consistency_report.json"),
            "--legacy-output",
            str(tmp_path / "consistency_adjusted.csv"),
            "--apply",
        ],
    )
    assert vc.main() == 0
    final_rows = list(csv.DictReader((tmp_path / "final_order.csv").open("r", encoding="utf-8")))
    assert [row["student_id"] for row in final_rows] == ["s2", "s1"]
    assert (tmp_path / "consistency_adjusted.csv").exists()
    report = json.loads((tmp_path / "consistency_report.json").read_text(encoding="utf-8"))
    assert report["summary"]["judgment_count"] == 1


def test_parse_json_fallback():
    payload = vc.parse_json('prefix {"decision": "KEEP", "confidence": "low", "rationale": "ok"} suffix')
    assert payload["decision"] == "KEEP"


def test_parse_json_invalid():
    try:
        vc.parse_json("no json here")
    except ValueError:
        assert True


def test_select_pairs_window():
    rows = [
        {"student_id": "s1", "seed_rank": 1},
        {"student_id": "s2", "seed_rank": 2},
        {"student_id": "s3", "seed_rank": 3},
    ]
    pairs = vc.select_pairs(rows, window=2)
    assert [(left["student_id"], right["student_id"]) for left, right in pairs] == [("s1", "s2"), ("s1", "s3"), ("s2", "s3")]


def test_verify_consistency_missing_scores(tmp_path, monkeypatch):
    missing = tmp_path / "missing.csv"
    monkeypatch.setattr("sys.argv", ["vc", "--scores", str(missing)])
    assert vc.main() == 1


def test_verify_consistency_no_rows(tmp_path, monkeypatch):
    scores_path = tmp_path / "scores.csv"
    scores_path.write_text("student_id,consensus_rank\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["vc", "--scores", str(scores_path)])
    assert vc.main() == 1
