import json
import shutil
import types
from pathlib import Path

import pytest

from server.pipeline_queue import PipelineQueue, build_pipeline_manifest, manifest_hash, snapshot_hash
import server.pipeline_queue as pqmod


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _seed_runtime(root: Path):
    for dirname in ["scripts", "config", "prompts", "templates", "docs", "ui", "server", "outputs"]:
        (root / dirname).mkdir(parents=True, exist_ok=True)
    exemplar_dir = root / "inputs" / "exemplars" / "grade_6_7" / "literary_analysis"
    exemplar_dir.mkdir(parents=True, exist_ok=True)
    (exemplar_dir / "level_3.md").write_text("anchor exemplar", encoding="utf-8")
    (root / "prompts" / "assessor_pass1.md").write_text("prompt v1", encoding="utf-8")
    (root / "templates" / "assessor_pass1_template.json").write_text("{}", encoding="utf-8")
    (root / "docs" / "ASSESSOR_ROLES.md").write_text("roles", encoding="utf-8")
    (root / "ui" / "app.js").write_text("console.log('ui')", encoding="utf-8")
    (root / "scripts" / "placeholder.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "server" / "bootstrap.py").write_text("BOOTSTRAP = True\n", encoding="utf-8")
    (root / "server" / "pipeline_queue.py").write_text("PIPELINE = True\n", encoding="utf-8")
    (root / "server" / "step_runner.py").write_text("STEP_RUNNER = True\n", encoding="utf-8")
    _write_json(
        root / "config" / "llm_routing.json",
        {
            "mode": "openai",
            "tasks": {
                "pass1_assessor": {"model": "gpt-5.2", "reasoning": "medium"},
                "pairwise_reviewer": {"model": "gpt-5.2-mini", "reasoning": "low"},
            },
            "quality_gates": {"min_model_coverage": 0.9},
            "pass1_guard": {"enabled": True},
            "calibration_gate": {"enabled": True, "bias_path": "outputs/calibration_bias.json"},
        },
    )
    _write_json(root / "config" / "marking_config.json", {"curve": {"profile": "default"}})
    _write_json(root / "config" / "rubric_criteria.json", {"criteria": []})
    _write_json(root / "config" / "accuracy_gate.json", {"thresholds": {"min_rank_kendall_w": 0.65}})
    _write_json(root / "config" / "sota_gate.json", {"thresholds": {"require_publish_gate_ok": True}})
    _write_json(root / "config" / "grade_level_profiles.json", {"grade_7": {"notes": "profile"}})
    _write_json(root / "config" / "calibration_set.json", {"samples": []})
    _write_json(root / "config" / "cost_limits.json", {"hard_cap": 1.0})
    _write_json(root / "config" / "pricing.json", {"models": {}})
    _write_json(root / "outputs" / "calibration_bias.json", {"bias": 0.0, "generated_at": "2026-01-01T00:00:00+00:00"})


def _write_inputs(base: Path, submission_name: str = "s1.txt", submission_text: str = "essay one"):
    subs = base / "subs"
    subs.mkdir(parents=True, exist_ok=True)
    rubric = base / "rubric.md"
    outline = base / "assignment_outline.md"
    rubric.write_text("rubric", encoding="utf-8")
    outline.write_text("outline", encoding="utf-8")
    (subs / submission_name).write_text(submission_text, encoding="utf-8")
    return rubric, outline, subs


def _extra_paths(root: Path) -> list[Path]:
    return [
        root / "config" / "llm_routing.json",
        root / "config" / "marking_config.json",
        root / "config" / "rubric_criteria.json",
        root / "config" / "accuracy_gate.json",
        root / "config" / "sota_gate.json",
    ]


def _make_queue(tmp_path, run_fn=None, reset_fn=None):
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    _seed_runtime(root)
    data = tmp_path / "data"
    data.mkdir()
    logs = []
    resets = []

    def log_fn(_root, run_id, message, detail=None):
        logs.append((run_id, message, detail))

    def api_key_fn():
        return "k"

    def default_reset(workspace_root: Path):
        resets.append(workspace_root)
        inputs_dir = workspace_root / "inputs"
        exemplars_dir = inputs_dir / "exemplars"
        subs_dir = inputs_dir / "submissions"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        exemplars_dir.mkdir(parents=True, exist_ok=True)
        for item in inputs_dir.iterdir():
            if item.name in {"submissions", "exemplars"}:
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        if subs_dir.exists():
            shutil.rmtree(subs_dir)
        subs_dir.mkdir(parents=True, exist_ok=True)
        for name in ["processing", "assessments", "outputs"]:
            path = workspace_root / name
            if path.exists():
                shutil.rmtree(path)

    queue = PipelineQueue(
        root=root,
        data_dir=data,
        reset_workspace_fn=reset_fn or default_reset,
        run_fn=run_fn or (lambda *a, **k: types.SimpleNamespace(returncode=0, stderr="", stdout="")),
        log_fn=log_fn,
        api_key_fn=api_key_fn,
    )
    return queue, root, data, logs, resets


def test_snapshot_hash_changes_with_inputs_and_manifest_round_trip(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _seed_runtime(root)
    rubric, outline, subs = _write_inputs(tmp_path / "a")
    first = snapshot_hash("openai", rubric, outline, subs, _extra_paths(root), root=root)
    second = snapshot_hash("openai", rubric, outline, subs, _extra_paths(root), root=root)
    assert first == second
    manifest = build_pipeline_manifest(root, "openai", rubric, outline, subs, _extra_paths(root))
    manifest_path = tmp_path / "pipeline_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_hash(loaded) == manifest["manifest_hash"]
    assert manifest["run_scope"]["grade_band"] == "grade_6_7"
    assert "calibration_manifest" in manifest
    (subs / "s1.txt").write_text("essay changed", encoding="utf-8")
    changed = snapshot_hash("openai", rubric, outline, subs, _extra_paths(root), root=root)
    assert changed != first


def test_snapshot_hash_missing_paths_and_non_file_entries(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _seed_runtime(root)
    base = tmp_path / "b"
    subs = base / "subs"
    (subs / "nested").mkdir(parents=True)
    digest = snapshot_hash(
        "codex_local",
        base / "missing_rubric.md",
        base / "missing_outline.md",
        subs,
        [base / "missing.json"],
        root=root,
    )
    assert isinstance(digest, str) and len(digest) == 64


@pytest.mark.parametrize(
    ("target_relpath", "write_fn"),
    [
        ("config/llm_routing.json", lambda path: _write_json(path, {"mode": "openai", "tasks": {"pass1_assessor": {"model": "gpt-5.4"}}})),
        ("config/marking_config.json", lambda path: _write_json(path, {"curve": {"profile": "shifted"}})),
        ("inputs/exemplars/grade_6_7/literary_analysis/level_3.md", lambda path: path.write_text("edited exemplar", encoding="utf-8")),
        ("outputs/calibration_bias.json", lambda path: _write_json(path, {"bias": 1.5, "generated_at": "2026-01-02T00:00:00+00:00"})),
    ],
)
def test_manifest_hash_busts_when_dependency_changes(tmp_path, target_relpath, write_fn):
    root = tmp_path / "root"
    root.mkdir()
    _seed_runtime(root)
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    baseline = snapshot_hash("openai", rubric, outline, subs, _extra_paths(root), root=root)
    write_fn(root / target_relpath)
    changed = snapshot_hash("openai", rubric, outline, subs, _extra_paths(root), root=root)
    assert changed != baseline


def test_submit_and_worker_success_uses_isolated_workspace_and_manifest_artifacts(tmp_path):
    calls = {}

    def run_ok(_cmd, env=None, cwd=None, **kwargs):
        workspace = Path(cwd)
        calls.setdefault("cwds", []).append(workspace)
        calls["env"] = env
        assert (workspace / "inputs" / "submissions" / "s1.txt").exists()
        assert (workspace / "config" / "marking_config.json").exists()
        out = workspace / "outputs"
        out.mkdir(parents=True, exist_ok=True)
        (out / "dashboard_data.json").write_text(json.dumps({"students": [{"student_id": "s1"}]}), encoding="utf-8")
        (out / "consistency_adjusted.csv").write_text("student_id\ns1\n", encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stderr="", stdout="")

    queue, root, data, _logs, resets = _make_queue(tmp_path, run_fn=run_ok)
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    queue._start_worker = lambda: None
    result = queue.submit("openai", rubric, outline, subs, _extra_paths(root))
    queue._process_job(result["job_id"])
    job = queue.get_job(result["job_id"])
    assert job["status"] == "completed"
    workspace_dir = Path(job["workspace_dir"])
    assert workspace_dir == queue._workspace_dir(result["job_id"], "local-dev-tenant")
    assert workspace_dir in resets
    assert calls["cwds"] and calls["cwds"][0] == workspace_dir
    assert calls["env"]["LLM_MODE"] == "openai"
    assert calls["env"]["OPENAI_API_KEY"] == "k"
    assert calls["env"]["PIPELINE_MANIFEST_HASH"] == result["manifest_hash"]
    assert "PYTHONPATH" in calls["env"]
    assert not (root / "outputs" / "dashboard_data.json").exists()
    assert (workspace_dir / "pipeline_manifest.json").exists()
    assert (Path(job["manifest_path"])).exists()
    artifact_dir = queue._artifact_dir(result["manifest_hash"], "local-dev-tenant")
    assert (artifact_dir / "pipeline_manifest.json").exists()
    assert (artifact_dir / "outputs" / "dashboard_data.json").exists()
    data_json = queue.load_dashboard_data(result["job_id"])
    assert data_json["students"][0]["student_id"] == "s1"


def test_submit_cached_completed_snapshot(tmp_path):
    queue, root, _data, _logs, _resets = _make_queue(tmp_path)
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    snap = snapshot_hash("openai", rubric, outline, subs, _extra_paths(root), root=root)
    artifact = queue._artifact_dir(snap, "local-dev-tenant") / "outputs" / "dashboard_data.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{}", encoding="utf-8")
    (artifact.parent.parent / "pipeline_manifest.json").write_text(json.dumps({"manifest_hash": snap}), encoding="utf-8")
    queue._insert_job("done", snap, "openai", queue._job_dir("done", "local-dev-tenant"), tenant_id="local-dev-tenant", teacher_id="local-dev-teacher", project_id="")
    queue._update_job("done", "completed", artifact=artifact)
    out = queue.submit("openai", rubric, outline, subs, _extra_paths(root))
    assert out["cached"] is True
    assert out["job_id"] == "done"
    assert out["manifest_hash"] == snap


def test_two_jobs_stage_inputs_into_separate_workspaces(tmp_path):
    queue, root, data, _logs, _resets = _make_queue(tmp_path)
    queue._start_worker = lambda: None
    rubric1, outline1, subs1 = _write_inputs(tmp_path / "inputs1", submission_name="alpha.txt", submission_text="alpha essay")
    rubric2, outline2, subs2 = _write_inputs(tmp_path / "inputs2", submission_name="beta.txt", submission_text="beta essay")
    first = queue.submit("openai", rubric1, outline1, subs1, _extra_paths(root))
    second = queue.submit("openai", rubric2, outline2, subs2, _extra_paths(root))
    first_workspace = queue._workspace_dir(first["job_id"], "local-dev-tenant")
    second_workspace = queue._workspace_dir(second["job_id"], "local-dev-tenant")
    assert first_workspace != second_workspace
    assert (first_workspace / "inputs" / "submissions" / "alpha.txt").exists()
    assert not (first_workspace / "inputs" / "submissions" / "beta.txt").exists()
    assert (second_workspace / "inputs" / "submissions" / "beta.txt").exists()
    assert not (second_workspace / "inputs" / "submissions" / "alpha.txt").exists()
    assert not (root / "inputs" / "submissions" / "alpha.txt").exists()
    assert not (root / "inputs" / "submissions" / "beta.txt").exists()


def test_process_job_failure_paths(tmp_path):
    def run_fail(*_a, **_k):
        return types.SimpleNamespace(returncode=1, stderr="boom", stdout="out")

    queue, root, _data, logs, _resets = _make_queue(tmp_path, run_fn=run_fail)
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    queue._start_worker = lambda: None
    result = queue.submit("openai", rubric, outline, subs, _extra_paths(root))
    queue._process_job(result["job_id"])
    job = queue.get_job(result["job_id"])
    assert job["status"] == "failed"
    assert "boom" in job["error"]
    assert any("QUEUE ERROR step" in entry[1] for entry in logs)


def test_process_job_without_api_key_and_skip_nonqueued(tmp_path, monkeypatch):
    calls = {}

    def run_ok(_cmd, env=None, cwd=None, **kwargs):
        calls["env"] = env
        out = Path(cwd) / "outputs"
        out.mkdir(parents=True, exist_ok=True)
        (out / "dashboard_data.json").write_text("{}", encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stderr="", stdout="")

    queue, root, _data, _logs, _resets = _make_queue(tmp_path, run_fn=run_ok)
    queue.get_api_key = lambda: None
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    queue._start_worker = lambda: None
    result = queue.submit("openai", rubric, outline, subs, _extra_paths(root))
    queue._process_job(result["job_id"])
    assert "OPENAI_API_KEY" not in calls["env"]
    queue._update_job(result["job_id"], "failed", error="x")
    queue._process_job(result["job_id"])


def test_process_job_missing_dashboard_and_unhandled(tmp_path):
    queue, root, _data, logs, _resets = _make_queue(tmp_path)
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    queue._start_worker = lambda: None
    result = queue.submit("openai", rubric, outline, subs, _extra_paths(root))
    queue._process_job(result["job_id"])
    assert queue.get_job(result["job_id"])["status"] == "failed"
    assert any("dashboard missing" in entry[1] for entry in logs)

    def boom_run(*_a, **_k):
        raise RuntimeError("kaboom")

    boom_queue, boom_root, _d2, _l2, _r2 = _make_queue(tmp_path / "boom", run_fn=boom_run)
    rubric2, outline2, subs2 = _write_inputs(tmp_path / "boom_inputs")
    boom_queue._start_worker = lambda: None
    result2 = boom_queue.submit("openai", rubric2, outline2, subs2, _extra_paths(boom_root))
    boom_queue._process_job(result2["job_id"])
    assert boom_queue.get_job(result2["job_id"])["status"] == "failed"


def test_job_lookup_and_artifact_edge_cases(tmp_path):
    queue, root, _data, _logs, _resets = _make_queue(tmp_path)
    assert queue.get_job("missing") is None
    assert queue.load_dashboard_data("missing") is None
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    queue._start_worker = lambda: None
    result = queue.submit("openai", rubric, outline, subs, _extra_paths(root))
    assert queue.load_dashboard_data(result["job_id"]) is None
    job = queue.get_job(result["job_id"])
    queue._update_job(result["job_id"], "completed", artifact=Path(job["job_dir"]) / "missing.json")
    assert queue.load_dashboard_data(result["job_id"]) is None


def test_find_completed_snapshot_missing_artifact(tmp_path):
    queue, _root, _data, _logs, _resets = _make_queue(tmp_path)
    queue._insert_job("j1", "abc", "openai", queue._job_dir("j1", "local-dev-tenant"), tenant_id="local-dev-tenant", teacher_id="local-dev-teacher", project_id="")
    queue._update_job("j1", "completed", artifact=queue._artifact_dir("abc", "local-dev-tenant") / "outputs" / "nope.json")
    assert queue._find_completed_snapshot("abc", "local-dev-tenant", "local-dev-teacher") is None


def test_get_events_handles_offsets_bad_json_and_done_flag(tmp_path):
    queue, root, _data, _logs, _resets = _make_queue(tmp_path)
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    queue._start_worker = lambda: None
    submitted = queue.submit("openai", rubric, outline, subs, _extra_paths(root))
    job_id = submitted["job_id"]
    job = queue.get_job(job_id)
    event_path = Path(job["job_dir"]) / "events.jsonl"
    event_path.write_text(
        json.dumps({"timestamp": "t", "stage": "extract", "event": "output", "source": "stdout", "level": "info", "message": "first"}) + "\n"
        + "{bad json}\n",
        encoding="utf-8",
    )
    all_events = queue.get_events(job_id, after=-1, limit=10)
    assert all_events["status"] == "queued"
    assert all_events["done"] is False
    assert [e["index"] for e in all_events["events"]] == [0, 1]
    assert all_events["events"][1]["level"] == "error"
    one_event = queue.get_events(job_id, after=0, limit=1)
    assert len(one_event["events"]) == 1
    assert one_event["events"][0]["index"] == 1
    queue._update_job(job_id, "completed")
    done_events = queue.get_events(job_id, after=-1, limit=10)
    assert done_events["done"] is True


def test_get_events_returns_none_for_missing_job(tmp_path):
    queue, _root, _data, _logs, _resets = _make_queue(tmp_path)
    assert queue.get_events("missing") is None


def test_standardized_events_include_start_output_artifacts_and_complete(tmp_path, monkeypatch):
    steps = [{"id": "single", "label": "Single", "cmd": ["single"]}]
    monkeypatch.setattr(pqmod, "pipeline_steps", lambda: steps)

    def run_fn(_cmd, env=None, cwd=None, **kwargs):
        out = Path(cwd) / "outputs"
        out.mkdir(parents=True, exist_ok=True)
        (out / "dashboard_data.json").write_text("{}", encoding="utf-8")
        (out / "step_output.txt").write_text("made", encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="hello", stderr="warn")

    queue, root, _data, _logs, _resets = _make_queue(tmp_path, run_fn=run_fn)
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    queue._start_worker = lambda: None
    submitted = queue.submit("openai", rubric, outline, subs, _extra_paths(root))
    queue._process_job(submitted["job_id"])
    events = queue.get_events(submitted["job_id"], after=-1, limit=100)["events"]
    event_types = [item.get("event") for item in events]
    assert "start" in event_types
    assert "output" in event_types
    assert "artifact" in event_types
    assert "complete" in event_types
    artifact_events = [item for item in events if item.get("event") == "artifact"]
    assert any("outputs/step_output.txt" in item.get("artifacts", []) for item in artifact_events)


def test_non_blocking_step_failure_continues(tmp_path, monkeypatch):
    steps = [
        {"id": "ok", "label": "Ok", "cmd": ["ok"]},
        {"id": "warn", "label": "Warn", "cmd": ["warn"], "required": False},
        {"id": "final", "label": "Final", "cmd": ["final"]},
    ]
    monkeypatch.setattr(pqmod, "pipeline_steps", lambda: steps)

    def run_fn(cmd, env=None, cwd=None, **kwargs):
        if cmd == ["warn"]:
            return types.SimpleNamespace(returncode=1, stdout="w", stderr="e")
        out = Path(cwd) / "outputs"
        out.mkdir(parents=True, exist_ok=True)
        (out / "dashboard_data.json").write_text("{}", encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    queue, root, _data, logs, _resets = _make_queue(tmp_path, run_fn=run_fn)
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    queue._start_worker = lambda: None
    submitted = queue.submit("openai", rubric, outline, subs, _extra_paths(root))
    queue._process_job(submitted["job_id"])
    job = queue.get_job(submitted["job_id"])
    assert job["status"] == "completed"
    assert any("QUEUE WARN step warn failed (non-blocking)" in entry[1] for entry in logs)


def test_cache_lookup_is_teacher_scoped_and_ops_track_validation_failures(tmp_path):
    queue, root, _data, _logs, _resets = _make_queue(tmp_path)
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    snap = snapshot_hash("openai", rubric, outline, subs, _extra_paths(root), root=root)
    bad_artifact = queue._artifact_dir(snap, "tenant-a") / "outputs" / "dashboard_data.json"
    bad_artifact.parent.mkdir(parents=True, exist_ok=True)
    bad_artifact.write_text("{}", encoding="utf-8")
    (bad_artifact.parent.parent / "pipeline_manifest.json").write_text(json.dumps({"manifest_hash": "wrong"}), encoding="utf-8")
    queue._insert_job("cached-a", snap, "openai", queue._job_dir("cached-a", "tenant-a"), tenant_id="tenant-a", teacher_id="teacher-a", project_id="")
    queue._update_job("cached-a", "completed", artifact=bad_artifact)
    assert queue._find_completed_snapshot(snap, "tenant-a", "teacher-a") is None
    ops = queue.ops_summary()
    assert ops["cache"]["validation_failures"] == 1
    assert "cache_validation_failures_present" in ops["warnings"]

    fresh = queue.submit(
        "openai",
        rubric,
        outline,
        subs,
        _extra_paths(root),
        identity={"tenant_id": "tenant-a", "teacher_id": "teacher-b"},
    )
    assert fresh["cached"] is False


def test_large_class_staging_smoke(tmp_path):
    queue, root, _data, _logs, _resets = _make_queue(tmp_path)
    queue._start_worker = lambda: None
    inputs_dir = tmp_path / "large_inputs"
    rubric, outline, subs = _write_inputs(inputs_dir, submission_name="essay_000.txt", submission_text="essay 0")
    for index in range(1, 121):
        (subs / f"essay_{index:03d}.txt").write_text(f"essay {index}", encoding="utf-8")
    submitted = queue.submit("openai", rubric, outline, subs, _extra_paths(root))
    workspace = queue._workspace_dir(submitted["job_id"], "local-dev-tenant")
    staged = sorted((workspace / "inputs" / "submissions").glob("*.txt"))
    assert len(staged) == 121
    assert staged[0].name == "essay_000.txt"
    assert staged[-1].name == "essay_120.txt"


def test_ops_summary_and_retention_report(tmp_path):
    queue, root, _data, _logs, _resets = _make_queue(tmp_path)
    rubric, outline, subs = _write_inputs(tmp_path / "inputs")
    queue._start_worker = lambda: None
    submitted = queue.submit("openai", rubric, outline, subs, _extra_paths(root))
    queue._update_job(
        submitted["job_id"],
        "completed",
        artifact=queue._artifact_dir(submitted["manifest_hash"], "local-dev-tenant") / "outputs" / "dashboard_data.json",
        started_at="2026-03-30T00:00:00+00:00",
        completed_at="2026-03-30T00:02:00+00:00",
    )
    artifact = queue._artifact_dir(submitted["manifest_hash"], "local-dev-tenant") / "outputs" / "dashboard_data.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{}", encoding="utf-8")
    (artifact.parent.parent / "pipeline_manifest.json").write_text(json.dumps({"manifest_hash": submitted["manifest_hash"]}), encoding="utf-8")
    ops = queue.ops_summary()
    assert ops["jobs"]["completed"] == 1
    assert ops["latency"]["p95_seconds"] == 120.0
    report = queue.prune_retention(dry_run=True)
    assert report["dry_run"] is True
    assert queue.ops_summary()["last_retention_report"]["dry_run"] is True
