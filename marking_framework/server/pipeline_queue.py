#!/usr/bin/env python3
import hashlib
import json
import os
import queue
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_file(path: Path, digest):
    digest.update(path.name.encode("utf-8"))
    digest.update(b"\0")
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    digest.update(b"\0")


def snapshot_hash(mode: str, rubric_path: Path, outline_path: Path, submissions_dir: Path, extra_paths: list[Path]) -> str:
    digest = hashlib.sha256()
    digest.update(f"mode:{mode}\n".encode("utf-8"))
    for path in [rubric_path, outline_path]:
        if path.exists():
            _hash_file(path, digest)
    for path in sorted(submissions_dir.glob("*")):
        if path.is_file():
            _hash_file(path, digest)
    for path in extra_paths:
        if path.exists():
            _hash_file(path, digest)
    return digest.hexdigest()


class PipelineQueue:
    def __init__(self, root: Path, data_dir: Path, reset_workspace_fn, run_fn, log_fn, api_key_fn):
        self.root = root
        self.data_dir = data_dir
        self.jobs_dir = data_dir / "pipeline_jobs"
        self.artifacts_dir = data_dir / "artifacts"
        self.db_path = data_dir / "pipeline_jobs.sqlite3"
        self.reset_workspace = reset_workspace_fn
        self.run = run_fn
        self.log = log_fn
        self.get_api_key = api_key_fn
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._queue = queue.Queue()
        self._thread = None
        self._lock = threading.Lock()

    def _conn(self):
        return sqlite3.connect(self.db_path)

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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_snapshot_status ON jobs(snapshot_hash, status)")
            conn.commit()

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
                "INSERT INTO jobs(id, snapshot_hash, mode, status, job_dir, created_at, updated_at) VALUES(?, ?, ?, 'queued', ?, ?, ?)",
                (job_id, snap, mode, str(job_dir), stamp, stamp),
            )
            conn.commit()

    def _update_job(self, job_id: str, status: str, artifact: Path | None = None, error: str = ""):
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET status=?, artifact_path=?, error=?, updated_at=? WHERE id=?",
                (status, str(artifact) if artifact else None, error, now_iso(), job_id),
            )
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
                "SELECT id, snapshot_hash, mode, status, job_dir, artifact_path, error, created_at, updated_at FROM jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        if not row:
            return None
        keys = ("id", "snapshot_hash", "mode", "status", "job_dir", "artifact_path", "error", "created_at", "updated_at")
        return dict(zip(keys, row))

    def submit(self, mode: str, rubric_path: Path, outline_path: Path, submissions_dir: Path, extra_paths: list[Path]) -> dict:
        snap = snapshot_hash(mode, rubric_path, outline_path, submissions_dir, extra_paths)
        cached = self._find_completed_snapshot(snap)
        if cached:
            return {"job_id": cached["job_id"], "status": "completed", "cached": True, "snapshot_hash": snap}
        job_id = uuid.uuid4().hex
        job_dir = self.jobs_dir / job_id
        inputs_dir = job_dir / "inputs"
        subs_dir = inputs_dir / "submissions"
        subs_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rubric_path, inputs_dir / rubric_path.name)
        shutil.copy2(outline_path, inputs_dir / outline_path.name)
        for file in submissions_dir.glob("*"):
            if file.is_file():
                shutil.copy2(file, subs_dir / file.name)
        self._insert_job(job_id, snap, mode, job_dir)
        self._start_worker()
        self._queue.put(job_id)
        return {"job_id": job_id, "status": "queued", "cached": False, "snapshot_hash": snap}

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

    def _copy_inputs_to_workspace(self, job_dir: Path):
        src_inputs = job_dir / "inputs"
        dst_inputs = self.root / "inputs"
        (dst_inputs / "submissions").mkdir(parents=True, exist_ok=True)
        for file in src_inputs.glob("rubric.*"):
            shutil.copy2(file, dst_inputs / file.name)
        for file in src_inputs.glob("assignment_outline.*"):
            shutil.copy2(file, dst_inputs / file.name)
        dst_submissions = dst_inputs / "submissions"
        for file in dst_submissions.glob("*"):
            if file.is_file():
                file.unlink()
        for file in (src_inputs / "submissions").glob("*"):
            if file.is_file():
                shutil.copy2(file, dst_submissions / file.name)

    def _process_job(self, job_id: str):
        job = self.get_job(job_id)
        if not job or job["status"] != "queued":
            return
        self._update_job(job_id, "running")
        run_id = job_id[:8]
        mode = job["mode"]
        job_dir = Path(job["job_dir"])
        self.log(self.root, run_id, f"QUEUE START mode={mode}")
        try:
            self.reset_workspace(self.root)
            self._copy_inputs_to_workspace(job_dir)
            env = os.environ.copy()
            env["LLM_MODE"] = mode
            api_key = self.get_api_key()
            if api_key:
                env["OPENAI_API_KEY"] = api_key
            cmd = [
                "python3",
                "scripts/hero_path.py",
                "--calibrate",
                "--llm-assessors",
                "--verify-consistency",
                "--apply-consistency",
                "--generate-pairs",
                "--build-dashboard",
            ]
            self.log(self.root, run_id, "QUEUE RUN hero_path")
            result = self.run(cmd, env=env, cwd=str(self.root), capture_output=True, text=True)
            if result.returncode != 0:
                detail_parts = []
                if result.stderr:
                    detail_parts.append("stderr:\n" + result.stderr)
                if result.stdout:
                    detail_parts.append("stdout:\n" + result.stdout)
                detail = "\n".join(detail_parts).strip() or "Pipeline failed"
                self.log(self.root, run_id, "QUEUE ERROR hero_path failed", detail=detail[:8000])
                self._update_job(job_id, "failed", error=detail[:500])
                return
            dashboard = self.root / "outputs" / "dashboard_data.json"
            if not dashboard.exists():
                self.log(self.root, run_id, "QUEUE ERROR dashboard missing")
                self._update_job(job_id, "failed", error="Dashboard data not found")
                return
            artifact_dir = self.artifacts_dir / job["snapshot_hash"]
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / "dashboard_data.json"
            shutil.copy2(dashboard, artifact_path)
            self._update_job(job_id, "completed", artifact=artifact_path)
            self.log(self.root, run_id, "QUEUE SUCCESS")
        except Exception as exc:  # pragma: no cover - defensive
            self.log(self.root, run_id, "QUEUE ERROR unhandled", detail=str(exc))
            self._update_job(job_id, "failed", error=str(exc)[:500])
