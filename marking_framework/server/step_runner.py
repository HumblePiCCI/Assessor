#!/usr/bin/env python3
import queue
import subprocess
import threading
from pathlib import Path


def pipeline_steps() -> list[dict]:
    return [
        {"id": "extract", "label": "Extracting text", "cmd": ["python3", "scripts/extract_text.py"]},
        {"id": "conventions", "label": "Scanning writing conventions", "cmd": ["python3", "scripts/conventions_scan.py"]},
        {"id": "calibrate", "label": "Calibrating assessors", "cmd": ["python3", "scripts/calibrate_assessors.py"]},
        {"id": "assess", "label": "Running assessor passes", "cmd": ["python3", "scripts/run_llm_assessors.py"]},
        {"id": "aggregate_1", "label": "Building consensus ranking", "cmd": ["python3", "scripts/aggregate_assessments.py", "--config", "config/marking_config.json"]},
        {"id": "boundary", "label": "Rechecking boundary essays", "cmd": ["python3", "scripts/boundary_recheck.py"]},
        {"id": "aggregate_2", "label": "Rebuilding consensus ranking", "cmd": ["python3", "scripts/aggregate_assessments.py", "--config", "config/marking_config.json"]},
        {"id": "consistency", "label": "Verifying ordering consistency", "cmd": ["python3", "scripts/verify_consistency.py", "--apply"]},
        {"id": "quality_gate", "label": "Running publish quality gate", "cmd": ["python3", "scripts/publish_gate.py", "--gate-config", "config/accuracy_gate.json"]},
        {"id": "pairwise", "label": "Preparing pairwise review", "cmd": ["python3", "scripts/generate_pairwise_review.py"]},
        {"id": "dashboard", "label": "Building dashboard output", "cmd": ["python3", "scripts/build_dashboard_data.py"]},
    ]


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
