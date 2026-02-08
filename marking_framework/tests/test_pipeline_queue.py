import json
import types
from pathlib import Path

from server.pipeline_queue import PipelineQueue, snapshot_hash


def _write_inputs(base: Path):
    subs = base / "subs"
    subs.mkdir(parents=True, exist_ok=True)
    rubric = base / "rubric.md"
    outline = base / "assignment_outline.md"
    rubric.write_text("rubric", encoding="utf-8")
    outline.write_text("outline", encoding="utf-8")
    (subs / "s1.txt").write_text("essay one", encoding="utf-8")
    return rubric, outline, subs


def _make_queue(tmp_path, run_fn=None, reset_fn=None):
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    data = tmp_path / "data"
    data.mkdir()
    logs = []

    def log_fn(_root, run_id, message, detail=None):
        logs.append((run_id, message, detail))

    def api_key_fn():
        return "k"

    queue = PipelineQueue(
        root=root,
        data_dir=data,
        reset_workspace_fn=reset_fn or (lambda _root: None),
        run_fn=run_fn or (lambda *a, **k: types.SimpleNamespace(returncode=0, stderr="", stdout="")),
        log_fn=log_fn,
        api_key_fn=api_key_fn,
    )
    return queue, root, data, logs


def test_snapshot_hash_deterministic(tmp_path):
    rubric, outline, subs = _write_inputs(tmp_path / "a")
    cfg = tmp_path / "a" / "cfg.json"
    cfg.write_text("{}", encoding="utf-8")
    first = snapshot_hash("openai", rubric, outline, subs, [cfg])
    second = snapshot_hash("openai", rubric, outline, subs, [cfg])
    assert first == second
    (subs / "s1.txt").write_text("essay changed", encoding="utf-8")
    third = snapshot_hash("openai", rubric, outline, subs, [cfg])
    assert third != first


def test_snapshot_hash_missing_paths_and_non_file_entries(tmp_path):
    base = tmp_path / "b"
    subs = base / "subs"
    (subs / "nested").mkdir(parents=True)
    h = snapshot_hash("codex_local", base / "missing_rubric.md", base / "missing_outline.md", subs, [base / "missing.json"])
    assert isinstance(h, str) and len(h) == 64


def test_submit_and_worker_success(tmp_path):
    def run_ok(_cmd, env=None, cwd=None, **kwargs):
        out = Path(cwd) / "outputs"
        out.mkdir(parents=True, exist_ok=True)
        (out / "dashboard_data.json").write_text(json.dumps({"students": [{"student_id": "s1"}]}), encoding="utf-8")
        assert env["LLM_MODE"] == "openai"
        assert env["OPENAI_API_KEY"] == "k"
        return types.SimpleNamespace(returncode=0, stderr="", stdout="")

    queue, root, _data, _logs = _make_queue(tmp_path, run_fn=run_ok)
    old_subs = root / "inputs" / "submissions"
    old_subs.mkdir(parents=True, exist_ok=True)
    (old_subs / "old.txt").write_text("old", encoding="utf-8")
    (old_subs / "dir").mkdir()
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    result = queue.submit("openai", rubric, outline, subs, [])
    assert result["status"] == "queued"
    queue._queue.join()
    job = queue.get_job(result["job_id"])
    assert job["status"] == "completed"
    data = queue.load_dashboard_data(result["job_id"])
    assert data["students"][0]["student_id"] == "s1"


def test_start_worker_idempotent(tmp_path):
    queue, _root, _data, _logs = _make_queue(tmp_path)
    queue._start_worker()
    first = queue._thread
    queue._start_worker()
    assert queue._thread is first


def test_submit_cached_completed_snapshot(tmp_path):
    queue, _root, _data, _logs = _make_queue(tmp_path)
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    snap = snapshot_hash("openai", rubric, outline, subs, [])
    artifact = queue.artifacts_dir / snap / "dashboard_data.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{}", encoding="utf-8")
    queue._insert_job("done", snap, "openai", queue.jobs_dir / "done")
    queue._update_job("done", "completed", artifact=artifact)
    out = queue.submit("openai", rubric, outline, subs, [])
    assert out["cached"] is True
    assert out["job_id"] == "done"


def test_process_job_failure_paths(tmp_path):
    def run_fail(*_a, **_k):
        return types.SimpleNamespace(returncode=1, stderr="boom", stdout="out")

    queue, _root, _data, logs = _make_queue(tmp_path, run_fn=run_fail)
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    queue._start_worker = lambda: None
    result = queue.submit("openai", rubric, outline, subs, [])
    queue._process_job(result["job_id"])
    job = queue.get_job(result["job_id"])
    assert job["status"] == "failed"
    assert "boom" in job["error"]
    assert any("QUEUE ERROR hero_path failed" in entry[1] for entry in logs)


def test_process_job_without_api_key_and_skip_nonqueued(tmp_path, monkeypatch):
    calls = {}

    def run_ok(_cmd, env=None, cwd=None, **kwargs):
        calls["env"] = env
        out = Path(cwd) / "outputs"
        out.mkdir(parents=True, exist_ok=True)
        (out / "dashboard_data.json").write_text("{}", encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stderr="", stdout="")

    root = tmp_path / "root"
    root.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    queue = PipelineQueue(root, data, lambda _root: None, run_ok, lambda *_a, **_k: None, lambda: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    (subs / "dir").mkdir()
    queue._start_worker = lambda: None
    result = queue.submit("openai", rubric, outline, subs, [])
    queue._process_job(result["job_id"])
    assert "OPENAI_API_KEY" not in calls["env"]
    queue._update_job(result["job_id"], "failed", error="x")
    queue._process_job(result["job_id"])


def test_process_job_failure_stdout_or_stderr_only(tmp_path):
    queue_err, _root1, _data1, _logs1 = _make_queue(tmp_path / "e1", run_fn=lambda *_a, **_k: types.SimpleNamespace(returncode=1, stderr="boom", stdout=""))
    rubric1, outline1, subs1 = _write_inputs(tmp_path / "inputs1")
    queue_err._start_worker = lambda: None
    job1 = queue_err.submit("openai", rubric1, outline1, subs1, [])
    queue_err._process_job(job1["job_id"])
    assert queue_err.get_job(job1["job_id"])["status"] == "failed"

    queue_out, _root2, _data2, _logs2 = _make_queue(tmp_path / "e2", run_fn=lambda *_a, **_k: types.SimpleNamespace(returncode=1, stderr="", stdout="boom"))
    rubric2, outline2, subs2 = _write_inputs(tmp_path / "inputs2")
    queue_out._start_worker = lambda: None
    job2 = queue_out.submit("openai", rubric2, outline2, subs2, [])
    queue_out._process_job(job2["job_id"])
    assert queue_out.get_job(job2["job_id"])["status"] == "failed"


def test_process_job_missing_dashboard_and_unhandled(tmp_path):
    queue, _root, _data, logs = _make_queue(tmp_path)
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    queue._start_worker = lambda: None
    result = queue.submit("openai", rubric, outline, subs, [])
    queue._process_job(result["job_id"])
    assert queue.get_job(result["job_id"])["status"] == "failed"
    assert any("dashboard missing" in entry[1] for entry in logs)

    boom_queue, _r2, _d2, _logs2 = _make_queue(tmp_path / "boom", reset_fn=lambda _root: (_ for _ in ()).throw(RuntimeError("kaboom")))
    rubric2, outline2, subs2 = _write_inputs(tmp_path / "boom_inputs")
    boom_queue._start_worker = lambda: None
    result2 = boom_queue.submit("openai", rubric2, outline2, subs2, [])
    boom_queue._process_job(result2["job_id"])
    assert boom_queue.get_job(result2["job_id"])["status"] == "failed"


def test_job_lookup_and_artifact_edge_cases(tmp_path):
    queue, _root, _data, _logs = _make_queue(tmp_path)
    assert queue.get_job("missing") is None
    assert queue.load_dashboard_data("missing") is None
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    queue._start_worker = lambda: None
    result = queue.submit("openai", rubric, outline, subs, [])
    assert queue.load_dashboard_data(result["job_id"]) is None
    job = queue.get_job(result["job_id"])
    queue._update_job(result["job_id"], "completed", artifact=Path(job["job_dir"]) / "missing.json")
    assert queue.load_dashboard_data(result["job_id"]) is None


def test_find_completed_snapshot_missing_artifact(tmp_path):
    queue, _root, _data, _logs = _make_queue(tmp_path)
    queue._insert_job("j1", "abc", "openai", queue.jobs_dir / "j1")
    queue._update_job("j1", "completed", artifact=queue.artifacts_dir / "abc" / "nope.json")
    assert queue._find_completed_snapshot("abc") is None


def test_copy_inputs_skips_non_files_in_source_submissions(tmp_path):
    queue, root, _data, _logs = _make_queue(tmp_path)
    job_dir = tmp_path / "job"
    src_inputs = job_dir / "inputs"
    src_subs = src_inputs / "submissions"
    src_subs.mkdir(parents=True, exist_ok=True)
    (src_inputs / "rubric.md").write_text("r", encoding="utf-8")
    (src_inputs / "assignment_outline.md").write_text("o", encoding="utf-8")
    (src_subs / "s1.txt").write_text("essay", encoding="utf-8")
    (src_subs / "nested").mkdir()
    queue._copy_inputs_to_workspace(job_dir)
    assert (root / "inputs" / "submissions" / "s1.txt").exists()
    assert not (root / "inputs" / "submissions" / "nested").exists()
