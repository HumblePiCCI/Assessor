#!/usr/bin/env python3
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from server.bootstrap import ensure_bootstrap_calibration, ensure_class_metadata
    from server.step_runner import pipeline_step_command, workspace_asset_dirs
except ImportError:  # pragma: no cover
    from server.bootstrap import ensure_bootstrap_calibration, ensure_class_metadata  # type: ignore  # pragma: no cover

    def pipeline_step_command(step_id: str) -> list[str]:  # pragma: no cover
        defaults = {
            "extract": [
                "python3",
                "scripts/extract_text.py",
                "--inputs",
                "inputs/submissions",
                "--output",
                "processing/normalized_text",
                "--metadata",
                "processing/submission_metadata.json",
            ],
            "conventions": [
                "python3",
                "scripts/conventions_scan.py",
                "--inputs",
                "processing/normalized_text",
                "--output",
                "processing/conventions_report.csv",
            ],
            "assess": ["python3", "scripts/run_llm_assessors.py"],
            "cost": [
                "python3",
                "scripts/usage_pricing.py",
                "--usage",
                "outputs/usage_log.jsonl",
                "--pricing",
                "config/pricing.json",
                "--output",
                "outputs/usage_costs.json",
            ],
            "aggregate_1": ["python3", "scripts/aggregate_assessments.py", "--config", "config/marking_config.json"],
        }
        return list(defaults[step_id])

    def workspace_asset_dirs() -> tuple[str, ...]:  # pragma: no cover
        return ("scripts", "config", "prompts", "templates", "docs", "ui")


REPORT_VERSION = 2
LEVEL_ORDINALS = {"1": 1.0, "2": 2.0, "3": 3.0, "4": 4.0, "4+": 5.0}
OPTIONAL_GOLD_FIELDS = {
    "gold_canonical_level",
    "gold_neighbors",
    "boundary_flag",
    "adjudication_notes",
    "notes",
    "source_file",
    "display_name",
}
REQUIRED_GOLD_FIELDS = {"student_id", "gold_level", "gold_band_min", "gold_band_max", "gold_rank"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def population_variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    return sum((item - avg) ** 2 for item in values) / len(values)


def level_to_ordinal(level: str) -> float:
    token = str(level).strip()
    if token not in LEVEL_ORDINALS:
        raise ValueError(f"Unsupported level: {level}")
    return LEVEL_ORDINALS[token]


def parse_neighbors(raw) -> list[str]:
    if raw in (None, ""):
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, tuple):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        token = raw.strip()
        if not token:
            return []
        try:
            decoded = json.loads(token)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, list):
            return [str(item).strip() for item in decoded if str(item).strip()]
        if "|" in token:
            return [item.strip() for item in token.split("|") if item.strip()]
        if "," in token:
            return [item.strip() for item in token.split(",") if item.strip()]
        return [token]
    raise ValueError(f"Invalid gold_neighbors value: {raw!r}")


def parse_bool(raw) -> bool:
    if isinstance(raw, bool):
        return raw
    token = str(raw or "").strip().lower()
    if token in {"", "0", "false", "no", "n"}:
        return False
    if token in {"1", "true", "yes", "y"}:
        return True
    raise ValueError(f"Invalid boolean value: {raw!r}")


def normalize_gold_record(record: dict, source: str) -> dict:
    missing = [field for field in REQUIRED_GOLD_FIELDS if str(record.get(field, "")).strip() == ""]
    if missing:
        raise ValueError(f"{source}: missing required gold field(s): {', '.join(sorted(missing))}")
    student_id = str(record["student_id"]).strip()
    gold_level = str(record["gold_level"]).strip()
    gold_canonical_level = str(record.get("gold_canonical_level") or gold_level).strip()
    if gold_canonical_level not in LEVEL_ORDINALS:
        if gold_level in LEVEL_ORDINALS:
            raise ValueError(f"{source}: invalid gold_canonical_level {gold_canonical_level!r}")
        raise ValueError(
            f"{source}: non-canonical gold_level {gold_level!r} requires a valid gold_canonical_level "
            f"({', '.join(sorted(LEVEL_ORDINALS))})"
        )
    try:
        band_min = float(record["gold_band_min"])
        band_max = float(record["gold_band_max"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source}: gold band values must be numeric") from exc
    if band_max < band_min:
        raise ValueError(f"{source}: gold_band_max must be >= gold_band_min")
    try:
        gold_rank = int(record["gold_rank"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source}: gold_rank must be an integer") from exc
    if gold_rank <= 0:
        raise ValueError(f"{source}: gold_rank must be positive")
    notes = str(record.get("adjudication_notes") or record.get("notes") or "").strip()
    source_file = str(record.get("source_file") or "").strip()
    display_name = str(record.get("display_name") or "").strip()
    return {
        "student_id": student_id,
        "gold_level": gold_level,
        "gold_canonical_level": gold_canonical_level,
        "gold_level_ordinal": level_to_ordinal(gold_canonical_level),
        "gold_band_min": band_min,
        "gold_band_max": band_max,
        "gold_rank": gold_rank,
        "gold_neighbors": parse_neighbors(record.get("gold_neighbors")),
        "boundary_flag": parse_bool(record.get("boundary_flag")),
        "adjudication_notes": notes,
        "source_file": source_file,
        "display_name": display_name,
    }


def load_gold_rows(path: Path) -> list[dict]:
    rows = []
    if path.suffix.lower() == ".jsonl":
        with path.open("r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}: invalid JSON on line {lineno}") from exc
                if not isinstance(payload, dict):
                    raise ValueError(f"{path}: gold.jsonl line {lineno} must be an object")
                rows.append(normalize_gold_record(payload, f"{path}:{lineno}"))
    elif path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = REQUIRED_GOLD_FIELDS - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"{path}: missing required gold column(s): {', '.join(sorted(missing))}")
            for lineno, row in enumerate(reader, start=2):
                rows.append(normalize_gold_record(row, f"{path}:{lineno}"))
    else:
        raise ValueError(f"Unsupported gold file format: {path}")
    if not rows:
        raise ValueError(f"{path}: no gold rows found")
    ids = [row["student_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate student_id values")
    ranks = [row["gold_rank"] for row in rows]
    if len(ranks) != len(set(ranks)):
        raise ValueError(f"{path}: duplicate gold_rank values")
    ordered_ranks = sorted(ranks)
    expected_ranks = list(range(1, len(ranks) + 1))
    if ordered_ranks != expected_ranks:
        raise ValueError(f"{path}: gold_rank values must form a 1..N sequence")
    return rows


def ensure_dataset_shape(dataset: Path) -> tuple[Path, Path, Path]:
    inputs_dir = dataset / "inputs"
    submissions_dir = dataset / "submissions"
    gold_paths = [path for path in (dataset / "gold.jsonl", dataset / "gold.csv") if path.exists()]
    if not inputs_dir.exists() or not submissions_dir.exists() or len(gold_paths) != 1:
        raise ValueError(f"Dataset must contain inputs/, submissions/, and exactly one gold.jsonl or gold.csv: {dataset}")
    return inputs_dir, submissions_dir, gold_paths[0]


def copy_tree(src: Path, dst: Path):
    if not src.exists():
        return
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store", "*.pyc", "*.pyo"))


def copy_tree_contents(src: Path, dst: Path):
    dst.mkdir(parents=True, exist_ok=True)
    for item in sorted(src.iterdir()):
        target = dst / item.name
        if item.is_dir():
            copy_tree(item, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def setup_run(base_inputs: Path, base_submissions: Path, repo_root: Path, run_dir: Path):
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    for dirname in workspace_asset_dirs():
        copy_tree(repo_root / dirname, run_dir / dirname)
    exemplar_src = repo_root / "inputs" / "exemplars"
    if exemplar_src.exists():
        copy_tree(exemplar_src, run_dir / "inputs" / "exemplars")
    copy_tree_contents(base_inputs, run_dir / "inputs")
    copy_tree_contents(base_submissions, run_dir / "inputs" / "submissions")
    (run_dir / "processing").mkdir(parents=True, exist_ok=True)
    (run_dir / "assessments").mkdir(parents=True, exist_ok=True)
    (run_dir / "outputs").mkdir(parents=True, exist_ok=True)
    calibration_src = repo_root / "outputs" / "calibration_bias.json"
    if calibration_src.exists():
        shutil.copy2(calibration_src, run_dir / "outputs" / "calibration_bias.json")
    calibration_manifest_src = repo_root / "outputs" / "calibration_manifest.json"
    if calibration_manifest_src.exists():
        shutil.copy2(calibration_manifest_src, run_dir / "outputs" / "calibration_manifest.json")
    metadata = ensure_class_metadata(run_dir / "inputs")
    ensure_bootstrap_calibration(run_dir, metadata)


def run_cmd(cmd: list[str], env: dict, cwd: Path) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(cwd), check=False)
    return proc.returncode, proc.stdout, proc.stderr


def pass1_model_usage_ratio(pass1_dir: Path) -> float:
    files = sorted(pass1_dir.glob("assessor_*.json"))
    total = 0
    model_rows = 0
    for path in files:
        payload = load_json(path)
        if not isinstance(payload, dict):
            continue
        for row in payload.get("scores", []):
            total += 1
            notes = str(row.get("notes", ""))
            if "Fallback deterministic score" not in notes:
                model_rows += 1
    return (model_rows / total) if total else 0.0


def usage_cost_usd(outputs_dir: Path) -> float:
    payload = load_json(outputs_dir / "usage_costs.json")
    if not isinstance(payload, dict):
        return 0.0
    try:
        return float(payload.get("grand_total", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def score_band_error(score: float, band_min: float, band_max: float) -> float:
    if score < band_min:
        return band_min - score
    if score > band_max:
        return score - band_max
    return 0.0


def pairwise_order_metrics(predicted_ranks: dict[str, int], gold_ranks: dict[str, int]) -> tuple[float, float]:
    student_ids = sorted(gold_ranks, key=lambda sid: gold_ranks[sid])
    pairs = 0
    correct = 0
    for idx, left in enumerate(student_ids):
        for right in student_ids[idx + 1 :]:
            pairs += 1
            if predicted_ranks[left] < predicted_ranks[right]:
                correct += 1
    if pairs == 0:
        return 1.0, 1.0
    agreement = correct / pairs
    return agreement, (2.0 * agreement) - 1.0


def evaluate_run(run_dir: Path, gold_rows: list[dict], latency_seconds: float = 0.0) -> dict:
    metadata = load_json(run_dir / "processing" / "submission_metadata.json")
    if not isinstance(metadata, list):
        metadata = []
    metadata_by_id = {str(row.get("student_id", "")).strip(): row for row in metadata if str(row.get("student_id", "")).strip()}

    consensus_rows = load_rows(run_dir / "outputs" / "consensus_scores.csv")
    predicted = {}
    for row in consensus_rows:
        sid = str(row.get("student_id", "")).strip()
        if not sid:
            continue
        try:
            predicted[sid] = {
                "predicted_level": str(row["adjusted_level"]).strip(),
                "predicted_level_ordinal": level_to_ordinal(row["adjusted_level"]),
                "predicted_rank": int(row["consensus_rank"]),
                "predicted_score": float(row["rubric_after_penalty_percent"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{run_dir}: invalid consensus row for student {sid}") from exc

    gold_by_student = {row["student_id"]: row for row in gold_rows}
    missing = sorted(set(gold_by_student) - set(predicted))
    unexpected = sorted(set(predicted) - set(gold_by_student))
    if missing:
        raise ValueError(f"{run_dir}: consensus output missing gold student(s): {', '.join(missing)}")
    if unexpected:
        raise ValueError(f"{run_dir}: consensus output contains unexpected student(s): {', '.join(unexpected)}")

    if metadata_by_id and set(metadata_by_id) != set(gold_by_student):
        missing_meta = sorted(set(gold_by_student) - set(metadata_by_id))
        unexpected_meta = sorted(set(metadata_by_id) - set(gold_by_student))
        if missing_meta:
            raise ValueError(f"{run_dir}: submission metadata missing student(s): {', '.join(missing_meta)}")
        if unexpected_meta:
            raise ValueError(f"{run_dir}: submission metadata contains unexpected student(s): {', '.join(unexpected_meta)}")

    details = {}
    exact_hits = 0
    within_one_hits = 0
    band_errors = []
    rank_displacements = []
    predicted_ranks = {}
    gold_ranks = {}
    for gold in gold_rows:
        sid = gold["student_id"]
        item = predicted[sid]
        metadata_row = metadata_by_id.get(sid, {})
        actual_source_file = str(metadata_row.get("source_file") or "").strip()
        if gold.get("source_file") and actual_source_file and gold["source_file"] != actual_source_file:
            raise ValueError(f"{run_dir}: gold source_file mismatch for {sid}: expected {gold['source_file']}, got {actual_source_file}")

        exact = item["predicted_level"] == gold["gold_canonical_level"]
        within_one = abs(item["predicted_level_ordinal"] - gold["gold_level_ordinal"]) <= 1.0
        band_error = score_band_error(item["predicted_score"], gold["gold_band_min"], gold["gold_band_max"])
        rank_displacement = abs(item["predicted_rank"] - gold["gold_rank"])
        exact_hits += int(exact)
        within_one_hits += int(within_one)
        band_errors.append(band_error)
        rank_displacements.append(float(rank_displacement))
        predicted_ranks[sid] = item["predicted_rank"]
        gold_ranks[sid] = gold["gold_rank"]
        details[sid] = {
            "student_id": sid,
            "display_name": gold.get("display_name") or metadata_row.get("display_name", ""),
            "source_file": gold.get("source_file") or metadata_row.get("source_file", ""),
            "gold_level": gold["gold_level"],
            "gold_canonical_level": gold["gold_canonical_level"],
            "predicted_level": item["predicted_level"],
            "gold_band_min": gold["gold_band_min"],
            "gold_band_max": gold["gold_band_max"],
            "predicted_score": item["predicted_score"],
            "score_band_error": round(band_error, 6),
            "gold_rank": gold["gold_rank"],
            "predicted_rank": item["predicted_rank"],
            "rank_displacement": rank_displacement,
            "exact_level_hit": exact,
            "within_one_level_hit": within_one,
            "boundary_flag": bool(gold.get("boundary_flag", False)),
            "gold_neighbors": list(gold.get("gold_neighbors", [])),
            "adjudication_notes": gold.get("adjudication_notes", ""),
            "predicted_level_ordinal": item["predicted_level_ordinal"],
        }

    pairwise_order_agreement, kendall_tau = pairwise_order_metrics(predicted_ranks, gold_ranks)
    return {
        "student_count": len(gold_rows),
        "exact_level_hit_rate": round(exact_hits / len(gold_rows), 6),
        "within_one_level_hit_rate": round(within_one_hits / len(gold_rows), 6),
        "score_band_mae": round(mean(band_errors), 6),
        "mean_rank_displacement": round(mean(rank_displacements), 6),
        "max_rank_displacement": round(max(rank_displacements) if rank_displacements else 0.0, 6),
        "kendall_tau": round(kendall_tau, 6),
        "pairwise_order_agreement": round(pairwise_order_agreement, 6),
        "model_usage_ratio": round(pass1_model_usage_ratio(run_dir / "assessments" / "pass1_individual"), 6),
        "cost_usd": round(usage_cost_usd(run_dir / "outputs"), 6),
        "latency_seconds": round(float(latency_seconds or 0.0), 6),
        "students": details,
    }


def summarize_stability(successful_runs: list[dict]) -> dict:
    if not successful_runs:
        return {
            "mean_student_level_variance": 0.0,
            "max_student_level_variance": 0.0,
            "mean_student_rank_variance": 0.0,
            "max_student_rank_variance": 0.0,
            "mean_student_score_variance": 0.0,
            "max_student_score_variance": 0.0,
            "cohort_metric_variance": {},
            "per_student": {},
        }
    student_ids = sorted(successful_runs[0].get("students", {}))
    per_student = {}
    level_vars = []
    rank_vars = []
    score_vars = []
    for sid in student_ids:
        level_values = [run["students"][sid]["predicted_level_ordinal"] for run in successful_runs]
        rank_values = [float(run["students"][sid]["predicted_rank"]) for run in successful_runs]
        score_values = [float(run["students"][sid]["predicted_score"]) for run in successful_runs]
        level_var = population_variance(level_values)
        rank_var = population_variance(rank_values)
        score_var = population_variance(score_values)
        level_vars.append(level_var)
        rank_vars.append(rank_var)
        score_vars.append(score_var)
        per_student[sid] = {
            "level_variance": round(level_var, 6),
            "rank_variance": round(rank_var, 6),
            "score_variance": round(score_var, 6),
            "levels": [run["students"][sid]["predicted_level"] for run in successful_runs],
            "ranks": [run["students"][sid]["predicted_rank"] for run in successful_runs],
            "scores": [run["students"][sid]["predicted_score"] for run in successful_runs],
        }
    cohort_metric_variance = {}
    for key in (
        "exact_level_hit_rate",
        "within_one_level_hit_rate",
        "score_band_mae",
        "mean_rank_displacement",
        "max_rank_displacement",
        "kendall_tau",
        "pairwise_order_agreement",
        "model_usage_ratio",
        "cost_usd",
        "latency_seconds",
    ):
        cohort_metric_variance[key] = round(population_variance([float(run.get(key, 0.0) or 0.0) for run in successful_runs]), 6)
    return {
        "mean_student_level_variance": round(mean(level_vars), 6),
        "max_student_level_variance": round(max(level_vars) if level_vars else 0.0, 6),
        "mean_student_rank_variance": round(mean(rank_vars), 6),
        "max_student_rank_variance": round(max(rank_vars) if rank_vars else 0.0, 6),
        "mean_student_score_variance": round(mean(score_vars), 6),
        "max_student_score_variance": round(max(score_vars) if score_vars else 0.0, 6),
        "cohort_metric_variance": cohort_metric_variance,
        "per_student": per_student,
    }


def summarize_runs(runs: list[dict]) -> dict:
    successful = [row for row in runs if row.get("ok")]
    summary = {
        "runs_attempted": len(runs),
        "runs_successful": len(successful),
        "student_count": successful[0].get("student_count", 0) if successful else 0,
        "exact_level_hit_rate_mean": 0.0,
        "within_one_level_hit_rate_mean": 0.0,
        "score_band_mae_mean": 0.0,
        "mean_rank_displacement_mean": 0.0,
        "max_rank_displacement_mean": 0.0,
        "kendall_tau_mean": 0.0,
        "pairwise_order_agreement_mean": 0.0,
        "model_usage_ratio_mean": 0.0,
        "cost_usd_mean": 0.0,
        "latency_seconds_mean": 0.0,
        "stability": summarize_stability(successful),
    }
    if not successful:
        return summary
    for key in (
        "exact_level_hit_rate",
        "within_one_level_hit_rate",
        "score_band_mae",
        "mean_rank_displacement",
        "max_rank_displacement",
        "kendall_tau",
        "pairwise_order_agreement",
        "model_usage_ratio",
        "cost_usd",
        "latency_seconds",
    ):
        summary[f"{key}_mean"] = round(mean([float(run.get(key, 0.0) or 0.0) for run in successful]), 6)
    return summary


def compare_modes(candidate_label: str, baseline_label: str, modes: dict[str, dict]) -> dict:
    candidate = modes.get(candidate_label, {}).get("summary", {})
    baseline = modes.get(baseline_label, {}).get("summary", {})
    if not candidate or not baseline:
        return {
            "candidate_mode": candidate_label,
            "baseline_mode": baseline_label,
            "present": False,
            "delta": {},
        }
    delta = {
        "exact_level_hit_rate": round(candidate.get("exact_level_hit_rate_mean", 0.0) - baseline.get("exact_level_hit_rate_mean", 0.0), 6),
        "within_one_level_hit_rate": round(candidate.get("within_one_level_hit_rate_mean", 0.0) - baseline.get("within_one_level_hit_rate_mean", 0.0), 6),
        "score_band_mae": round(candidate.get("score_band_mae_mean", 0.0) - baseline.get("score_band_mae_mean", 0.0), 6),
        "mean_rank_displacement": round(candidate.get("mean_rank_displacement_mean", 0.0) - baseline.get("mean_rank_displacement_mean", 0.0), 6),
        "max_rank_displacement": round(candidate.get("max_rank_displacement_mean", 0.0) - baseline.get("max_rank_displacement_mean", 0.0), 6),
        "kendall_tau": round(candidate.get("kendall_tau_mean", 0.0) - baseline.get("kendall_tau_mean", 0.0), 6),
        "pairwise_order_agreement": round(candidate.get("pairwise_order_agreement_mean", 0.0) - baseline.get("pairwise_order_agreement_mean", 0.0), 6),
        "model_usage_ratio": round(candidate.get("model_usage_ratio_mean", 0.0) - baseline.get("model_usage_ratio_mean", 0.0), 6),
        "cost_usd": round(candidate.get("cost_usd_mean", 0.0) - baseline.get("cost_usd_mean", 0.0), 6),
        "latency_seconds": round(candidate.get("latency_seconds_mean", 0.0) - baseline.get("latency_seconds_mean", 0.0), 6),
        "mean_student_level_variance": round(
            candidate.get("stability", {}).get("mean_student_level_variance", 0.0)
            - baseline.get("stability", {}).get("mean_student_level_variance", 0.0),
            6,
        ),
        "mean_student_rank_variance": round(
            candidate.get("stability", {}).get("mean_student_rank_variance", 0.0)
            - baseline.get("stability", {}).get("mean_student_rank_variance", 0.0),
            6,
        ),
        "mean_student_score_variance": round(
            candidate.get("stability", {}).get("mean_student_score_variance", 0.0)
            - baseline.get("stability", {}).get("mean_student_score_variance", 0.0),
            6,
        ),
    }
    return {
        "candidate_mode": candidate_label,
        "baseline_mode": baseline_label,
        "present": True,
        "delta": delta,
    }


def build_mode_env(
    base_env: dict[str, str],
    forced_llm_mode: str | None = None,
    *,
    shared_cache_dir: Path | None = None,
) -> dict[str, str]:
    env = dict(base_env)
    if forced_llm_mode:
        env["LLM_MODE"] = forced_llm_mode
    else:
        env.pop("LLM_MODE", None)
    env.setdefault("PYTHONHASHSEED", "0")
    env.setdefault("LLM_CACHE", "1")
    env.setdefault("OPENAI_MAX_RETRIES", "3")
    env.setdefault("OPENAI_RETRY_BACKOFF_SECONDS", "0.2")
    if shared_cache_dir is not None:
        shared_cache_dir.mkdir(parents=True, exist_ok=True)
        env["LLM_CACHE_DIR"] = str(shared_cache_dir.resolve())
    return env


def write_routing_files(out_dir: Path, candidate_routing: Path, baseline_routing: Path | None, candidate_label: str, baseline_label: str) -> list[dict]:
    candidate_payload = load_json(candidate_routing)
    if not isinstance(candidate_payload, dict):
        raise ValueError(f"Invalid candidate routing config: {candidate_routing}")
    candidate_out = out_dir / f"routing_{candidate_label}.json"
    candidate_out.write_text(json.dumps(candidate_payload, indent=2, sort_keys=True), encoding="utf-8")

    if baseline_routing:
        baseline_payload = load_json(baseline_routing)
        if not isinstance(baseline_payload, dict):
            raise ValueError(f"Invalid baseline routing config: {baseline_routing}")
        forced_llm_mode = None
    else:
        baseline_payload = dict(candidate_payload)
        baseline_payload["mode"] = "codex_local"
        forced_llm_mode = "codex_local"
    baseline_out = out_dir / f"routing_{baseline_label}.json"
    baseline_out.write_text(json.dumps(baseline_payload, indent=2, sort_keys=True), encoding="utf-8")

    return [
        {
            "label": candidate_label,
            "routing_path": candidate_out,
            "routing_mode": candidate_payload.get("mode"),
            "forced_llm_mode": None,
            "require_model_usage": True,
        },
        {
            "label": baseline_label,
            "routing_path": baseline_out,
            "routing_mode": baseline_payload.get("mode"),
            "forced_llm_mode": forced_llm_mode,
            "require_model_usage": False,
        },
    ]


def run_pipeline(run_dir: Path, routing_path: Path, env: dict[str, str], require_model_usage: bool) -> tuple[bool, str, float]:
    assess_cmd = pipeline_step_command("assess")
    assess_cmd.extend(
        [
            "--texts",
            "processing/normalized_text",
            "--rubric",
            "inputs/rubric.md",
            "--outline",
            "inputs/assignment_outline.md",
            "--routing",
            str(routing_path.name),
            "--grade-profiles",
            "config/grade_level_profiles.json",
            "--class-metadata",
            "inputs/class_metadata.json",
            "--exemplars",
            "inputs/exemplars",
            "--rubric-criteria",
            "config/rubric_criteria.json",
            "--fallback",
            "deterministic",
            "--ignore-cost-limits",
        ]
    )
    if require_model_usage:
        assess_cmd.append("--require-model-usage")
    aggregate_cmd = pipeline_step_command("aggregate_1")
    aggregate_cmd.extend(
        [
            "--pass1",
            "assessments/pass1_individual",
            "--pass2",
            "assessments/pass2_comparative",
            "--conventions",
            "processing/conventions_report.csv",
            "--output",
            "outputs/consensus_scores.csv",
            "--rubric-criteria",
            "config/rubric_criteria.json",
            "--routing",
            str(routing_path.name),
        ]
    )
    commands = [
        {"required": True, "cmd": pipeline_step_command("extract")},
        {"required": True, "cmd": pipeline_step_command("conventions")},
        {"required": True, "cmd": assess_cmd},
        {"required": False, "cmd": pipeline_step_command("cost")},
        {"required": True, "cmd": aggregate_cmd},
    ]
    start = time.perf_counter()
    for item in commands:
        code, stdout, stderr = run_cmd(item["cmd"], env, run_dir)
        if code == 0:
            continue
        if not item["required"]:
            continue
        duration = time.perf_counter() - start
        detail = f"cmd={' '.join(item['cmd'])}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        return False, detail, duration
    return True, "", time.perf_counter() - start


def build_markdown(report: dict) -> str:
    lines = [
        "# Benchmark Report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Dataset: `{report['dataset']['path']}`",
        f"- Gold file: `{report['dataset']['gold_path']}`",
        f"- Students: {report['dataset']['student_count']}",
        f"- Runs per mode: {report['runs_per_mode']}",
        "",
        "## Mode Summaries",
    ]
    for label, payload in report["modes"].items():
        summary = payload.get("summary", {})
        lines.extend(
            [
                "",
                f"### {label}",
                "",
                f"- Runs successful: {summary.get('runs_successful', 0)}/{summary.get('runs_attempted', 0)}",
                f"- Exact-level hit rate: {summary.get('exact_level_hit_rate_mean', 0.0):.4f}",
                f"- Within-one-level hit rate: {summary.get('within_one_level_hit_rate_mean', 0.0):.4f}",
                f"- Score-band MAE: {summary.get('score_band_mae_mean', 0.0):.4f}",
                f"- Mean rank displacement: {summary.get('mean_rank_displacement_mean', 0.0):.4f}",
                f"- Kendall tau: {summary.get('kendall_tau_mean', 0.0):.4f}",
                f"- Pairwise order agreement: {summary.get('pairwise_order_agreement_mean', 0.0):.4f}",
                f"- Model usage ratio: {summary.get('model_usage_ratio_mean', 0.0):.4f}",
                f"- Cost (USD): {summary.get('cost_usd_mean', 0.0):.4f}",
                f"- Latency (s): {summary.get('latency_seconds_mean', 0.0):.4f}",
                f"- Mean student level variance: {summary.get('stability', {}).get('mean_student_level_variance', 0.0):.6f}",
                f"- Mean student rank variance: {summary.get('stability', {}).get('mean_student_rank_variance', 0.0):.6f}",
                f"- Mean student score variance: {summary.get('stability', {}).get('mean_student_score_variance', 0.0):.6f}",
            ]
        )
    comparison = report.get("comparison", {})
    if comparison.get("present"):
        delta = comparison.get("delta", {})
        lines.extend(
            [
                "",
                "## Candidate Vs Baseline",
                "",
                f"- Candidate mode: `{comparison.get('candidate_mode', '')}`",
                f"- Baseline mode: `{comparison.get('baseline_mode', '')}`",
                f"- Exact-level hit delta: {delta.get('exact_level_hit_rate', 0.0):.4f}",
                f"- Within-one-level delta: {delta.get('within_one_level_hit_rate', 0.0):.4f}",
                f"- Score-band MAE delta: {delta.get('score_band_mae', 0.0):.4f}",
                f"- Mean rank displacement delta: {delta.get('mean_rank_displacement', 0.0):.4f}",
                f"- Kendall tau delta: {delta.get('kendall_tau', 0.0):.4f}",
                f"- Pairwise agreement delta: {delta.get('pairwise_order_agreement', 0.0):.4f}",
                f"- Cost delta (USD): {delta.get('cost_usd', 0.0):.4f}",
                f"- Latency delta (s): {delta.get('latency_seconds', 0.0):.4f}",
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark candidate routing against an explicit-gold baseline.")
    parser.add_argument("--dataset", default="bench/internet_samples_thoughtful", help="Dataset root with inputs/, submissions/, and gold.jsonl or gold.csv")
    parser.add_argument("--runs", type=int, default=3, help="Runs per mode")
    parser.add_argument("--output", default="", help="Benchmark output directory")
    parser.add_argument("--candidate-routing", default="config/llm_routing.json", help="Candidate routing config")
    parser.add_argument("--baseline-routing", default="", help="Optional baseline routing config; defaults to a synthesized codex_local fallback")
    parser.add_argument("--candidate-label", default="main", help="Candidate mode label")
    parser.add_argument("--baseline-label", default="fallback", help="Baseline mode label")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    dataset = Path(args.dataset).resolve()
    inputs_dir, submissions_dir, gold_path = ensure_dataset_shape(dataset)
    gold_rows = load_gold_rows(gold_path)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output).resolve() if args.output else (repo_root / f"bench/runs/benchmark_{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    modes = write_routing_files(
        out_dir,
        (repo_root / args.candidate_routing).resolve(),
        (repo_root / args.baseline_routing).resolve() if args.baseline_routing else None,
        args.candidate_label,
        args.baseline_label,
    )
    report = {
        "report_version": REPORT_VERSION,
        "benchmark": "explicit_gold_candidate_vs_baseline",
        "generated_at": now_iso(),
        "dataset": {
            "path": str(dataset),
            "gold_path": str(gold_path),
            "student_count": len(gold_rows),
        },
        "runs_per_mode": args.runs,
        "modes": {},
    }

    base_env = os.environ.copy()
    for spec in modes:
        label = spec["label"]
        report["modes"][label] = {
            "routing_path": str(spec["routing_path"]),
            "routing_mode": spec.get("routing_mode"),
            "runs": [],
        }
        for run_idx in range(1, args.runs + 1):
            run_dir = out_dir / label / f"run_{run_idx}"
            setup_run(inputs_dir, submissions_dir, repo_root, run_dir)
            shutil.copy2(spec["routing_path"], run_dir / spec["routing_path"].name)
            shared_cache_dir = out_dir / "_shared_cache" / spec["label"]
            env = build_mode_env(
                base_env,
                spec.get("forced_llm_mode"),
                shared_cache_dir=shared_cache_dir,
            )
            ok, error, latency_seconds = run_pipeline(run_dir, run_dir / spec["routing_path"].name, env, bool(spec["require_model_usage"]))
            payload = {"run": run_idx, "ok": ok}
            if ok:
                payload.update(evaluate_run(run_dir, gold_rows, latency_seconds=latency_seconds))
            else:
                payload["error"] = error
                payload["latency_seconds"] = round(latency_seconds, 6)
            report["modes"][label]["runs"].append(payload)
        report["modes"][label]["summary"] = summarize_runs(report["modes"][label]["runs"])

    report["comparison"] = compare_modes(args.candidate_label, args.baseline_label, report["modes"])

    json_path = out_dir / "benchmark_report.json"
    md_path = out_dir / "benchmark_report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(build_markdown(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(json.dumps(report["comparison"], indent=2, sort_keys=True))

    delta = report.get("comparison", {}).get("delta", {})
    return 0 if float(delta.get("exact_level_hit_rate", 0.0) or 0.0) >= 0.0 else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
