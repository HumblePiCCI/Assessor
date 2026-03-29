#!/usr/bin/env python3
import hashlib
import json
import os
import queue
import shutil
import sqlite3
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from server.bootstrap import ensure_bootstrap_calibration, ensure_class_metadata
from server.step_runner import (
    artifact_watch_roots,
    pipeline_step_graph_hash,
    pipeline_steps,
    run_step,
    workspace_asset_dirs,
)

PIPELINE_MANIFEST_VERSION = 1
IGNORED_RUNTIME_NAMES = ("__pycache__", ".DS_Store")
IGNORED_RUNTIME_SUFFIXES = (".pyc", ".pyo")
CORE_CONFIG_PATHS = (
    "config/accuracy_gate.json",
    "config/calibration_set.json",
    "config/cost_limits.json",
    "config/grade_level_profiles.json",
    "config/llm_routing.json",
    "config/marking_config.json",
    "config/pricing.json",
    "config/rubric_criteria.json",
    "config/sota_gate.json",
)
GATE_CONFIG_PATHS = (
    "config/accuracy_gate.json",
    "config/sota_gate.json",
)
PROMPTS_DIR = "prompts"
EXEMPLARS_DIR = "inputs/exemplars"
CALIBRATION_ARTIFACT = "outputs/calibration_bias.json"
RUNTIME_SOURCE_PATHS = (
    "server/bootstrap.py",
    "server/pipeline_queue.py",
    "server/step_runner.py",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _should_ignore_path(path: Path) -> bool:
    return path.name in IGNORED_RUNTIME_NAMES or path.suffix in IGNORED_RUNTIME_SUFFIXES


def _root_relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return path.name


def _file_sha256(path: Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _hash_file_into_digest(path: Path, digest, rel_path: str):
    digest.update(rel_path.encode("utf-8"))
    digest.update(b"\0")
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    digest.update(b"\0")


def _iter_tree_files(path: Path):
    if not path.exists():
        return []
    if path.is_file():
        return [path]
    files = []
    for item in sorted(path.rglob("*")):
        if not item.is_file() or _should_ignore_path(item):
            continue
        files.append(item)
    return files


def _tree_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    files = _iter_tree_files(path)
    if path.is_file():
        _hash_file_into_digest(path, digest, path.name)
    else:
        for item in files:
            rel = str(item.relative_to(path))
            _hash_file_into_digest(item, digest, rel)
    return digest.hexdigest()


def _tree_manifest(path: Path, label: str) -> dict:
    files = []
    if path.exists():
        if path.is_file():
            files.append({"path": label, "sha256": _file_sha256(path)})
        else:
            for item in _iter_tree_files(path):
                files.append({"path": str(item.relative_to(path)), "sha256": _file_sha256(item)})
    return {
        "path": label,
        "exists": path.exists(),
        "file_count": len(files),
        "tree_hash": _tree_hash(path),
        "files": files,
    }


def _file_manifest(path: Path, label: str) -> dict:
    return {
        "path": label,
        "exists": path.exists(),
        "sha256": _file_sha256(path),
    }


def _collect_input_files(rubric_path: Path, outline_path: Path, submissions_dir: Path) -> dict:
    submissions = []
    if submissions_dir.exists():
        for item in sorted(submissions_dir.glob("*")):
            if not item.is_file():
                continue
            submissions.append({"path": f"inputs/submissions/{item.name}", "sha256": _file_sha256(item)})
    return {
        "rubric": _file_manifest(rubric_path, f"inputs/{rubric_path.name}"),
        "outline": _file_manifest(outline_path, f"inputs/{outline_path.name}"),
        "submissions": submissions,
    }


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _git_sha(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip() or None


def _git_dirty(root: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return bool((result.stdout or "").strip())


def _routing_summary(path: Path) -> dict:
    payload = _load_json(path)
    tasks = payload.get("tasks", {})
    task_models = {}
    task_settings = {}
    if isinstance(tasks, dict):
        for task_name in sorted(tasks):
            task_cfg = tasks.get(task_name)
            if not isinstance(task_cfg, dict):
                continue
            task_models[task_name] = task_cfg.get("model")
            task_settings[task_name] = {
                key: task_cfg.get(key)
                for key in ("model", "reasoning", "temperature", "max_output_tokens", "require_evidence")
                if key in task_cfg
            }
    return {
        "path": "config/llm_routing.json",
        "sha256": _file_sha256(path),
        "mode": payload.get("mode"),
        "task_models": task_models,
        "task_settings": task_settings,
        "quality_gates": payload.get("quality_gates", {}),
        "pass1_guard": payload.get("pass1_guard", {}),
        "calibration_gate": payload.get("calibration_gate", {}),
    }


def _config_hashes(root: Path, extra_paths: list[Path]) -> tuple[dict, dict]:
    config_hashes = {}
    seen = set()
    for rel_path in CORE_CONFIG_PATHS:
        full_path = root / rel_path
        config_hashes[rel_path] = _file_manifest(full_path, rel_path)
        seen.add(str(full_path.resolve()) if full_path.exists() else str(full_path))
    extra_hashes = {}
    for path in extra_paths:
        key = _root_relative(path, root)
        token = str(path.resolve()) if path.exists() else str(path)
        if token in seen:
            continue
        extra_hashes[key] = _file_manifest(path, key)
        seen.add(token)
    return config_hashes, extra_hashes


def manifest_hash(manifest: dict) -> str:
    canonical = {key: value for key, value in manifest.items() if key not in {"manifest_hash", "snapshot_hash"}}
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _infer_root(rubric_path: Path, outline_path: Path, submissions_dir: Path, extra_paths: list[Path]) -> Path:
    candidates = [rubric_path.parent, outline_path.parent, submissions_dir]
    candidates.extend(path.parent for path in extra_paths)
    try:
        common = os.path.commonpath([str(path.resolve()) for path in candidates])
    except Exception:
        return Path.cwd()
    return Path(common)


def build_pipeline_manifest(
    root: Path,
    mode: str,
    rubric_path: Path,
    outline_path: Path,
    submissions_dir: Path,
    extra_paths: list[Path] | None = None,
) -> dict:
    root = root.resolve()
    extra_paths = extra_paths or []
    config_hashes, extra_hashes = _config_hashes(root, extra_paths)
    gate_hashes = {
        rel_path: config_hashes.get(rel_path) or _file_manifest(root / rel_path, rel_path)
        for rel_path in GATE_CONFIG_PATHS
    }
    prompt_manifest = _tree_manifest(root / PROMPTS_DIR, PROMPTS_DIR)
    exemplar_manifest = _tree_manifest(root / EXEMPLARS_DIR, EXEMPLARS_DIR)
    runtime_dir_hashes = {}
    for dirname in workspace_asset_dirs():
        runtime_dir_hashes[dirname] = _tree_manifest(root / dirname, dirname)
    runtime_source_hashes = {}
    for rel_path in RUNTIME_SOURCE_PATHS:
        runtime_source_hashes[rel_path] = _file_manifest(root / rel_path, rel_path)
    step_graph_steps = []
    for step in pipeline_steps():
        step_graph_steps.append(
            {
                "id": step["id"],
                "label": step["label"],
                "cmd": list(step["cmd"]),
                "required": bool(step.get("required", True)),
            }
        )
    manifest = {
        "manifest_version": PIPELINE_MANIFEST_VERSION,
        "execution_engine": "pipeline_queue",
        "execution_mode": mode,
        "git": {
            "sha": _git_sha(root),
            "dirty": _git_dirty(root),
        },
        "step_graph": {
            "hash": pipeline_step_graph_hash(),
            "steps": step_graph_steps,
        },
        "uploaded_inputs": _collect_input_files(rubric_path, outline_path, submissions_dir),
        "prompt_hashes": prompt_manifest,
        "config_hashes": config_hashes,
        "extra_hashes": extra_hashes,
        "exemplar_tree": exemplar_manifest,
        "calibration_artifact": _file_manifest(root / CALIBRATION_ARTIFACT, CALIBRATION_ARTIFACT),
        "model_routing": _routing_summary(root / "config" / "llm_routing.json"),
        "grade_profile": _file_manifest(root / "config" / "grade_level_profiles.json", "config/grade_level_profiles.json"),
        "gate_threshold_hashes": gate_hashes,
        "runtime_assets": {
            "directories": runtime_dir_hashes,
            "source_files": runtime_source_hashes,
        },
    }
    digest = manifest_hash(manifest)
    manifest["manifest_hash"] = digest
    manifest["snapshot_hash"] = digest
    return manifest


def snapshot_hash(
    mode: str,
    rubric_path: Path,
    outline_path: Path,
    submissions_dir: Path,
    extra_paths: list[Path],
    root: Path | None = None,
) -> str:
    manifest = build_pipeline_manifest(
        root=(root or _infer_root(rubric_path, outline_path, submissions_dir, extra_paths)),
        mode=mode,
        rubric_path=rubric_path,
        outline_path=outline_path,
        submissions_dir=submissions_dir,
        extra_paths=extra_paths,
    )
    return manifest["manifest_hash"]


class PipelineQueue:
    def __init__(self, root: Path, data_dir: Path, reset_workspace_fn, run_fn, log_fn, api_key_fn):
        self.root = root
        self.data_dir = data_dir
        self.jobs_dir = data_dir / "pipeline_jobs"
        self.workspaces_dir = data_dir / "workspaces"
        self.artifacts_dir = data_dir / "artifacts"
        self.db_path = data_dir / "pipeline_jobs.sqlite3"
        self.reset_workspace = reset_workspace_fn
        self.run = run_fn
        self.log = log_fn
        self.get_api_key = api_key_fn
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._queue = queue.Queue()
        self._thread = None
        self._lock = threading.Lock()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _ensure_columns(self, conn):
        required = {
            "progress_current": "INTEGER DEFAULT 0",
            "progress_total": "INTEGER DEFAULT 0",
            "progress_stage": "TEXT DEFAULT ''",
            "progress_message": "TEXT DEFAULT ''",
        }
        existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        for name, ddl in required.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {ddl}")

    def _init_db(self):
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    snapshot_hash TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    job_dir TEXT NOT NULL,
                    artifact_path TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_columns(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_snapshot_status ON jobs(snapshot_hash, status)")
            conn.commit()

    def _event_path(self, job_dir: Path) -> Path:
        return job_dir / "events.jsonl"

    def _manifest_path(self, job_dir: Path) -> Path:
        return job_dir / "pipeline_manifest.json"

    def _workspace_dir(self, job_id: str) -> Path:
        return self.workspaces_dir / job_id

    def _write_json(self, path: Path, payload: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _append_event(
        self,
        job_dir: Path,
        stage: str,
        message: str,
        source: str = "system",
        level: str = "info",
        event: str = "message",
        artifacts: list[str] | None = None,
    ):
        path = self._event_path(job_dir)
        payload = {
            "timestamp": now_iso(),
            "stage": stage,
            "event": event,
            "source": source,
            "level": level,
            "message": message,
        }
        if artifacts:
            payload["artifacts"] = artifacts
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def _start_worker(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._thread.start()

    def _insert_job(self, job_id: str, snap: str, mode: str, job_dir: Path):
        stamp = now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO jobs(
                    id, snapshot_hash, mode, status, job_dir,
                    artifact_path, error, created_at, updated_at,
                    progress_current, progress_total, progress_stage, progress_message
                ) VALUES(?, ?, ?, 'queued', ?, NULL, '', ?, ?, 0, 0, '', '')
                """,
                (job_id, snap, mode, str(job_dir), stamp, stamp),
            )
            conn.commit()

    def _update_job(
        self,
        job_id: str,
        status: str,
        artifact: Path | None = None,
        error: str = "",
        current: int | None = None,
        total: int | None = None,
        stage: str | None = None,
        message: str | None = None,
    ):
        fields = ["status=?", "updated_at=?"]
        values = [status, now_iso()]
        if artifact is not None:
            fields.append("artifact_path=?")
            values.append(str(artifact))
        if error:
            fields.append("error=?")
            values.append(error)
        if current is not None:
            fields.append("progress_current=?")
            values.append(int(current))
        if total is not None:
            fields.append("progress_total=?")
            values.append(int(total))
        if stage is not None:
            fields.append("progress_stage=?")
            values.append(stage)
        if message is not None:
            fields.append("progress_message=?")
            values.append(message)
        values.append(job_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id=?", tuple(values))
            conn.commit()

    def _find_completed_snapshot(self, snap: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, artifact_path FROM jobs WHERE snapshot_hash=? AND status='completed' ORDER BY updated_at DESC LIMIT 1",
                (snap,),
            ).fetchone()
        if not row:
            return None
        artifact = Path(row[1]) if row[1] else None
        if not artifact or not artifact.exists():
            return None
        return {"job_id": row[0], "artifact_path": str(artifact)}

    def get_job(self, job_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, snapshot_hash, mode, status, job_dir, artifact_path, error,
                       created_at, updated_at, progress_current, progress_total,
                       progress_stage, progress_message
                FROM jobs WHERE id=?
                """,
                (job_id,),
            ).fetchone()
        if not row:
            return None
        keys = (
            "id",
            "snapshot_hash",
            "mode",
            "status",
            "job_dir",
            "artifact_path",
            "error",
            "created_at",
            "updated_at",
            "progress_current",
            "progress_total",
            "progress_stage",
            "progress_message",
        )
        payload = dict(zip(keys, row))
        total = int(payload.get("progress_total") or 0)
        current = int(payload.get("progress_current") or 0)
        payload["progress_percent"] = round((current / total) * 100.0, 2) if total > 0 else 0.0
        payload["manifest_hash"] = payload["snapshot_hash"]
        payload["manifest_path"] = str(self._manifest_path(Path(payload["job_dir"])))
        payload["workspace_dir"] = str(self._workspace_dir(job_id))
        return payload

    def get_events(self, job_id: str, after: int = -1, limit: int = 200) -> dict | None:
        job = self.get_job(job_id)
        if not job:
            return None
        path = self._event_path(Path(job["job_dir"]))
        events = []
        next_after = int(after)
        if path.exists():
            for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
                if idx <= after:
                    continue
                if len(events) >= max(1, limit):
                    break
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    item = {
                        "timestamp": now_iso(),
                        "stage": "",
                        "event": "failed",
                        "source": "system",
                        "level": "error",
                        "message": line,
                    }
                item["index"] = idx
                events.append(item)
                next_after = idx
        return {
            "job_id": job_id,
            "events": events,
            "next_after": next_after,
            "done": job["status"] in {"completed", "failed"},
            "status": job["status"],
        }

    def _copytree(self, src: Path, dst: Path):
        if not src.exists():
            return
        shutil.copytree(
            src,
            dst,
            ignore=shutil.ignore_patterns(*IGNORED_RUNTIME_NAMES, *IGNORED_RUNTIME_SUFFIXES),
        )

    def _copy_upload_inputs(self, rubric_path: Path, outline_path: Path, submissions_dir: Path, dst_inputs: Path):
        subs_dir = dst_inputs / "submissions"
        subs_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rubric_path, dst_inputs / rubric_path.name)
        shutil.copy2(outline_path, dst_inputs / outline_path.name)
        for item in sorted(submissions_dir.glob("*")):
            if item.is_file():
                shutil.copy2(item, subs_dir / item.name)

    def _stage_workspace(self, job_id: str, job_dir: Path, manifest: dict, rubric_path: Path, outline_path: Path, submissions_dir: Path):
        workspace_dir = self._workspace_dir(job_id)
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
        workspace_dir.mkdir(parents=True, exist_ok=True)
        for dirname in workspace_asset_dirs():
            self._copytree(self.root / dirname, workspace_dir / dirname)
        self._copytree(self.root / EXEMPLARS_DIR, workspace_dir / EXEMPLARS_DIR)
        self.reset_workspace(workspace_dir)
        self._copy_upload_inputs(rubric_path, outline_path, submissions_dir, workspace_dir / "inputs")
        self._copy_upload_inputs(rubric_path, outline_path, submissions_dir, job_dir / "inputs")
        calibration_src = self.root / CALIBRATION_ARTIFACT
        if calibration_src.exists():
            calibration_dst = workspace_dir / CALIBRATION_ARTIFACT
            calibration_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(calibration_src, calibration_dst)
        self._write_json(self._manifest_path(job_dir), manifest)
        self._write_json(workspace_dir / "pipeline_manifest.json", manifest)

    def submit(self, mode: str, rubric_path: Path, outline_path: Path, submissions_dir: Path, extra_paths: list[Path]) -> dict:
        manifest = build_pipeline_manifest(
            root=self.root,
            mode=mode,
            rubric_path=rubric_path,
            outline_path=outline_path,
            submissions_dir=submissions_dir,
            extra_paths=extra_paths,
        )
        snap = manifest["manifest_hash"]
        cached = self._find_completed_snapshot(snap)
        if cached:
            return {
                "job_id": cached["job_id"],
                "status": "completed",
                "cached": True,
                "snapshot_hash": snap,
                "manifest_hash": snap,
            }
        job_id = uuid.uuid4().hex
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        self._event_path(job_dir).touch()
        self._stage_workspace(job_id, job_dir, manifest, rubric_path, outline_path, submissions_dir)
        self._insert_job(job_id, snap, mode, job_dir)
        self._append_event(
            job_dir,
            "queued",
            f"Job {job_id} accepted for processing",
            event="start",
        )
        self._start_worker()
        self._queue.put(job_id)
        return {
            "job_id": job_id,
            "status": "queued",
            "cached": False,
            "snapshot_hash": snap,
            "manifest_hash": snap,
        }

    def load_dashboard_data(self, job_id: str) -> dict | None:
        job = self.get_job(job_id)
        if not job or job["status"] != "completed" or not job.get("artifact_path"):
            return None
        artifact = Path(job["artifact_path"])
        if not artifact.exists():
            return None
        return json.loads(artifact.read_text(encoding="utf-8"))

    def _worker_loop(self):
        while True:
            job_id = self._queue.get()
            try:
                self._process_job(job_id)
            finally:
                self._queue.task_done()

    def _artifact_snapshot(self, workspace_dir: Path) -> dict:
        snapshot = {}
        for root_name in artifact_watch_roots():
            base = workspace_dir / root_name
            if not base.exists():
                continue
            for item in sorted(base.rglob("*")):
                if not item.is_file():
                    continue
                rel = str(item.relative_to(workspace_dir))
                stat = item.stat()
                snapshot[rel] = (stat.st_size, stat.st_mtime_ns)
        return snapshot

    def _artifact_changes(self, before: dict, after: dict) -> list[str]:
        changed = []
        for path, meta in after.items():
            if before.get(path) != meta:
                changed.append(path)
        return sorted(changed)

    def _artifact_listing(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        items = []
        for item in sorted(path.rglob("*")):
            if item.is_file():
                items.append(str(item.relative_to(path)))
        return items

    def _process_job(self, job_id: str):
        job = self.get_job(job_id)
        if not job or job["status"] != "queued":
            return
        run_id = job_id[:8]
        mode = job["mode"]
        job_dir = Path(job["job_dir"])
        workspace_dir = self._workspace_dir(job_id)
        manifest = _load_json(self._manifest_path(job_dir))
        steps = pipeline_steps()
        self._update_job(job_id, "running", current=0, total=len(steps), stage="queued", message="Job queued")
        self.log(self.root, run_id, f"QUEUE START mode={mode} manifest={job['snapshot_hash']} workspace={workspace_dir}")
        try:
            baseline = self._artifact_snapshot(workspace_dir)
            metadata = ensure_class_metadata(workspace_dir / "inputs")
            bias_path = ensure_bootstrap_calibration(workspace_dir, metadata)
            after_bootstrap = self._artifact_snapshot(workspace_dir)
            bootstrap_artifacts = self._artifact_changes(baseline, after_bootstrap)
            self._append_event(job_dir, "bootstrap", "Bootstrap calibration ready", event="complete")
            if bootstrap_artifacts:
                self._append_event(
                    job_dir,
                    "bootstrap",
                    "Produced artifacts",
                    event="artifact",
                    artifacts=bootstrap_artifacts,
                )
            self._append_event(job_dir, "bootstrap", f"Calibration profile ready: {bias_path}", event="message")

            env = os.environ.copy()
            env["LLM_MODE"] = mode
            env["PYTHONUNBUFFERED"] = "1"
            env["PIPELINE_MANIFEST_HASH"] = job["snapshot_hash"]
            env["PIPELINE_WORKSPACE"] = str(workspace_dir)
            env["PIPELINE_MANIFEST_PATH"] = str(workspace_dir / "pipeline_manifest.json")
            pythonpath_parts = [str(workspace_dir), str(self.root)]
            existing_pythonpath = env.get("PYTHONPATH", "")
            if existing_pythonpath:
                pythonpath_parts.append(existing_pythonpath)
            env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
            api_key = self.get_api_key()
            if api_key:
                env["OPENAI_API_KEY"] = api_key

            for index, step in enumerate(steps, start=1):
                stage = step["id"]
                label = step["label"]
                self._update_job(job_id, "running", current=index - 1, total=len(steps), stage=stage, message=label)
                self._append_event(job_dir, stage, f"Starting: {label}", event="start")
                self.log(self.root, run_id, f"QUEUE RUN step={stage}")
                before = self._artifact_snapshot(workspace_dir)

                def on_output(source, text):
                    self._append_event(
                        job_dir,
                        stage,
                        text,
                        source=source,
                        level="warning" if source == "stderr" else "info",
                        event="output",
                    )

                code, stdout, stderr = run_step(self.run, step["cmd"], env, workspace_dir, on_output)
                after = self._artifact_snapshot(workspace_dir)
                produced = self._artifact_changes(before, after)
                if produced:
                    self._append_event(job_dir, stage, "Produced artifacts", event="artifact", artifacts=produced)
                if code != 0:
                    detail = (f"step={stage}\nstdout:\n{stdout}\n\nstderr:\n{stderr}").strip()
                    if step.get("required", True):
                        self._append_event(job_dir, stage, f"Step failed: {label}", level="error", event="failed")
                        self.log(self.root, run_id, f"QUEUE ERROR step {stage} failed", detail=detail[:8000])
                        self._update_job(
                            job_id,
                            "failed",
                            error=detail[:500],
                            current=index - 1,
                            total=len(steps),
                            stage=stage,
                            message=f"Failed: {label}",
                        )
                        return
                    self._append_event(
                        job_dir,
                        stage,
                        f"Non-blocking step failed: {label}",
                        level="warning",
                        event="failed",
                    )
                    self.log(self.root, run_id, f"QUEUE WARN step {stage} failed (non-blocking)", detail=detail[:8000])
                    self._update_job(
                        job_id,
                        "running",
                        current=index,
                        total=len(steps),
                        stage=stage,
                        message=f"Skipped failed step: {label}",
                    )
                    continue
                self._update_job(job_id, "running", current=index, total=len(steps), stage=stage, message=f"Complete: {label}")
                self._append_event(job_dir, stage, f"Completed: {label}", event="complete")

            dashboard = workspace_dir / "outputs" / "dashboard_data.json"
            if not dashboard.exists():
                self._append_event(job_dir, "dashboard", "Dashboard data missing after successful run", level="error", event="failed")
                self.log(self.root, run_id, "QUEUE ERROR dashboard missing")
                self._update_job(
                    job_id,
                    "failed",
                    error="Dashboard data not found",
                    current=len(steps),
                    total=len(steps),
                    stage="dashboard",
                    message="Failed: Dashboard output missing",
                )
                return

            artifact_dir = self.artifacts_dir / job["snapshot_hash"]
            if artifact_dir.exists():
                shutil.rmtree(artifact_dir)
            artifact_outputs_dir = artifact_dir / "outputs"
            artifact_outputs_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(workspace_dir / "outputs", artifact_outputs_dir)
            manifest_artifact = artifact_dir / "pipeline_manifest.json"
            self._write_json(manifest_artifact, manifest)
            artifact_path = artifact_outputs_dir / "dashboard_data.json"
            published = self._artifact_listing(artifact_dir)
            self._append_event(job_dir, "completed", "Published artifacts", event="artifact", artifacts=published)
            self._update_job(
                job_id,
                "completed",
                artifact=artifact_path,
                current=len(steps),
                total=len(steps),
                stage="completed",
                message="Pipeline complete",
            )
            self._append_event(job_dir, "completed", "Pipeline complete", event="complete")
            self.log(self.root, run_id, "QUEUE SUCCESS")
        except Exception as exc:  # pragma: no cover - defensive
            self._append_event(job_dir, "unhandled", f"Unhandled error: {exc}", level="error", event="failed")
            self.log(self.root, run_id, "QUEUE ERROR unhandled", detail=str(exc))
            self._update_job(job_id, "failed", error=str(exc)[:500], stage="unhandled", message="Failed with unhandled error")
