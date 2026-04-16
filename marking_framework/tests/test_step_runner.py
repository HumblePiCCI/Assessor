import os
import subprocess
import types

from server import step_runner


def test_pipeline_steps_structure():
    steps = step_runner.pipeline_steps()
    ids = [item["id"] for item in steps]
    assert ids[0] == "rubric"
    assert ids[-1] == "dashboard"
    assert {"rubric", "assess", "band_seam", "consistency", "pairwise_escalation", "rerank", "quality_gate", "sota_gate", "grade"}.issubset(set(ids))
    assert "scope_grounding" in ids
    assert "cohort_confidence" in ids
    assert all("cmd" in item and "label" in item for item in steps)
    rubric = next(item for item in steps if item["id"] == "rubric")
    assert "normalize_rubric.py" in " ".join(str(part) for part in rubric["cmd"])
    extract = next(item for item in steps if item["id"] == "extract")
    assert "--inputs" in extract["cmd"]
    assert "inputs/submissions" in extract["cmd"]
    conventions = next(item for item in steps if item["id"] == "conventions")
    assert "--output" in conventions["cmd"]
    assert "processing/conventions_report.csv" in conventions["cmd"]
    rerank = next(item for item in steps if item["id"] == "rerank")
    assert "global_rerank.py" in " ".join(str(part) for part in rerank["cmd"])
    assert "outputs/consistency_checks.escalated.json" in rerank["cmd"]
    escalation = next(item for item in steps if item["id"] == "pairwise_escalation")
    assert "escalate_pairwise_adjudications.py" in " ".join(str(part) for part in escalation["cmd"])
    band_seam = next(item for item in steps if item["id"] == "band_seam")
    assert "band_seam_adjudication.py" in " ".join(str(part) for part in band_seam["cmd"])
    quality_gate = next(item for item in steps if item["id"] == "quality_gate")
    assert quality_gate["required"] is False
    sota_gate = next(item for item in steps if item["id"] == "sota_gate")
    assert sota_gate["required"] is False
    grade = next(item for item in steps if item["id"] == "grade")
    assert "--non-interactive" in grade["cmd"]
    assert step_runner.pipeline_step_ids() == tuple(ids)
    anchor_ids = [item["id"] for item in step_runner.anchor_resume_steps()]
    assert anchor_ids == list(step_runner.ANCHOR_RESUME_STEP_IDS)


def test_can_stream_subprocess_detection():
    assert step_runner._can_stream_subprocess(subprocess.run) is True
    assert step_runner._can_stream_subprocess(lambda *_a, **_k: None) is False


def test_run_capture_collects_nonempty_lines(tmp_path):
    seen = []

    def fake_run(cmd, env=None, cwd=None, capture_output=None, text=None):
        assert cmd == ["cmd"]
        assert capture_output is True
        assert text is True
        assert cwd == str(tmp_path)
        assert env["A"] == "1"
        return types.SimpleNamespace(returncode=7, stdout="one\n\n two \n", stderr="\nerr\n")

    code, stdout, stderr = step_runner._run_capture(
        fake_run,
        ["cmd"],
        {"A": "1"},
        tmp_path,
        lambda source, text: seen.append((source, text)),
    )
    assert code == 7
    assert stdout.startswith("one")
    assert stderr.strip() == "err"
    assert seen == [("stdout", "one"), ("stdout", "two"), ("stderr", "err")]


def test_run_stream_collects_stdout_and_stderr(tmp_path):
    cmd = ["python3", "-c", "import sys; print('hello'); print('warn', file=sys.stderr)"]
    seen = []
    code, stdout, stderr = step_runner._run_stream(
        cmd,
        os.environ.copy(),
        tmp_path,
        lambda source, text: seen.append((source, text)),
    )
    assert code == 0
    assert "hello" in stdout
    assert "warn" in stderr
    assert ("stdout", "hello") in seen
    assert ("stderr", "warn") in seen


def test_run_stream_skips_blank_lines(tmp_path):
    cmd = ["python3", "-c", "print(''); print('ok')"]
    seen = []
    code, stdout, stderr = step_runner._run_stream(
        cmd,
        os.environ.copy(),
        tmp_path,
        lambda source, text: seen.append((source, text)),
    )
    assert code == 0
    assert stderr == ""
    assert stdout.strip() == "ok"
    assert seen == [("stdout", "ok")]


def test_run_step_routes_by_runner_type(tmp_path):
    capture_seen = []

    def fake_run(cmd, env=None, cwd=None, capture_output=None, text=None):
        return types.SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    code, stdout, stderr = step_runner.run_step(
        fake_run,
        ["cmd"],
        {"A": "1"},
        tmp_path,
        lambda source, text: capture_seen.append((source, text)),
    )
    assert code == 0
    assert stdout.strip() == "ok"
    assert stderr == ""
    assert capture_seen == [("stdout", "ok")]

    stream_seen = []
    stream_code, stream_stdout, _stream_stderr = step_runner.run_step(
        subprocess.run,
        ["python3", "-c", "print('stream-ok')"],
        os.environ.copy(),
        tmp_path,
        lambda source, text: stream_seen.append((source, text)),
    )
    assert stream_code == 0
    assert "stream-ok" in stream_stdout
    assert ("stdout", "stream-ok") in stream_seen
