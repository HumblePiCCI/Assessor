import csv
import json
import scripts.global_rerank as gr


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_judgments(path, checks):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": "2026-03-29T00:00:00+00:00", "checks": checks}
    path.write_text(json.dumps(payload), encoding="utf-8")


def run_rerank(tmp_path, seed_rows, checks, config="{}", local_prior=None, pipeline_manifest=None):
    scores = tmp_path / "consensus.csv"
    judgments = tmp_path / "checks.json"
    cfg = tmp_path / "config.json"
    local_prior_path = tmp_path / "local_teacher_prior.json"
    final_order = tmp_path / "final_order.csv"
    matrix = tmp_path / "pairwise_matrix.json"
    score_csv = tmp_path / "rerank_scores.csv"
    report = tmp_path / "consistency_report.json"
    legacy = tmp_path / "consistency_adjusted.csv"
    write_csv(scores, seed_rows)
    write_judgments(judgments, checks)
    cfg.write_text(config, encoding="utf-8")
    local_prior_path.write_text(json.dumps(local_prior or {}), encoding="utf-8")
    if pipeline_manifest is not None:
        (tmp_path / "pipeline_manifest.json").write_text(json.dumps(pipeline_manifest), encoding="utf-8")
    result = gr.run_global_rerank(
        scores_path=scores,
        judgments_path=judgments,
        config_path=cfg,
        local_prior_path=local_prior_path,
        final_order_path=final_order,
        matrix_output_path=matrix,
        score_output_path=score_csv,
        report_output_path=report,
        legacy_output_path=legacy,
        iterations=300,
        learning_rate=0.18,
        regularization=0.75,
        low_confidence_max_displacement=1,
        medium_confidence_max_displacement=3,
        high_confidence_max_displacement=999999,
        max_cross_level_gap=1,
        max_cross_rubric_gap=2.0,
        min_crossing_margin=1.5,
        hard_evidence_margin=1.5,
    )
    return result, final_order, matrix, score_csv, report, legacy


def test_global_rerank_known_optimum_order(tmp_path):
    seed_rows = [
        {"student_id": "s1", "seed_rank": "1", "consensus_rank": "1", "adjusted_level": "4", "rubric_after_penalty_percent": "84", "composite_score": "0.82"},
        {"student_id": "s2", "seed_rank": "2", "consensus_rank": "2", "adjusted_level": "4", "rubric_after_penalty_percent": "83", "composite_score": "0.80"},
        {"student_id": "s3", "seed_rank": "3", "consensus_rank": "3", "adjusted_level": "4", "rubric_after_penalty_percent": "85", "composite_score": "0.79"},
    ]
    checks = [
        {"pair": ["s1", "s2"], "decision": "KEEP", "confidence": "medium", "rationale": "s1 edges s2"},
        {"pair": ["s1", "s3"], "decision": "SWAP", "confidence": "high", "rationale": "s3 is stronger than s1"},
        {"pair": ["s2", "s3"], "decision": "SWAP", "confidence": "high", "rationale": "s3 is stronger than s2"},
    ]
    _result, final_order, _matrix, _score_csv, report, legacy = run_rerank(tmp_path, seed_rows, checks)
    rows = list(csv.DictReader(final_order.open("r", encoding="utf-8")))
    assert [row["student_id"] for row in rows] == ["s3", "s1", "s2"]
    assert legacy.exists()
    report_payload = json.loads(report.read_text(encoding="utf-8"))
    assert report_payload["summary"]["pairwise_agreement_with_final_order"] == 1.0
    assert "pairwise_conflict_density" in report_payload["summary"]
    assert "boundary_disagreement_concentration" in report_payload["summary"]


def test_global_rerank_preserves_pairwise_criterion_audit_fields(tmp_path):
    seed_rows = [
        {"student_id": "s1", "seed_rank": "1", "consensus_rank": "1", "adjusted_level": "3", "rubric_after_penalty_percent": "72", "composite_score": "0.72"},
        {"student_id": "s2", "seed_rank": "2", "consensus_rank": "2", "adjusted_level": "3", "rubric_after_penalty_percent": "71", "composite_score": "0.71"},
    ]
    checks = [
        {
            "pair": ["s1", "s2"],
            "winner_side": "B",
            "decision": "SWAP",
            "confidence": "high",
            "rationale": "s2 has stronger interpretation despite rougher mechanics.",
            "criterion_notes": [{"criterion": "content/reasoning", "stronger": "B", "reason": "More developed analysis."}],
            "decision_basis": "content_reasoning",
            "cautions_applied": ["rougher_but_stronger_content"],
            "decision_checks": {
                "deeper_interpretation": "B",
                "better_text_evidence_explanation": "B",
                "cleaner_or_more_formulaic": "A",
            },
        }
    ]
    _result, _final_order, matrix_path, *_ = run_rerank(tmp_path, seed_rows, checks)
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    judgment = matrix["comparisons"][0]["judgments"][0]
    assert judgment["criterion_notes"][0]["criterion"] == "content/reasoning"
    assert judgment["decision_basis"] == "content_reasoning"
    assert judgment["cautions_applied"] == ["rougher_but_stronger_content"]
    assert judgment["winner_side"] == "B"
    assert judgment["decision_checks"]["deeper_interpretation"] == "B"


def test_global_rerank_prefers_winner_side_over_conflicting_decision(tmp_path):
    seed_rows = [
        {"student_id": "s1", "seed_rank": "1", "consensus_rank": "1", "adjusted_level": "3", "rubric_after_penalty_percent": "72", "composite_score": "0.72"},
        {"student_id": "s2", "seed_rank": "2", "consensus_rank": "2", "adjusted_level": "3", "rubric_after_penalty_percent": "71", "composite_score": "0.71"},
    ]
    checks = [
        {
            "pair": ["s1", "s2"],
            "winner_side": "B",
            "decision": "KEEP",
            "confidence": "high",
            "rationale": "s2 is stronger even though a legacy field says keep.",
        }
    ]
    _result, final_order, matrix_path, *_ = run_rerank(tmp_path, seed_rows, checks)
    rows = list(csv.DictReader(final_order.open("r", encoding="utf-8")))
    assert [row["student_id"] for row in rows] == ["s2", "s1"]
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    judgment = matrix["comparisons"][0]["judgments"][0]
    assert judgment["winner_side"] == "B"
    assert judgment["decision"] == "SWAP"
    assert judgment["winner"] == "s2"


def test_global_rerank_is_deterministic_under_contradictory_evidence(tmp_path):
    seed_rows = [
        {"student_id": "a", "seed_rank": "1", "consensus_rank": "1", "adjusted_level": "4", "rubric_after_penalty_percent": "84", "composite_score": "0.84"},
        {"student_id": "b", "seed_rank": "2", "consensus_rank": "2", "adjusted_level": "4", "rubric_after_penalty_percent": "83", "composite_score": "0.83"},
        {"student_id": "c", "seed_rank": "3", "consensus_rank": "3", "adjusted_level": "4", "rubric_after_penalty_percent": "82", "composite_score": "0.82"},
    ]
    checks = [
        {"pair": ["a", "b"], "decision": "KEEP", "confidence": "high", "rationale": "a over b"},
        {"pair": ["b", "c"], "decision": "KEEP", "confidence": "high", "rationale": "b over c"},
        {"pair": ["a", "c"], "decision": "SWAP", "confidence": "high", "rationale": "c over a"},
    ]
    result_one, *_ = run_rerank(tmp_path / "run1", seed_rows, checks)
    result_two, *_ = run_rerank(tmp_path / "run2", seed_rows, checks)
    assert [row["student_id"] for row in result_one["final_rows"]] == [row["student_id"] for row in result_two["final_rows"]]
    assert result_one["report"]["summary"] == result_two["report"]["summary"]
    diagnostics = result_one["report"]["direct_edge_diagnostics"]
    assert diagnostics["direct_edge_violation_count"] >= 1
    assert result_one["report"]["summary"]["high_confidence_direct_edge_violations"] >= 1
    assert diagnostics["violations"][0]["confidence"] == "high"


def test_global_rerank_preserves_level_lock_without_justified_crossing(tmp_path):
    seed_rows = [
        {"student_id": "s1", "seed_rank": "1", "consensus_rank": "1", "adjusted_level": "3", "rubric_after_penalty_percent": "79", "composite_score": "0.90"},
        {"student_id": "s2", "seed_rank": "2", "consensus_rank": "2", "adjusted_level": "4", "rubric_after_penalty_percent": "86", "composite_score": "0.70"},
    ]
    checks = [
        {"pair": ["s1", "s2"], "decision": "KEEP", "confidence": "low", "rationale": "weak keep"},
    ]
    _result, final_order, *_ = run_rerank(tmp_path, seed_rows, checks)
    rows = list(csv.DictReader(final_order.open("r", encoding="utf-8")))
    assert [row["student_id"] for row in rows] == ["s2", "s1"]


def test_global_rerank_allows_direct_high_confidence_override_for_adjacent_levels(tmp_path):
    seed_rows = [
        {"student_id": "s1", "seed_rank": "1", "consensus_rank": "1", "adjusted_level": "3", "rubric_after_penalty_percent": "71", "composite_score": "0.78"},
        {"student_id": "s2", "seed_rank": "2", "consensus_rank": "2", "adjusted_level": "2", "rubric_after_penalty_percent": "67", "composite_score": "0.74"},
    ]
    checks = [
        {"pair": ["s1", "s2"], "decision": "SWAP", "confidence": "high", "rationale": "s2 is clearly stronger on interpretation despite the lower seed."},
    ]
    result, final_order, _matrix, _score_csv, report, _legacy = run_rerank(tmp_path, seed_rows, checks)
    rows = list(csv.DictReader(final_order.open("r", encoding="utf-8")))
    assert [row["student_id"] for row in rows] == ["s2", "s1"]
    report_payload = json.loads(report.read_text(encoding="utf-8"))
    assert report_payload["constraints"]["overridden_crossings"]


def test_global_rerank_prioritizes_strong_pairwise_edges_before_generic_level_locks(tmp_path):
    seed_rows = [
        {"student_id": "s1", "seed_rank": "1", "consensus_rank": "1", "adjusted_level": "3", "rubric_after_penalty_percent": "74", "composite_score": "0.80"},
        {"student_id": "s2", "seed_rank": "2", "consensus_rank": "2", "adjusted_level": "3", "rubric_after_penalty_percent": "73", "composite_score": "0.79"},
        {"student_id": "s3", "seed_rank": "3", "consensus_rank": "3", "adjusted_level": "2", "rubric_after_penalty_percent": "68", "composite_score": "0.76"},
    ]
    checks = [
        {"pair": ["s1", "s3"], "decision": "SWAP", "confidence": "high", "rationale": "s3 interprets the text better."},
        {"pair": ["s2", "s3"], "decision": "SWAP", "confidence": "high", "rationale": "s3 interprets the text better."},
    ]
    result, final_order, _matrix, _score_csv, report, _legacy = run_rerank(tmp_path, seed_rows, checks)
    rows = list(csv.DictReader(final_order.open("r", encoding="utf-8")))
    assert [row["student_id"] for row in rows] == ["s3", "s1", "s2"]
    report_payload = json.loads(report.read_text(encoding="utf-8"))
    added_kinds = [item["kind"] for item in report_payload["constraints"]["added_edges"]]
    assert "strong_pairwise_evidence" in added_kinds


def test_global_rerank_caps_low_confidence_displacement(tmp_path):
    seed_rows = [
        {"student_id": "s1", "seed_rank": "1", "consensus_rank": "1", "adjusted_level": "4", "rubric_after_penalty_percent": "89", "composite_score": "0.95"},
        {"student_id": "s2", "seed_rank": "2", "consensus_rank": "2", "adjusted_level": "4", "rubric_after_penalty_percent": "88", "composite_score": "0.90"},
        {"student_id": "s3", "seed_rank": "3", "consensus_rank": "3", "adjusted_level": "4", "rubric_after_penalty_percent": "87", "composite_score": "0.85"},
        {"student_id": "s4", "seed_rank": "4", "consensus_rank": "4", "adjusted_level": "4", "rubric_after_penalty_percent": "86", "composite_score": "0.80"},
    ]
    checks = [
        {"pair": ["s1", "s4"], "decision": "SWAP", "confidence": "low", "rationale": "single low-confidence upset"},
    ]
    result, *_ = run_rerank(tmp_path, seed_rows, checks)
    row = next(item for item in result["final_rows"] if item["student_id"] == "s4")
    assert abs(int(row["rerank_displacement"])) <= int(row["rerank_displacement_cap"])


def test_global_rerank_allows_large_downward_move_for_strong_opposition_outlier(tmp_path):
    seed_rows = [
        {"student_id": "s1", "seed_rank": "1", "consensus_rank": "1", "adjusted_level": "3", "rubric_after_penalty_percent": "74", "composite_score": "0.74", "borda_percent": "0.05"},
        {"student_id": "s2", "seed_rank": "2", "consensus_rank": "2", "adjusted_level": "3", "rubric_after_penalty_percent": "73", "composite_score": "0.73", "borda_percent": "0.90"},
        {"student_id": "s3", "seed_rank": "3", "consensus_rank": "3", "adjusted_level": "3", "rubric_after_penalty_percent": "72", "composite_score": "0.72", "borda_percent": "0.88"},
        {"student_id": "s4", "seed_rank": "4", "consensus_rank": "4", "adjusted_level": "3", "rubric_after_penalty_percent": "71", "composite_score": "0.71", "borda_percent": "0.86"},
        {"student_id": "s5", "seed_rank": "5", "consensus_rank": "5", "adjusted_level": "3", "rubric_after_penalty_percent": "70", "composite_score": "0.70", "borda_percent": "0.84"},
        {"student_id": "s6", "seed_rank": "6", "consensus_rank": "6", "adjusted_level": "3", "rubric_after_penalty_percent": "69", "composite_score": "0.69", "borda_percent": "0.82"},
        {"student_id": "s7", "seed_rank": "7", "consensus_rank": "7", "adjusted_level": "3", "rubric_after_penalty_percent": "68", "composite_score": "0.68", "borda_percent": "0.80"},
    ]
    checks = [
        {"pair": ["s1", "s2"], "decision": "SWAP", "confidence": "high", "rationale": "s1 is weaker."},
        {"pair": ["s1", "s3"], "decision": "SWAP", "confidence": "high", "rationale": "s1 is weaker."},
        {"pair": ["s1", "s4"], "decision": "SWAP", "confidence": "high", "rationale": "s1 is weaker."},
        {"pair": ["s1", "s5"], "decision": "SWAP", "confidence": "high", "rationale": "s1 is weaker."},
        {"pair": ["s1", "s6"], "decision": "SWAP", "confidence": "high", "rationale": "s1 is weaker."},
        {"pair": ["s1", "s7"], "decision": "SWAP", "confidence": "high", "rationale": "s1 is weaker."},
    ]
    result, *_ = run_rerank(tmp_path, seed_rows, checks)
    row = next(item for item in result["final_rows"] if item["student_id"] == "s1")
    assert int(row["final_rank"]) >= 6
    assert row["rerank_displacement_cap_label"] == "high_opposition"
    assert int(row["rerank_worst_rank"]) >= 6


def test_global_rerank_local_teacher_prior_is_gated_on_clear_cases(tmp_path):
    seed_rows = [
        {"student_id": "s1", "seed_rank": "1", "consensus_rank": "1", "adjusted_level": "4", "rubric_after_penalty_percent": "92", "composite_score": "0.95"},
        {"student_id": "s2", "seed_rank": "2", "consensus_rank": "2", "adjusted_level": "4", "rubric_after_penalty_percent": "79.9", "composite_score": "0.70"},
    ]
    local_prior = {
        "active": True,
        "run_scope": {},
        "support": {"support_scalar": 1.0, "freshness_scalar": 1.0},
        "weights": {"boundary_level_bias": 0.08, "seed_order_bias": 0.06, "max_adjustment": 0.08, "boundary_margin": 1.5},
    }
    result, *_ = run_rerank(tmp_path, seed_rows, [], local_prior=local_prior)
    assert [row["student_id"] for row in result["final_rows"]] == ["s1", "s2"]
    assert next(row for row in result["final_rows"] if row["student_id"] == "s2")["teacher_preference_adjustment"] > 0


def test_global_rerank_local_teacher_prior_surfaces_bounded_adjustments_on_ambiguous_boundary_rows(tmp_path):
    seed_rows = [
        {"student_id": "s1", "seed_rank": "1", "consensus_rank": "1", "adjusted_level": "4", "rubric_after_penalty_percent": "80.1", "composite_score": "0.800"},
        {"student_id": "s2", "seed_rank": "2", "consensus_rank": "2", "adjusted_level": "4", "rubric_after_penalty_percent": "79.9", "composite_score": "0.799"},
    ]
    local_prior = {
        "active": True,
        "run_scope": {},
        "support": {"support_scalar": 1.0, "freshness_scalar": 1.0},
        "weights": {"boundary_level_bias": 0.08, "seed_order_bias": 0.0, "max_adjustment": 0.08, "boundary_margin": 1.5},
    }
    result, *_ = run_rerank(tmp_path, seed_rows, [], local_prior=local_prior)
    rows = {row["student_id"]: row for row in result["final_rows"]}
    assert rows["s1"]["teacher_preference_adjustment"] < 0
    assert rows["s2"]["teacher_preference_adjustment"] > 0
    assert all(abs(int(row["rerank_displacement"])) <= 1 for row in result["final_rows"])


def test_global_rerank_suppresses_local_prior_during_anchor_calibration(tmp_path, monkeypatch):
    seed_rows = [
        {"student_id": "s1", "seed_rank": "1", "consensus_rank": "1", "adjusted_level": "4", "rubric_after_penalty_percent": "80.1", "composite_score": "0.800"},
        {"student_id": "s2", "seed_rank": "2", "consensus_rank": "2", "adjusted_level": "4", "rubric_after_penalty_percent": "79.9", "composite_score": "0.799"},
    ]
    local_prior = {
        "active": True,
        "run_scope": {},
        "support": {"support_scalar": 1.0, "freshness_scalar": 1.0},
        "weights": {"boundary_level_bias": 0.08, "seed_order_bias": 0.0, "max_adjustment": 0.08, "boundary_margin": 1.5},
    }
    monkeypatch.setenv("ANCHOR_CALIBRATION_ACTIVE", "1")
    result, *_ = run_rerank(tmp_path, seed_rows, [], local_prior=local_prior)
    rows = {row["student_id"]: row for row in result["final_rows"]}
    assert rows["s1"]["teacher_preference_adjustment"] == 0.0
    assert rows["s2"]["teacher_preference_adjustment"] == 0.0
    assert result["report"]["teacher_prior"]["suppressed_by_anchor_calibration"] is True


def test_global_rerank_keeps_draft_completion_floor_rows_from_moving_up(tmp_path):
    seed_rows = [
        {
            "student_id": "s1",
            "seed_rank": "1",
            "consensus_rank": "1",
            "adjusted_level": "2",
            "rubric_after_penalty_percent": "60",
            "composite_score": "0.60",
            "draft_completion_floor_applied": "false",
            "flags": "",
        },
        {
            "student_id": "s2",
            "seed_rank": "2",
            "consensus_rank": "2",
            "adjusted_level": "1",
            "rubric_after_penalty_percent": "35",
            "composite_score": "0.35",
            "draft_completion_floor_applied": "true",
            "flags": "draft_completion_penalty;draft_completion_floor",
        },
        {
            "student_id": "s3",
            "seed_rank": "3",
            "consensus_rank": "3",
            "adjusted_level": "1",
            "rubric_after_penalty_percent": "40",
            "composite_score": "0.40",
            "draft_completion_floor_applied": "false",
            "flags": "",
        },
    ]
    checks = [
        {"pair": ["s2", "s3"], "decision": "KEEP", "confidence": "high", "rationale": "Noisy pairwise check prefers unfinished draft."},
    ]
    result, *_ = run_rerank(tmp_path, seed_rows, checks)
    rows = {row["student_id"]: row for row in result["final_rows"]}
    assert rows["s2"]["final_rank"] == 3
    assert rows["s2"]["rerank_notes"].find("draft_completion_floor_lock") >= 0


def test_global_rerank_caps_severe_collapse_rescue_rows(tmp_path):
    seed_rows = [
        {
            "student_id": "s1",
            "seed_rank": "1",
            "consensus_rank": "1",
            "adjusted_level": "3",
            "rubric_after_penalty_percent": "76",
            "pre_boundary_calibration_percent": "76",
            "composite_score": "0.90",
            "flags": "",
        },
        {
            "student_id": "s2",
            "seed_rank": "2",
            "consensus_rank": "2",
            "adjusted_level": "3",
            "rubric_after_penalty_percent": "74",
            "pre_boundary_calibration_percent": "74",
            "composite_score": "0.86",
            "flags": "",
        },
        {
            "student_id": "s3",
            "seed_rank": "3",
            "consensus_rank": "3",
            "adjusted_level": "3",
            "rubric_after_penalty_percent": "73",
            "pre_boundary_calibration_percent": "73",
            "composite_score": "0.84",
            "flags": "",
        },
        {
            "student_id": "s4",
            "seed_rank": "6",
            "consensus_rank": "6",
            "adjusted_level": "3",
            "rubric_after_penalty_percent": "70",
            "pre_boundary_calibration_percent": "62.5",
            "composite_score": "0.80",
            "flags": "boundary_calibration;severe_collapse_rescue",
        },
        {
            "student_id": "s5",
            "seed_rank": "4",
            "consensus_rank": "4",
            "adjusted_level": "3",
            "rubric_after_penalty_percent": "72",
            "pre_boundary_calibration_percent": "72",
            "composite_score": "0.82",
            "flags": "",
        },
        {
            "student_id": "s6",
            "seed_rank": "5",
            "consensus_rank": "5",
            "adjusted_level": "3",
            "rubric_after_penalty_percent": "71",
            "pre_boundary_calibration_percent": "71",
            "composite_score": "0.81",
            "flags": "",
        },
    ]
    checks = [
        {"pair": ["s1", "s4"], "decision": "SWAP", "confidence": "high", "rationale": "rescued essay seems stronger"},
        {"pair": ["s2", "s4"], "decision": "SWAP", "confidence": "high", "rationale": "rescued essay seems stronger"},
        {"pair": ["s3", "s4"], "decision": "SWAP", "confidence": "high", "rationale": "rescued essay seems stronger"},
    ]
    result, *_ = run_rerank(tmp_path, seed_rows, checks)
    rows = {row["student_id"]: row for row in result["final_rows"]}
    assert rows["s4"]["final_rank"] >= 4
    assert "severe_collapse_rescue_cap" in rows["s4"]["rerank_notes"]
