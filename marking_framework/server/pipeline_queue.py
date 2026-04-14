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
import csv
from datetime import datetime, timezone
from pathlib import Path

from scripts.calibration_contract import build_run_scope, calibration_manifest_path, canonical_json_hash, load_json as load_contract_json
from scripts.rubric_contract import RUBRIC_ARTIFACTS, build_rubric_artifacts, rubric_contract_summary, stable_contract_hash
from scripts.assessor_utils import resolve_input_path
from server.bootstrap import ensure_bootstrap_calibration, ensure_class_metadata
from server.runtime_context import identity_can_access, identity_token, launch_contract, strict_auth_enabled
from server.step_runner import (
    anchor_resume_steps,
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
RUBRIC_CRITERIA_CONFIG = "config/rubric_criteria.json"
GATE_CONFIG_PATHS = (
    "config/accuracy_gate.json",
    "config/sota_gate.json",
)
PROMPTS_DIR = "prompts"
EXEMPLARS_DIR = "inputs/exemplars"
CALIBRATION_ARTIFACT = "outputs/calibration_bias.json"
CALIBRATION_MANIFEST_ARTIFACT = f"outputs/{calibration_manifest_path(Path(CALIBRATION_ARTIFACT)).name}"
CLASS_METADATA_ARTIFACT = "inputs/class_metadata.json"
RUNTIME_SOURCE_PATHS = (
    "server/bootstrap.py",
    "server/pipeline_queue.py",
    "server/step_runner.py",
)
OPS_STATE_FILE = "pipeline_ops.json"
RECENT_FAILURE_LIMIT = 20
ANCHOR_SCORES_ARTIFACT = "outputs/teacher_anchor_scores.json"
ANCHOR_CALIBRATION_ARTIFACT = "outputs/cohort_anchor_calibration.json"
COHORT_CONFIDENCE_ARTIFACT = "outputs/cohort_confidence.json"
ANCHOR_PACKET_ARTIFACT = "outputs/teacher_anchor_packet.json"
CONSISTENCY_REPORT_ARTIFACT = "outputs/consistency_report.json"
FINAL_ORDER_ARTIFACT = "outputs/final_order.csv"


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


def _json_artifact_manifest(payload: dict | None, label: str) -> dict:
    normalized = payload if isinstance(payload, dict) else {}
    return {
        "path": label,
        "exists": bool(normalized),
        "sha256": stable_contract_hash(normalized) if normalized else None,
    }


def _collect_input_files(root: Path, rubric_path: Path, outline_path: Path, submissions_dir: Path) -> dict:
    submissions = []
    if submissions_dir.exists():
        for item in sorted(submissions_dir.glob("*")):
            if not item.is_file():
                continue
            submissions.append({"path": f"inputs/submissions/{item.name}", "sha256": _file_sha256(item)})
    class_metadata_path = root / CLASS_METADATA_ARTIFACT
    return {
        "rubric": _file_manifest(rubric_path, f"inputs/{rubric_path.name}"),
        "outline": _file_manifest(outline_path, f"inputs/{outline_path.name}"),
        "class_metadata": _file_manifest(class_metadata_path, CLASS_METADATA_ARTIFACT),
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
        "profile_hash": _file_sha256(path),
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
    rubric_artifacts: dict | None = None,
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
    routing_payload = load_contract_json(root / "config" / "llm_routing.json")
    class_metadata_payload = load_contract_json(root / CLASS_METADATA_ARTIFACT)
    rubric_artifacts = rubric_artifacts or {}
    rubric_manifest_payload = rubric_artifacts.get("rubric_manifest", {}) if isinstance(rubric_artifacts.get("rubric_manifest", {}), dict) else {}
    run_scope = build_run_scope(
        metadata=class_metadata_payload,
        routing=routing_payload,
        rubric_path=rubric_path,
        rubric_manifest=rubric_manifest_payload,
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
        "uploaded_inputs": _collect_input_files(root, rubric_path, outline_path, submissions_dir),
        "run_scope": run_scope,
        "rubric_contract": {
            "summary": rubric_contract_summary(rubric_artifacts),
            "normalized_rubric": _json_artifact_manifest(rubric_artifacts.get("normalized_rubric"), RUBRIC_ARTIFACTS["normalized_rubric"]),
            "rubric_manifest": _json_artifact_manifest(rubric_artifacts.get("rubric_manifest"), RUBRIC_ARTIFACTS["rubric_manifest"]),
            "rubric_validation_report": _json_artifact_manifest(
                rubric_artifacts.get("rubric_validation_report"),
                RUBRIC_ARTIFACTS["rubric_validation_report"],
            ),
            "rubric_verification": _json_artifact_manifest(rubric_artifacts.get("rubric_verification"), RUBRIC_ARTIFACTS["rubric_verification"]),
        },
        "prompt_hashes": prompt_manifest,
        "config_hashes": config_hashes,
        "extra_hashes": extra_hashes,
        "exemplar_tree": exemplar_manifest,
        "calibration_artifact": _file_manifest(root / CALIBRATION_ARTIFACT, CALIBRATION_ARTIFACT),
        "calibration_manifest": _file_manifest(root / CALIBRATION_MANIFEST_ARTIFACT, CALIBRATION_MANIFEST_ARTIFACT),
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
    rubric_artifacts: dict | None = None,
) -> str:
    manifest = build_pipeline_manifest(
        root=(root or _infer_root(rubric_path, outline_path, submissions_dir, extra_paths)),
        mode=mode,
        rubric_path=rubric_path,
        outline_path=outline_path,
        submissions_dir=submissions_dir,
        extra_paths=extra_paths,
        rubric_artifacts=rubric_artifacts,
    )
    return manifest["manifest_hash"]


class PipelineQueue:
    def __init__(self, root: Path, data_dir: Path, reset_workspace_fn, run_fn, log_fn, api_key_fn):
        self.root = root
        self.data_dir = data_dir
        self.jobs_dir = data_dir / "pipeline_jobs"
        self.workspaces_dir = data_dir / "workspaces"
        self.artifacts_dir = data_dir / "artifacts"
        self.ops_path = data_dir / OPS_STATE_FILE
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
        if not self.ops_path.exists():
            self._write_json(
                self.ops_path,
                {
                    "cache_hits": 0,
                    "cache_misses": 0,
                    "cache_validation_failures": 0,
                    "recent_gate_failures": [],
                    "recent_incidents": [],
                    "last_retention_report": {},
                },
            )

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _ensure_columns(self, conn):
        required = {
            "progress_current": "INTEGER DEFAULT 0",
            "progress_total": "INTEGER DEFAULT 0",
            "progress_stage": "TEXT DEFAULT ''",
            "progress_message": "TEXT DEFAULT ''",
            "tenant_id": "TEXT DEFAULT ''",
            "teacher_id": "TEXT DEFAULT ''",
            "project_id": "TEXT DEFAULT ''",
            "started_at": "TEXT DEFAULT ''",
            "completed_at": "TEXT DEFAULT ''",
            "cache_status": "TEXT DEFAULT 'miss'",
            "cache_source_job_id": "TEXT DEFAULT ''",
            "gate_summary": "TEXT DEFAULT '{}'",
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

    def _anchor_state_dir(self, job_dir: Path) -> Path:
        path = job_dir / "anchor_state"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _pre_anchor_snapshot_dir(self, job_dir: Path) -> Path:
        return self._anchor_state_dir(job_dir) / "pre_anchor_snapshot"

    def _pre_anchor_metrics_path(self, job_dir: Path) -> Path:
        return self._anchor_state_dir(job_dir) / "pre_anchor_metrics.json"

    def _post_anchor_metrics_path(self, job_dir: Path) -> Path:
        return self._anchor_state_dir(job_dir) / "post_anchor_metrics.json"

    def _tenant_token(self, tenant_id: str) -> str:
        return identity_token(tenant_id or "local-dev-tenant")

    def _job_dir(self, job_id: str, tenant_id: str) -> Path:
        return self.jobs_dir / self._tenant_token(tenant_id) / job_id

    def _workspace_dir(self, job_id: str, tenant_id: str = "") -> Path:
        return self.workspaces_dir / self._tenant_token(tenant_id or "local-dev-tenant") / job_id

    def _artifact_dir(self, manifest_hash_value: str, tenant_id: str) -> Path:
        return self.artifacts_dir / self._tenant_token(tenant_id or "local-dev-tenant") / manifest_hash_value

    def _job_inputs_dir(self, job_dir: Path) -> Path:
        return job_dir / "inputs"

    def _rubric_output_paths(self, root: Path) -> dict[str, Path]:
        return {key: root / rel_path for key, rel_path in RUBRIC_ARTIFACTS.items()}

    def _load_rubric_artifacts_from_root(self, root: Path) -> dict:
        artifacts = {}
        for key, path in self._rubric_output_paths(root).items():
            artifacts[key] = _load_json(path)
        return artifacts

    def _write_rubric_artifacts(self, root: Path, artifacts: dict):
        for key, path in self._rubric_output_paths(root).items():
            self._write_json(path, artifacts.get(key, {}) if isinstance(artifacts.get(key, {}), dict) else {})

    def _input_paths_from_root(self, root: Path) -> tuple[Path, Path, Path]:
        inputs_dir = root / "inputs"
        rubric_path = resolve_input_path(inputs_dir / "rubric.md", "rubric")
        outline_path = resolve_input_path(inputs_dir / "assignment_outline.md", "assignment_outline")
        submissions_dir = inputs_dir / "submissions"
        return rubric_path, outline_path, submissions_dir

    def _build_rubric_artifacts(self, rubric_path: Path, outline_path: Path, *, existing_verification: dict | None = None, teacher_edits: dict | None = None, action: str | None = None) -> dict:
        return build_rubric_artifacts(
            rubric_path,
            outline_path=outline_path,
            criteria_config_path=self.root / RUBRIC_CRITERIA_CONFIG,
            existing_verification=existing_verification,
            teacher_edits=teacher_edits,
            action=action,
        )

    def _write_json(self, path: Path, payload: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _load_json_path(self, path: Path):
        return _load_json(path)

    def _load_csv_rows(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def _workspace_dashboard_path(self, workspace_dir: Path) -> Path:
        return workspace_dir / "outputs" / "dashboard_data.json"

    def _workspace_artifact_path(self, workspace_dir: Path) -> Path | None:
        dashboard = self._workspace_dashboard_path(workspace_dir)
        return dashboard if dashboard.exists() else None

    def _load_cohort_confidence(self, workspace_dir: Path) -> dict:
        return _load_json(workspace_dir / COHORT_CONFIDENCE_ARTIFACT)

    def _should_pause_for_anchors(self, workspace_dir: Path) -> bool:
        payload = self._load_cohort_confidence(workspace_dir)
        if not payload:
            return False
        return bool(
            payload.get("blocking_enabled", False)
            and str(payload.get("effective_runtime_state", "") or "") == "anchor_calibration_required"
        )

    def _top_n_ids(self, workspace_dir: Path, limit: int = 5) -> list[str]:
        rows = self._load_csv_rows(workspace_dir / FINAL_ORDER_ARTIFACT)
        ordered = []
        for row in rows:
            sid = str(row.get("student_id", "") or "").strip()
            if sid:
                ordered.append(sid)
        return ordered[: max(1, int(limit))]

    def _anchor_hold_harmless_metrics(self, workspace_dir: Path) -> dict:
        consistency = _load_json(workspace_dir / CONSISTENCY_REPORT_ARTIFACT)
        summary = consistency.get("summary", {}) if isinstance(consistency, dict) else {}
        return {
            "swap_rate": float(summary.get("swap_rate", 0.0) or 0.0),
            "boundary_disagreement_concentration": float(summary.get("boundary_disagreement_concentration", 0.0) or 0.0),
            "top_5_ids": self._top_n_ids(workspace_dir, limit=5),
        }

    def _write_anchor_metrics(self, path: Path, workspace_dir: Path) -> dict:
        payload = self._anchor_hold_harmless_metrics(workspace_dir)
        self._write_json(path, payload)
        return payload

    def _anchor_patch_acceptance(self, pre_metrics: dict, post_metrics: dict) -> dict:
        pre_top = list(pre_metrics.get("top_5_ids", []) or [])
        post_top = list(post_metrics.get("top_5_ids", []) or [])
        overlap = len(set(pre_top) & set(post_top))
        pre_boundary = float(pre_metrics.get("boundary_disagreement_concentration", 0.0) or 0.0)
        post_boundary = float(post_metrics.get("boundary_disagreement_concentration", 0.0) or 0.0)
        pre_swap = float(pre_metrics.get("swap_rate", 0.0) or 0.0)
        post_swap = float(post_metrics.get("swap_rate", 0.0) or 0.0)
        accepted = (
            post_swap <= (pre_swap + 1e-9)
            and post_boundary <= (pre_boundary + 1e-9)
            and overlap >= min(len(pre_top), len(post_top))
        )
        reason = "" if accepted else "anchor_patch_not_helpful"
        return {
            "accepted": accepted,
            "fallback_used": not accepted,
            "fallback_reason": reason,
            "pre_metrics": pre_metrics,
            "post_metrics": post_metrics,
            "top_5_overlap_count": overlap,
        }

    def _load_ops_state(self) -> dict:
        payload = _load_json(self.ops_path)
        if payload:
            return payload
        return {
            "cache_hits": 0,
            "cache_misses": 0,
            "cache_validation_failures": 0,
            "recent_gate_failures": [],
            "recent_incidents": [],
            "last_retention_report": {},
        }

    def _update_ops_state(self, mutator):
        with self._lock:
            payload = self._load_ops_state()
            mutator(payload)
            self._write_json(self.ops_path, payload)

    def _record_incident(self, kind: str, message: str, *, extra: dict | None = None):
        def mutate(payload):
            items = list(payload.get("recent_incidents", []) or [])
            items.append(
                {
                    "timestamp": now_iso(),
                    "kind": kind,
                    "message": message,
                    "extra": extra or {},
                }
            )
            payload["recent_incidents"] = items[-RECENT_FAILURE_LIMIT:]

        self._update_ops_state(mutate)

    def _record_gate_summary(self, job_id: str, gate_summary: dict):
        failures = []
        if not bool(gate_summary.get("publish_ok", False)):
            failures.extend(str(item) for item in gate_summary.get("publish_failures", []) or [])
        if not bool(gate_summary.get("sota_ok", False)):
            failures.extend(str(item) for item in gate_summary.get("sota_failures", []) or [])
        if not failures:
            return

        def mutate(payload):
            items = list(payload.get("recent_gate_failures", []) or [])
            items.append(
                {
                    "timestamp": now_iso(),
                    "job_id": job_id,
                    "publish_profile": gate_summary.get("publish_profile", ""),
                    "sota_profile": gate_summary.get("sota_profile", ""),
                    "failures": sorted(set(failures)),
                }
            )
            payload["recent_gate_failures"] = items[-RECENT_FAILURE_LIMIT:]

        self._update_ops_state(mutate)

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

    def _insert_job(
        self,
        job_id: str,
        snap: str,
        mode: str,
        job_dir: Path,
        *,
        tenant_id: str,
        teacher_id: str,
        project_id: str,
        status: str = "queued",
    ):
        stamp = now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO jobs(
                    id, snapshot_hash, mode, status, job_dir,
                    artifact_path, error, created_at, updated_at,
                    progress_current, progress_total, progress_stage, progress_message,
                    tenant_id, teacher_id, project_id, started_at, completed_at,
                    cache_status, cache_source_job_id, gate_summary
                ) VALUES(?, ?, ?, ?, ?, NULL, '', ?, ?, 0, 0, '', '', ?, ?, ?, '', '', 'miss', '', '{}')
                """,
                (job_id, snap, mode, status, str(job_dir), stamp, stamp, tenant_id, teacher_id, project_id),
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
        started_at: str | None = None,
        completed_at: str | None = None,
        cache_status: str | None = None,
        cache_source_job_id: str | None = None,
        gate_summary: dict | None = None,
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
        if started_at is not None:
            fields.append("started_at=?")
            values.append(started_at)
        if completed_at is not None:
            fields.append("completed_at=?")
            values.append(completed_at)
        if cache_status is not None:
            fields.append("cache_status=?")
            values.append(cache_status)
        if cache_source_job_id is not None:
            fields.append("cache_source_job_id=?")
            values.append(cache_source_job_id)
        if gate_summary is not None:
            fields.append("gate_summary=?")
            values.append(json.dumps(gate_summary, sort_keys=True))
        values.append(job_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id=?", tuple(values))
            conn.commit()

    def _validate_cached_artifact(self, snap: str, artifact: Path) -> tuple[bool, str]:
        if not artifact.exists():
            return False, "artifact_missing"
        manifest_path = artifact.parent.parent / "pipeline_manifest.json"
        if not manifest_path.exists():
            return False, "artifact_manifest_missing"
        manifest = _load_json(manifest_path)
        if str(manifest.get("manifest_hash", "") or "") != snap:
            return False, "artifact_manifest_hash_mismatch"
        dashboard = artifact.parent / "dashboard_data.json"
        if not dashboard.exists():
            return False, "dashboard_missing"
        return True, ""

    def _find_completed_snapshot(self, snap: str, tenant_id: str, teacher_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, artifact_path FROM jobs
                WHERE snapshot_hash=? AND tenant_id=? AND teacher_id=? AND status='completed'
                ORDER BY updated_at DESC LIMIT 1
                """,
                (snap, tenant_id, teacher_id),
            ).fetchone()
        if not row:
            return None
        artifact = Path(row[1]) if row[1] else None
        if not artifact:
            return None
        valid, reason = self._validate_cached_artifact(snap, artifact)
        if not valid:
            self._record_incident("cache_validation_failure", f"Manifest {snap} cache invalid: {reason}", extra={"job_id": row[0]})
            self._update_ops_state(lambda payload: payload.__setitem__("cache_validation_failures", int(payload.get("cache_validation_failures", 0) or 0) + 1))
            return None
        return {"job_id": row[0], "artifact_path": str(artifact)}

    def get_job(self, job_id: str, identity: dict | None = None) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, snapshot_hash, mode, status, job_dir, artifact_path, error,
                       created_at, updated_at, progress_current, progress_total,
                       progress_stage, progress_message, tenant_id, teacher_id,
                       project_id, started_at, completed_at, cache_status,
                       cache_source_job_id, gate_summary
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
            "tenant_id",
            "teacher_id",
            "project_id",
            "started_at",
            "completed_at",
            "cache_status",
            "cache_source_job_id",
            "gate_summary",
        )
        payload = dict(zip(keys, row))
        owner = {
            "tenant_id": payload.get("tenant_id", ""),
            "teacher_id": payload.get("teacher_id", ""),
        }
        if identity and not identity_can_access(owner, identity):
            return None
        total = int(payload.get("progress_total") or 0)
        current = int(payload.get("progress_current") or 0)
        payload["progress_percent"] = round((current / total) * 100.0, 2) if total > 0 else 0.0
        payload["manifest_hash"] = payload["snapshot_hash"]
        payload["manifest_path"] = str(self._manifest_path(Path(payload["job_dir"])))
        payload["workspace_dir"] = str(self._workspace_dir(job_id, payload.get("tenant_id", "")))
        try:
            payload["gate_summary"] = json.loads(payload.get("gate_summary") or "{}")
        except json.JSONDecodeError:
            payload["gate_summary"] = {}
        return payload

    def get_events(self, job_id: str, identity: dict | None = None, after: int = -1, limit: int = 200) -> dict | None:
        job = self.get_job(job_id, identity=identity)
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

    def _copy_context_input(self, rel_path: str, dst_root: Path):
        src = self.root / rel_path
        if not src.exists() or not src.is_file():
            return
        dst = dst_root / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    def _stage_workspace(
        self,
        job_id: str,
        tenant_id: str,
        job_dir: Path,
        manifest: dict,
        rubric_path: Path,
        outline_path: Path,
        submissions_dir: Path,
        rubric_artifacts: dict,
    ):
        workspace_dir = self._workspace_dir(job_id, tenant_id)
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
        workspace_dir.mkdir(parents=True, exist_ok=True)
        for dirname in workspace_asset_dirs():
            self._copytree(self.root / dirname, workspace_dir / dirname)
        self._copytree(self.root / EXEMPLARS_DIR, workspace_dir / EXEMPLARS_DIR)
        self.reset_workspace(workspace_dir)
        self._copy_upload_inputs(rubric_path, outline_path, submissions_dir, workspace_dir / "inputs")
        self._copy_upload_inputs(rubric_path, outline_path, submissions_dir, job_dir / "inputs")
        self._copy_context_input(CLASS_METADATA_ARTIFACT, workspace_dir)
        self._copy_context_input(CLASS_METADATA_ARTIFACT, job_dir)
        calibration_src = self.root / CALIBRATION_ARTIFACT
        if calibration_src.exists():
            calibration_dst = workspace_dir / CALIBRATION_ARTIFACT
            calibration_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(calibration_src, calibration_dst)
        calibration_manifest_src = self.root / CALIBRATION_MANIFEST_ARTIFACT
        if calibration_manifest_src.exists():
            calibration_manifest_dst = workspace_dir / CALIBRATION_MANIFEST_ARTIFACT
            calibration_manifest_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(calibration_manifest_src, calibration_manifest_dst)
        self._write_rubric_artifacts(workspace_dir, rubric_artifacts)
        self._write_rubric_artifacts(job_dir, rubric_artifacts)
        self._write_json(self._manifest_path(job_dir), manifest)
        self._write_json(workspace_dir / "pipeline_manifest.json", manifest)

    def submit(
        self,
        mode: str,
        rubric_path: Path,
        outline_path: Path,
        submissions_dir: Path,
        extra_paths: list[Path],
        *,
        identity: dict | None = None,
        project_id: str = "",
    ) -> dict:
        identity = dict(identity or {})
        tenant_id = str(identity.get("tenant_id", "") or "local-dev-tenant")
        teacher_id = str(identity.get("teacher_id", "") or "local-dev-teacher")
        rubric_artifacts = self._build_rubric_artifacts(rubric_path, outline_path)
        manifest = build_pipeline_manifest(
            root=self.root,
            mode=mode,
            rubric_path=rubric_path,
            outline_path=outline_path,
            submissions_dir=submissions_dir,
            extra_paths=extra_paths,
            rubric_artifacts=rubric_artifacts,
        )
        snap = manifest["manifest_hash"]
        requires_confirmation = bool((rubric_artifacts.get("rubric_verification", {}) or {}).get("required_confirmation", False))
        if not requires_confirmation:
            cached = self._find_completed_snapshot(snap, tenant_id, teacher_id)
            if cached:
                cached_job = self.get_job(cached["job_id"])
                if cached_job:
                    cached_workspace = Path(str(cached_job.get("workspace_dir", "") or ""))
                    if cached_workspace.exists():
                        self._sync_completed_project_state(cached_job, cached_workspace)
                self._update_ops_state(lambda payload: payload.__setitem__("cache_hits", int(payload.get("cache_hits", 0) or 0) + 1))
                return {
                    "job_id": cached["job_id"],
                    "status": "completed",
                    "cached": True,
                    "snapshot_hash": snap,
                    "manifest_hash": snap,
                    "rubric_verification": rubric_artifacts.get("rubric_verification", {}),
                }
        self._update_ops_state(lambda payload: payload.__setitem__("cache_misses", int(payload.get("cache_misses", 0) or 0) + 1))
        job_id = uuid.uuid4().hex
        job_dir = self._job_dir(job_id, tenant_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        self._event_path(job_dir).touch()
        self._stage_workspace(job_id, tenant_id, job_dir, manifest, rubric_path, outline_path, submissions_dir, rubric_artifacts)
        initial_status = "awaiting_rubric_confirmation" if requires_confirmation else "queued"
        self._insert_job(
            job_id,
            snap,
            mode,
            job_dir,
            tenant_id=tenant_id,
            teacher_id=teacher_id,
            project_id=project_id,
            status=initial_status,
        )
        self._append_event(
            job_dir,
            "queued",
            f"Job {job_id} accepted for processing",
            event="start",
        )
        if requires_confirmation:
            self._append_event(
                job_dir,
                "rubric",
                "Rubric normalization needs teacher confirmation before scoring can continue",
                level="warning",
                event="message",
            )
        else:
            self._start_worker()
            self._queue.put(job_id)
        return {
            "job_id": job_id,
            "status": initial_status,
            "cached": False,
            "snapshot_hash": snap,
            "manifest_hash": snap,
            "rubric_verification": rubric_artifacts.get("rubric_verification", {}),
        }

    def load_dashboard_data(self, job_id: str, identity: dict | None = None) -> dict | None:
        job = self.get_job(job_id, identity=identity)
        if not job:
            return None
        artifact = Path(job["artifact_path"]) if job.get("artifact_path") else None
        if artifact is None or not artifact.exists():
            workspace_artifact = self._workspace_artifact_path(Path(job["workspace_dir"]))
            artifact = workspace_artifact if workspace_artifact and workspace_artifact.exists() else None
        if artifact is None or not artifact.exists():
            return None
        return json.loads(artifact.read_text(encoding="utf-8"))

    def anchor_status(self, job_id: str, identity: dict | None = None) -> dict | None:
        job = self.get_job(job_id, identity=identity)
        if not job:
            return None
        workspace_dir = Path(job["workspace_dir"])
        return {
            "job_id": job_id,
            "status": job.get("status", ""),
            "cohort_confidence": self._load_cohort_confidence(workspace_dir),
            "anchor_packet": _load_json(workspace_dir / ANCHOR_PACKET_ARTIFACT),
            "anchor_calibration": _load_json(workspace_dir / ANCHOR_CALIBRATION_ARTIFACT),
            "pre_anchor_metrics": _load_json(self._pre_anchor_metrics_path(Path(job["job_dir"]))),
            "post_anchor_metrics": _load_json(self._post_anchor_metrics_path(Path(job["job_dir"]))),
        }

    def confirm_anchor_scores(
        self,
        job_id: str,
        *,
        teacher_scores: dict | None = None,
        identity: dict | None = None,
    ) -> dict | None:
        job = self.get_job(job_id, identity=identity)
        if not job:
            return None
        if str(job.get("status", "") or "") != "awaiting_anchor_scores":
            return self.anchor_status(job_id, identity=identity)
        job_dir = Path(job["job_dir"])
        workspace_dir = Path(job["workspace_dir"])
        scores_payload = {
            "generated_at": now_iso(),
            "anchors": list((teacher_scores or {}).get("anchors", []) or []),
        }
        self._write_json(job_dir / ANCHOR_SCORES_ARTIFACT, scores_payload)
        self._write_json(workspace_dir / ANCHOR_SCORES_ARTIFACT, scores_payload)
        env = os.environ.copy()
        env["LLM_MODE"] = str(job.get("mode", "") or "")
        env["PYTHONUNBUFFERED"] = "1"
        env["PIPELINE_MANIFEST_HASH"] = str(job.get("snapshot_hash", "") or "")
        env["PIPELINE_WORKSPACE"] = str(workspace_dir)
        env["PIPELINE_MANIFEST_PATH"] = str(workspace_dir / "pipeline_manifest.json")
        env["ANCHOR_CALIBRATION_ACTIVE"] = "1"
        pythonpath_parts = [str(workspace_dir), str(self.root)]
        existing_pythonpath = env.get("PYTHONPATH", "")
        if existing_pythonpath:
            pythonpath_parts.append(existing_pythonpath)
        env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
        api_key = self.get_api_key()
        if api_key:
            env["OPENAI_API_KEY"] = api_key
        self._append_event(job_dir, "anchor_resume", "Teacher anchor scores received", event="message")
        self._update_job(job_id, "running", stage="anchor_resume", message="Applying anchor calibration", completed_at="")
        apply_step = {
            "id": "anchor_calibration",
            "label": "Applying teacher anchor calibration",
            "cmd": ["python3", "scripts/apply_anchor_calibration.py", "--rows", "outputs/consensus_scores.csv"],
            "required": True,
        }
        if not self._run_pipeline_steps(job_id, job_dir, workspace_dir, env, [apply_step], start_completed=0, tenant_id=str(job.get("tenant_id", "") or "")):
            return self.anchor_status(job_id, identity=identity)
        resume_steps = anchor_resume_steps()
        if not self._run_pipeline_steps(job_id, job_dir, workspace_dir, env, resume_steps, start_completed=1, tenant_id=str(job.get("tenant_id", "") or "")):
            return self.anchor_status(job_id, identity=identity)
        dashboard = self._workspace_dashboard_path(workspace_dir)
        if not dashboard.exists():
            self._update_job(job_id, "failed", error="Dashboard data not found after anchor resume", stage="dashboard", message="Failed: Dashboard output missing", completed_at=now_iso())
            return self.anchor_status(job_id, identity=identity)
        post_metrics = self._write_anchor_metrics(self._post_anchor_metrics_path(job_dir), workspace_dir)
        pre_metrics = _load_json(self._pre_anchor_metrics_path(job_dir))
        decision = self._anchor_patch_acceptance(pre_metrics, post_metrics)
        patch_path = workspace_dir / ANCHOR_CALIBRATION_ARTIFACT
        patch = _load_json(patch_path)
        patch.update(decision)
        self._write_json(patch_path, patch)
        self._write_json(job_dir / ANCHOR_CALIBRATION_ARTIFACT, patch)
        if not decision["accepted"]:
            snapshot_dir = self._pre_anchor_snapshot_dir(job_dir)
            if snapshot_dir.exists():
                self._copy_runtime_state(snapshot_dir, workspace_dir)
                self._write_json(workspace_dir / ANCHOR_CALIBRATION_ARTIFACT, patch)
            self._append_event(job_dir, "anchor_reverted", "Anchor calibration reverted to pre-anchor snapshot", level="warning", event="message")
        refreshed_job = self.get_job(job_id, identity=identity)
        if refreshed_job:
            self._publish_completed_workspace(refreshed_job, workspace_dir, _load_json(workspace_dir / "pipeline_manifest.json"), total_steps=1 + len(resume_steps))
        return self.anchor_status(job_id, identity=identity)

    def rubric_status(self, job_id: str, identity: dict | None = None) -> dict | None:
        job = self.get_job(job_id, identity=identity)
        if not job:
            return None
        job_dir = Path(job["job_dir"])
        workspace_dir = self._workspace_dir(job_id, job.get("tenant_id", ""))
        artifact_root = workspace_dir if workspace_dir.exists() else job_dir
        artifacts = self._load_rubric_artifacts_from_root(artifact_root)
        return {
            "job_id": job_id,
            "status": job.get("status", ""),
            "manifest_hash": job.get("manifest_hash", ""),
            **artifacts,
        }

    def confirm_rubric(
        self,
        job_id: str,
        *,
        action: str,
        teacher_edits: dict | None = None,
        identity: dict | None = None,
    ) -> dict | None:
        job = self.get_job(job_id, identity=identity)
        if not job:
            return None
        status = str(job.get("status", "") or "")
        if status not in {"awaiting_rubric_confirmation", "queued"}:
            return self.rubric_status(job_id, identity=identity)
        job_dir = Path(job["job_dir"])
        workspace_dir = self._workspace_dir(job_id, job.get("tenant_id", ""))
        rubric_path, outline_path, submissions_dir = self._input_paths_from_root(job_dir)
        existing_verification = self._load_rubric_artifacts_from_root(workspace_dir).get("rubric_verification", {})
        if action == "reject":
            self._append_event(job_dir, "rubric", "Teacher rejected rubric interpretation", level="error", event="failed")
            self._update_job(
                job_id,
                "failed",
                error="Rubric interpretation rejected by teacher",
                stage="rubric",
                message="Failed: Rubric rejected",
                completed_at=now_iso(),
            )
            return self.rubric_status(job_id, identity=identity)

        rubric_artifacts = self._build_rubric_artifacts(
            rubric_path,
            outline_path,
            existing_verification=existing_verification,
            teacher_edits=teacher_edits or {},
            action="edit" if teacher_edits else "confirm",
        )
        manifest = build_pipeline_manifest(
            root=self.root,
            mode=job["mode"],
            rubric_path=rubric_path,
            outline_path=outline_path,
            submissions_dir=submissions_dir,
            extra_paths=[],
            rubric_artifacts=rubric_artifacts,
        )
        snap = manifest["manifest_hash"]
        self._write_rubric_artifacts(job_dir, rubric_artifacts)
        self._write_rubric_artifacts(workspace_dir, rubric_artifacts)
        self._write_json(self._manifest_path(job_dir), manifest)
        self._write_json(workspace_dir / "pipeline_manifest.json", manifest)
        with self._conn() as conn:
            conn.execute("UPDATE jobs SET snapshot_hash=?, updated_at=? WHERE id=?", (snap, now_iso(), job_id))
            conn.commit()
        cached = self._find_completed_snapshot(snap, str(job.get("tenant_id", "") or ""), str(job.get("teacher_id", "") or ""))
        if cached:
            artifact = Path(cached["artifact_path"])
            self._update_job(
                job_id,
                "completed",
                artifact=artifact,
                current=len(pipeline_steps()),
                total=len(pipeline_steps()),
                stage="completed",
                message="Loaded cached artifact after rubric confirmation",
                completed_at=now_iso(),
                cache_status="hit",
                cache_source_job_id=cached["job_id"],
            )
            self._append_event(job_dir, "rubric", "Rubric confirmed; matched a cached manifest-identical run", event="complete")
            return self.rubric_status(job_id, identity=identity)
        self._append_event(job_dir, "rubric", "Rubric confirmed; queueing full scoring run", event="complete")
        self._update_job(
            job_id,
            "queued",
            stage="rubric",
            message="Rubric confirmed; queued for scoring",
            completed_at="",
        )
        self._start_worker()
        self._queue.put(job_id)
        return self.rubric_status(job_id, identity=identity)

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

    def _job_identity(self, tenant_id: str, teacher_id: str) -> dict:
        teacher = str(teacher_id or "local-dev-teacher")
        tenant = str(tenant_id or "local-dev-tenant")
        return {
            "tenant_id": tenant,
            "teacher_id": teacher,
            "role": "admin" if teacher == "local-dev-teacher" else "teacher",
            "strict_auth": strict_auth_enabled(self.root),
            "tenant_token": identity_token(tenant),
            "teacher_token": identity_token(teacher),
        }

    def _copy_runtime_state(self, source_root: Path, target_root: Path):
        self.reset_workspace(target_root)
        for folder in ["inputs", "processing", "assessments", "outputs"]:
            src = source_root / folder
            if not src.exists():
                continue
            shutil.copytree(src, target_root / folder, dirs_exist_ok=True)
        manifest = source_root / "pipeline_manifest.json"
        if manifest.exists():
            shutil.copy2(manifest, target_root / "pipeline_manifest.json")

    def _sync_completed_project_state(self, job: dict, workspace_dir: Path):
        tenant_id = str(job.get("tenant_id", "") or "local-dev-tenant")
        teacher_id = str(job.get("teacher_id", "") or "local-dev-teacher")
        identity = self._job_identity(tenant_id, teacher_id)
        active_root = self.root if not identity.get("strict_auth", False) else None
        if active_root is None:
            from server import projects as projectsmod

            active_root = projectsmod.workspace_root(identity)
        self._copy_runtime_state(workspace_dir, active_root)
        project_id = str(job.get("project_id", "") or "").strip()
        if not project_id:
            return
        from server import projects as projectsmod

        current = projectsmod.get_current_project(identity)
        if current and str(current.get("id", "") or "") != project_id:
            current = None
        if current is None:
            meta_path = projectsmod.project_dir(project_id, identity) / "project.json"
            if meta_path.exists():
                current = projectsmod.normalize_project_meta(json.loads(meta_path.read_text(encoding="utf-8")))
        name = str((current or {}).get("name", "") or project_id)
        aggregate_learning = (current or {}).get("aggregate_learning")
        owner = (current or {}).get("owner")
        meta = projectsmod.save_project_snapshot(
            active_root,
            project_id,
            name,
            aggregate_learning=aggregate_learning,
            owner=owner,
            identity=identity,
        )
        projectsmod.set_current_project(meta, identity)

    def _publish_completed_workspace(self, job: dict, workspace_dir: Path, manifest: dict, *, total_steps: int):
        artifact_dir = self._artifact_dir(job["snapshot_hash"], str(job.get("tenant_id", "") or "local-dev-tenant"))
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        artifact_outputs_dir = artifact_dir / "outputs"
        artifact_outputs_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(workspace_dir / "outputs", artifact_outputs_dir)
        self._write_json(artifact_dir / "pipeline_manifest.json", manifest)
        artifact_path = artifact_outputs_dir / "dashboard_data.json"
        gate_summary = self._gate_summary(workspace_dir)
        published = self._artifact_listing(artifact_dir)
        self._sync_completed_project_state(job, workspace_dir)
        self._append_event(Path(job["job_dir"]), "completed", "Published artifacts", event="artifact", artifacts=published)
        self._update_job(
            str(job["id"]),
            "completed",
            artifact=artifact_path,
            current=total_steps,
            total=total_steps,
            stage="completed",
            message="Pipeline complete",
            completed_at=now_iso(),
            gate_summary=gate_summary,
        )
        self._record_gate_summary(str(job["id"]), gate_summary)
        self._append_event(Path(job["job_dir"]), "completed", "Pipeline complete", event="complete")

    def _pause_for_anchor_scores(self, job: dict, workspace_dir: Path, *, total_steps: int):
        job_dir = Path(job["job_dir"])
        snapshot_dir = self._pre_anchor_snapshot_dir(job_dir)
        self._copy_runtime_state(workspace_dir, snapshot_dir)
        metrics = self._write_anchor_metrics(self._pre_anchor_metrics_path(job_dir), workspace_dir)
        self._sync_completed_project_state(job, workspace_dir)
        artifact = self._workspace_artifact_path(workspace_dir)
        self._update_job(
            str(job["id"]),
            "awaiting_anchor_scores",
            artifact=artifact,
            current=total_steps,
            total=total_steps,
            stage="anchor_wait",
            message="Teacher anchor scores required",
            gate_summary=self._gate_summary(workspace_dir),
        )
        self._append_event(
            job_dir,
            "anchor_wait",
            "Cohort confidence requires teacher anchor scores before finalizing",
            level="warning",
            event="message",
        )
        self._append_event(
            job_dir,
            "anchor_wait",
            "Stored pre-anchor snapshot",
            event="artifact",
            artifacts=[str(self._pre_anchor_snapshot_dir(job_dir).relative_to(job_dir))],
        )
        return metrics

    def _run_pipeline_steps(self, job_id: str, job_dir: Path, workspace_dir: Path, env: dict, steps: list[dict], *, start_completed: int = 0, tenant_id: str = "") -> bool:
        total = start_completed + len(steps)
        run_id = job_id[:8]
        for offset, step in enumerate(steps, start=1):
            index = start_completed + offset
            stage = step["id"]
            label = step["label"]
            self._update_job(job_id, "running", current=index - 1, total=total, stage=stage, message=label)
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
                    self._record_incident(
                        "job_step_failed",
                        f"Job {job_id} failed at step {stage}",
                        extra={"job_id": job_id, "step": stage, "tenant_id": str(tenant_id or "")},
                    )
                    self._update_job(
                        job_id,
                        "failed",
                        error=detail[:500],
                        current=index - 1,
                        total=total,
                        stage=stage,
                        message=f"Failed: {label}",
                        completed_at=now_iso(),
                    )
                    return False
                self._append_event(job_dir, stage, f"Non-blocking step failed: {label}", level="warning", event="failed")
                self.log(self.root, run_id, f"QUEUE WARN step {stage} failed (non-blocking)", detail=detail[:8000])
                self._update_job(job_id, "running", current=index, total=total, stage=stage, message=f"Skipped failed step: {label}")
                continue
            self._update_job(job_id, "running", current=index, total=total, stage=stage, message=f"Complete: {label}")
            self._append_event(job_dir, stage, f"Completed: {label}", event="complete")
        return True

    def _gate_summary(self, workspace_dir: Path) -> dict:
        publish_path = workspace_dir / "outputs" / "publish_gate.json"
        sota_path = workspace_dir / "outputs" / "sota_gate.json"
        publish = _load_json(publish_path)
        sota = _load_json(sota_path)
        publish_profiles = publish.get("profiles", {}) if isinstance(publish, dict) else {}
        publish_failures = []
        if isinstance(publish_profiles, dict):
            for item in publish_profiles.values():
                publish_failures.extend(str(value) for value in item.get("failures", []) or [])
        sota_profiles = sota.get("profiles", {}) if isinstance(sota, dict) else {}
        sota_failures = []
        if isinstance(sota_profiles, dict):
            for item in sota_profiles.values():
                sota_failures.extend(str(value) for value in item.get("failures", []) or [])
        return {
            "publish_ok": bool(publish.get("ok", False)),
            "publish_profile": str(publish.get("highest_attained_profile", "") or publish.get("target_profile", "") or ""),
            "publish_failures": sorted(set(publish_failures)),
            "sota_ok": bool(sota.get("ok", False)),
            "sota_profile": str(sota.get("highest_attained_profile", "") or sota.get("target_profile", "") or ""),
            "sota_failures": sorted(set(sota_failures)),
        }

    def ops_summary(self, identity: dict | None = None) -> dict:
        ops = self._load_ops_state()
        observability = launch_contract(self.root).get("observability", {})
        with self._conn() as conn:
            where = ""
            params = []
            if identity and str(identity.get("tenant_id", "") or "").strip():
                where = "WHERE tenant_id=?"
                params.append(str(identity.get("tenant_id", "") or "").strip())
            counts = {
                "queued": conn.execute(f"SELECT COUNT(*) FROM jobs {where} AND status='queued'" if where else "SELECT COUNT(*) FROM jobs WHERE status='queued'", tuple(params)).fetchone()[0],
                "running": conn.execute(f"SELECT COUNT(*) FROM jobs {where} AND status='running'" if where else "SELECT COUNT(*) FROM jobs WHERE status='running'", tuple(params)).fetchone()[0],
                "awaiting_rubric_confirmation": conn.execute(
                    f"SELECT COUNT(*) FROM jobs {where} AND status='awaiting_rubric_confirmation'"
                    if where
                    else "SELECT COUNT(*) FROM jobs WHERE status='awaiting_rubric_confirmation'",
                    tuple(params),
                ).fetchone()[0],
                "awaiting_anchor_scores": conn.execute(
                    f"SELECT COUNT(*) FROM jobs {where} AND status='awaiting_anchor_scores'"
                    if where
                    else "SELECT COUNT(*) FROM jobs WHERE status='awaiting_anchor_scores'",
                    tuple(params),
                ).fetchone()[0],
                "completed": conn.execute(f"SELECT COUNT(*) FROM jobs {where} AND status='completed'" if where else "SELECT COUNT(*) FROM jobs WHERE status='completed'", tuple(params)).fetchone()[0],
                "failed": conn.execute(f"SELECT COUNT(*) FROM jobs {where} AND status='failed'" if where else "SELECT COUNT(*) FROM jobs WHERE status='failed'", tuple(params)).fetchone()[0],
            }
            rows = conn.execute(
                f"SELECT started_at, completed_at, status FROM jobs {where}" if where else "SELECT started_at, completed_at, status FROM jobs",
                tuple(params),
            ).fetchall()
        latencies = []
        for started_at, completed_at, status in rows:
            if status not in {"completed", "failed"} or not started_at or not completed_at:
                continue
            start_dt = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
            latencies.append(max(0.0, (end_dt - start_dt).total_seconds()))
        latencies.sort()
        p95 = latencies[int((len(latencies) - 1) * 0.95)] if latencies else 0.0
        queue_depth = self._queue.qsize()
        warnings = []
        if queue_depth > int(observability.get("max_queue_depth_warning", 5) or 5):
            warnings.append("queue_depth_above_warning")
        if p95 > float(observability.get("max_p95_job_latency_seconds", 3600.0) or 3600.0):
            warnings.append("p95_job_latency_above_warning")
        if int(ops.get("cache_validation_failures", 0) or 0) > 0:
            warnings.append("cache_validation_failures_present")
        return {
            "queue_depth": queue_depth,
            "jobs": counts,
            "latency": {
                "completed_jobs": len(latencies),
                "mean_seconds": round(sum(latencies) / len(latencies), 6) if latencies else 0.0,
                "p95_seconds": round(p95, 6),
            },
            "cache": {
                "hits": int(ops.get("cache_hits", 0) or 0),
                "misses": int(ops.get("cache_misses", 0) or 0),
                "validation_failures": int(ops.get("cache_validation_failures", 0) or 0),
            },
            "recent_gate_failures": list(ops.get("recent_gate_failures", []) or []),
            "recent_incidents": list(ops.get("recent_incidents", []) or []),
            "retention_policy": launch_contract(self.root).get("retention", {}),
            "observability_thresholds": observability,
            "warnings": warnings,
            "last_retention_report": ops.get("last_retention_report", {}),
        }

    def prune_retention(self, dry_run: bool = True) -> dict:
        retention = launch_contract(self.root).get("retention", {})
        now = datetime.now(timezone.utc)
        report = {
            "dry_run": bool(dry_run),
            "generated_at": now_iso(),
            "jobs_removed": [],
            "workspaces_removed": [],
            "artifacts_removed": [],
        }
        with self._conn() as conn:
            rows = conn.execute("SELECT id, tenant_id, status, updated_at, job_dir, artifact_path FROM jobs").fetchall()
        for job_id, tenant_id, status, updated_at, job_dir, artifact_path in rows:
            if status not in {"completed", "failed"}:
                continue
            updated_dt = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00")) if updated_at else now
            age_days = max(0.0, (now - updated_dt).total_seconds() / 86400.0)
            job_path = Path(str(job_dir))
            workspace_path = self._workspace_dir(str(job_id), str(tenant_id or ""))
            artifact = Path(str(artifact_path)) if artifact_path else None
            artifact_dir = artifact.parent.parent if artifact else self._artifact_dir(str(job_id), str(tenant_id or ""))
            if age_days >= float(retention.get("job_days", 14) or 14):
                report["jobs_removed"].append(str(job_path))
                if not dry_run and job_path.exists():
                    shutil.rmtree(job_path)
            if age_days >= float(retention.get("workspace_days", 7) or 7):
                report["workspaces_removed"].append(str(workspace_path))
                if not dry_run and workspace_path.exists():
                    shutil.rmtree(workspace_path)
            if age_days >= float(retention.get("artifact_days", 30) or 30):
                report["artifacts_removed"].append(str(artifact_dir))
                if not dry_run and artifact_dir.exists():
                    shutil.rmtree(artifact_dir)

        def mutate(payload):
            payload["last_retention_report"] = report

        self._update_ops_state(mutate)
        return report

    def _process_job(self, job_id: str):
        job = self.get_job(job_id)
        if not job or job["status"] != "queued":
            return
        run_id = job_id[:8]
        mode = str(job["mode"] or "")
        job_dir = Path(job["job_dir"])
        tenant_id = str(job.get("tenant_id", "") or "local-dev-tenant")
        workspace_dir = self._workspace_dir(job_id, tenant_id)
        manifest = _load_json(self._manifest_path(job_dir))
        steps = pipeline_steps()
        self._update_job(
            job_id,
            "running",
            current=0,
            total=len(steps),
            stage="queued",
            message="Job queued",
            started_at=now_iso(),
            cache_status="miss",
        )
        self.log(self.root, run_id, f"QUEUE START mode={mode} manifest={job['snapshot_hash']} workspace={workspace_dir}")
        try:
            baseline = self._artifact_snapshot(workspace_dir)
            metadata = ensure_class_metadata(workspace_dir / "inputs")
            bias_path = ensure_bootstrap_calibration(workspace_dir, metadata)
            rubric_manifest = _load_json(workspace_dir / RUBRIC_ARTIFACTS["rubric_manifest"])
            rubric_input = resolve_input_path(workspace_dir / "inputs" / "rubric.md", "rubric")
            manifest["run_scope"] = build_run_scope(
                metadata=metadata,
                routing=load_contract_json(workspace_dir / "config" / "llm_routing.json"),
                rubric_path=rubric_input,
                rubric_manifest=rubric_manifest,
            )
            manifest["calibration_artifact"] = _file_manifest(workspace_dir / CALIBRATION_ARTIFACT, CALIBRATION_ARTIFACT)
            manifest["calibration_manifest"] = _file_manifest(workspace_dir / CALIBRATION_MANIFEST_ARTIFACT, CALIBRATION_MANIFEST_ARTIFACT)
            self._write_json(self._manifest_path(job_dir), manifest)
            self._write_json(workspace_dir / "pipeline_manifest.json", manifest)
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

            if not self._run_pipeline_steps(job_id, job_dir, workspace_dir, env, steps, start_completed=0, tenant_id=tenant_id):
                return

            dashboard = workspace_dir / "outputs" / "dashboard_data.json"
            if not dashboard.exists():
                self._append_event(job_dir, "dashboard", "Dashboard data missing after successful run", level="error", event="failed")
                self.log(self.root, run_id, "QUEUE ERROR dashboard missing")
                self._record_incident(
                    "dashboard_missing",
                    f"Job {job_id} completed steps but did not produce dashboard output",
                    extra={"job_id": job_id, "tenant_id": tenant_id},
                )
                self._update_job(
                    job_id,
                    "failed",
                    error="Dashboard data not found",
                    current=len(steps),
                    total=len(steps),
                    stage="dashboard",
                    message="Failed: Dashboard output missing",
                    completed_at=now_iso(),
                )
                return

            if self._should_pause_for_anchors(workspace_dir):
                self._pause_for_anchor_scores(job, workspace_dir, total_steps=len(steps))
                self.log(self.root, run_id, "QUEUE PAUSED awaiting_anchor_scores")
                return

            refreshed_job = self.get_job(job_id)
            if refreshed_job:
                self._publish_completed_workspace(refreshed_job, workspace_dir, manifest, total_steps=len(steps))
            self.log(self.root, run_id, "QUEUE SUCCESS")
        except Exception as exc:  # pragma: no cover - defensive
            self._append_event(job_dir, "unhandled", f"Unhandled error: {exc}", level="error", event="failed")
            self.log(self.root, run_id, "QUEUE ERROR unhandled", detail=str(exc))
            self._record_incident(
                "job_unhandled_exception",
                f"Unhandled exception while processing job {job_id}",
                extra={"job_id": job_id, "tenant_id": tenant_id, "error": str(exc)[:500]},
            )
            self._update_job(
                job_id,
                "failed",
                error=str(exc)[:500],
                stage="unhandled",
                message="Failed with unhandled error",
                completed_at=now_iso(),
            )
