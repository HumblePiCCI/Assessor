import csv
import json

import scripts.global_rerank as gr


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def run_rerank(tmp_path, seed_rows, checks, *, cohort_confidence=None, seed_trust_mode="adaptive"):
    scores = tmp_path / "consensus.csv"
    judgments = tmp_path / "checks.json"
    cfg = tmp_path / "config.json"
    write_csv(scores, seed_rows)
    judgments.write_text(json.dumps({"checks": checks}), encoding="utf-8")
    cfg.write_text("{}", encoding="utf-8")
    (tmp_path / "local_teacher_prior.json").write_text("{}", encoding="utf-8")
    cohort_path = None
    if cohort_confidence is not None:
        cohort_path = tmp_path / "cohort_confidence.json"
        cohort_path.write_text(json.dumps(cohort_confidence), encoding="utf-8")
    result = gr.run_global_rerank(
        scores_path=scores,
        judgments_path=judgments,
        config_path=cfg,
        local_prior_path=tmp_path / "local_teacher_prior.json",
        final_order_path=tmp_path / "final_order.csv",
        matrix_output_path=tmp_path / "pairwise_matrix.json",
        score_output_path=tmp_path / "rerank_scores.csv",
        report_output_path=tmp_path / "consistency_report.json",
        legacy_output_path=tmp_path / "consistency_adjusted.csv",
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
        cohort_confidence_path=cohort_path,
        seed_trust_mode=seed_trust_mode,
    )
    report = json.loads((tmp_path / "consistency_report.json").read_text(encoding="utf-8"))
    ranks = {row["student_id"]: int(row["final_rank"]) for row in result["final_rows"]}
    return result, report, ranks


def unvalidated_cohort():
    return {
        "decision_inputs": {
            "calibration_type": "synthetic",
            "scope_familiarity_label": "novel",
            "mean_assessor_sd": 1.6,
        }
    }


def calibrated_cohort():
    return {
        "decision_inputs": {
            "calibration_type": "scoped",
            "scope_familiarity_label": "familiar",
            "mean_assessor_sd": 0.8,
        }
    }


def seed_rows_two_bands():
    return [
        {"student_id": "s1", "seed_rank": "1", "consensus_rank": "1", "adjusted_level": "3", "rubric_after_penalty_percent": "75", "composite_score": "0.82"},
        {"student_id": "s2", "seed_rank": "2", "consensus_rank": "2", "adjusted_level": "3", "rubric_after_penalty_percent": "74", "composite_score": "0.80"},
        {"student_id": "s3", "seed_rank": "3", "consensus_rank": "3", "adjusted_level": "2", "rubric_after_penalty_percent": "73", "composite_score": "0.78"},
        {"student_id": "s4", "seed_rank": "4", "consensus_rank": "4", "adjusted_level": "2", "rubric_after_penalty_percent": "70", "composite_score": "0.74"},
    ]


def swap_check(pair, rationale="Lower-seeded essay shows stronger sustained interpretation.", confidence="high", source=None, metadata=None):
    check = {"pair": list(pair), "decision": "SWAP", "confidence": confidence, "rationale": rationale}
    md = dict(metadata or {})
    if source:
        md["adjudication_source"] = source
    if md:
        check["model_metadata"] = md
    return check


def test_seed_trust_reported_and_full_for_calibrated_scope(tmp_path):
    _, report, _ = run_rerank(tmp_path, seed_rows_two_bands(), [], cohort_confidence=calibrated_cohort())
    trust = report["seed_trust"]
    assert trust["seed_reliability"] == 1.0
    assert trust["seeds_unvalidated"] is False
    assert trust["effective_regularization"] == 0.75


def test_seed_trust_drops_for_synthetic_novel_scope(tmp_path):
    _, report, _ = run_rerank(tmp_path, seed_rows_two_bands(), [], cohort_confidence=unvalidated_cohort())
    trust = report["seed_trust"]
    assert trust["seeds_unvalidated"] is True
    assert trust["seed_reliability"] < 0.5
    assert trust["effective_regularization"] < 0.75
    assert trust["effective_medium_cap"] > 3


def test_fixed_mode_keeps_legacy_behavior(tmp_path):
    _, report, _ = run_rerank(
        tmp_path, seed_rows_two_bands(), [], cohort_confidence=unvalidated_cohort(), seed_trust_mode="fixed"
    )
    assert report["seed_trust"] == {"mode": "fixed", "seed_reliability": 1.0,
                                    "effective_regularization": 0.75,
                                    "effective_min_crossing_margin": 1.5,
                                    "effective_low_cap": 1,
                                    "effective_medium_cap": 3,
                                    "cap_scale": 1.0}


def test_underbanded_paper_crosses_with_adjudicated_evidence_on_unvalidated_scope(tmp_path):
    # Ghost P0-1 regression shape: pass-1 underbanded s3 one level below s1/s2,
    # but adjudicated direct evidence says s3 beats both. With unvalidated
    # seeds, the band gap alone must not hold s3 down.
    checks = [
        swap_check(["s1", "s3"], source="escalated_adjudication"),
        swap_check(["s2", "s3"], source="escalated_adjudication"),
    ]
    _, report, ranks = run_rerank(tmp_path, seed_rows_two_bands(), checks, cohort_confidence=unvalidated_cohort())
    assert ranks["s3"] < ranks["s1"]
    assert ranks["s3"] < ranks["s2"]
    override_or_waiver = report["constraints"]["overridden_crossings"] or [
        edge for edge in report["constraints"]["dropped_edges"] if edge["reason"] == "level_lock_waived_low_seed_trust"
    ]
    assert override_or_waiver


def test_calibrated_scope_keeps_level_locks_without_evidence(tmp_path):
    # Same shape but calibrated scope and no judgments: band order holds.
    _, report, ranks = run_rerank(tmp_path, seed_rows_two_bands(), [], cohort_confidence=calibrated_cohort())
    assert ranks["s3"] > ranks["s1"] and ranks["s3"] > ranks["s2"]
    assert not [e for e in report["constraints"]["dropped_edges"] if "waived" in e.get("reason", "")]


def seed_rows_override_gap():
    # Rubric gap above max_cross_rubric_gap so the crossing is blocked and
    # only the direct-pairwise override path can lift s3.
    return [
        {"student_id": "s1", "seed_rank": "1", "consensus_rank": "1", "adjusted_level": "3", "rubric_after_penalty_percent": "75", "composite_score": "0.82"},
        {"student_id": "s2", "seed_rank": "2", "consensus_rank": "2", "adjusted_level": "3", "rubric_after_penalty_percent": "74", "composite_score": "0.80"},
        {"student_id": "s3", "seed_rank": "3", "consensus_rank": "3", "adjusted_level": "2", "rubric_after_penalty_percent": "70", "composite_score": "0.78"},
        {"student_id": "s4", "seed_rank": "4", "consensus_rank": "4", "adjusted_level": "2", "rubric_after_penalty_percent": "66", "composite_score": "0.74"},
    ]


def test_override_blocked_for_flagged_incomplete_paper(tmp_path):
    rows = seed_rows_override_gap()
    for row in rows:
        row["flags"] = ""
    rows[2]["flags"] = "incomplete; scaffold_remnant"
    checks = [
        swap_check(["s1", "s3"], source="escalated_adjudication"),
        swap_check(["s2", "s3"], source="escalated_adjudication"),
    ]
    _, report, ranks = run_rerank(tmp_path, rows, checks, cohort_confidence=calibrated_cohort())
    # Calibrated scope: no waivers; the flagged paper may not override the lock.
    assert ranks["s3"] > ranks["s1"]
    blocked = [c for c in report["constraints"]["blocked_crossings"] if c.get("override_blocked_by_guard_flags")]
    assert blocked


def test_override_audit_fields_present(tmp_path):
    checks = [
        swap_check(["s1", "s3"], source="escalated_adjudication"),
        swap_check(["s2", "s3"], source="escalated_adjudication"),
    ]
    _, report, _ = run_rerank(tmp_path, seed_rows_override_gap(), checks, cohort_confidence=calibrated_cohort())
    overrides = report["constraints"]["overridden_crossings"]
    assert overrides
    sample = overrides[0]
    for field in ("override_reason", "direct_pairwise_margin", "net_support_margin", "level_gap", "rubric_gap"):
        assert field in sample


def test_tainted_judgment_downweighted_and_never_hard(tmp_path):
    tainted = swap_check(
        ["s1", "s2"],
        metadata={"repair_used": True, "repair_reasons": ["invalid_json_response"]},
    )
    clean_pairs = [swap_check(["s3", "s4"]), swap_check(["s3", "s4"], rationale="Second read agrees.")]
    result, report, _ = run_rerank(
        tmp_path, seed_rows_two_bands(), [tainted] + clean_pairs, cohort_confidence=calibrated_cohort()
    )
    summary = report["summary"]
    assert summary["tainted_judgment_count"] == 1
    assert summary["pairwise_repair_tainted_rate"] > 0
    hard_edges = [e for e in report["constraints"]["added_edges"] if e["kind"] == "strong_pairwise_evidence"]
    assert all({e["src"], e["dst"]} != {"s1", "s2"} for e in hard_edges)
    # The clean corroborated pair still forms a hard edge.
    assert any({e["src"], e["dst"]} == {"s3", "s4"} for e in hard_edges)


def test_tainted_committee_edge_not_protected(tmp_path):
    tainted_committee = {
        "pair": ["s1", "s2"],
        "decision": "SWAP",
        "confidence": "high",
        "rationale": "Prior response was not valid JSON.",
        "model_metadata": {"adjudication_source": "committee_edge", "repair_used": True},
    }
    _, report, _ = run_rerank(tmp_path, seed_rows_two_bands(), [tainted_committee], cohort_confidence=calibrated_cohort())
    committee_edges = [e for e in report["constraints"]["added_edges"] if e["kind"] == "committee_direct_edge"]
    assert committee_edges == []


def test_single_uncorroborated_read_never_hard_edge(tmp_path):
    _, report, _ = run_rerank(tmp_path, seed_rows_two_bands(), [swap_check(["s3", "s4"])], cohort_confidence=calibrated_cohort())
    hard_edges = [e for e in report["constraints"]["added_edges"] if e["kind"] == "strong_pairwise_evidence"]
    assert hard_edges == []
    dropped = [e for e in report["constraints"]["dropped_edges"] if e.get("reason") == "single_uncorroborated_read"]
    assert dropped


def test_seed_anchor_waivers_only_on_unvalidated_scopes(tmp_path):
    # Heavy contradicting evidence on a calibrated scope must not waive
    # seed-anchored protections.
    checks = [
        swap_check(["s1", "s4"]),
        swap_check(["s1", "s4"], rationale="Second read agrees."),
    ]
    _, report, _ = run_rerank(tmp_path, seed_rows_two_bands(), checks, cohort_confidence=calibrated_cohort())
    assert not [e for e in report["constraints"]["dropped_edges"] if e.get("reason") == "seed_anchor_waived_low_seed_trust"]


def test_literary_pass1_contract_guidance_separates_interpretation_from_recall():
    # P0-4: pass-1 prompts must separate plot recall from sustained
    # interpretation and protect rough-but-deep writing.
    import json as _json
    from pathlib import Path as _Path

    from scripts.rubric_criteria import contract_prompt

    criteria = _json.loads((_Path(__file__).resolve().parents[1] / "config" / "rubric_criteria.json").read_text(encoding="utf-8"))
    prompt = contract_prompt(criteria, "literary_analysis")
    assert "SCORING CONTRACT" in prompt
    for marker in ("plot recall", "sustained interpretation", "list of events", "mechanical roughness"):
        assert marker in prompt


def test_argumentative_pass1_contract_guards_against_source_recall():
    # Holdout finding 2026-06-11: fluent source-retelling essays were ranked
    # top while human raters scored them 1/6. Argumentative scoring must
    # separate the writer's own position from source recall.
    import json as _json
    from pathlib import Path as _Path

    from scripts.rubric_criteria import contract_prompt

    criteria = _json.loads((_Path(__file__).resolve().parents[1] / "config" / "rubric_criteria.json").read_text(encoding="utf-8"))
    prompt = contract_prompt(criteria, "argumentative")
    assert "SCORING CONTRACT" in prompt
    for marker in ("own position", "retelling", "lowest bands", "no viable point of view"):
        assert marker in prompt, marker


def test_anchor_judgments_injected_when_calibration_active(tmp_path, monkeypatch):
    rows = seed_rows_two_bands()
    calibration = {
        "active": True,
        "anchor_pairwise_judgments": [
            {"pair": ["s3", "s1"], "decision": "KEEP", "confidence": "high",
             "rationale": "Teacher anchor adjudication.",
             "model_metadata": {"adjudication_source": "committee_edge", "committee_read": "teacher_anchor"}},
            {"pair": ["s3", "s2"], "decision": "KEEP", "confidence": "high",
             "rationale": "Teacher anchor adjudication.",
             "model_metadata": {"adjudication_source": "committee_edge", "committee_read": "teacher_anchor"}},
        ],
    }
    (tmp_path / "cohort_anchor_calibration.json").write_text(json.dumps(calibration), encoding="utf-8")
    monkeypatch.setenv("ANCHOR_CALIBRATION_ACTIVE", "1")
    _, report, ranks = run_rerank(tmp_path, rows, [], cohort_confidence=calibrated_cohort())
    assert report["summary"]["anchor_judgments_injected"] == 2
    # Teacher-adjudicated anchors are protected committee edges: s3 crosses.
    assert ranks["s3"] < ranks["s1"] and ranks["s3"] < ranks["s2"]


def test_no_anchor_injection_without_env(tmp_path, monkeypatch):
    monkeypatch.delenv("ANCHOR_CALIBRATION_ACTIVE", raising=False)
    (tmp_path / "cohort_anchor_calibration.json").write_text(
        json.dumps({"active": True, "anchor_pairwise_judgments": [
            {"pair": ["s3", "s1"], "decision": "KEEP", "confidence": "high", "rationale": "x",
             "model_metadata": {"adjudication_source": "committee_edge"}}]}), encoding="utf-8")
    _, report, ranks = run_rerank(tmp_path, seed_rows_two_bands(), [], cohort_confidence=calibrated_cohort())
    assert report["summary"]["anchor_judgments_injected"] == 0
    assert ranks["s3"] > ranks["s1"]
