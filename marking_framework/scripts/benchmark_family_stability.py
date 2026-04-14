#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import benchmark_corpus as bc  # noqa: E402
from scripts.assessor_context import load_class_metadata, normalize_genre  # noqa: E402
from scripts.benchmark_main_vs_fallback import (  # noqa: E402
    build_mode_env,
    ensure_dataset_shape,
    evaluate_run,
    load_gold_rows,
    setup_run,
    summarize_runs,
    write_routing_files,
    run_pipeline,
)


SUMMARY_METRICS = (
    "exact_level_hit_rate_mean",
    "within_one_level_hit_rate_mean",
    "score_band_mae_mean",
    "mean_rank_displacement_mean",
    "max_rank_displacement_mean",
    "kendall_tau_mean",
    "pairwise_order_agreement_mean",
    "model_usage_ratio_mean",
    "cost_usd_mean",
    "latency_seconds_mean",
)
STABILITY_METRICS = (
    "mean_student_level_variance",
    "mean_student_rank_variance",
    "mean_student_score_variance",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_dataset_metadata(dataset: Path) -> dict:
    metadata = load_class_metadata(dataset / "inputs" / "class_metadata.json")
    source_family = str(metadata.get("source_family") or "unknown").strip() or "unknown"
    genre = normalize_genre(
        metadata.get("genre")
        or metadata.get("assignment_genre")
        or metadata.get("genre_form")
        or metadata.get("assessment_unit")
    ) or "unknown"
    cohort_shape = str(metadata.get("cohort_shape") or metadata.get("cohort_coherence") or "unknown").strip() or "unknown"
    return {
        "source_family": source_family,
        "genre": genre,
        "cohort_shape": cohort_shape,
        "family_key": f"{source_family} | {genre} | {cohort_shape}",
    }


def flatten_mode_summary(summary: dict) -> dict:
    flat = {metric: float(summary.get(metric, 0.0) or 0.0) for metric in SUMMARY_METRICS}
    stability = summary.get("stability", {}) if isinstance(summary, dict) else {}
    for metric in STABILITY_METRICS:
        flat[metric] = float(stability.get(metric, 0.0) or 0.0)
    return flat


def compare_mode_summaries(candidate: dict, baseline: dict) -> dict:
    delta = {}
    candidate_flat = flatten_mode_summary(candidate)
    baseline_flat = flatten_mode_summary(baseline)
    for metric in (*SUMMARY_METRICS, *STABILITY_METRICS):
        delta[metric] = round(candidate_flat.get(metric, 0.0) - baseline_flat.get(metric, 0.0), 6)
    return delta


def collect_top_unstable_students(summary: dict, dataset_name: str, limit: int = 5) -> list[dict]:
    stability = summary.get("stability", {}) if isinstance(summary, dict) else {}
    per_student = stability.get("per_student", {}) if isinstance(stability, dict) else {}
    rows = []
    for student_id, data in per_student.items():
        if not isinstance(data, dict):
            continue
        rows.append(
            {
                "dataset": dataset_name,
                "student_id": student_id,
                "level_variance": round(float(data.get("level_variance", 0.0) or 0.0), 6),
                "rank_variance": round(float(data.get("rank_variance", 0.0) or 0.0), 6),
                "score_variance": round(float(data.get("score_variance", 0.0) or 0.0), 6),
                "levels": list(data.get("levels", [])),
                "ranks": list(data.get("ranks", [])),
                "scores": list(data.get("scores", [])),
            }
        )
    rows.sort(
        key=lambda row: (
            -row["level_variance"],
            -row["rank_variance"],
            -row["score_variance"],
            row["dataset"],
            row["student_id"],
        )
    )
    return rows[:limit]


def dataset_result(report: dict, dataset: Path, candidate_label: str, baseline_label: str) -> dict:
    dataset_name = dataset.name
    metadata = load_dataset_metadata(dataset)
    student_count = int(report.get("dataset", {}).get("student_count", 0) or 0)
    candidate_summary = report.get("modes", {}).get(candidate_label, {}).get("summary", {})
    baseline_summary = report.get("modes", {}).get(baseline_label, {}).get("summary", {})
    candidate_unstable = collect_top_unstable_students(candidate_summary, dataset_name)
    return {
        "name": dataset_name,
        "path": str(dataset),
        "student_count": student_count,
        **metadata,
        "candidate_summary": flatten_mode_summary(candidate_summary),
        "baseline_summary": flatten_mode_summary(baseline_summary),
        "delta": compare_mode_summaries(candidate_summary, baseline_summary),
        "candidate_unstable_students": candidate_unstable,
    }


def weighted_snapshot(rows: list[dict], key: str) -> dict:
    result = {}
    for metric in (*SUMMARY_METRICS, *STABILITY_METRICS):
        weighted = [(float(row.get(key, {}).get(metric, 0.0) or 0.0), int(row.get("student_count", 0) or 0)) for row in rows]
        result[metric] = bc.weighted_mean(weighted)
    return result


def cluster_families(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["family_key"], []).append(row)
    clusters = []
    for family_key, items in sorted(grouped.items()):
        unstable = []
        for row in items:
            unstable.extend(row.get("candidate_unstable_students", []))
        unstable.sort(
            key=lambda row: (
                -float(row.get("level_variance", 0.0) or 0.0),
                -float(row.get("rank_variance", 0.0) or 0.0),
                -float(row.get("score_variance", 0.0) or 0.0),
                row.get("dataset", ""),
                row.get("student_id", ""),
            )
        )
        clusters.append(
            {
                "family_key": family_key,
                "students": sum(int(row.get("student_count", 0) or 0) for row in items),
                "dataset_count": len(items),
                "datasets": [row["name"] for row in items],
                "candidate_summary": weighted_snapshot(items, "candidate_summary"),
                "baseline_summary": weighted_snapshot(items, "baseline_summary"),
                "delta": weighted_snapshot(items, "delta"),
                "top_unstable_students": unstable[:6],
            }
        )
    clusters.sort(
        key=lambda row: (
            float(row["delta"].get("exact_level_hit_rate_mean", 0.0) or 0.0),
            -float(row["delta"].get("score_band_mae_mean", 0.0) or 0.0),
            float(row["delta"].get("pairwise_order_agreement_mean", 0.0) or 0.0),
            -float(row["candidate_summary"].get("mean_student_rank_variance", 0.0) or 0.0),
            row["family_key"],
        )
    )
    return clusters


def lagging_families(clusters: list[dict], has_baseline: bool) -> list[dict]:
    if not has_baseline:
        return list(clusters)
    rows = []
    for row in clusters:
        delta = row.get("delta", {})
        if (
            float(delta.get("exact_level_hit_rate_mean", 0.0) or 0.0) < 0.0
            or float(delta.get("score_band_mae_mean", 0.0) or 0.0) > 0.0
            or float(delta.get("kendall_tau_mean", 0.0) or 0.0) < 0.0
            or float(delta.get("pairwise_order_agreement_mean", 0.0) or 0.0) < 0.0
        ):
            rows.append(row)
    return rows


def build_markdown(summary: dict) -> str:
    has_baseline = bool(summary.get("has_baseline"))
    lines = [
        "# Family Stability Benchmark",
        "",
        f"- Generated: {summary['generated_at']}",
        f"- Datasets: {summary['dataset_count']}",
        f"- Students: {summary['student_count']}",
        f"- Runs per dataset mode: {summary['runs_per_dataset_mode']}",
        f"- Candidate label: {summary['candidate_label']}",
        f"- Baseline label: {summary['baseline_label'] or 'none'}",
        "",
        "## Overall Candidate Summary",
    ]
    candidate = summary["overall"]["candidate_summary"]
    baseline = summary["overall"]["baseline_summary"]
    delta = summary["overall"]["delta"]
    lines.extend(
        [
            f"- Exact-level hit rate: {candidate['exact_level_hit_rate_mean']:.4f}",
            f"- Within-one-level hit rate: {candidate['within_one_level_hit_rate_mean']:.4f}",
            f"- Score-band MAE: {candidate['score_band_mae_mean']:.4f}",
            f"- Kendall tau: {candidate['kendall_tau_mean']:.4f}",
            f"- Pairwise agreement: {candidate['pairwise_order_agreement_mean']:.4f}",
            f"- Mean student level variance: {candidate['mean_student_level_variance']:.6f}",
            f"- Mean student rank variance: {candidate['mean_student_rank_variance']:.6f}",
            f"- Mean student score variance: {candidate['mean_student_score_variance']:.6f}",
            "",
        ]
    )
    if has_baseline:
        lines.extend(
            [
                "",
                "## Candidate vs Baseline Delta",
                f"- Exact-level hit delta: {delta['exact_level_hit_rate_mean']:.4f}",
                f"- Within-one-level hit delta: {delta['within_one_level_hit_rate_mean']:.4f}",
                f"- Score-band MAE delta: {delta['score_band_mae_mean']:.4f}",
                f"- Kendall tau delta: {delta['kendall_tau_mean']:.4f}",
                f"- Pairwise agreement delta: {delta['pairwise_order_agreement_mean']:.4f}",
                f"- Mean student level variance delta: {delta['mean_student_level_variance']:.6f}",
                f"- Mean student rank variance delta: {delta['mean_student_rank_variance']:.6f}",
                f"- Mean student score variance delta: {delta['mean_student_score_variance']:.6f}",
                "",
                "## Lagging Families",
            ]
        )
    else:
        lines.extend(["", "## Candidate Family Stability"])
    if not summary["lagging_families"]:
        lines.append("- None.")
    for cluster in summary["lagging_families"]:
        candidate_cluster = cluster["candidate_summary"]
        delta_cluster = cluster["delta"]
        lines.extend(
            [
                "",
                f"### {cluster['family_key']}",
                f"- Datasets: {', '.join(cluster['datasets'])}",
                f"- Students: {cluster['students']}",
                f"- Candidate exact-level hit: {candidate_cluster['exact_level_hit_rate_mean']:.4f}",
                f"- Candidate score-band MAE: {candidate_cluster['score_band_mae_mean']:.4f}",
                f"- Candidate Kendall tau: {candidate_cluster['kendall_tau_mean']:.4f}",
                f"- Candidate pairwise agreement: {candidate_cluster['pairwise_order_agreement_mean']:.4f}",
                f"- Candidate mean student rank variance: {candidate_cluster['mean_student_rank_variance']:.6f}",
            ]
        )
        if has_baseline:
            lines.extend(
                [
                    f"- Exact delta vs baseline: {delta_cluster['exact_level_hit_rate_mean']:.4f}",
                    f"- MAE delta vs baseline: {delta_cluster['score_band_mae_mean']:.4f}",
                    f"- Pairwise delta vs baseline: {delta_cluster['pairwise_order_agreement_mean']:.4f}",
                ]
            )
        if cluster["top_unstable_students"]:
            lines.append("- Most unstable candidate students:")
            for student in cluster["top_unstable_students"][:3]:
                lines.append(
                    f"  - {student['dataset']} / {student['student_id']}: level_var {student['level_variance']:.6f}, "
                    f"rank_var {student['rank_variance']:.6f}, score_var {student['score_variance']:.6f}"
                )
    return "\n".join(lines) + "\n"


def write_report(output_dir: Path, summary: dict):
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "benchmark_family_stability.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output_dir / "benchmark_family_stability.md").write_text(build_markdown(summary), encoding="utf-8")


def run_candidate_only_benchmark(dataset: Path, output_dir: Path, runs: int, candidate_routing: str, candidate_label: str) -> dict:
    repo_root = Path(__file__).resolve().parents[1]
    inputs_dir, submissions_dir, gold_path = ensure_dataset_shape(dataset)
    gold_rows = load_gold_rows(gold_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    routing_specs = write_routing_files(
        output_dir,
        (repo_root / candidate_routing).resolve(),
        None,
        candidate_label,
        "codex_local_fallback_unused",
    )
    spec = routing_specs[0]
    report = {
        "dataset": {"path": str(dataset), "student_count": len(gold_rows)},
        "modes": {
            candidate_label: {
                "summary": {},
                "runs": [],
            }
        },
    }
    base_env = os.environ.copy()
    for run_idx in range(1, runs + 1):
        run_dir = output_dir / candidate_label / f"run_{run_idx}"
        setup_run(inputs_dir, submissions_dir, repo_root, run_dir)
        routing_out = run_dir / spec["routing_path"].name
        routing_out.write_text(spec["routing_path"].read_text(encoding="utf-8"), encoding="utf-8")
        shared_cache_dir = output_dir / "_shared_cache" / spec["label"]
        env = build_mode_env(
            base_env,
            spec.get("forced_llm_mode"),
            shared_cache_dir=shared_cache_dir,
        )
        ok, error, latency_seconds = run_pipeline(run_dir, routing_out, env, bool(spec["require_model_usage"]))
        payload = {"run": run_idx, "ok": ok}
        if ok:
            payload.update(evaluate_run(run_dir, gold_rows, latency_seconds=latency_seconds))
        else:
            payload["error"] = error
            payload["latency_seconds"] = round(latency_seconds, 6)
        report["modes"][candidate_label]["runs"].append(payload)
    report["modes"][candidate_label]["summary"] = summarize_runs(report["modes"][candidate_label]["runs"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run repeated-run benchmark slices and cluster the results by source/genre family.")
    parser.add_argument("--bench-root", default="bench", help="Benchmark root")
    parser.add_argument("--runs", type=int, default=3, help="Runs per mode per dataset")
    parser.add_argument("--candidate-routing", default="config/llm_routing_benchmark.json", help="Candidate routing path, repo-relative")
    parser.add_argument("--baseline-routing", default="config/llm_routing_benchmark_gpt52.json", help="Baseline routing path, repo-relative")
    parser.add_argument("--candidate-label", default="gpt54_split", help="Candidate mode label")
    parser.add_argument("--baseline-label", default="gpt52_legacy", help="Baseline mode label")
    parser.add_argument("--candidate-only", action="store_true", help="Skip baseline runs and summarize repeated candidate-only stability.")
    parser.add_argument("--dataset", action="append", default=[], help="Dataset directory name to run; repeatable")
    parser.add_argument("--output", required=True, help="Output directory")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    bench_root = (repo_root / args.bench_root).resolve()
    datasets = bc.discover_datasets(bench_root)
    if args.dataset:
        wanted = {name.strip() for name in args.dataset if name.strip()}
        datasets = [path for path in datasets if path.name in wanted]
        missing = sorted(wanted - {path.name for path in datasets})
        if missing:
            raise SystemExit(f"Unknown dataset(s): {', '.join(missing)}")
    if not datasets:
        raise SystemExit("No benchmark datasets selected.")

    output_dir = Path(args.output).resolve()
    dataset_rows = []
    has_baseline = bool(args.baseline_routing) and not args.candidate_only
    for dataset in datasets:
        if has_baseline:
            report = bc.run_benchmark(
                dataset,
                output_dir / dataset.name,
                args.runs,
                args.candidate_routing,
                args.baseline_routing,
                args.candidate_label,
                args.baseline_label,
            )
        else:
            report = run_candidate_only_benchmark(
                dataset,
                output_dir / dataset.name,
                args.runs,
                args.candidate_routing,
                args.candidate_label,
            )
        dataset_rows.append(dataset_result(report, dataset, args.candidate_label, args.baseline_label))

    family_clusters = cluster_families(dataset_rows)
    summary = {
        "generated_at": now_iso(),
        "dataset_count": len(dataset_rows),
        "student_count": sum(int(row.get("student_count", 0) or 0) for row in dataset_rows),
        "runs_per_dataset_mode": int(args.runs),
        "candidate_label": args.candidate_label,
        "baseline_label": args.baseline_label if has_baseline else "",
        "has_baseline": has_baseline,
        "datasets": dataset_rows,
        "overall": {
            "candidate_summary": weighted_snapshot(dataset_rows, "candidate_summary"),
            "baseline_summary": weighted_snapshot(dataset_rows, "baseline_summary"),
            "delta": weighted_snapshot(dataset_rows, "delta"),
        },
        "family_clusters": family_clusters,
        "lagging_families": lagging_families(family_clusters, has_baseline),
    }
    write_report(output_dir, summary)
    print(f"Wrote family stability report to {output_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
