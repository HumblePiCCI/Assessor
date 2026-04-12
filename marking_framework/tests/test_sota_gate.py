import json

import scripts.sota_gate as sg


def _write_pass1(path, assessor_id, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"assessor_id": assessor_id, "scores": rows}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_benchmark_report(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "modes": {
            "main": {
                "summary": {
                    "runs_attempted": 3,
                    "runs_successful": 3,
                    "exact_level_hit_rate_mean": 0.9,
                    "within_one_level_hit_rate_mean": 1.0,
                    "score_band_mae_mean": 1.0,
                    "mean_rank_displacement_mean": 0.5,
                    "kendall_tau_mean": 0.9,
                    "pairwise_order_agreement_mean": 0.95,
                    "model_usage_ratio_mean": 0.9,
                    "cost_usd_mean": 1.0,
                    "latency_seconds_mean": 10.0,
                    "stability": {
                        "mean_student_level_variance": 0.05,
                        "mean_student_rank_variance": 0.05,
                        "mean_student_score_variance": 0.5,
                    },
                }
            },
            "fallback": {
                "summary": {
                    "runs_attempted": 3,
                    "runs_successful": 3,
                    "exact_level_hit_rate_mean": 0.7,
                    "within_one_level_hit_rate_mean": 0.8,
                    "score_band_mae_mean": 3.0,
                    "mean_rank_displacement_mean": 1.5,
                    "kendall_tau_mean": 0.6,
                    "pairwise_order_agreement_mean": 0.8,
                    "model_usage_ratio_mean": 0.0,
                    "cost_usd_mean": 0.0,
                    "latency_seconds_mean": 4.0,
                    "stability": {
                        "mean_student_level_variance": 0.2,
                        "mean_student_rank_variance": 0.2,
                        "mean_student_score_variance": 2.0,
                    },
                }
            },
        },
        "comparison": {"candidate_mode": "main", "baseline_mode": "fallback"},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_corpus_benchmark_summary(path, *, failed_datasets=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset_count": 2,
        "datasets": ["d1", "d2"],
        "runs_per_dataset_mode": 1,
        "failed_datasets": list(failed_datasets or []),
        "comparison": {
            "candidate_mode": "gpt54_split",
            "baseline_mode": "gpt52_legacy",
            "candidate_weighted_summary": {
                "exact_level_hit_rate_mean": 0.84,
                "within_one_level_hit_rate_mean": 0.93,
                "score_band_mae_mean": 2.7,
                "mean_rank_displacement_mean": 0.4,
                "kendall_tau_mean": 0.82,
                "pairwise_order_agreement_mean": 0.91,
                "model_usage_ratio_mean": 1.0,
                "cost_usd_mean": 0.5,
                "latency_seconds_mean": 20.0,
            },
            "baseline_weighted_summary": {
                "exact_level_hit_rate_mean": 0.8,
                "within_one_level_hit_rate_mean": 0.9,
                "score_band_mae_mean": 3.0,
                "mean_rank_displacement_mean": 0.6,
                "kendall_tau_mean": 0.8,
                "pairwise_order_agreement_mean": 0.88,
                "model_usage_ratio_mean": 1.0,
                "cost_usd_mean": 0.7,
                "latency_seconds_mean": 25.0,
            },
            "delta": {
                "exact_level_hit_rate_mean": 0.04,
                "within_one_level_hit_rate_mean": 0.03,
                "score_band_mae_mean": -0.3,
                "mean_rank_displacement_mean": -0.2,
                "kendall_tau_mean": 0.02,
                "pairwise_order_agreement_mean": 0.03,
                "cost_usd_mean": -0.2,
                "latency_seconds_mean": -5.0,
            },
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_helpers_and_core_metrics(tmp_path):
    assert sg.load_json(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{bad", encoding="utf-8")
    assert sg.load_json(bad) == {}
    assert sg.model_coverage([]) == 0.0
    assert sg.score_rate([]) == 0.0
    assert sg.criteria_coverage([]) == 0.0
    assert sg.evidence_coverage([]) == 0.0

    pass1_file = tmp_path / "assessments/pass1_individual/assessor_A.json"
    _write_pass1(
        pass1_file,
        "assessor_A",
        [
            {
                "student_id": "s1",
                "rubric_total_points": 80,
                "criteria_points": {"K1": 70},
                "criteria_evidence": [{"criterion_id": "K1"}],
                "notes": "Model score",
            },
            {
                "student_id": "s2",
                "rubric_total_points": 0,
                "criteria_points": {},
                "criteria_evidence": [],
                "notes": "Fallback deterministic score",
            },
        ],
    )
    rows = sg.load_pass1_rows(pass1_file.parent)
    assert len(rows) == 2
    assert all(row["assessor_id"] == "assessor_A" for row in rows)
    assert sg.model_coverage(rows) == 0.5
    assert sg.score_rate(rows) == 0.5
    assert sg.criteria_coverage(rows) == 0.5
    assert sg.evidence_coverage(rows) == 0.5
    assert round(sg.score_rate(rows + [{"rubric_total_points": "oops"}]), 5) == round(1 / 3, 5)

    assert sg._stdev([]) == 0.0
    assert sg._stdev([1.0]) == 0.0
    assert round(sg._stdev([0.0, 2.0]), 5) == 1.0
    assert sg._percentile([], 0.95) == 0.0
    assert sg._percentile([1.0, 2.0, 3.0], 0.0) == 1.0
    assert sg._percentile([1.0, 2.0, 3.0], 0.95) == 3.0


def test_assessor_spread_and_consistency_metrics(tmp_path):
    _write_pass1(
        tmp_path / "assessments/pass1_individual/assessor_A.json",
        "assessor_A",
        [{"student_id": "s1", "rubric_total_points": 70, "notes": "ok"}],
    )
    _write_pass1(
        tmp_path / "assessments/pass1_individual/assessor_B.json",
        "assessor_B",
        [{"student_id": "s1", "rubric_total_points": 90, "notes": "ok"}],
    )
    rows = sg.load_pass1_rows(tmp_path / "assessments/pass1_individual")
    mean_sd, p95_sd = sg.assessor_spread(rows)
    assert mean_sd > 0
    assert p95_sd >= mean_sd
    assert sg.assessor_spread([{"student_id": "", "rubric_total_points": 70}, {"student_id": "s1", "rubric_total_points": "oops"}]) == (0.0, 0.0)

    assert sg.consistency_metrics(tmp_path / "missing.json") == (0, 0.0, 0.0)
    checks_path = tmp_path / "outputs/consistency_checks.json"
    checks_path.parent.mkdir(parents=True, exist_ok=True)
    checks_path.write_text(
        json.dumps(
            {
                "checks": [
                    {"decision": "KEEP", "confidence": "high"},
                    {"decision": "SWAP", "confidence": "low"},
                    {"decision": "SWAP", "confidence": "medium"},
                ]
            }
        ),
        encoding="utf-8",
    )
    total, swap_rate, low_rate = sg.consistency_metrics(checks_path)
    assert total == 3
    assert round(swap_rate, 5) == round(2 / 3, 5)
    assert round(low_rate, 5) == round(1 / 3, 5)
    _write_benchmark_report(tmp_path / "benchmark_report.json")
    benchmark = sg.benchmark_comparison_metrics(tmp_path / "benchmark_report.json", "main", "fallback")
    assert benchmark["present"] is True
    assert benchmark["candidate"]["mean_student_level_sd"] > 0
    assert benchmark["delta"]["exact_level_hit_rate"] == 0.2
    _write_corpus_benchmark_summary(tmp_path / "corpus_benchmark.json", failed_datasets=["broken_dataset"])
    corpus_benchmark = sg.benchmark_comparison_metrics(tmp_path / "corpus_benchmark.json")
    assert corpus_benchmark["present"] is True
    assert corpus_benchmark["failed_dataset_count"] == 1
    assert corpus_benchmark["dataset_count"] == 2
    assert corpus_benchmark["candidate"]["runs_successful"] == 1
    assert corpus_benchmark["delta"]["score_band_mae"] == -0.3


def test_evaluate_covers_failure_codes():
    metrics = {
        "publish_gate_present": False,
        "publish_gate_ok": False,
        "publish_profile_order": ["dev", "candidate", "release"],
        "publish_highest_attained_profile": "dev",
        "assessor_files": 1,
        "model_coverage": 0.1,
        "nonzero_score_rate": 0.1,
        "criteria_coverage": 0.1,
        "evidence_coverage": 0.1,
        "mean_assessor_sd": 20.0,
        "p95_assessor_sd": 25.0,
        "consistency_swap_rate": 0.9,
        "consistency_low_confidence_rate": 0.9,
        "benchmark_comparison_present": True,
        "benchmark_runs_successful": 0,
        "benchmark_failed_dataset_count": 1,
        "benchmark_exact_level_hit_rate": 0.1,
        "benchmark_within_one_level_hit_rate": 0.2,
        "benchmark_score_band_mae": 6.0,
        "benchmark_mean_rank_displacement": 4.0,
        "benchmark_kendall_tau": 0.1,
        "benchmark_pairwise_order_agreement": 0.2,
        "benchmark_model_usage_ratio": 0.1,
        "benchmark_cost_usd": 10.0,
        "benchmark_latency_seconds": 100.0,
        "benchmark_mean_student_level_variance": 1.0,
        "benchmark_mean_student_rank_variance": 1.0,
        "benchmark_mean_student_score_variance": 1.0,
        "benchmark_mean_student_level_sd": 1.0,
        "benchmark_mean_student_rank_sd": 1.0,
        "benchmark_mean_student_score_sd": 1.0,
        "benchmark_exact_level_hit_rate_delta": -0.5,
        "benchmark_within_one_level_hit_rate_delta": -0.5,
        "benchmark_score_band_mae_delta": 5.0,
        "benchmark_mean_rank_displacement_delta": 5.0,
        "benchmark_kendall_tau_delta": -0.5,
        "benchmark_pairwise_order_agreement_delta": -0.5,
        "benchmark_model_usage_ratio_delta": -0.5,
        "benchmark_cost_usd_delta": 10.0,
        "benchmark_latency_seconds_delta": 10.0,
        "benchmark_mean_student_level_variance_delta": 1.0,
        "benchmark_mean_student_rank_variance_delta": 1.0,
        "benchmark_mean_student_score_variance_delta": 1.0,
        "benchmark_mean_student_level_sd_delta": 1.0,
        "benchmark_mean_student_rank_sd_delta": 1.0,
        "benchmark_mean_student_score_sd_delta": 1.0,
    }
    thresholds = {
        "require_publish_gate_ok": True,
        "min_publish_profile": "candidate",
        "min_assessor_files": 3,
        "min_model_coverage": 0.9,
        "min_nonzero_score_rate": 0.9,
        "min_criteria_coverage": 0.9,
        "min_evidence_coverage": 0.8,
        "max_mean_assessor_sd": 10.0,
        "max_p95_assessor_sd": 15.0,
        "max_consistency_swap_rate": 0.3,
        "max_consistency_low_confidence_rate": 0.5,
        "require_benchmark_report": True,
        "benchmark_min_runs_successful": 1,
        "benchmark_max_failed_datasets": 0,
        "benchmark_min_exact_level_hit_rate": 0.8,
        "benchmark_min_within_one_level_hit_rate": 0.95,
        "benchmark_max_score_band_mae": 2.0,
        "benchmark_max_mean_rank_displacement": 1.0,
        "benchmark_min_kendall_tau": 0.8,
        "benchmark_min_pairwise_order_agreement": 0.9,
        "benchmark_min_model_usage_ratio": 0.8,
        "benchmark_max_cost_usd": 2.0,
        "benchmark_max_latency_seconds": 20.0,
        "benchmark_max_mean_student_level_variance": 0.1,
        "benchmark_max_mean_student_rank_variance": 0.1,
        "benchmark_max_mean_student_score_variance": 0.5,
        "benchmark_max_mean_student_level_sd": 0.3,
        "benchmark_max_mean_student_rank_sd": 0.3,
        "benchmark_max_mean_student_score_sd": 0.7,
        "benchmark_min_exact_level_hit_rate_delta": 0.0,
        "benchmark_min_within_one_level_hit_rate_delta": 0.0,
        "benchmark_max_score_band_mae_delta": 0.0,
        "benchmark_max_mean_rank_displacement_delta": 0.0,
        "benchmark_min_kendall_tau_delta": 0.0,
        "benchmark_min_pairwise_order_agreement_delta": 0.0,
        "benchmark_min_model_usage_ratio_delta": 0.0,
        "benchmark_max_cost_usd_delta": 1.0,
        "benchmark_max_latency_seconds_delta": 1.0,
        "benchmark_max_mean_student_level_variance_delta": 0.0,
        "benchmark_max_mean_student_rank_variance_delta": 0.0,
        "benchmark_max_mean_student_score_variance_delta": 0.0,
        "benchmark_max_mean_student_level_sd_delta": 0.0,
        "benchmark_max_mean_student_rank_sd_delta": 0.0,
        "benchmark_max_mean_student_score_sd_delta": 0.0,
    }
    failures = sg.evaluate(metrics, thresholds)
    assert "publish_gate_not_ok" in failures
    assert "publish_gate_missing" in failures
    assert "publish_gate_profile_below_threshold" in failures
    assert "assessor_count_below_threshold" in failures
    assert "model_coverage_below_threshold" in failures
    assert "nonzero_score_rate_below_threshold" in failures
    assert "criteria_coverage_below_threshold" in failures
    assert "evidence_coverage_below_threshold" in failures
    assert "mean_assessor_sd_above_threshold" in failures
    assert "p95_assessor_sd_above_threshold" in failures
    assert "consistency_swap_rate_above_threshold" in failures
    assert "consistency_low_confidence_rate_above_threshold" in failures
    assert "benchmark_runs_successful_below_threshold" in failures
    assert "benchmark_failed_datasets_above_threshold" in failures
    assert "benchmark_exact_level_hit_rate_below_threshold" in failures
    assert "benchmark_within_one_level_hit_rate_below_threshold" in failures
    assert "benchmark_score_band_mae_above_threshold" in failures
    assert "benchmark_mean_rank_displacement_above_threshold" in failures
    assert "benchmark_kendall_tau_below_threshold" in failures
    assert "benchmark_pairwise_order_below_threshold" in failures
    assert "benchmark_model_usage_below_threshold" in failures
    assert "benchmark_cost_above_threshold" in failures
    assert "benchmark_latency_above_threshold" in failures
    assert "benchmark_student_level_variance_above_threshold" in failures
    assert "benchmark_student_rank_variance_above_threshold" in failures
    assert "benchmark_student_score_variance_above_threshold" in failures
    assert "benchmark_student_level_sd_above_threshold" in failures
    assert "benchmark_student_rank_sd_above_threshold" in failures
    assert "benchmark_student_score_sd_above_threshold" in failures
    assert "benchmark_exact_level_hit_rate_delta_below_threshold" in failures
    assert "benchmark_within_one_level_hit_rate_delta_below_threshold" in failures
    assert "benchmark_score_band_mae_delta_above_threshold" in failures
    assert "benchmark_mean_rank_displacement_delta_above_threshold" in failures
    assert "benchmark_kendall_tau_delta_below_threshold" in failures
    assert "benchmark_pairwise_order_delta_below_threshold" in failures
    assert "benchmark_model_usage_delta_below_threshold" in failures
    assert "benchmark_cost_delta_above_threshold" in failures
    assert "benchmark_latency_delta_above_threshold" in failures
    assert "benchmark_student_level_variance_delta_above_threshold" in failures
    assert "benchmark_student_rank_variance_delta_above_threshold" in failures
    assert "benchmark_student_score_variance_delta_above_threshold" in failures
    assert "benchmark_student_level_sd_delta_above_threshold" in failures
    assert "benchmark_student_rank_sd_delta_above_threshold" in failures
    assert "benchmark_student_score_sd_delta_above_threshold" in failures


def test_main_success_and_failure(tmp_path, monkeypatch):
    pass1_dir = tmp_path / "assessments/pass1_individual"
    rows_a = [
        {
            "student_id": "s1",
            "rubric_total_points": 82,
            "criteria_points": {"K1": 81},
            "criteria_evidence": [{"criterion_id": "K1"}],
            "notes": "Model score",
        },
        {
            "student_id": "s2",
            "rubric_total_points": 74,
            "criteria_points": {"K1": 73},
            "criteria_evidence": [{"criterion_id": "K1"}],
            "notes": "Model score",
        },
    ]
    rows_b = [dict(item, rubric_total_points=item["rubric_total_points"] + 1) for item in rows_a]
    rows_c = [dict(item, rubric_total_points=item["rubric_total_points"] - 1) for item in rows_a]
    _write_pass1(pass1_dir / "assessor_A.json", "assessor_A", rows_a)
    _write_pass1(pass1_dir / "assessor_B.json", "assessor_B", rows_b)
    _write_pass1(pass1_dir / "assessor_C.json", "assessor_C", rows_c)

    publish = tmp_path / "outputs/publish_gate.json"
    publish.parent.mkdir(parents=True, exist_ok=True)
    publish.write_text(json.dumps({"ok": True}), encoding="utf-8")
    consistency = tmp_path / "outputs/consistency_checks.json"
    consistency.write_text(json.dumps({"checks": [{"decision": "KEEP", "confidence": "high"}]}), encoding="utf-8")
    _write_benchmark_report(tmp_path / "outputs/benchmark_report.json")

    config = tmp_path / "config/sota_gate.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "thresholds": {
                    "require_publish_gate_ok": True,
                    "min_assessor_files": 3,
                    "min_model_coverage": 0.8,
                    "min_nonzero_score_rate": 1.0,
                    "min_criteria_coverage": 1.0,
                    "min_evidence_coverage": 1.0,
                    "max_mean_assessor_sd": 5.0,
                    "max_p95_assessor_sd": 6.0,
                    "max_consistency_swap_rate": 0.2,
                    "max_consistency_low_confidence_rate": 0.2,
                    "require_benchmark_report": True,
                    "benchmark_candidate_mode": "main",
                    "benchmark_baseline_mode": "fallback",
                    "benchmark_min_exact_level_hit_rate_delta": 0.0,
                    "benchmark_min_within_one_level_hit_rate_delta": 0.0,
                    "benchmark_max_score_band_mae_delta": 0.0,
                    "benchmark_max_mean_rank_displacement_delta": 0.0,
                    "benchmark_min_kendall_tau_delta": 0.0,
                    "benchmark_min_pairwise_order_agreement_delta": 0.0,
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "sota_gate",
            "--publish-gate",
            "outputs/publish_gate.json",
            "--pass1",
            "assessments/pass1_individual",
            "--consistency",
            "outputs/consistency_checks.json",
            "--benchmark-report",
            "outputs/benchmark_report.json",
            "--gate-config",
            "config/sota_gate.json",
            "--output",
            "outputs/sota_gate.json",
        ],
    )
    assert sg.main() == 0
    payload = json.loads((tmp_path / "outputs/sota_gate.json").read_text(encoding="utf-8"))
    assert payload["ok"] is True

    (tmp_path / "outputs/publish_gate.json").write_text(json.dumps({"ok": False}), encoding="utf-8")
    assert sg.main() == 2
    failed = json.loads((tmp_path / "outputs/sota_gate.json").read_text(encoding="utf-8"))
    assert failed["ok"] is False
    assert "publish_gate_not_ok" in failed["failures"]


def test_sota_gate_profile_contracts_and_publish_profile_handoff(tmp_path, monkeypatch):
    pass1_dir = tmp_path / "assessments/pass1_individual"
    rows = [
        {
            "student_id": "s1",
            "rubric_total_points": 82,
            "criteria_points": {"K1": 81},
            "criteria_evidence": [{"criterion_id": "K1"}],
            "notes": "Model score",
        },
        {
            "student_id": "s2",
            "rubric_total_points": 74,
            "criteria_points": {"K1": 73},
            "criteria_evidence": [{"criterion_id": "K1"}],
            "notes": "Model score",
        },
    ]
    _write_pass1(pass1_dir / "assessor_A.json", "assessor_A", rows)
    _write_pass1(pass1_dir / "assessor_B.json", "assessor_B", [dict(item, rubric_total_points=item["rubric_total_points"] + 1) for item in rows])
    _write_pass1(pass1_dir / "assessor_C.json", "assessor_C", [dict(item, rubric_total_points=item["rubric_total_points"] - 1) for item in rows])

    publish = tmp_path / "outputs/publish_gate.json"
    publish.parent.mkdir(parents=True, exist_ok=True)
    publish.write_text(
        json.dumps(
            {
                "ok": True,
                "target_profile": "release",
                "highest_attained_profile": "release",
                "profile_order": ["dev", "candidate", "release"],
            }
        ),
        encoding="utf-8",
    )
    consistency = tmp_path / "outputs/consistency_checks.json"
    consistency.write_text(json.dumps({"checks": [{"decision": "KEEP", "confidence": "high"}]}), encoding="utf-8")
    _write_benchmark_report(tmp_path / "outputs/benchmark_report.json")

    config = tmp_path / "config/sota_gate.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "target_profile": "release",
                "profiles": {
                    "dev": {
                        "thresholds": {
                            "require_publish_gate_ok": True,
                            "min_publish_profile": "dev",
                            "min_assessor_files": 3,
                            "min_model_coverage": 0.8,
                            "min_nonzero_score_rate": 1.0,
                            "min_criteria_coverage": 1.0,
                            "min_evidence_coverage": 1.0,
                            "max_mean_assessor_sd": 5.0,
                            "max_p95_assessor_sd": 6.0,
                            "max_consistency_swap_rate": 0.2,
                            "max_consistency_low_confidence_rate": 0.2,
                            "require_benchmark_report": True,
                            "benchmark_candidate_mode": "main",
                            "benchmark_baseline_mode": "fallback",
                            "benchmark_min_runs_successful": 2,
                            "benchmark_min_exact_level_hit_rate": 0.8,
                            "benchmark_min_within_one_level_hit_rate": 0.95,
                            "benchmark_max_score_band_mae": 2.0,
                            "benchmark_max_mean_rank_displacement": 1.0,
                            "benchmark_min_kendall_tau": 0.8,
                            "benchmark_min_pairwise_order_agreement": 0.9,
                            "benchmark_min_model_usage_ratio": 0.8,
                            "benchmark_max_cost_usd": 2.0,
                            "benchmark_max_latency_seconds": 20.0,
                            "benchmark_max_mean_student_level_sd": 0.25,
                            "benchmark_max_mean_student_rank_sd": 0.25,
                            "benchmark_max_mean_student_score_sd": 1.0,
                            "benchmark_min_exact_level_hit_rate_delta": 0.0,
                            "benchmark_min_within_one_level_hit_rate_delta": 0.0,
                            "benchmark_max_score_band_mae_delta": 0.0,
                            "benchmark_max_mean_rank_displacement_delta": 0.0,
                            "benchmark_min_kendall_tau_delta": 0.0,
                            "benchmark_min_pairwise_order_agreement_delta": 0.0,
                            "benchmark_min_model_usage_ratio_delta": 0.0
                        }
                    },
                    "candidate": {
                        "inherits": "dev",
                        "thresholds": {
                            "min_publish_profile": "candidate"
                        }
                    },
                    "release": {
                        "inherits": "candidate",
                        "thresholds": {
                            "min_publish_profile": "release"
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "sota_gate",
            "--publish-gate",
            "outputs/publish_gate.json",
            "--pass1",
            "assessments/pass1_individual",
            "--consistency",
            "outputs/consistency_checks.json",
            "--benchmark-report",
            "outputs/benchmark_report.json",
            "--gate-config",
            "config/sota_gate.json",
            "--output",
            "outputs/sota_gate.json",
        ],
    )
    assert sg.main() == 0
    payload = json.loads((tmp_path / "outputs/sota_gate.json").read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["highest_attained_profile"] == "release"
    assert payload["decision_state"] == "release_ready"
