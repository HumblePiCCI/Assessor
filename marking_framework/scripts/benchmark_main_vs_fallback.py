#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


def parse_expected_level(name: str) -> str | None:
    token = str(name).lower()
    if (
        "level_4_plus" in token
        or "level4_plus" in token
        or "level4plus" in token
        or "level_4+" in token
    ):
        return "4+"
    match = re.search(r"level[_\s-]?(1|2|3|4)(?:\b|_)", token)
    return match.group(1) if match else None


def ensure_dataset_shape(dataset: Path) -> tuple[Path, Path]:
    if (dataset / "inputs").exists() and (dataset / "submissions").exists():
        return dataset / "inputs", dataset / "submissions"
    raise ValueError(f"Dataset must contain inputs/ and submissions/: {dataset}")


def run_cmd(cmd: list[str], env: dict) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return proc.returncode, proc.stdout, proc.stderr


def pass1_model_usage_ratio(pass1_dir: Path) -> float:
    files = list(pass1_dir.glob("assessor_*.json"))
    total = 0
    model_rows = 0
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload.get("scores", []):
            total += 1
            notes = str(row.get("notes", ""))
            if "Fallback deterministic score" not in notes:
                model_rows += 1
    if total == 0:
        return 0.0
    return model_rows / total


def run_pipeline(run_dir: Path, routing_path: Path, env: dict, require_model_usage: bool) -> tuple[bool, str]:
    cmds = [
        [
            "python3",
            "scripts/extract_text.py",
            "--inputs",
            str(run_dir / "inputs/submissions"),
            "--output",
            str(run_dir / "processing/normalized_text"),
            "--metadata",
            str(run_dir / "processing/submission_metadata.json"),
        ],
        [
            "python3",
            "scripts/conventions_scan.py",
            "--inputs",
            str(run_dir / "processing/normalized_text"),
            "--output",
            str(run_dir / "processing/conventions_report.csv"),
        ],
        [
            "python3",
            "scripts/run_llm_assessors.py",
            "--texts",
            str(run_dir / "processing/normalized_text"),
            "--rubric",
            str(run_dir / "inputs/rubric.md"),
            "--outline",
            str(run_dir / "inputs/assignment_outline.md"),
            "--routing",
            str(routing_path),
            "--pass1-out",
            str(run_dir / "assessments/pass1"),
            "--pass2-out",
            str(run_dir / "assessments/pass2"),
            "--grade-profiles",
            "config/grade_level_profiles.json",
            "--class-metadata",
            str(run_dir / "inputs/class_metadata.json"),
            "--exemplars",
            "inputs/exemplars",
            "--rubric-criteria",
            "config/rubric_criteria.json",
            "--fallback",
            "deterministic",
        ] + (["--require-model-usage"] if require_model_usage else []),
        [
            "python3",
            "scripts/aggregate_assessments.py",
            "--config",
            "config/marking_config.json",
            "--pass1",
            str(run_dir / "assessments/pass1"),
            "--pass2",
            str(run_dir / "assessments/pass2"),
            "--conventions",
            str(run_dir / "processing/conventions_report.csv"),
            "--output",
            str(run_dir / "outputs/consensus_scores.csv"),
            "--rubric-criteria",
            "config/rubric_criteria.json",
        ],
    ]
    for cmd in cmds:
        code, stdout, stderr = run_cmd(cmd, env)
        if code != 0:
            detail = f"cmd={' '.join(cmd)}\nstdout:\n{stdout}\nstderr:\n{stderr}"
            return False, detail
    return True, ""


def evaluate_run(run_dir: Path) -> dict:
    metadata = json.loads((run_dir / "processing/submission_metadata.json").read_text(encoding="utf-8"))
    name_by_id = {row["student_id"]: row["display_name"] for row in metadata}
    rows = list(csv.DictReader((run_dir / "outputs/consensus_scores.csv").open()))
    hit = 0
    total = 0
    details = {}
    for row in rows:
        sid = row["student_id"]
        display = name_by_id.get(sid, sid)
        expected = parse_expected_level(display)
        if expected is None:
            continue
        total += 1
        got = row["adjusted_level"]
        if got == expected:
            hit += 1
        details[sid] = {
            "display_name": display,
            "expected": expected,
            "level": got,
            "rank": int(row["consensus_rank"]),
            "score": float(row["rubric_after_penalty_percent"]),
        }
    accuracy = (hit / total) if total else 0.0
    usage_ratio = pass1_model_usage_ratio(run_dir / "assessments/pass1")
    return {"accuracy": round(accuracy, 4), "model_usage_ratio": round(usage_ratio, 4), "students": details}


def setup_run(base_inputs: Path, base_submissions: Path, run_dir: Path):
    if run_dir.exists():
        shutil.rmtree(run_dir)
    (run_dir / "inputs/submissions").mkdir(parents=True)
    (run_dir / "processing").mkdir(parents=True)
    (run_dir / "assessments").mkdir(parents=True)
    (run_dir / "outputs").mkdir(parents=True)
    for file in base_inputs.glob("*"):
        if file.is_file():
            shutil.copy(file, run_dir / "inputs" / file.name)
    for file in base_submissions.glob("*"):
        if file.is_file():
            shutil.copy(file, run_dir / "inputs/submissions" / file.name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare OpenAI main-path grading vs deterministic fallback.")
    parser.add_argument("--dataset", default="bench/internet_samples_thoughtful", help="Dataset root with inputs/ and submissions/")
    parser.add_argument("--runs", type=int, default=3, help="Runs per mode")
    parser.add_argument("--output", default="", help="Benchmark output directory")
    args = parser.parse_args()

    dataset = Path(args.dataset)
    inputs_dir, submissions_dir = ensure_dataset_shape(dataset)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output) if args.output else Path(f"bench/runs/main_vs_fallback_{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    routing_main = json.loads(Path("config/llm_routing.json").read_text(encoding="utf-8"))
    (out_dir / "routing_main.json").write_text(json.dumps(routing_main, indent=2), encoding="utf-8")
    routing_fallback = dict(routing_main)
    routing_fallback["mode"] = "codex_local"
    (out_dir / "routing_fallback.json").write_text(json.dumps(routing_fallback, indent=2), encoding="utf-8")

    main_env = os.environ.copy()
    fallback_env = os.environ.copy()
    fallback_env["LLM_MODE"] = "codex_local"
    fallback_env["PATH"] = "/Library/Frameworks/Python.framework/Versions/3.13/bin:/usr/bin:/bin:/usr/sbin:/sbin"

    report = {"benchmark": "main_vs_fallback", "dataset": str(dataset), "runs": args.runs, "modes": {"main": [], "fallback": []}}
    for run_idx in range(1, args.runs + 1):
        run_main = out_dir / "main" / f"run_{run_idx}"
        run_fb = out_dir / "fallback" / f"run_{run_idx}"
        setup_run(inputs_dir, submissions_dir, run_main)
        setup_run(inputs_dir, submissions_dir, run_fb)

        ok_main, err_main = run_pipeline(run_main, out_dir / "routing_main.json", main_env, True)
        ok_fb, err_fb = run_pipeline(run_fb, out_dir / "routing_fallback.json", fallback_env, False)
        main_payload = {"run": run_idx, "ok": ok_main}
        fb_payload = {"run": run_idx, "ok": ok_fb}
        if ok_main:
            main_payload.update(evaluate_run(run_main))
        else:
            main_payload["error"] = err_main
        if ok_fb:
            fb_payload.update(evaluate_run(run_fb))
        else:
            fb_payload["error"] = err_fb
        report["modes"]["main"].append(main_payload)
        report["modes"]["fallback"].append(fb_payload)

    def summarize(rows: list[dict]) -> dict:
        good = [r for r in rows if r.get("ok")]
        if not good:
            return {"runs_successful": 0, "accuracy_mean": 0.0, "model_usage_ratio_mean": 0.0}
        return {
            "runs_successful": len(good),
            "accuracy_mean": round(sum(r["accuracy"] for r in good) / len(good), 4),
            "model_usage_ratio_mean": round(sum(r["model_usage_ratio"] for r in good) / len(good), 4),
        }

    report["summary"] = {"main": summarize(report["modes"]["main"]), "fallback": summarize(report["modes"]["fallback"])}
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {report_path}")
    print(json.dumps(report["summary"], indent=2))

    main_acc = report["summary"]["main"]["accuracy_mean"]
    fb_acc = report["summary"]["fallback"]["accuracy_mean"]
    return 0 if main_acc >= fb_acc else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
