#!/usr/bin/env python3
import hashlib
import json
import os
import queue
import subprocess
import threading
from pathlib import Path

RUNTIME_ASSET_DIRS = ("scripts", "config", "prompts", "templates", "docs", "ui")
ARTIFACT_WATCH_ROOTS = ("inputs", "processing", "assessments", "outputs")

FULL_PIPELINE_STEP_IDS = (
    "rubric",
    "scope_grounding",
    "extract",
    "conventions",
    "assess",
    "cost",
    "aggregate_1",
    "boundary",
    "aggregate_2",
    "band_seam",
    "consistency",
    "pairwise_escalation",
    "committee_edge_resolver",
    "rerank",
    "pairwise_eval",
    "quality_gate",
    "sota_gate",
    "cohort_confidence",
    "pairwise",
    "grade",
    "dashboard",
)

ANCHOR_RESUME_STEP_IDS = (
    "aggregate_1",
    "boundary",
    "aggregate_2",
    "band_seam",
    "consistency",
    "pairwise_escalation",
    "committee_edge_resolver",
    "rerank",
    "pairwise_eval",
    "quality_gate",
    "sota_gate",
    "cohort_confidence",
    "grade",
    "dashboard",
)

def pipeline_steps() -> list[dict]:
    return [
        {
            "id": "rubric",
            "label": "Normalizing rubric contract",
            "cmd": [
                "python3",
                "scripts/normalize_rubric.py",
            ],
        },
        {
            "id": "scope_grounding",
            "label": "Grounding live cohort scope",
            "cmd": [
                "python3",
                "scripts/scope_retrieval.py",
            ],
            "required": False,
        },
        {
            "id": "extract",
            "label": "Extracting text",
            "cmd": [
                "python3",
                "scripts/extract_text.py",
                "--inputs",
                "inputs/submissions",
                "--output",
                "processing/normalized_text",
                "--metadata",
                "processing/submission_metadata.json",
            ],
        },
        {
            "id": "conventions",
            "label": "Scanning writing conventions",
            "cmd": [
                "python3",
                "scripts/conventions_scan.py",
                "--inputs",
                "processing/normalized_text",
                "--output",
                "processing/conventions_report.csv",
            ],
        },
        {"id": "assess", "label": "Running assessor passes", "cmd": ["python3", "scripts/run_llm_assessors.py"]},
        {
            "id": "cost",
            "label": "Tracking API usage cost",
            "cmd": ["python3", "scripts/usage_pricing.py", "--usage", "outputs/usage_log.jsonl", "--pricing", "config/pricing.json", "--output", "outputs/usage_costs.json"],
            "required": False,
        },
        {"id": "aggregate_1", "label": "Building consensus ranking", "cmd": ["python3", "scripts/aggregate_assessments.py", "--config", "config/marking_config.json"]},
        {"id": "boundary", "label": "Rechecking boundary essays", "cmd": ["python3", "scripts/boundary_recheck.py"]},
        {"id": "aggregate_2", "label": "Rebuilding consensus ranking", "cmd": ["python3", "scripts/aggregate_assessments.py", "--config", "config/marking_config.json"]},
        {"id": "band_seam", "label": "Adjudicating band seams", "cmd": ["python3", "scripts/band_seam_adjudication.py"]},
        {"id": "consistency", "label": "Collecting pairwise consistency evidence", "cmd": ["python3", "scripts/verify_consistency.py"]},
        {"id": "pairwise_escalation", "label": "Escalating unstable pairwise evidence", "cmd": ["python3", "scripts/escalate_pairwise_adjudications.py"]},
        {
            "id": "committee_edge_resolver",
            "label": "Resolving committee-edge overrides",
            "cmd": ["python3", "scripts/committee_edge_resolver.py"],
            "required": False,
        },
        {"id": "rerank", "label": "Applying global reranker", "cmd": ["python3", "scripts/global_rerank.py", "--judgments", "outputs/consistency_checks.committee_edge.json"]},
        {
            "id": "pairwise_eval",
            "label": "Evaluating routed hard-pair adjudication",
            "cmd": [
                "python3",
                "scripts/evaluate_pairwise_adjudicator.py",
                "--judgments",
                "outputs/consistency_checks.committee_edge.json",
                "--output",
                "outputs/pairwise_adjudicator_eval.json",
            ],
            "required": False,
        },
        {
            "id": "quality_gate",
            "label": "Running publish quality gate",
            "cmd": ["python3", "scripts/publish_gate.py", "--gate-config", "config/accuracy_gate.json"],
            "required": False,
        },
        {
            "id": "sota_gate",
            "label": "Enforcing SOTA readiness gate",
            "cmd": ["python3", "scripts/sota_gate.py", "--gate-config", "config/sota_gate.json"],
            "required": False,
        },
        {
            "id": "cohort_confidence",
            "label": "Evaluating live cohort confidence",
            "cmd": ["python3", "scripts/cohort_confidence.py"],
            "required": False,
        },
        {"id": "pairwise", "label": "Preparing pairwise review", "cmd": ["python3", "scripts/generate_pairwise_review.py"]},
        {"id": "grade", "label": "Applying level-aware bell curve", "cmd": ["python3", "scripts/review_and_grade.py", "--non-interactive"]},
        {"id": "dashboard", "label": "Building dashboard output", "cmd": ["python3", "scripts/build_dashboard_data.py"]},
    ]


def pipeline_step_map() -> dict[str, dict]:
    return {step["id"]: step for step in pipeline_steps()}


def pipeline_step_ids() -> tuple[str, ...]:
    return tuple(step["id"] for step in pipeline_steps())


def pipeline_steps_by_ids(step_ids: list[str] | tuple[str, ...]) -> list[dict]:
    step_map = pipeline_step_map()
    return [dict(step_map[step_id]) for step_id in step_ids if step_id in step_map]


def anchor_resume_steps() -> list[dict]:
    return pipeline_steps_by_ids(ANCHOR_RESUME_STEP_IDS)


def pipeline_step_command(step_id: str) -> list[str]:
    step = pipeline_step_map()[step_id]
    cmd = list(step["cmd"])
    if step_id == "committee_edge_resolver" and os.environ.get("COMMITTEE_EDGE_LIVE", "").strip().lower() in {"1", "true", "yes", "on"}:
        if "--live" not in cmd:
            cmd.append("--live")
    return cmd


def pipeline_step_graph_hash() -> str:
    payload = []
    for step in pipeline_steps():
        payload.append(
            {
                "id": step["id"],
                "label": step["label"],
                "cmd": list(step["cmd"]),
                "required": bool(step.get("required", True)),
            }
        )
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def workspace_asset_dirs() -> tuple[str, ...]:
    return RUNTIME_ASSET_DIRS


def artifact_watch_roots() -> tuple[str, ...]:
    return ARTIFACT_WATCH_ROOTS


def _can_stream_subprocess(run_fn) -> bool:
    return getattr(run_fn, "__module__", "") == "subprocess" and getattr(run_fn, "__name__", "") == "run"


def _run_capture(run_fn, cmd: list[str], env: dict, cwd: Path, on_output) -> tuple[int, str, str]:
    result = run_fn(cmd, env=env, cwd=str(cwd), capture_output=True, text=True)
    stdout = str(getattr(result, "stdout", "") or "")
    stderr = str(getattr(result, "stderr", "") or "")
    for line in stdout.splitlines():
        if line.strip():
            on_output("stdout", line.strip())
    for line in stderr.splitlines():
        if line.strip():
            on_output("stderr", line.strip())
    return int(getattr(result, "returncode", 1)), stdout, stderr


def _run_stream(cmd: list[str], env: dict, cwd: Path, on_output) -> tuple[int, str, str]:
    proc = subprocess.Popen(cmd, env=env, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    lines = queue.Queue()

    def pump(stream, source):
        for line in iter(stream.readline, ""):
            lines.put((source, line.rstrip("\n")))
        lines.put((source, None))

    th_out = threading.Thread(target=pump, args=(proc.stdout, "stdout"), daemon=True)
    th_err = threading.Thread(target=pump, args=(proc.stderr, "stderr"), daemon=True)
    th_out.start()
    th_err.start()

    closed = 0
    out_lines, err_lines = [], []
    while closed < 2:
        source, line = lines.get()
        if line is None:
            closed += 1
            continue
        text = line.strip()
        if not text:
            continue
        if source == "stdout":
            out_lines.append(text)
        else:
            err_lines.append(text)
        on_output(source, text)

    proc.wait()
    return int(proc.returncode), "\n".join(out_lines), "\n".join(err_lines)


def run_step(run_fn, cmd: list[str], env: dict, cwd: Path, on_output) -> tuple[int, str, str]:
    if _can_stream_subprocess(run_fn):
        return _run_stream(cmd, env, cwd, on_output)
    return _run_capture(run_fn, cmd, env, cwd, on_output)
