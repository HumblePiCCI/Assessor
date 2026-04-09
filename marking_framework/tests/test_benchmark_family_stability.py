import json

from scripts import benchmark_family_stability as bfs


def _dataset_row(name: str, student_count: int, family_key: str, *, exact: float, mae: float, level_var: float) -> dict:
    source_family, genre, cohort_shape = [part.strip() for part in family_key.split("|")]
    candidate = {
        metric: 0.0 for metric in bfs.SUMMARY_METRICS
    }
    baseline = {
        metric: 0.0 for metric in bfs.SUMMARY_METRICS
    }
    candidate["exact_level_hit_rate_mean"] = exact
    candidate["score_band_mae_mean"] = mae
    candidate["mean_student_level_variance"] = level_var
    baseline["exact_level_hit_rate_mean"] = exact - 0.1
    baseline["score_band_mae_mean"] = mae + 0.2
    baseline["mean_student_level_variance"] = level_var + 0.01
    return {
        "name": name,
        "path": f"bench/{name}",
        "student_count": student_count,
        "source_family": source_family,
        "genre": genre,
        "cohort_shape": cohort_shape,
        "family_key": family_key,
        "candidate_summary": candidate,
        "baseline_summary": baseline,
        "delta": {
            "exact_level_hit_rate_mean": round(candidate["exact_level_hit_rate_mean"] - baseline["exact_level_hit_rate_mean"], 6),
            "score_band_mae_mean": round(candidate["score_band_mae_mean"] - baseline["score_band_mae_mean"], 6),
            "kendall_tau_mean": 0.0,
            "pairwise_order_agreement_mean": 0.0,
            "within_one_level_hit_rate_mean": 0.0,
            "mean_rank_displacement_mean": 0.0,
            "max_rank_displacement_mean": 0.0,
            "model_usage_ratio_mean": 0.0,
            "cost_usd_mean": 0.0,
            "latency_seconds_mean": 0.0,
            "mean_student_level_variance": -0.01,
            "mean_student_rank_variance": 0.0,
            "mean_student_score_variance": 0.0,
        },
        "candidate_unstable_students": [{"dataset": name, "student_id": "s1", "level_variance": level_var, "rank_variance": 0.0, "score_variance": 0.0}],
    }


def test_load_dataset_metadata_normalizes_family_key(tmp_path):
    dataset = tmp_path / "bench" / "x"
    (dataset / "inputs").mkdir(parents=True)
    (dataset / "inputs" / "class_metadata.json").write_text(
        json.dumps(
            {
                "source_family": "Thoughtful",
                "assignment_genre": "opinion letter",
                "cohort_shape": "same_rubric_family_cross_topic",
            }
        ),
        encoding="utf-8",
    )
    metadata = bfs.load_dataset_metadata(dataset)
    assert metadata["genre"] == "argumentative"
    assert metadata["family_key"] == "Thoughtful | argumentative | same_rubric_family_cross_topic"


def test_cluster_families_aggregates_weighted_metrics():
    rows = [
        _dataset_row("a", 4, "Thoughtful | argumentative | same_rubric_family_cross_topic", exact=0.5, mae=4.0, level_var=0.2),
        _dataset_row("b", 8, "Thoughtful | argumentative | same_rubric_family_cross_topic", exact=0.75, mae=2.0, level_var=0.1),
        _dataset_row("c", 6, "NAEP | narrative | single_prompt", exact=0.6, mae=3.0, level_var=0.3),
    ]
    clusters = bfs.cluster_families(rows)
    thoughtful = next(row for row in clusters if row["family_key"] == "Thoughtful | argumentative | same_rubric_family_cross_topic")
    assert thoughtful["students"] == 12
    assert thoughtful["dataset_count"] == 2
    assert thoughtful["candidate_summary"]["exact_level_hit_rate_mean"] == 0.666667
    assert thoughtful["candidate_summary"]["score_band_mae_mean"] == 2.666667
    assert thoughtful["delta"]["exact_level_hit_rate_mean"] == 0.1
    assert thoughtful["top_unstable_students"][0]["dataset"] == "a"


def test_lagging_families_filters_negative_exact_or_positive_mae():
    cluster = {
        "family_key": "Thoughtful | argumentative | same_rubric_family_cross_topic",
        "delta": {
            "exact_level_hit_rate_mean": -0.25,
            "score_band_mae_mean": 0.4,
            "kendall_tau_mean": 0.0,
            "pairwise_order_agreement_mean": 0.0,
        },
    }
    ok_cluster = {
        "family_key": "NAEP | narrative | single_prompt",
        "delta": {
            "exact_level_hit_rate_mean": 0.1,
            "score_band_mae_mean": -0.2,
            "kendall_tau_mean": 0.1,
            "pairwise_order_agreement_mean": 0.05,
        },
    }
    assert bfs.lagging_families([cluster, ok_cluster], True) == [cluster]
