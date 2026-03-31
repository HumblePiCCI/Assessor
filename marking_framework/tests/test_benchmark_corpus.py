import json
from pathlib import Path

from scripts import benchmark_corpus as bc


def _report(dataset: str, student_count: int, *, candidate: dict, baseline: dict, students: dict | None = None) -> dict:
    return {
        "dataset": {"path": dataset, "student_count": student_count},
        "modes": {
            "main": {
                "summary": candidate,
                "runs": [{"run": 1, "ok": True, "students": students or {}}],
            },
            "fallback": {
                "summary": baseline,
                "runs": [{"run": 1, "ok": True, "students": students or {}}],
            },
        },
    }


def test_summarize_mode_weighted_mean():
    reports = [
        _report(
            "bench/a",
            4,
            candidate={
                "exact_level_hit_rate_mean": 0.5,
                "within_one_level_hit_rate_mean": 1.0,
                "score_band_mae_mean": 2.0,
                "mean_rank_displacement_mean": 1.0,
                "max_rank_displacement_mean": 2.0,
                "kendall_tau_mean": 0.5,
                "pairwise_order_agreement_mean": 0.75,
                "model_usage_ratio_mean": 1.0,
                "cost_usd_mean": 0.2,
                "latency_seconds_mean": 10.0,
            },
            baseline={metric: 0.0 for metric in bc.METRICS},
        ),
        _report(
            "bench/b",
            8,
            candidate={
                "exact_level_hit_rate_mean": 0.75,
                "within_one_level_hit_rate_mean": 0.875,
                "score_band_mae_mean": 1.0,
                "mean_rank_displacement_mean": 0.5,
                "max_rank_displacement_mean": 1.0,
                "kendall_tau_mean": 1.0,
                "pairwise_order_agreement_mean": 1.0,
                "model_usage_ratio_mean": 1.0,
                "cost_usd_mean": 0.3,
                "latency_seconds_mean": 20.0,
            },
            baseline={metric: 0.0 for metric in bc.METRICS},
        ),
    ]
    summary = bc.summarize_mode(reports, "main")
    assert summary["exact_level_hit_rate_mean"] == 0.666667
    assert summary["score_band_mae_mean"] == 1.333333
    assert summary["latency_seconds_mean"] == 16.666667


def test_collect_mismatches_and_confusion():
    students = {
        "s001": {
            "student_id": "s001",
            "display_name": "Strong Essay",
            "gold_level": "4",
            "predicted_level": "3",
            "predicted_score": 76.0,
            "score_band_error": 4.0,
            "gold_rank": 1,
            "predicted_rank": 1,
            "rank_displacement": 0,
            "exact_level_hit": False,
        },
        "s002": {
            "student_id": "s002",
            "display_name": "Good Essay",
            "gold_level": "3",
            "predicted_level": "3",
            "predicted_score": 74.0,
            "score_band_error": 0.0,
            "gold_rank": 2,
            "predicted_rank": 2,
            "rank_displacement": 0,
            "exact_level_hit": True,
        },
    }
    report = _report(
        "bench/example_dataset",
        2,
        candidate={metric: 0.0 for metric in bc.METRICS},
        baseline={metric: 0.0 for metric in bc.METRICS},
        students=students,
    )
    mismatches = bc.collect_mismatches([report], "main")
    assert len(mismatches) == 1
    assert mismatches[0]["dataset"] == "example_dataset"
    confusion = bc.aggregate_level_confusion([report], "main")
    assert confusion == {"3": {"3": 1}, "4": {"3": 1}}


def test_run_benchmark_allows_return_code_two(tmp_path, monkeypatch):
    out_dir = tmp_path / "report"
    out_dir.mkdir(parents=True)
    expected = {"dataset": {"path": "bench/example", "student_count": 4}, "modes": {}}
    (out_dir / "benchmark_report.json").write_text(json.dumps(expected), encoding="utf-8")

    calls = {}

    class Result:
        returncode = 2

    def fake_run(cmd, cwd, check):
        calls["cmd"] = cmd
        calls["cwd"] = cwd
        calls["check"] = check
        return Result()

    monkeypatch.setattr(bc.subprocess, "run", fake_run)
    got = bc.run_benchmark(Path("bench/example"), out_dir, 1, "config/llm_routing_benchmark.json", "", "main", "fallback")
    assert got == expected
    assert calls["check"] is False
