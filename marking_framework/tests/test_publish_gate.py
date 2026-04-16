import csv
import json

import scripts.publish_gate as pg
from scripts.calibration_contract import file_sha256


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_pass1(path, fallback=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    note = "Fallback deterministic score" if fallback else "Model score"
    payload = {
        "assessor_id": "assessor_A",
        "scores": [
            {"student_id": "s001", "rubric_total_points": 84, "notes": note},
            {"student_id": "s002", "rubric_total_points": 74, "notes": note},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_inputs(tmp_path):
    _write_csv(
        tmp_path / "outputs/consensus_scores.csv",
        [
            {
                "student_id": "s001",
                "rubric_after_penalty_percent": "84.0",
                "adjusted_level": "4",
            },
            {
                "student_id": "s002",
                "rubric_after_penalty_percent": "74.0",
                "adjusted_level": "3",
            },
        ],
    )
    (tmp_path / "processing").mkdir(parents=True, exist_ok=True)
    (tmp_path / "processing/submission_metadata.json").write_text(
        json.dumps(
            [
                {"student_id": "s001", "display_name": "anchor_level_4", "gold_level": "4"},
                {"student_id": "s002", "display_name": "anchor_level_3", "gold_level": "3"},
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "outputs/irr_metrics.json").write_text(
        json.dumps({"inter_rater_reliability": {"rank_kendall_w": 0.9, "mean_rubric_sd": 1.0}}),
        encoding="utf-8",
    )
    _write_pass1(tmp_path / "assessments/pass1_individual/assessor_A.json", fallback=False)
    _write_pass1(tmp_path / "assessments/pass1_individual/assessor_B.json", fallback=False)
    _write_pass1(tmp_path / "assessments/pass1_individual/assessor_C.json", fallback=False)
    (tmp_path / "inputs/class_metadata.json").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "inputs/class_metadata.json").write_text(
        json.dumps({"grade_level": 8, "assignment_genre": "argumentative"}),
        encoding="utf-8",
    )
    (tmp_path / "config/marking_config.json").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config/marking_config.json").write_text(
        json.dumps({"levels": {"bands": [
            {"level": "1", "min": 50, "max": 59},
            {"level": "2", "min": 60, "max": 69},
            {"level": "3", "min": 70, "max": 79},
            {"level": "4", "min": 80, "max": 89},
            {"level": "4+", "min": 90, "max": 100},
        ]}}),
        encoding="utf-8",
    )
    (tmp_path / "outputs/calibration_bias.json").write_text(
        json.dumps(
            {
                "assessors": {
                    "assessor_A": {
                        "scopes": {
                            "grade_8_10|argumentative": {
                                "level_hit_rate": 0.9,
                                "mae": 3.0,
                                "pairwise_order_agreement": 0.9,
                                "repeat_level_consistency": 0.95,
                                "bias": 0.5,
                            }
                        }
                    },
                    "assessor_B": {
                        "scopes": {
                            "grade_8_10|argumentative": {
                                "level_hit_rate": 0.9,
                                "mae": 3.0,
                                "pairwise_order_agreement": 0.9,
                                "repeat_level_consistency": 0.95,
                                "bias": 0.5,
                            }
                        }
                    },
                    "assessor_C": {
                        "scopes": {
                            "grade_8_10|argumentative": {
                                "level_hit_rate": 0.9,
                                "mae": 3.0,
                                "pairwise_order_agreement": 0.9,
                                "repeat_level_consistency": 0.95,
                                "bias": 0.5,
                            }
                        }
                    },
                }
            }
        ),
        encoding="utf-8",
    )


def _write_benchmark_report(path, exact=0.9, within_one=1.0, score_band_mae=1.5, rank_disp=0.5, kendall=0.9, pairwise=0.95):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "modes": {
            "main": {
                "summary": {
                    "runs_attempted": 3,
                    "runs_successful": 3,
                    "exact_level_hit_rate_mean": exact,
                    "within_one_level_hit_rate_mean": within_one,
                    "score_band_mae_mean": score_band_mae,
                    "mean_rank_displacement_mean": rank_disp,
                    "kendall_tau_mean": kendall,
                    "pairwise_order_agreement_mean": pairwise,
                    "model_usage_ratio_mean": 0.9,
                    "cost_usd_mean": 1.5,
                    "latency_seconds_mean": 12.0,
                    "stability": {
                        "mean_student_level_variance": 0.02,
                        "mean_student_rank_variance": 0.03,
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
                    "score_band_mae_mean": 4.0,
                    "mean_rank_displacement_mean": 1.5,
                    "kendall_tau_mean": 0.6,
                    "pairwise_order_agreement_mean": 0.8,
                    "model_usage_ratio_mean": 0.0,
                    "cost_usd_mean": 0.0,
                    "latency_seconds_mean": 3.0,
                    "stability": {
                        "mean_student_level_variance": 0.1,
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
        "dataset_count": 3,
        "datasets": ["d1", "d2", "d3"],
        "runs_per_dataset_mode": 1,
        "failed_datasets": list(failed_datasets or []),
        "comparison": {
            "candidate_mode": "main",
            "baseline_mode": "fallback",
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


def _write_calibration_manifest(tmp_path, *, synthetic=False, samples=12, observations=12, generated_at="2026-03-28T00:00:00+00:00"):
    (tmp_path / "outputs/calibration_manifest.json").write_text(
        json.dumps(
            {
                "generated_at": generated_at,
                "synthetic": synthetic,
                "profile_type": "calibrated" if not synthetic else "bootstrap_neutral",
                "freshness_window_hours": 336,
                "scope_coverage": [
                    {
                        "key": "grade_8_10|argumentative",
                        "grade_band": "grade_8_10",
                        "genre": "argumentative",
                        "rubric_family": "rubric_unknown",
                        "model_family": "",
                        "samples": samples,
                        "observations": observations,
                    }
                ],
                "artifact_hashes": {"calibration_bias_sha256": file_sha256(tmp_path / "outputs/calibration_bias.json")},
            }
        ),
        encoding="utf-8",
    )


def _write_reproducibility_report(path, *, exact=True, within_tolerance=None, manifest_identical=True, runs_compared=2, max_delta=0.0):
    if within_tolerance is None:
        within_tolerance = exact
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "summary": {
                    "runs_compared": runs_compared,
                    "manifest_identical": manifest_identical,
                    "final_outputs_exact_match": exact,
                    "within_tolerance": within_tolerance,
                    "max_intermediate_metric_delta": max_delta,
                    "mismatched_final_artifacts": [] if exact else ["outputs/final_order.csv"],
                    "mismatched_intermediate_artifacts": [] if max_delta == 0.0 else ["outputs/consistency_report.json"],
                }
            }
        ),
        encoding="utf-8",
    )


def test_publish_gate_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_inputs(tmp_path)
    _write_benchmark_report(tmp_path / "outputs/benchmark_report.json")
    (tmp_path / "config/accuracy_gate.json").write_text(
        json.dumps(
            {
                "thresholds": {
                    "min_rank_kendall_w": 0.8,
                    "max_mean_rubric_sd": 2.0,
                    "min_model_coverage": 0.9,
                    "boundary_margin_percent": 1.0,
                    "max_boundary_students": 2,
                    "anchor_min_hit_rate": 0.8,
                    "anchor_max_mae": 0.5,
                    "calibration_min_level_hit_rate": 0.8,
                    "calibration_max_mae": 8.0,
                    "calibration_min_pairwise_order": 0.8,
                    "calibration_min_repeat_level_consistency": 0.8,
                    "calibration_max_abs_bias": 6.0,
                    "require_benchmark_report": True,
                    "benchmark_mode": "main",
                    "benchmark_min_runs_successful": 3,
                    "benchmark_min_exact_level_hit_rate": 0.8,
                    "benchmark_min_within_one_level_hit_rate": 0.95,
                    "benchmark_max_score_band_mae": 2.0,
                    "benchmark_max_mean_rank_displacement": 1.0,
                    "benchmark_min_kendall_tau": 0.8,
                    "benchmark_min_pairwise_order_agreement": 0.9,
                    "benchmark_min_model_usage_ratio": 0.8,
                    "benchmark_max_cost_usd": 2.0,
                    "benchmark_max_latency_seconds": 20.0,
                    "benchmark_max_mean_student_level_variance": 0.05,
                    "benchmark_max_mean_student_rank_variance": 0.05,
                    "benchmark_max_mean_student_score_variance": 1.0,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "publish_gate",
            "--gate-config",
            "config/accuracy_gate.json",
            "--output",
            "outputs/publish_gate.json",
        ],
    )
    assert pg.main() == 0
    result = json.loads((tmp_path / "outputs/publish_gate.json").read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["metrics"]["benchmark_mode"] == "main"


def test_publish_gate_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_inputs(tmp_path)
    # Force fallback-only notes for coverage failure.
    _write_pass1(tmp_path / "assessments/pass1_individual/assessor_A.json", fallback=True)
    _write_pass1(tmp_path / "assessments/pass1_individual/assessor_B.json", fallback=True)
    _write_pass1(tmp_path / "assessments/pass1_individual/assessor_C.json", fallback=True)
    (tmp_path / "config/accuracy_gate.json").write_text(
        json.dumps(
            {
                "thresholds": {
                    "min_rank_kendall_w": 0.95,
                    "max_mean_rubric_sd": 0.5,
                    "min_model_coverage": 1.0,
                    "boundary_margin_percent": 1.0,
                    "max_boundary_students": 0,
                    "anchor_min_hit_rate": 1.0,
                    "anchor_max_mae": 0.0,
                    "calibration_min_level_hit_rate": 0.95,
                    "calibration_max_mae": 1.0,
                    "calibration_min_pairwise_order": 0.95,
                    "calibration_min_repeat_level_consistency": 0.95,
                    "calibration_max_abs_bias": 0.1,
                    "require_benchmark_report": True,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "publish_gate",
            "--gate-config",
            "config/accuracy_gate.json",
            "--output",
            "outputs/publish_gate.json",
        ],
    )
    assert pg.main() == 2
    result = json.loads((tmp_path / "outputs/publish_gate.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert "model_coverage_below_threshold" in result["failures"]
    assert "benchmark_report_missing" in result["failures"]


def test_publish_gate_helper_branches(tmp_path):
    assert pg.load_json(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{broken", encoding="utf-8")
    assert pg.load_json(bad) == {}
    assert pg.load_rows(tmp_path / "missing.csv") == []
    assert pg.boundary_count([], [], 1.0) == 0
    rows = [{"rubric_after_penalty_percent": "oops"}, {"rubric_after_penalty_percent": "79.5"}]
    bands = [{"min": 50}, {"min": 60}, {"min": 70}, {"min": 80}]
    assert pg.boundary_count(rows, bands, 1.0) == 1
    assert pg.anchor_metrics([], []) == (0, 0.0, 0.0)
    assert pg.anchor_metrics([{"student_id": "s1", "adjusted_level": "4"}], [{"student_id": "s1", "gold_level": "4"}]) == (1, 1.0, 0.0)
    assert pg.scope_from_metadata(tmp_path / "missing-class.json") == ""
    cal = pg.calibration_metrics(tmp_path / "missing-cal.json", ["A"], "grade_8_10|argumentative")
    assert "assessor_A" in cal["missing_assessors"]
    _write_benchmark_report(tmp_path / "benchmark.json")
    bench = pg.benchmark_metrics(tmp_path / "benchmark.json", "main")
    assert bench["present"] is True
    assert bench["exact_level_hit_rate"] == 0.9
    _write_corpus_benchmark_summary(tmp_path / "corpus_benchmark.json", failed_datasets=["broken_dataset"])
    corpus_bench = pg.benchmark_metrics(tmp_path / "corpus_benchmark.json", "main")
    assert corpus_bench["present"] is True
    assert corpus_bench["failed_dataset_count"] == 1
    assert corpus_bench["dataset_count"] == 3
    assert corpus_bench["exact_level_hit_rate"] == 0.84
    assert pg.pairwise_eval_metrics(tmp_path / "missing-pairwise-eval.json")["present"] is False
    (tmp_path / "pairwise_eval.json").write_text(
        json.dumps(
            {
                "summary": {
                    "pair_count": 4,
                    "evaluated_count": 3,
                    "accuracy": 0.67,
                    "coverage": 0.75,
                    "critical_accuracy": 0.5,
                    "failures": ["accuracy_below_threshold"],
                },
                "polish_bias_risks": [{"id": "p1"}],
            }
        ),
        encoding="utf-8",
    )
    pairwise_eval = pg.pairwise_eval_metrics(tmp_path / "pairwise_eval.json")
    assert pairwise_eval["present"] is True
    assert pairwise_eval["polish_bias_risk_count"] == 1
    assert pairwise_eval["failures"] == ["accuracy_below_threshold"]


def test_publish_gate_evaluate_covers_all_failure_codes():
    metrics = {
        "irr_rank_kendalls_w": 0.1,
        "irr_mean_rubric_sd": 9.0,
        "model_coverage": 0.1,
        "boundary_count": 9,
        "anchors_total": 2,
        "anchor_hit_rate": 0.1,
        "anchor_level_mae": 2.0,
        "cal_missing_assessors": ["assessor_A"],
        "cal_level_hit_rate": 0.1,
        "cal_mae": 20.0,
        "cal_pairwise_order": 0.1,
        "cal_repeat_consistency": 0.1,
        "cal_abs_bias": 20.0,
        "benchmark_report_present": True,
        "benchmark_runs_successful": 0,
        "benchmark_failed_dataset_count": 1,
        "benchmark_exact_level_hit_rate": 0.1,
        "benchmark_within_one_level_hit_rate": 0.2,
        "benchmark_score_band_mae": 20.0,
        "benchmark_mean_rank_displacement": 10.0,
        "benchmark_kendall_tau": 0.1,
        "benchmark_pairwise_order_agreement": 0.1,
        "benchmark_model_usage_ratio": 0.1,
        "benchmark_cost_usd": 50.0,
        "benchmark_latency_seconds": 500.0,
        "benchmark_mean_student_level_variance": 10.0,
        "benchmark_mean_student_rank_variance": 10.0,
        "benchmark_mean_student_score_variance": 10.0,
        "benchmark_mean_student_level_sd": 4.0,
        "benchmark_mean_student_rank_sd": 4.0,
        "benchmark_mean_student_score_sd": 4.0,
        "pairwise_eval_present": True,
        "pairwise_eval_accuracy": 0.5,
        "pairwise_eval_critical_accuracy": 0.5,
        "pairwise_eval_coverage": 0.5,
        "pairwise_eval_polish_bias_risk_count": 2,
        "pairwise_eval_failures": ["accuracy_below_threshold"],
    }
    thresholds = {
        "min_rank_kendall_w": 0.7,
        "max_mean_rubric_sd": 2.0,
        "min_model_coverage": 0.95,
        "max_boundary_students": 0,
        "anchor_min_hit_rate": 0.8,
        "anchor_max_mae": 0.5,
        "calibration_min_level_hit_rate": 0.8,
        "calibration_max_mae": 8.0,
        "calibration_min_pairwise_order": 0.8,
        "calibration_min_repeat_level_consistency": 0.8,
        "calibration_max_abs_bias": 6.0,
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
        "benchmark_max_cost_usd": 5.0,
        "benchmark_max_latency_seconds": 30.0,
        "benchmark_max_mean_student_level_variance": 0.5,
        "benchmark_max_mean_student_rank_variance": 0.5,
        "benchmark_max_mean_student_score_variance": 1.0,
        "benchmark_max_mean_student_level_sd": 0.5,
        "benchmark_max_mean_student_rank_sd": 0.5,
        "benchmark_max_mean_student_score_sd": 1.0,
        "require_pairwise_eval_report": True,
        "pairwise_eval_min_accuracy": 0.9,
        "pairwise_eval_min_critical_accuracy": 1.0,
        "pairwise_eval_min_coverage": 1.0,
        "pairwise_eval_max_polish_bias_risks": 0,
        "pairwise_eval_fail_on_report_failures": True,
    }
    failures = pg.evaluate(metrics, thresholds)
    assert "kendall_w_below_threshold" in failures
    assert "rubric_sd_above_threshold" in failures
    assert "model_coverage_below_threshold" in failures
    assert "too_many_boundary_students" in failures
    assert "anchor_hit_rate_below_threshold" in failures
    assert "anchor_mae_above_threshold" in failures
    assert "calibration_scope_missing" in failures
    assert "calibration_level_hit_rate_below_threshold" in failures
    assert "calibration_mae_above_threshold" in failures
    assert "calibration_pairwise_below_threshold" in failures
    assert "calibration_repeat_consistency_below_threshold" in failures
    assert "calibration_abs_bias_above_threshold" in failures
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
    assert "pairwise_eval_accuracy_below_threshold" in failures
    assert "pairwise_eval_critical_accuracy_below_threshold" in failures
    assert "pairwise_eval_coverage_below_threshold" in failures
    assert "pairwise_eval_polish_bias_risks_above_threshold" in failures
    assert "pairwise_eval_report_failures_present" in failures


def test_publish_gate_evaluate_requires_pairwise_eval_report():
    metrics = {
        "irr_rank_kendalls_w": 1.0,
        "irr_mean_rubric_sd": 0.0,
        "model_coverage": 1.0,
        "boundary_count": 0,
        "anchors_total": 0,
        "cal_missing_assessors": [],
        "calibration_scope_samples": 0,
        "calibration_scope_observations": 0,
        "cal_level_hit_rate": 1.0,
        "cal_mae": 0.0,
        "cal_pairwise_order": 1.0,
        "cal_repeat_consistency": 1.0,
        "cal_abs_bias": 0.0,
        "benchmark_report_present": False,
        "pairwise_eval_present": False,
    }
    failures = pg.evaluate(metrics, {"require_pairwise_eval_report": True})
    assert "pairwise_eval_report_missing" in failures


def test_publish_gate_main_with_non_list_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_inputs(tmp_path)
    (tmp_path / "processing/submission_metadata.json").write_text(json.dumps({"bad": True}), encoding="utf-8")
    (tmp_path / "inputs/class_metadata.json").write_text(json.dumps({"grade_level": 5}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["publish_gate", "--output", "outputs/publish_gate.json"])
    code = pg.main()
    assert code in (0, 2)
    result = json.loads((tmp_path / "outputs/publish_gate.json").read_text(encoding="utf-8"))
    assert result["metrics"]["scope"] == "grade_4_5|literary_analysis"


def test_publish_gate_release_mode_rejects_synthetic_calibration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_inputs(tmp_path)
    (tmp_path / "outputs/calibration_manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-03-01T00:00:00+00:00",
                "synthetic": True,
                "scope_coverage": [
                    {
                        "key": "grade_8_10|argumentative",
                        "grade_band": "grade_8_10",
                        "genre": "argumentative",
                        "rubric_family": "rubric_unknown",
                        "model_family": "",
                    }
                ],
                "artifact_hashes": {"calibration_bias_sha256": file_sha256(tmp_path / "outputs/calibration_bias.json")},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "config/accuracy_gate.json").write_text(
        json.dumps(
            {
                "thresholds": {
                    "release_mode": "candidate",
                    "min_rank_kendall_w": 0.0,
                    "max_mean_rubric_sd": 999.0,
                    "min_model_coverage": 0.0,
                    "max_boundary_students": 99,
                    "calibration_min_level_hit_rate": 0.0,
                    "calibration_max_mae": 999.0,
                    "calibration_min_pairwise_order": 0.0,
                    "calibration_min_repeat_level_consistency": 0.0,
                    "calibration_max_abs_bias": 999.0,
                    "require_benchmark_report": False,
                    "calibration_require_manifest": True,
                    "calibration_require_production_profile": True,
                    "calibration_require_scope_match": True,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "publish_gate",
            "--gate-config",
            "config/accuracy_gate.json",
            "--output",
            "outputs/publish_gate.json",
        ],
    )
    assert pg.main() == 2
    result = json.loads((tmp_path / "outputs/publish_gate.json").read_text(encoding="utf-8"))
    assert "calibration_synthetic_not_allowed" in result["failures"]


def test_publish_gate_release_profile_contract_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_inputs(tmp_path)
    _write_benchmark_report(tmp_path / "outputs/benchmark_report.json")
    _write_calibration_manifest(
        tmp_path,
        synthetic=False,
        samples=12,
        observations=12,
        generated_at="2026-04-11T00:00:00+00:00",
    )
    _write_reproducibility_report(tmp_path / "outputs/reproducibility_report.json", exact=True, within_tolerance=True, max_delta=0.0)
    (tmp_path / "config/accuracy_gate.json").write_text(
        json.dumps(
            {
                "target_profile": "release",
                "profiles": {
                    "dev": {
                        "thresholds": {
                            "min_rank_kendall_w": 0.0,
                            "max_mean_rubric_sd": 999.0,
                            "min_model_coverage": 0.0,
                            "max_boundary_students": 99,
                            "calibration_min_level_hit_rate": 0.0,
                            "calibration_max_mae": 999.0,
                            "calibration_min_pairwise_order": 0.0,
                            "calibration_min_repeat_level_consistency": 0.0,
                            "calibration_max_abs_bias": 999.0,
                            "benchmark_mode": "main"
                        }
                    },
                    "candidate": {
                        "inherits": "dev",
                        "thresholds": {
                            "calibration_require_manifest": True,
                            "calibration_require_manifest_integrity": True,
                            "calibration_require_scope_match": True,
                            "calibration_require_production_profile": True,
                            "calibration_fail_on_drift": True,
                            "calibration_min_scope_samples": 8,
                            "calibration_min_scope_observations": 8,
                            "calibration_max_age_hours": 336,
                            "require_benchmark_report": True,
                            "benchmark_min_runs_successful": 2,
                            "benchmark_min_exact_level_hit_rate": 0.8,
                            "benchmark_min_within_one_level_hit_rate": 0.95,
                            "benchmark_max_score_band_mae": 2.0,
                            "benchmark_min_pairwise_order_agreement": 0.9,
                            "benchmark_max_mean_student_level_sd": 0.2,
                            "benchmark_max_mean_student_rank_sd": 0.2,
                            "benchmark_max_mean_student_score_sd": 1.0,
                            "reproducibility_require_report": True,
                            "reproducibility_min_runs_compared": 2,
                            "reproducibility_require_manifest_identical": True,
                            "reproducibility_require_within_tolerance": True
                        }
                    },
                    "release": {
                        "inherits": "candidate",
                        "thresholds": {
                            "reproducibility_require_exact_final_outputs": True,
                            "reproducibility_max_intermediate_metric_delta": 0.0
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "publish_gate",
            "--gate-config",
            "config/accuracy_gate.json",
            "--reproducibility-report",
            "outputs/reproducibility_report.json",
            "--output",
            "outputs/publish_gate.json",
        ],
    )
    assert pg.main() == 0
    result = json.loads((tmp_path / "outputs/publish_gate.json").read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["highest_attained_profile"] == "release"
    assert result["decision_state"] == "release_ready"
    assert result["profiles"]["release"]["ok"] is True


def test_publish_gate_release_profile_rejects_reproducibility_mismatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_inputs(tmp_path)
    _write_benchmark_report(tmp_path / "outputs/benchmark_report.json")
    _write_calibration_manifest(tmp_path, synthetic=False, samples=12, observations=12)
    _write_reproducibility_report(tmp_path / "outputs/reproducibility_report.json", exact=False, within_tolerance=False, max_delta=0.05)
    (tmp_path / "config/accuracy_gate.json").write_text(
        json.dumps(
            {
                "target_profile": "release",
                "profiles": {
                    "dev": {
                        "thresholds": {
                            "min_rank_kendall_w": 0.0,
                            "max_mean_rubric_sd": 999.0,
                            "min_model_coverage": 0.0,
                            "max_boundary_students": 99,
                            "calibration_min_level_hit_rate": 0.0,
                            "calibration_max_mae": 999.0,
                            "calibration_min_pairwise_order": 0.0,
                            "calibration_min_repeat_level_consistency": 0.0,
                            "calibration_max_abs_bias": 999.0,
                            "benchmark_mode": "main"
                        }
                    },
                    "release": {
                        "inherits": "dev",
                        "thresholds": {
                            "calibration_require_manifest": True,
                            "calibration_require_manifest_integrity": True,
                            "calibration_require_scope_match": True,
                            "calibration_require_production_profile": True,
                            "require_benchmark_report": True,
                            "benchmark_min_runs_successful": 2,
                            "benchmark_min_exact_level_hit_rate": 0.8,
                            "reproducibility_require_report": True,
                            "reproducibility_min_runs_compared": 2,
                            "reproducibility_require_manifest_identical": True,
                            "reproducibility_require_within_tolerance": True,
                            "reproducibility_require_exact_final_outputs": True,
                            "reproducibility_max_intermediate_metric_delta": 0.0
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "publish_gate",
            "--gate-config",
            "config/accuracy_gate.json",
            "--reproducibility-report",
            "outputs/reproducibility_report.json",
            "--output",
            "outputs/publish_gate.json",
        ],
    )
    assert pg.main() == 2
    result = json.loads((tmp_path / "outputs/publish_gate.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["highest_attained_profile"] == "dev"
    assert "reproducibility_final_outputs_mismatch" in result["failures"]
