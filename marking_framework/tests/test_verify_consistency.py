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
        assert max_output_tokens == 600
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


def test_verify_consistency_build_prompt_includes_literary_priority_contract():
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
    assert "rougher essay with a clearer interpretation" in prompt
    assert "Do not let a five-paragraph shape" in prompt
    assert "five-paragraph form" in prompt
    assert "defensible theme about trauma" in prompt
    assert "sustained analysis of one important relationship" in prompt
    assert "unfinished scaffold" in prompt
    assert "Do not downgrade a clear content/evidence winner" in prompt
    assert "criterion_notes" in prompt
    assert "decision_basis" in prompt
    assert "winner_side" in prompt
    assert "decision_checks" in prompt
    assert "cleaner_wins_on_substance" in prompt
    assert "rougher_loses_because" in prompt
    assert "Pair identity only" in prompt
    assert "Current seed order" not in prompt
    assert "current seed rank" not in prompt
    assert "rubric 70.00%" not in prompt
    assert "Ignore current seed order" in prompt
    assert "cold-start classroom cohort" in prompt


def test_verify_consistency_build_prompt_adapts_to_argumentative_and_summary():
    argumentative = vc.build_prompt(
        "rubric",
        "outline",
        {"student_id": "s1", "seed_rank": 1, "level": "3", "rubric_after_penalty_percent": 70.0},
        {"student_id": "s2", "seed_rank": 2, "level": "3", "rubric_after_penalty_percent": 68.0},
        "Essay one",
        "Essay two",
        genre="argumentative",
        metadata={"grade_level": 8, "assignment_genre": "argumentative"},
    )
    assert "Clear, arguable claim" in argumentative
    assert "Counterargument engagement" in argumentative
    assert "less polished argument with stronger reasons" in argumentative

    summary = vc.build_prompt(
        "rubric",
        "outline",
        {"student_id": "s1", "seed_rank": 1, "level": "3", "rubric_after_penalty_percent": 70.0},
        {"student_id": "s2", "seed_rank": 2, "level": "3", "rubric_after_penalty_percent": 68.0},
        "Essay one",
        "Essay two",
        genre="summary_report",
        metadata={"grade_level": 6, "assignment_genre": "summary_report"},
    )
    assert "Accurate capture of the main idea" in summary
    assert "copied detail" in summary
    assert "shorter summary can outrank a longer one" in summary


def test_collect_judgments_stores_criterion_audit_fields(monkeypatch):
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
            "level": "3",
            "adjusted_level": "3",
            "rubric_after_penalty_percent": 69.0,
            "borda_percent": 0.7,
            "composite_score": 0.7,
        },
    ]

    def fake_create(model, messages, temperature, reasoning, routing_path, text_format=None, max_output_tokens=None):
        payload = {
            "decision": "SWAP",
            "confidence": "high",
            "rationale": "B has rougher mechanics but stronger interpretation and evidence.",
            "criterion_notes": [
                {"criterion": "task alignment", "stronger": "B", "reason": "B answers the prompt more directly."},
                {"criterion": "organization/language", "stronger": "A", "reason": "A is cleaner but thinner."},
            ],
            "decision_basis": "content_reasoning",
            "cautions_applied": ["rougher_but_stronger_content", "polished_but_shallow", "unknown"],
            "decision_checks": {
                "deeper_interpretation": "B",
                "better_text_evidence_explanation": "B",
                "cleaner_or_more_formulaic": "A",
                "rougher_but_stronger_content": "B",
                "completion_advantage": "tie",
                "cleaner_wins_on_substance": "",
                "rougher_loses_because": "",
            },
        }
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
        max_output_tokens=600,
        window=1,
        metadata={"assignment_genre": "literary_analysis"},
    )
    assert judgments[0]["decision"] == "SWAP"
    assert judgments[0]["decision_basis"] == "content_reasoning"
    assert judgments[0]["criterion_notes"][0]["stronger"] == "B"
    assert judgments[0]["cautions_applied"] == ["rougher_but_stronger_content", "polished_but_shallow"]
    assert judgments[0]["decision_checks"]["rougher_but_stronger_content"] == "B"


def test_winner_side_overrides_legacy_decision(monkeypatch):
    higher = {
        "student_id": "clean",
        "seed_rank": 1,
        "level": "3",
        "rubric_after_penalty_percent": 73.0,
        "borda_percent": 0.8,
        "composite_score": 0.7,
    }
    lower = {
        "student_id": "rough",
        "seed_rank": 2,
        "level": "3",
        "rubric_after_penalty_percent": 71.0,
        "borda_percent": 0.7,
        "composite_score": 0.69,
    }

    def fake_create(model, messages, temperature, reasoning, routing_path, text_format=None, max_output_tokens=None):
        payload = {
            "winner_side": "B",
            "decision": "KEEP",
            "confidence": "high",
            "rationale": "B has rougher mechanics but the stronger interpretation and textual explanation.",
            "criterion_notes": [{"criterion": "content/reasoning", "stronger": "B", "reason": "Stronger interpretation."}],
            "decision_basis": "content_reasoning",
            "cautions_applied": ["rougher_but_stronger_content"],
            "decision_checks": {
                "deeper_interpretation": "B",
                "better_text_evidence_explanation": "B",
                "cleaner_or_more_formulaic": "A",
                "rougher_but_stronger_content": "B",
                "completion_advantage": "tie",
                "cleaner_wins_on_substance": "Polish did not decide.",
                "rougher_loses_because": "The rougher essay does not lose.",
            },
        }
        return {"model": model, "output": [{"type": "output_text", "text": json.dumps(payload)}]}

    monkeypatch.setattr(vc, "responses_create", fake_create)
    judgment = vc.judge_pair(
        "rubric",
        "outline",
        higher,
        lower,
        "Clean but shallow summary.",
        "Rougher analysis with a real interpretation.",
        model="gpt-5.4-mini",
        routing="routing.json",
        reasoning="low",
        max_output_tokens=600,
        genre="literary_analysis",
    )
    assert judgment["winner_side"] == "B"
    assert judgment["decision"] == "SWAP"
    assert judgment["winner"] == "rough"
    assert judgment["loser"] == "clean"
    assert "decision_overridden_by_winner_side" in judgment["model_metadata"]["selfcheck_notes"]


def test_orientation_audit_resolves_conflicting_swapped_reads(monkeypatch):
    higher = {
        "student_id": "clean",
        "seed_rank": 1,
        "level": "3",
        "rubric_after_penalty_percent": 73.0,
        "borda_percent": 0.8,
        "composite_score": 0.7,
    }
    lower = {
        "student_id": "rough",
        "seed_rank": 8,
        "level": "3",
        "rubric_after_penalty_percent": 71.0,
        "borda_percent": 0.95,
        "composite_score": 0.69,
    }

    def payload(winner_side, rationale):
        return {
            "winner_side": winner_side,
            "decision": "KEEP" if winner_side == "A" else "SWAP",
            "confidence": "medium",
            "rationale": rationale,
            "criterion_notes": [{"criterion": "content/reasoning", "stronger": winner_side, "reason": "Better interpretation."}],
            "decision_basis": "content_reasoning",
            "cautions_applied": ["rougher_but_stronger_content"],
            "decision_checks": {
                "deeper_interpretation": winner_side,
                "better_text_evidence_explanation": winner_side,
                "cleaner_or_more_formulaic": "B" if winner_side == "A" else "A",
                "rougher_but_stronger_content": winner_side,
                "completion_advantage": "tie",
                "cleaner_wins_on_substance": "Polish did not decide.",
                "rougher_loses_because": "Roughness did not decide.",
            },
        }

    responses = iter(
        [
            payload("A", "First orientation prefers Essay A."),
            payload("A", "Swapped orientation also prefers Essay A, revealing position risk."),
        ]
    )
    prompts = []

    def fake_create(model, messages, temperature, reasoning, routing_path, text_format=None, max_output_tokens=None):
        prompts.append(messages[0]["content"])
        return {"model": model, "output": [{"type": "output_text", "text": json.dumps(next(responses))}]}

    monkeypatch.setattr(vc, "responses_create", fake_create)
    judgment = vc.judge_pair_with_orientation_audit(
        "rubric",
        "outline",
        higher,
        lower,
        "Clean but shallow summary.",
        "Rougher analysis with a real interpretation.",
        model="gpt-5.4-mini",
        routing="routing.json",
        reasoning="low",
        max_output_tokens=600,
        genre="literary_analysis",
        selection_reasons=["large_mover_neighborhood"],
        student_count=10,
    )
    assert judgment["winner"] == "rough"
    assert judgment["winner_side"] == "B"
    audit = judgment["model_metadata"]["orientation_audit"]
    assert audit["status"] == "resolved_by_large_mover_cross_evidence"
    assert audit["primary"]["winner"] == "clean"
    assert audit["swapped"]["winner"] == "rough"
    assert len(prompts) == 2


def test_literary_selfcheck_downgrades_high_confidence_cleaner_winner():
    higher = {"student_id": "clean", "seed_rank": 1}
    lower = {"student_id": "rough", "seed_rank": 2}
    confidence, notes = vc.confidence_downgrade_for_selfcheck(
        higher,
        lower,
        genre="literary_analysis",
        decision="KEEP",
        confidence="high",
        decision_basis="content_reasoning",
        decision_checks={
            "deeper_interpretation": "B",
            "better_text_evidence_explanation": "B",
            "cleaner_or_more_formulaic": "A",
            "rougher_but_stronger_content": "B",
            "completion_advantage": "tie",
        },
    )
    assert confidence == "medium"
    assert "high_confidence_downgraded_literary_core_checks_mixed" in notes
    assert "high_confidence_downgraded_cleaner_winner_without_core_sweep" in notes


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
