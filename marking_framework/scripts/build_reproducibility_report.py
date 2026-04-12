#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


DEFAULT_FINAL_ARTIFACTS = (
    "outputs/final_order.csv",
    "outputs/consistency_adjusted.csv",
    "outputs/consistency_report.json",
)
DEFAULT_MANIFEST_ARTIFACTS = (
    "inputs/class_metadata.json",
    "inputs/rubric.md",
    "inputs/assignment_outline.md",
    "config/marking_config.json",
    "config/rubric_criteria.json",
    "config/calibration_set.json",
    "outputs/calibration_manifest.json",
)
DEFAULT_INTERMEDIATE_ARTIFACTS = (
    "outputs/irr_metrics.json",
    "outputs/usage_costs.json",
    "outputs/boundary_calibration_report.json",
)


def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def artifact_fingerprint(path: Path) -> str:
    if path.suffix == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return file_hash(path)
        return canonical_json_hash(payload)
    return file_hash(path)


def discover_runs(mode_dir: Path) -> list[Path]:
    runs = [path for path in sorted(mode_dir.glob("run_*")) if path.is_dir()]
    if not runs:
        raise SystemExit(f"No run_* directories found under {mode_dir}")
    return runs


def compare_file_set(runs: list[Path], artifacts: tuple[str, ...]) -> tuple[bool, list[str]]:
    mismatched = []
    for rel in artifacts:
        paths = [run / rel for run in runs]
        exists = [path.exists() for path in paths]
        if not any(exists):
            continue
        if len(set(exists)) != 1:
            mismatched.append(rel)
            continue
        hashes = [artifact_fingerprint(path) for path in paths]
        if len(set(hashes)) != 1:
            mismatched.append(rel)
    return (not mismatched), mismatched


def _consensus_numeric_map(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_student = {}
    for row in rows:
        sid = str(row.get("student_id", "")).strip()
        if not sid:
            continue
        by_student[sid] = {
            "rank": float(row.get("consensus_rank", 0.0) or 0.0),
            "score": float(row.get("rubric_after_penalty_percent", 0.0) or 0.0),
            "level": str(row.get("adjusted_level", "")).strip(),
        }
    return by_student


def consensus_exact_match(runs: list[Path]) -> tuple[bool, list[str]]:
    paths = [run / "outputs/consensus_scores.csv" for run in runs]
    exists = [path.exists() for path in paths]
    if not any(exists):
        return True, []
    if len(set(exists)) != 1:
        return False, ["outputs/consensus_scores.csv"]
    baseline = _consensus_numeric_map(paths[0])
    for path in paths[1:]:
        current = _consensus_numeric_map(path)
        if baseline != current:
            return False, ["outputs/consensus_scores.csv"]
    return True, []


def _level_to_ordinal(level: str) -> float:
    mapping = {"1": 1.0, "2": 2.0, "3": 3.0, "4": 4.0, "4+": 5.0}
    return mapping.get(level, 0.0)


def max_intermediate_delta(runs: list[Path], artifacts: tuple[str, ...]) -> tuple[float, list[str]]:
    baseline = runs[0]
    mismatched = []
    max_delta = 0.0

    baseline_consensus = _consensus_numeric_map(baseline / "outputs/consensus_scores.csv")
    if baseline_consensus:
        for run in runs[1:]:
            current = _consensus_numeric_map(run / "outputs/consensus_scores.csv")
            if set(current) != set(baseline_consensus):
                mismatched.append("outputs/consensus_scores.csv")
                max_delta = max(max_delta, 1.0)
                continue
            student_count = max(1.0, float(len(baseline_consensus)))
            for sid, expected in baseline_consensus.items():
                observed = current[sid]
                max_delta = max(max_delta, abs(expected["score"] - observed["score"]) / 100.0)
                max_delta = max(max_delta, abs(expected["rank"] - observed["rank"]) / student_count)
                max_delta = max(max_delta, abs(_level_to_ordinal(expected["level"]) - _level_to_ordinal(observed["level"])) / 5.0)

    return round(max_delta, 6), sorted(set(mismatched))


def canonical_json_hash(payload) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_summary(mode_dir: Path, tolerance: float) -> dict:
    runs = discover_runs(mode_dir)
    manifest_identical, mismatched_manifest = compare_file_set(runs, DEFAULT_MANIFEST_ARTIFACTS)
    final_exact, mismatched_final = consensus_exact_match(runs)
    aux_exact, aux_mismatched = compare_file_set(runs, DEFAULT_FINAL_ARTIFACTS)
    final_exact = final_exact and aux_exact
    mismatched_final = sorted(set(mismatched_final + aux_mismatched))
    max_delta, mismatched_intermediate = max_intermediate_delta(runs, DEFAULT_INTERMEDIATE_ARTIFACTS)
    return {
        "runs_compared": len(runs),
        "manifest_identical": manifest_identical,
        "final_outputs_exact_match": final_exact,
        "within_tolerance": final_exact or max_delta <= tolerance,
        "max_intermediate_metric_delta": max_delta,
        "mismatched_manifest_artifacts": mismatched_manifest,
        "mismatched_final_artifacts": mismatched_final,
        "mismatched_intermediate_artifacts": mismatched_intermediate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a reproducibility report from repeated benchmark run directories.")
    parser.add_argument("--mode-dir", required=True, help="Mode directory containing run_1, run_2, ...")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--tolerance", type=float, default=0.01, help="Max allowed intermediate metric delta for within-tolerance")
    args = parser.parse_args()

    mode_dir = Path(args.mode_dir).resolve()
    output = Path(args.output).resolve()
    summary = build_summary(mode_dir, args.tolerance)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"summary": summary}, indent=2), encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
