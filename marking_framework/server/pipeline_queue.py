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
from server.step_runner import pipeline_steps, run_step


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

    def _append_event(self, job_dir: Path, stage: str, message: str, source: str = "system", level: str = "info"):
        path = self._event_path(job_dir)
        payload = {
            "timestamp": now_iso(),
            "stage": stage,
            "source": source,
            "level": level,
            "message": message,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")

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
            "id", "snapshot_hash", "mode", "status", "job_dir", "artifact_path",
            "error", "created_at", "updated_at", "progress_current", "progress_total",
            "progress_stage", "progress_message",
        )
        payload = dict(zip(keys, row))
        total = int(payload.get("progress_total") or 0)
        current = int(payload.get("progress_current") or 0)
        payload["progress_percent"] = round((current / total) * 100.0, 2) if total > 0 else 0.0
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
                    item = {"timestamp": now_iso(), "stage": "", "source": "system", "level": "error", "message": line}
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
        self._event_path(job_dir).touch()
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
        run_id = job_id[:8]
        mode = job["mode"]
        job_dir = Path(job["job_dir"])
        steps = pipeline_steps()
        self._update_job(job_id, "running", current=0, total=len(steps), stage="queued", message="Job queued")
        self._append_event(job_dir, "queued", f"Job {job_id} accepted for processing")
        self.log(self.root, run_id, f"QUEUE START mode={mode}")
        try:
            self.reset_workspace(self.root)
            self._copy_inputs_to_workspace(job_dir)
            env = os.environ.copy()
            env["LLM_MODE"] = mode
            api_key = self.get_api_key()
            if api_key:
                env["OPENAI_API_KEY"] = api_key
            for index, step in enumerate(steps, start=1):
                stage = step["id"]
                label = step["label"]
                self._update_job(job_id, "running", current=index - 1, total=len(steps), stage=stage, message=label)
                self._append_event(job_dir, stage, f"Starting: {label}")
                self.log(self.root, run_id, f"QUEUE RUN step={stage}")
                def on_output(source, text):
                    self._append_event(job_dir, stage, text, source=source, level="warning" if source == "stderr" else "info")

                code, stdout, stderr = run_step(self.run, step["cmd"], env, self.root, on_output)
                if code != 0:
                    detail = (f"step={stage}\nstdout:\n{stdout}\n\nstderr:\n{stderr}").strip()
                    self._append_event(job_dir, stage, f"Step failed: {label}", level="error")
                    self.log(self.root, run_id, f"QUEUE ERROR step {stage} failed", detail=detail[:8000])
                    self._update_job(job_id, "failed", error=detail[:500], current=index - 1, total=len(steps), stage=stage, message=f"Failed: {label}")
                    return
                self._update_job(job_id, "running", current=index, total=len(steps), stage=stage, message=f"Complete: {label}")
                self._append_event(job_dir, stage, f"Completed: {label}")

            dashboard = self.root / "outputs" / "dashboard_data.json"
            if not dashboard.exists():
                self._append_event(job_dir, "dashboard", "Dashboard data missing after successful run", level="error")
                self.log(self.root, run_id, "QUEUE ERROR dashboard missing")
                self._update_job(job_id, "failed", error="Dashboard data not found", current=len(steps), total=len(steps), stage="dashboard", message="Failed: Dashboard output missing")
                return
            artifact_dir = self.artifacts_dir / job["snapshot_hash"]
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / "dashboard_data.json"
            shutil.copy2(dashboard, artifact_path)
            self._update_job(job_id, "completed", artifact=artifact_path, current=len(steps), total=len(steps), stage="completed", message="Pipeline complete")
            self._append_event(job_dir, "completed", "Pipeline complete")
            self.log(self.root, run_id, "QUEUE SUCCESS")
        except Exception as exc:  # pragma: no cover - defensive
            self._append_event(job_dir, "unhandled", f"Unhandled error: {exc}", level="error")
            self.log(self.root, run_id, "QUEUE ERROR unhandled", detail=str(exc))
            self._update_job(job_id, "failed", error=str(exc)[:500], stage="unhandled", message="Failed with unhandled error")
