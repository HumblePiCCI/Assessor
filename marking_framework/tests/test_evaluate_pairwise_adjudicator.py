import json

from scripts import evaluate_pairwise_adjudicator as epa


def test_pairwise_eval_scores_existing_judgments(tmp_path):
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(
        json.dumps(
            {
                "id": "toy",
                "thresholds": {"min_accuracy": 0.8, "min_critical_accuracy": 1.0, "min_coverage": 1.0},
                "pairs": [
                    {
                        "id": "p1",
                        "pair": ["a", "b"],
                        "winner": "b",
                        "priority": "critical",
                        "tags": ["rougher_stronger_interpretation"],
                        "rationale": "B has stronger reasoning.",
                    },
                    {
                        "id": "p2",
                        "pair": ["b", "c"],
                        "winner": "b",
                        "priority": "standard",
                        "tags": ["top_pack"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    judgments_path = tmp_path / "checks.json"
    judgments_path.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "pair": ["a", "b"],
                        "seed_order": {"higher": "a", "lower": "b"},
                        "decision": "SWAP",
                        "confidence": "high",
                        "decision_basis": "content_reasoning",
                        "cautions_applied": ["rougher_but_stronger_content"],
                    },
                    {
                        "pair": ["b", "c"],
                        "seed_order": {"higher": "b", "lower": "c"},
                        "decision": "SWAP",
                        "confidence": "medium",
                        "decision_basis": "organization",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    gold = epa.load_gold(gold_path)
    outcomes = epa.outcomes_from_judgments(judgments_path)
    report = epa.evaluate_outcomes(gold, gold["pairs"], outcomes)

    assert report["summary"]["accuracy"] == 0.5
    assert report["summary"]["critical_accuracy"] == 1.0
    assert report["summary"]["failures"] == ["accuracy_below_threshold"]
    assert report["misses"][0]["id"] == "p2"


def test_live_pair_eval_uses_anchor_prompt_without_leaking_gold_winner(monkeypatch, tmp_path):
    prompts = []

    def fake_create(model, messages, temperature, reasoning, routing_path, text_format=None, max_output_tokens=None):
        prompts.append(messages[0]["content"])
        payload = {
            "decision": "SWAP",
            "confidence": "high",
            "rationale": "B develops the interpretation more fully.",
            "criterion_notes": [{"criterion": "content/reasoning", "stronger": "B", "reason": "Better explanation."}],
            "decision_basis": "content_reasoning",
            "cautions_applied": ["rougher_but_stronger_content"],
        }
        return {"model": model, "output": [{"type": "output_text", "text": json.dumps(payload)}]}

    monkeypatch.setattr(epa.vc, "responses_create", fake_create)
    anchor_dir = tmp_path / "anchors"
    anchor_dir.mkdir()
    (anchor_dir / "literary_analysis.json").write_text(
        json.dumps(
            {
                "anchors": [
                    {
                        "title": "Rougher interpretation can win",
                        "decision_rule": "Prefer the stronger interpretation over cleaner summary.",
                    }
                ],
                "caution_checks": ["Check for plot summary."],
            }
        ),
        encoding="utf-8",
    )
    pair = {"id": "p1", "pair": ["a", "b"], "winner": "b", "loser": "a", "tags": ["secret_gold_tag"], "rationale": "Do not leak."}
    rows = {"a": epa.minimal_row("a", 1), "b": epa.minimal_row("b", 2)}

    outcomes = epa.live_outcomes(
        [pair],
        rows_by_id=rows,
        texts={"a": "Clean plot summary.", "b": "Rough but thoughtful interpretation."},
        rubric="rubric",
        outline="outline",
        metadata={"assignment_genre": "literary_analysis"},
        genre="literary_analysis",
        model="gpt-5.4-mini",
        routing="routing.json",
        reasoning="low",
        max_output_tokens=600,
        anchor_dir=str(anchor_dir),
        orientation_audit=False,
    )

    prompt = prompts[0]
    assert outcomes[epa.gold_pair_key(pair)]["winner"] == "b"
    assert "Pairwise calibration anchors" in prompt
    assert "Rougher interpretation can win" in prompt
    assert "Gold expects" not in prompt
    assert "Do not leak" not in prompt
    assert "secret_gold_tag" not in prompt


def test_pairwise_eval_prefers_winner_side_over_conflicting_decision():
    outcome = epa.judgment_outcome(
        {
            "pair": ["a", "b"],
            "seed_order": {"higher": "a", "lower": "b"},
            "winner_side": "B",
            "decision": "KEEP",
            "confidence": "high",
        }
    )
    assert outcome["winner"] == "b"
    assert outcome["loser"] == "a"
    assert outcome["winner_side"] == "B"
    assert outcome["decision"] == "SWAP"


def test_pairwise_eval_prefers_escalated_judgment_in_merged_checks(tmp_path):
    judgments_path = tmp_path / "checks.escalated.json"
    judgments_path.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "pair": ["a", "b"],
                        "seed_order": {"higher": "a", "lower": "b"},
                        "decision": "KEEP",
                        "confidence": "high",
                        "model_metadata": {"adjudication_source": "cheap_pairwise", "superseded_by_escalation": True},
                    },
                    {
                        "pair": ["a", "b"],
                        "seed_order": {"higher": "a", "lower": "b"},
                        "winner_side": "B",
                        "decision": "SWAP",
                        "confidence": "medium",
                        "model_metadata": {"adjudication_source": "escalated_adjudication"},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    outcomes = epa.outcomes_from_judgments(judgments_path)
    assert outcomes["a::b"]["winner"] == "b"
    assert outcomes["a::b"]["judgment_count"] == 1
    assert outcomes["a::b"]["strongest_judgment"]["adjudication_source"] == "escalated_adjudication"


def test_aggregate_outcomes_committee_edge_overrides_escalated():
    outcomes = epa.aggregate_judgment_outcomes(
        [
            {
                "pair": ["a", "b"],
                "seed_order": {"higher": "a", "lower": "b"},
                "winner_side": "B",
                "decision": "SWAP",
                "confidence": "high",
                "model_metadata": {"adjudication_source": "escalated_adjudication"},
            },
            {
                "pair": ["a", "b"],
                "seed_order": {"higher": "a", "lower": "b"},
                "winner_side": "A",
                "decision": "KEEP",
                "confidence": "medium",
                "model_metadata": {"adjudication_source": "committee_edge"},
            },
        ],
        source="fixture",
    )
    assert outcomes["a::b"]["winner"] == "a"
    assert outcomes["a::b"]["judgment_count"] == 1
    assert outcomes["a::b"]["strongest_judgment"]["adjudication_source"] == "committee_edge"


def test_pairwise_eval_reads_pairwise_matrix_comparisons(tmp_path):
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_text(
        json.dumps(
            {
                "comparisons": [
                    {
                        "pair": ["a", "b"],
                        "judgments": [
                            {
                                "winner": "b",
                                "loser": "a",
                                "confidence": "high",
                                "decision_basis": "content_reasoning",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    outcomes = epa.outcomes_from_judgments(matrix_path)
    assert outcomes["a::b"]["winner"] == "b"
    assert outcomes["a::b"]["judgment_count"] == 1


def test_default_ghost_gold_file_is_valid():
    gold = epa.load_gold(epa.DEFAULT_GOLD)
    assert gold["id"] == "ghost_grade7_literary_hard_pairs_2026_04_16"
    assert any(pair["priority"] == "critical" for pair in gold["pairs"])
