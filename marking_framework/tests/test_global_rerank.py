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


def run_rerank(tmp_path, seed_rows, checks, config="{}"):
    scores = tmp_path / "consensus.csv"
    judgments = tmp_path / "checks.json"
    cfg = tmp_path / "config.json"
    final_order = tmp_path / "final_order.csv"
    matrix = tmp_path / "pairwise_matrix.json"
    score_csv = tmp_path / "rerank_scores.csv"
    report = tmp_path / "consistency_report.json"
    legacy = tmp_path / "consistency_adjusted.csv"
    write_csv(scores, seed_rows)
    write_judgments(judgments, checks)
    cfg.write_text(config, encoding="utf-8")
    result = gr.run_global_rerank(
        scores_path=scores,
        judgments_path=judgments,
        config_path=cfg,
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
