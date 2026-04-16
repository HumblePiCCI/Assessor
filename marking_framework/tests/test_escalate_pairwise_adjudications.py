import csv
import json

from scripts import escalate_pairwise_adjudications as esc


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_pairwise_escalation_routes_only_unstable_pairs_and_merges(tmp_path, monkeypatch):
    scores = tmp_path / "outputs/consensus_scores.csv"
    write_csv(
        scores,
        [
            {
                "student_id": "s1",
                "seed_rank": "1",
                "consensus_rank": "1",
                "adjusted_level": "3",
                "rubric_after_penalty_percent": "73",
                "borda_percent": "0.35",
                "composite_score": "0.40",
            },
            {
                "student_id": "s2",
                "seed_rank": "2",
                "consensus_rank": "2",
                "adjusted_level": "3",
                "rubric_after_penalty_percent": "72",
                "borda_percent": "0.95",
                "composite_score": "0.92",
            },
        ],
    )
    checks = tmp_path / "outputs/consistency_checks.json"
    checks.write_text(
        json.dumps(
            {
                "generated_at": "2026-04-16T00:00:00+00:00",
                "checks": [
                    {
                        "pair": ["s1", "s2"],
                        "seed_order": {"higher": "s1", "lower": "s2", "higher_rank": 1, "lower_rank": 2},
                        "selection_reasons": ["top_pack"],
                        "decision": "KEEP",
                        "confidence": "medium",
                        "decision_basis": "organization",
                        "cautions_applied": ["formulaic_but_thin"],
                        "rationale": "s1 is cleaner.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    texts = tmp_path / "processing/normalized_text"
    texts.mkdir(parents=True)
    (texts / "s1.txt").write_text("Clean but shallow response.", encoding="utf-8")
    (texts / "s2.txt").write_text("Rougher response with stronger interpretation.", encoding="utf-8")
    rubric = tmp_path / "inputs/rubric.md"
    outline = tmp_path / "inputs/assignment_outline.md"
    metadata = tmp_path / "inputs/class_metadata.json"
    rubric.parent.mkdir(parents=True)
    rubric.write_text("rubric", encoding="utf-8")
    outline.write_text("outline", encoding="utf-8")
    metadata.write_text(json.dumps({"grade_level": 7, "assignment_genre": "literary_analysis"}), encoding="utf-8")
    routing = tmp_path / "config/llm_routing.json"
    routing.parent.mkdir(parents=True)
    routing.write_text(
        json.dumps({"mode": "codex_local", "tasks": {"pairwise_escalator": {"model": "strong", "reasoning": "high", "max_output_tokens": 700}}}),
        encoding="utf-8",
    )
    captured = {}

    def fake_judge(*_args, **kwargs):
        captured["kwargs"] = kwargs
        return {
            "pair": ["s1", "s2"],
            "seed_order": {"higher": "s1", "lower": "s2", "higher_rank": 1, "lower_rank": 2},
            "winner_side": "B",
            "decision": "SWAP",
            "winner": "s2",
            "loser": "s1",
            "confidence": "high",
            "rationale": "s2 has the stronger interpretation.",
            "criterion_notes": [],
            "decision_basis": "content_reasoning",
            "cautions_applied": ["rougher_but_stronger_content"],
            "decision_checks": {
                "deeper_interpretation": "B",
                "better_text_evidence_explanation": "B",
                "cleaner_or_more_formulaic": "A",
                "rougher_but_stronger_content": "B",
                "completion_advantage": "tie",
                "cleaner_wins_on_substance": "",
                "rougher_loses_because": "",
            },
            "model_metadata": {"requested_model": kwargs["model"]},
        }

    monkeypatch.setattr(esc.vc, "judge_pair_with_orientation_audit", fake_judge)
    candidates = tmp_path / "outputs/pairwise_escalation_candidates.json"
    escalations = tmp_path / "outputs/pairwise_escalations.json"
    merged = tmp_path / "outputs/consistency_checks.escalated.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "esc",
            "--checks",
            str(checks),
            "--scores",
            str(scores),
            "--texts",
            str(texts),
            "--rubric",
            str(rubric),
            "--outline",
            str(outline),
            "--class-metadata",
            str(metadata),
            "--routing",
            str(routing),
            "--candidate-output",
            str(candidates),
            "--escalations-output",
            str(escalations),
            "--merged-output",
            str(merged),
        ],
    )

    assert esc.main() == 0
    candidate_payload = json.loads(candidates.read_text(encoding="utf-8"))
    assert candidate_payload["candidate_count"] == 1
    triggers = set(candidate_payload["candidates"][0]["triggers"])
    assert {"top_pack", "low_medium_confidence_literary", "surface_form_winner", "caution_risk", "contradicts_aggregate_support"} <= triggers
    assert captured["kwargs"]["model"] == "strong"
    assert captured["kwargs"]["reasoning"] == "high"
    assert "escalated_adjudication" in captured["kwargs"]["selection_reasons"]
    assert any("Aggregate support" in detail for detail in captured["kwargs"]["selection_details"])

    merged_payload = json.loads(merged.read_text(encoding="utf-8"))
    assert len(merged_payload["checks"]) == 2
    assert merged_payload["checks"][0]["model_metadata"]["superseded_by_escalation"] is True
    assert merged_payload["checks"][0]["model_metadata"]["adjudication_source"] == "cheap_pairwise"
    assert merged_payload["checks"][1]["model_metadata"]["adjudication_source"] == "escalated_adjudication"
    assert merged_payload["pairwise_escalation"]["escalation_count"] == 1
