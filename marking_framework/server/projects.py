#!/usr/bin/env python3
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from scripts.aggregate_review_learning import default_aggregate_learning_policy, normalize_aggregate_learning_policy
from server import review_store

BASE_DIR = Path(__file__).resolve().parent
PROJECTS_DIR = BASE_DIR.parent / "projects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
CURRENT_PROJECT_PATH = PROJECTS_DIR / "current.json"

router = APIRouter()


class ProjectPayload(BaseModel):
    name: str | None = None
    project_id: str | None = None
    aggregate_learning_mode: str | None = None
    aggregate_policy_reference: str | None = None
    aggregate_retention_days: int | None = None


class ProjectReviewPayload(BaseModel):
    project_id: str | None = None
    action: str | None = None
    session_id: str | None = None
    students: list[dict] = Field(default_factory=list)
    pairwise: list[dict] = Field(default_factory=list)
    review_notes: str | None = None


def workspace_root() -> Path:
    return BASE_DIR.parent


def clear_workspace(root: Path):
    inputs = root / "inputs"
    if inputs.exists():
        for item in inputs.iterdir():
            if item.name == "exemplars":
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    (inputs / "submissions").mkdir(parents=True, exist_ok=True)
    for name in ["processing", "assessments", "outputs"]:
        path = root / name
        if path.exists():
            shutil.rmtree(path)


def project_id_from_name(name: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in name.strip().lower())
    slug = "-".join([part for part in slug.split("-") if part])
    suffix = uuid.uuid4().hex[:6]
    return f"{slug}-{suffix}" if slug else suffix


def get_current_project() -> dict | None:
    if not CURRENT_PROJECT_PATH.exists():
        return None
    return normalize_project_meta(json.loads(CURRENT_PROJECT_PATH.read_text(encoding="utf-8")))


def set_current_project(project: dict | None):
    if project is None:
        if CURRENT_PROJECT_PATH.exists():
            CURRENT_PROJECT_PATH.unlink()
        return
    CURRENT_PROJECT_PATH.write_text(json.dumps(normalize_project_meta(project), indent=2), encoding="utf-8")


def normalize_project_meta(meta: dict | None) -> dict:
    payload = dict(meta or {})
    payload["aggregate_learning"] = normalize_aggregate_learning_policy(
        payload.get("aggregate_learning", {}) if isinstance(payload.get("aggregate_learning"), dict) else default_aggregate_learning_policy()
    )
    return payload


def aggregate_learning_from_payload(payload: ProjectPayload | None, existing: dict | None = None) -> dict:
    merged = dict((existing or {}).get("aggregate_learning", {}) if isinstance((existing or {}).get("aggregate_learning"), dict) else {})
    if payload is not None and payload.aggregate_learning_mode is not None:
        merged["mode"] = payload.aggregate_learning_mode
    if payload is not None and payload.aggregate_policy_reference is not None:
        merged["policy_reference"] = payload.aggregate_policy_reference
    if payload is not None and payload.aggregate_retention_days is not None:
        merged["retention_days"] = payload.aggregate_retention_days
    merged.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
    if payload is not None and any(
        value is not None
        for value in (payload.aggregate_learning_mode, payload.aggregate_policy_reference, payload.aggregate_retention_days)
    ):
        merged["updated_at"] = datetime.now(timezone.utc).isoformat()
    return normalize_aggregate_learning_policy(merged or default_aggregate_learning_policy())


def list_projects() -> list:
    projects = []
    for path in PROJECTS_DIR.iterdir():
        if not path.is_dir():
            continue
        meta_path = path / "project.json"
        if not meta_path.exists():
            continue
        meta = normalize_project_meta(json.loads(meta_path.read_text(encoding="utf-8")))
        meta["review_summary"] = review_store.review_scope_summary(BASE_DIR, str(meta.get("id", "") or path.name), meta)
        projects.append(meta)
    projects.sort(key=lambda p: p.get("updated_at", ""), reverse=True)
    return projects


def current_project_with_review() -> dict | None:
    current = get_current_project()
    if not current:
        return None
    enriched = dict(current)
    enriched["review_summary"] = review_store.review_scope_summary(BASE_DIR, str(current.get("id", "") or "workspace"), current)
    return enriched


def project_meta_for_review(project_id: str | None) -> dict | None:
    if project_id:
        meta_path = PROJECTS_DIR / project_id / "project.json"
        if meta_path.exists():
            return normalize_project_meta(json.loads(meta_path.read_text(encoding="utf-8")))
        return normalize_project_meta({"id": project_id, "name": project_id})
    return get_current_project()


def copy_tree(src: Path, dst: Path):
    if not src.exists():
        return
    shutil.copytree(src, dst, dirs_exist_ok=True)


def save_project_snapshot(root: Path, project_id: str, name: str, include_logs: bool = True, aggregate_learning: dict | None = None) -> dict:
    project_dir = PROJECTS_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    meta_path = project_dir / "project.json"
    now = datetime.now(timezone.utc).isoformat()
    created = now
    if meta_path.exists():
        existing = normalize_project_meta(json.loads(meta_path.read_text(encoding="utf-8")))
        created = existing.get("created_at", now)
    meta = normalize_project_meta(
        {
            "id": project_id,
            "name": name,
            "created_at": created,
            "updated_at": now,
            "aggregate_learning": aggregate_learning or (existing.get("aggregate_learning") if meta_path.exists() else default_aggregate_learning_policy()),
        }
    )
    folders = ["inputs", "processing", "assessments", "outputs"]
    if include_logs:
        folders.append("logs")
    for folder in folders:
        src = root / folder
        dst = project_dir / folder
        if folder != "inputs":
            copy_tree(src, dst)
            continue
        # Inputs contain built-in exemplars; don't duplicate them into every project.
        dst.mkdir(parents=True, exist_ok=True)
        if src.exists():
            for item in src.iterdir():
                if item.name == "exemplars":
                    continue
                if item.is_dir():
                    copy_tree(item, dst / item.name)
                else:
                    shutil.copy2(item, dst / item.name)
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


@router.get("/projects")
async def projects_list():
    return {"current": current_project_with_review(), "projects": list_projects()}


@router.post("/projects/save")
async def projects_save(payload: ProjectPayload):
    root = workspace_root()
    current = get_current_project()
    name = payload.name or (current.get("name") if current else None) or f"Project {datetime.now(timezone.utc).date()}"
    project_id = payload.project_id or (current.get("id") if current else None) or project_id_from_name(name)
    meta = save_project_snapshot(root, project_id, name, aggregate_learning=aggregate_learning_from_payload(payload, current))
    set_current_project(meta)
    return meta


@router.post("/projects/new")
async def projects_new(payload: ProjectPayload):
    root = workspace_root()
    clear_workspace(root)
    name = payload.name or f"Project {datetime.now(timezone.utc).date()}"
    project_id = payload.project_id or project_id_from_name(name)
    meta = save_project_snapshot(root, project_id, name, include_logs=False, aggregate_learning=aggregate_learning_from_payload(payload))
    set_current_project(meta)
    return meta


@router.post("/projects/clear")
async def projects_clear():
    root = workspace_root()
    clear_workspace(root)
    set_current_project(None)
    return {"status": "cleared", "current": None}


@router.post("/projects/load")
async def projects_load(payload: ProjectPayload):
    if not payload.project_id:
        raise HTTPException(status_code=400, detail="Project id required")
    project_dir = PROJECTS_DIR / payload.project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    root = workspace_root()
    clear_workspace(root)
    for folder in ["inputs", "processing", "assessments", "outputs"]:
        copy_tree(project_dir / folder, root / folder)
    meta_path = project_dir / "project.json"
    meta = normalize_project_meta(json.loads(meta_path.read_text(encoding="utf-8"))) if meta_path.exists() else normalize_project_meta({"id": payload.project_id})
    set_current_project(meta)
    bundle = review_store.load_review_bundle(BASE_DIR, root, meta)
    review_store.materialize_workspace_review_state(root, bundle)
    return {"status": "ok", "project": meta}


@router.delete("/projects/{project_id}")
async def projects_delete(project_id: str):
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    shutil.rmtree(project_dir)
    review_store.delete_review_scope(BASE_DIR, project_id)
    current = get_current_project()
    if current and current.get("id") == project_id:
        set_current_project(None)
    return {"status": "deleted"}


@router.get("/projects/review")
async def projects_review():
    review_store.ensure_draft_review(BASE_DIR, workspace_root(), get_current_project())
    bundle = review_store.load_review_bundle(BASE_DIR, workspace_root(), get_current_project())
    review_store.materialize_workspace_review_state(workspace_root(), bundle)
    return bundle


@router.post("/projects/review")
async def projects_review_save(payload: ProjectReviewPayload):
    project = project_meta_for_review(payload.project_id)
    action = str(payload.action or "draft").strip().lower()
    stage = "final" if action in {"final", "finalize", "publish"} else "draft"
    return review_store.save_review_bundle(
        BASE_DIR,
        workspace_root(),
        project,
        payload.model_dump(exclude_none=True),
        stage=stage,
    )
