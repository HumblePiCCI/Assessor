#!/usr/bin/env python3
"""Offline rerank stability harness.

Live judge nondeterminism flips a few percent of pairwise verdicts between
runs (worst on close pairs). This harness simulates that: it perturbs the
judgment set with a seeded RNG (flipping or dropping a fraction of low/medium
confidence judgments), re-runs the deterministic rerank per perturbation, and
measures how much the final order moves. Lower movement = a rerank layer that
absorbs judge noise instead of amplifying it.

Fully offline and deterministic for a given --seed.

Usage:
  python3 scripts/stability_harness.py \
    --scores outputs/consensus_scores.csv \
    --judgments outputs/consistency_checks.committee_edge.json \
    --runs 20 --flip-rate 0.08 --drop-rate 0.05 \
    --output outputs/stability_report.json
"""
import argparse
import copy
import json
import random
import statistics
import tempfile
from pathlib import Path

try:
    from scripts.global_rerank import run_global_rerank
except ImportError:  # pragma: no cover - script execution
    from global_rerank import run_global_rerank  # pragma: no cover


def perturb_payload(payload: dict, rng: random.Random, flip_rate: float, drop_rate: float) -> dict:
    """Flip or drop a fraction of non-high-confidence checks."""
    out = copy.deepcopy(payload)
    checks = out.get("checks", out.get("judgments", []))
    kept = []
    for check in checks:
        confidence = str(check.get("confidence", "") or "").strip().lower()
        perturbable = confidence in {"low", "medium", ""}
        roll = rng.random()
        if perturbable and roll < drop_rate:
            continue
        if perturbable and roll < drop_rate + flip_rate:
            check = dict(check)
            check["decision"] = "SWAP" if str(check.get("decision", "")).upper() == "KEEP" else "KEEP"
            check.pop("winner_side", None)
        kept.append(check)
    if "checks" in out:
        out["checks"] = kept
    else:
        out["judgments"] = kept
    return out


def rerank_order(scores_path: Path, judgments_path: Path, config_path: Path, cohort_confidence_path: Path | None, seed_trust_mode: str, workdir: Path) -> list[str]:
    result = run_global_rerank(
        scores_path=scores_path,
        judgments_path=judgments_path,
        config_path=config_path,
        local_prior_path=workdir / "missing_local_prior.json",
        final_order_path=workdir / "final_order.csv",
        matrix_output_path=workdir / "pairwise_matrix.json",
        score_output_path=workdir / "rerank_scores.csv",
        report_output_path=workdir / "consistency_report.json",
        legacy_output_path=workdir / "consistency_adjusted.csv",
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
        cohort_confidence_path=cohort_confidence_path,
        seed_trust_mode=seed_trust_mode,
    )
    ordered = sorted(result["final_rows"], key=lambda row: int(row["final_rank"]))
    return [row["student_id"] for row in ordered]


def stability_metrics(base_order: list[str], orders: list[list[str]]) -> dict:
    base_rank = {sid: idx + 1 for idx, sid in enumerate(base_order)}
    per_student_ranks: dict[str, list[int]] = {sid: [] for sid in base_order}
    top5_overlaps = []
    displaced = []
    for order in orders:
        rank = {sid: idx + 1 for idx, sid in enumerate(order)}
        for sid in base_order:
            if sid in rank:
                per_student_ranks[sid].append(rank[sid])
        top5_overlaps.append(len(set(order[:5]) & set(base_order[:5])))
        displaced.append(
            sum(abs(rank.get(sid, 0) - base_rank[sid]) for sid in base_order) / max(1, len(base_order))
        )
    rank_sds = [
        statistics.pstdev(ranks) if len(ranks) > 1 else 0.0
        for ranks in per_student_ranks.values()
        if ranks
    ]
    return {
        "runs": len(orders),
        "mean_rank_sd": round(sum(rank_sds) / max(1, len(rank_sds)), 4),
        "max_rank_sd": round(max(rank_sds) if rank_sds else 0.0, 4),
        "mean_top5_overlap": round(sum(top5_overlaps) / max(1, len(top5_overlaps)), 4),
        "min_top5_overlap": min(top5_overlaps) if top5_overlaps else 0,
        "mean_abs_displacement_vs_base": round(sum(displaced) / max(1, len(displaced)), 4),
    }


def run_harness(
    *,
    scores_path: Path,
    judgments_path: Path,
    config_path: Path,
    cohort_confidence_path: Path | None,
    seed_trust_mode: str,
    runs: int,
    flip_rate: float,
    drop_rate: float,
    seed: int,
) -> dict:
    payload = json.loads(judgments_path.read_text(encoding="utf-8"))
    rng = random.Random(seed)
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        base_order = rerank_order(scores_path, judgments_path, config_path, cohort_confidence_path, seed_trust_mode, workdir)
        orders = []
        for run_idx in range(runs):
            perturbed = perturb_payload(payload, rng, flip_rate, drop_rate)
            perturbed_path = workdir / f"perturbed_{run_idx}.json"
            perturbed_path.write_text(json.dumps(perturbed), encoding="utf-8")
            orders.append(
                rerank_order(scores_path, perturbed_path, config_path, cohort_confidence_path, seed_trust_mode, workdir)
            )
    metrics = stability_metrics(base_order, orders)
    metrics.update(
        {
            "seed": seed,
            "flip_rate": flip_rate,
            "drop_rate": drop_rate,
            "seed_trust_mode": seed_trust_mode,
            "base_order": base_order,
        }
    )
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores", default="outputs/consensus_scores.csv")
    parser.add_argument("--judgments", default="outputs/consistency_checks.committee_edge.json")
    parser.add_argument("--config", default="config/marking_config.json")
    parser.add_argument("--cohort-confidence", default="outputs/cohort_confidence.json")
    parser.add_argument("--seed-trust-mode", default="adaptive", choices=["adaptive", "fixed"])
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--flip-rate", type=float, default=0.08)
    parser.add_argument("--drop-rate", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=20260610)
    parser.add_argument("--output", default="outputs/stability_report.json")
    args = parser.parse_args()

    cohort_path = Path(args.cohort_confidence)
    metrics = run_harness(
        scores_path=Path(args.scores),
        judgments_path=Path(args.judgments),
        config_path=Path(args.config),
        cohort_confidence_path=cohort_path if cohort_path.exists() else None,
        seed_trust_mode=args.seed_trust_mode,
        runs=max(1, args.runs),
        flip_rate=max(0.0, args.flip_rate),
        drop_rate=max(0.0, args.drop_rate),
        seed=args.seed,
    )
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(
        f"runs={metrics['runs']} mean_rank_sd={metrics['mean_rank_sd']} "
        f"top5_overlap={metrics['mean_top5_overlap']} displacement={metrics['mean_abs_displacement_vs_base']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
