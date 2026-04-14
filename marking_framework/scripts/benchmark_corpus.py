#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.benchmark_main_vs_fallback import REQUIRED_GOLD_FIELDS, ensure_dataset_shape, load_gold_rows  # noqa: E402


SUMMARY_VERSION = 1
METRICS = (
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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def discover_datasets(bench_root: Path) -> list[Path]:
    paths = []
    for child in sorted(bench_root.iterdir()):
        if not child.is_dir() or child.name == "runs" or child.name == "reports":
            continue
        try:
            _, _, gold_path = ensure_dataset_shape(child)
            load_gold_rows(gold_path)
        except Exception:
            continue
        paths.append(child)
    return paths


def weighted_mean(rows: list[tuple[float, int]]) -> float:
    total_weight = sum(weight for _, weight in rows)
    if total_weight <= 0:
        return 0.0
    return round(sum(value * weight for value, weight in rows) / total_weight, 6)


def summarize_mode(dataset_reports: list[dict], mode: str) -> dict:
    result = {}
    for metric in METRICS:
        weighted = []
        for report in dataset_reports:
            summary = report.get("modes", {}).get(mode, {}).get("summary", {})
            weight = int(report.get("dataset", {}).get("student_count", 0) or 0)
            weighted.append((float(summary.get(metric, 0.0) or 0.0), weight))
        result[metric] = weighted_mean(weighted)
    return result


def aggregate_level_confusion(dataset_reports: list[dict], mode: str) -> dict[str, dict[str, int]]:
    confusion: dict[str, dict[str, int]] = {}
    for report in dataset_reports:
        runs = report.get("modes", {}).get(mode, {}).get("runs", [])
        first_ok = next((row for row in runs if row.get("ok")), None)
        if not first_ok:
            continue
        for student in first_ok.get("students", {}).values():
            gold = str(student.get("gold_canonical_level") or student.get("gold_level", ""))
            predicted = str(student.get("predicted_level", ""))
            if not gold or not predicted:
                continue
            confusion.setdefault(gold, {})
            confusion[gold][predicted] = confusion[gold].get(predicted, 0) + 1
    return confusion


def collect_mismatches(dataset_reports: list[dict], mode: str, limit: int = 40) -> list[dict]:
    rows = []
    for report in dataset_reports:
        dataset_name = Path(report.get("dataset", {}).get("path", "")).name
        runs = report.get("modes", {}).get(mode, {}).get("runs", [])
        first_ok = next((row for row in runs if row.get("ok")), None)
        if not first_ok:
            continue
        for student in first_ok.get("students", {}).values():
            if student.get("exact_level_hit"):
                continue
            rows.append(
                {
                    "dataset": dataset_name,
                    "student_id": student.get("student_id"),
                    "display_name": student.get("display_name"),
                    "gold_level": student.get("gold_level"),
                    "gold_canonical_level": student.get("gold_canonical_level"),
                    "predicted_level": student.get("predicted_level"),
                    "predicted_score": student.get("predicted_score"),
                    "score_band_error": student.get("score_band_error"),
                    "gold_rank": student.get("gold_rank"),
                    "predicted_rank": student.get("predicted_rank"),
                    "rank_displacement": student.get("rank_displacement"),
                }
            )
    rows.sort(
        key=lambda row: (
            -abs(float(row.get("score_band_error", 0.0) or 0.0)),
            -abs(int(row.get("rank_displacement", 0) or 0)),
            row.get("dataset", ""),
            row.get("student_id", ""),
        )
    )
    return rows[:limit]


def compare_modes(dataset_reports: list[dict], candidate: str, baseline: str) -> dict:
    candidate_summary = summarize_mode(dataset_reports, candidate)
    baseline_summary = summarize_mode(dataset_reports, baseline)
    delta = {}
    for metric in METRICS:
        delta[metric] = round(candidate_summary.get(metric, 0.0) - baseline_summary.get(metric, 0.0), 6)
    return {
        "candidate_mode": candidate,
        "baseline_mode": baseline,
        "candidate_weighted_summary": candidate_summary,
        "baseline_weighted_summary": baseline_summary,
        "delta": delta,
    }


def build_markdown(summary: dict) -> str:
    lines = [
        "# Benchmark Corpus Summary",
        "",
        f"- Generated: {summary['generated_at']}",
        f"- Datasets: {summary['dataset_count']}",
        f"- Students: {summary['student_count']}",
        f"- Runs per dataset mode: {summary['runs_per_dataset_mode']}",
        "",
        "## Candidate Summary",
    ]
    candidate = summary["comparison"]["candidate_weighted_summary"]
    lines.extend(
        [
            f"- Exact-level hit rate: {candidate['exact_level_hit_rate_mean']:.4f}",
            f"- Within-one-level hit rate: {candidate['within_one_level_hit_rate_mean']:.4f}",
            f"- Score-band MAE: {candidate['score_band_mae_mean']:.4f}",
            f"- Mean rank displacement: {candidate['mean_rank_displacement_mean']:.4f}",
            f"- Kendall tau: {candidate['kendall_tau_mean']:.4f}",
            f"- Pairwise order agreement: {candidate['pairwise_order_agreement_mean']:.4f}",
            f"- Cost (USD): {candidate['cost_usd_mean']:.4f}",
            f"- Latency (s): {candidate['latency_seconds_mean']:.4f}",
            "",
            "## Candidate vs Baseline Delta",
        ]
    )
    delta = summary["comparison"]["delta"]
    lines.extend(
        [
            f"- Exact-level hit delta: {delta['exact_level_hit_rate_mean']:.4f}",
            f"- Within-one-level hit delta: {delta['within_one_level_hit_rate_mean']:.4f}",
            f"- Score-band MAE delta: {delta['score_band_mae_mean']:.4f}",
            f"- Mean rank displacement delta: {delta['mean_rank_displacement_mean']:.4f}",
            f"- Kendall tau delta: {delta['kendall_tau_mean']:.4f}",
            f"- Pairwise order agreement delta: {delta['pairwise_order_agreement_mean']:.4f}",
            "",
            "## Dataset Summaries",
        ]
    )
    failures = summary.get("failed_datasets", [])
    if failures:
        lines.extend(["", "## Failures"])
        for row in failures:
            lines.append(f"- {row['name']} ({row['mode']}): {row['error']}")
    for dataset in summary["datasets"]:
        lines.extend(
            [
                "",
                f"### {dataset['name']}",
                f"- Students: {dataset['student_count']}",
                f"- Candidate exact-level hit rate: {dataset['candidate_summary']['exact_level_hit_rate_mean']:.4f}",
                f"- Candidate within-one-level hit rate: {dataset['candidate_summary']['within_one_level_hit_rate_mean']:.4f}",
                f"- Candidate score-band MAE: {dataset['candidate_summary']['score_band_mae_mean']:.4f}",
                f"- Candidate Kendall tau: {dataset['candidate_summary']['kendall_tau_mean']:.4f}",
                f"- Candidate pairwise agreement: {dataset['candidate_summary']['pairwise_order_agreement_mean']:.4f}",
                f"- Candidate cost (USD): {dataset['candidate_summary']['cost_usd_mean']:.4f}",
                f"- Candidate latency (s): {dataset['candidate_summary']['latency_seconds_mean']:.4f}",
            ]
        )
    mismatches = summary.get("candidate_mismatches", [])
    if mismatches:
        lines.extend(["", "## Largest Candidate Misses"])
        for row in mismatches[:20]:
            gold_label = str(row.get("gold_level") or "")
            gold_canonical = str(row.get("gold_canonical_level") or gold_label)
            if gold_label and gold_label != gold_canonical:
                gold_display = f"{gold_label} (canon {gold_canonical})"
            else:
                gold_display = gold_canonical
            lines.append(
                f"- {row['dataset']} / {row['display_name']} ({row['student_id']}): gold {gold_display}, predicted {row['predicted_level']}, "
                f"score-band error {float(row['score_band_error'] or 0.0):.2f}, rank displacement {int(row['rank_displacement'] or 0)}"
            )
    return "\n".join(lines) + "\n"


def run_benchmark(dataset: Path, output_dir: Path, runs: int, candidate_routing: str, baseline_routing: str, candidate_label: str, baseline_label: str) -> dict:
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "benchmark_main_vs_fallback.py"),
        "--dataset",
        str(dataset),
        "--runs",
        str(runs),
        "--output",
        str(output_dir),
        "--candidate-routing",
        candidate_routing,
        "--candidate-label",
        candidate_label,
        "--baseline-label",
        baseline_label,
    ]
    if baseline_routing:
        cmd.extend(["--baseline-routing", baseline_routing])
    result = subprocess.run(cmd, cwd=str(repo_root), check=False)
    if result.returncode not in {0, 2}:
        raise subprocess.CalledProcessError(result.returncode, cmd)
    report_path = output_dir / "benchmark_report.json"
    return json.loads(report_path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the explicit-gold benchmark harness across every benchmark dataset in the corpus.")
    parser.add_argument("--bench-root", default="bench", help="Benchmark root")
    parser.add_argument("--runs", type=int, default=1, help="Runs per mode per dataset")
    parser.add_argument("--candidate-routing", default="config/llm_routing_benchmark.json", help="Candidate routing path, repo-relative")
    parser.add_argument("--baseline-routing", default="", help="Optional baseline routing path, repo-relative")
    parser.add_argument("--candidate-label", default="main", help="Candidate mode label")
    parser.add_argument("--baseline-label", default="fallback", help="Baseline mode label")
    parser.add_argument("--dataset", action="append", default=[], help="Optional dataset directory name to run; repeatable")
    parser.add_argument("--output", default="", help="Summary output directory")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    bench_root = (repo_root / args.bench_root).resolve()
    candidates = discover_datasets(bench_root)
    if args.dataset:
        wanted = {name.strip() for name in args.dataset if name.strip()}
        candidates = [path for path in candidates if path.name in wanted]
        missing = sorted(wanted - {path.name for path in candidates})
        if missing:
            raise SystemExit(f"Unknown dataset(s): {', '.join(missing)}")
    if not candidates:
        raise SystemExit("No explicit-gold datasets found to benchmark.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output).resolve() if args.output else (bench_root / "reports" / f"corpus_{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    dataset_reports = []
    dataset_rows = []
    failed_datasets = []
    for dataset in candidates:
        report = run_benchmark(
            dataset,
            out_dir / dataset.name,
            args.runs,
            args.candidate_routing,
            args.baseline_routing,
            args.candidate_label,
            args.baseline_label,
        )
        dataset_reports.append(report)
        for mode_name in (args.candidate_label, args.baseline_label):
            mode_payload = report.get("modes", {}).get(mode_name, {})
            summary_payload = mode_payload.get("summary", {})
            if int(summary_payload.get("runs_successful", 0) or 0) > 0:
                continue
            first_failed = next((row for row in mode_payload.get("runs", []) if not row.get("ok")), {})
            failed_datasets.append(
                {
                    "name": dataset.name,
                    "mode": mode_name,
                    "error": str(first_failed.get("error") or "no successful runs recorded").strip(),
                }
            )
        dataset_rows.append(
            {
                "name": dataset.name,
                "path": str(dataset),
                "student_count": int(report.get("dataset", {}).get("student_count", 0) or 0),
                "candidate_summary": report.get("modes", {}).get(args.candidate_label, {}).get("summary", {}),
                "baseline_summary": report.get("modes", {}).get(args.baseline_label, {}).get("summary", {}),
                "comparison": report.get("comparison", {}),
            }
        )

    summary = {
        "summary_version": SUMMARY_VERSION,
        "generated_at": now_iso(),
        "dataset_count": len(dataset_rows),
        "student_count": sum(row["student_count"] for row in dataset_rows),
        "runs_per_dataset_mode": args.runs,
        "datasets": dataset_rows,
        "comparison": compare_modes(dataset_reports, args.candidate_label, args.baseline_label),
        "candidate_level_confusion": aggregate_level_confusion(dataset_reports, args.candidate_label),
        "candidate_mismatches": collect_mismatches(dataset_reports, args.candidate_label),
        "failed_datasets": failed_datasets,
    }
    summary_json = out_dir / "benchmark_corpus_summary.json"
    summary_md = out_dir / "benchmark_corpus_summary.md"
    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    summary_md.write_text(build_markdown(summary), encoding="utf-8")
    print(f"Wrote {summary_json}")
    print(f"Wrote {summary_md}")
    return 2 if failed_datasets else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
