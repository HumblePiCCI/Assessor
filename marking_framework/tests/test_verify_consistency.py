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
    assert data["checks"][0]["model_metadata"]["requested_model"] == "gpt-5.4-mini"
    assert data["checks"][0]["model_metadata"]["repair_used"] is False


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
    pairs = vc.select_pairs(rows, window=2, metadata={})
    assert [(left["student_id"], right["student_id"]) for left, right in pairs] == [("s1", "s2"), ("s1", "s3"), ("s2", "s3")]


def test_verify_consistency_uses_bootstrap_literary_window():
    metadata = {"generated_by": "bootstrap", "assignment_genre": "literary_analysis"}
    assert vc.effective_window(2, metadata) == 4
    assert vc.effective_window(4, metadata) == 4


def test_select_pairs_expands_for_bootstrap_divergence_outliers():
    rows = [
        {"student_id": "s1", "seed_rank": 1, "borda_percent": 0.95, "composite_score": 0.9},
        {"student_id": "s2", "seed_rank": 2, "borda_percent": 0.75, "composite_score": 0.8},
        {"student_id": "s3", "seed_rank": 3, "borda_percent": 0.95, "composite_score": 0.9},
        {"student_id": "s4", "seed_rank": 4, "borda_percent": 0.1, "composite_score": 0.2},
    ]
    metadata = {"generated_by": "bootstrap", "assignment_genre": "literary_analysis"}
    pairs = vc.select_pairs(rows, window=1, metadata=metadata)
    tokens = [(left["student_id"], right["student_id"]) for left, right in pairs]
    assert ("s1", "s3") in tokens
    assert ("s1", "s4") in tokens


def test_select_pair_specs_fully_compares_top_pack_beyond_window():
    rows = [
        {"student_id": f"s{idx}", "seed_rank": idx, "borda_percent": 0.5, "composite_score": 0.5}
        for idx in range(1, 7)
    ]
    specs = vc.select_pair_specs(rows, window=1, metadata={}, top_pack_size=4)
    by_pair = {
        (spec["higher"]["student_id"], spec["lower"]["student_id"]): spec
        for spec in specs
    }
    assert ("s1", "s4") in by_pair
    assert "top_pack" in by_pair[("s1", "s4")]["selection_reasons"]


def test_select_pair_specs_checks_post_seam_movers_against_top_pack_and_neighbors():
    rows = [
        {"student_id": f"s{idx}", "seed_rank": idx, "adjusted_level": "2", "borda_percent": 0.5, "composite_score": 0.5}
        for idx in range(1, 8)
    ]
    report = {"applied": [{"student_id": "s7", "from_level": "1", "to_level": "2"}]}
    specs = vc.select_pair_specs(
        rows,
        window=1,
        metadata={},
        top_pack_size=3,
        large_mover_window=1,
        band_seam_report=report,
    )
    by_pair = {(item["higher"]["student_id"], item["lower"]["student_id"]): item for item in specs}
    assert "large_mover_top_pack" in by_pair[("s1", "s7")]["selection_reasons"]
    assert "large_mover_neighborhood" in by_pair[("s6", "s7")]["selection_reasons"]


def test_collect_judgments_records_selection_reasons(tmp_path, monkeypatch):
    rows = [
        {
            "student_id": "s1",
            "seed_rank": 1,
            "level": "3",
            "adjusted_level": "3",
            "rubric_after_penalty_percent": 70.0,
            "borda_percent": 0.6,
            "composite_score": 0.6,
        },
        {
            "student_id": "s2",
            "seed_rank": 2,
            "level": "2",
            "adjusted_level": "2",
            "rubric_after_penalty_percent": 68.0,
            "borda_percent": 0.7,
            "composite_score": 0.7,
        },
    ]
    prompts = []

    def fake_create(model, messages, temperature, reasoning, routing_path, text_format=None, max_output_tokens=None):
        prompts.append(messages[0]["content"])
        payload = {"decision": "SWAP", "confidence": "high", "rationale": "B has stronger evidence."}
        return {"model": model, "output": [{"type": "output_text", "text": json.dumps(payload)}]}

    monkeypatch.setattr(vc, "responses_create", fake_create)
    judgments = vc.collect_judgments(
        rows,
        {"s1": "Essay one", "s2": "Essay two"},
        "rubric",
        "outline",
        model="gpt-5.4-mini",
        routing="routing.json",
        reasoning="low",
        max_output_tokens=300,
        window=1,
        metadata={},
        top_pack_size=2,
    )
    assert judgments[0]["selection_reasons"][:2] == ["seed_window", "top_pack"]
    assert "Why this pair is being checked" in prompts[0]
    assert "top_pack" in prompts[0]


def test_verify_consistency_build_prompt_includes_literary_guidance():
    prompt = vc.build_prompt(
        "rubric",
        "outline",
        {"student_id": "s1", "seed_rank": 1, "level": "3", "rubric_after_penalty_percent": 70.0},
        {"student_id": "s2", "seed_rank": 2, "level": "3", "rubric_after_penalty_percent": 68.0},
        "Essay one",
        "Essay two",
        genre="literary_analysis",
        metadata={"generated_by": "bootstrap", "assignment_genre": "literary_analysis"},
    )
    assert "Do not over-reward rigid five-paragraph structure" in prompt
    assert "cold-start classroom cohort" in prompt


def test_verify_consistency_repairs_invalid_json_response(tmp_path, monkeypatch):
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
    out_path = tmp_path / "checks.json"

    responses = iter(
        [
            {"model": "gpt-5.4-mini", "output": [{"type": "output_text", "text": "decision=SWAP confidence=high"}]},
            {
                "model": "gpt-5.4-mini",
                "output": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"decision": "SWAP", "confidence": "high", "rationale": "Repair recovered valid JSON."}),
                    }
                ],
            },
        ]
    )

    def fake_create(model, messages, temperature, reasoning, routing_path, text_format=None, max_output_tokens=None):
        return next(responses)

    monkeypatch.setattr(vc, "responses_create", fake_create)
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
    assert data["checks"][0]["decision"] == "SWAP"
    assert data["checks"][0]["model_metadata"]["repair_used"] is True


def test_verify_consistency_missing_scores(tmp_path, monkeypatch):
    missing = tmp_path / "missing.csv"
    monkeypatch.setattr("sys.argv", ["vc", "--scores", str(missing)])
    assert vc.main() == 1


def test_verify_consistency_no_rows(tmp_path, monkeypatch):
    scores_path = tmp_path / "scores.csv"
    scores_path.write_text("student_id,consensus_rank\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["vc", "--scores", str(scores_path)])
    assert vc.main() == 1
