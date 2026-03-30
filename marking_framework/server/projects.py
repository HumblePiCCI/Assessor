#!/usr/bin/env python3
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from scripts.aggregate_review_learning import default_aggregate_learning_policy, normalize_aggregate_learning_policy
from server import review_store
from server.runtime_context import identity_can_access, project_owner, resolve_request_identity

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


def identity_context(request: Request | None) -> dict:
    return resolve_request_identity(request, BASE_DIR.parent)


def _strict_identity(identity: dict | None) -> bool:
    return bool((identity or {}).get("strict_auth", False))


def _tenant_root(identity: dict | None) -> Path:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    if not _strict_identity(identity):
        return PROJECTS_DIR
    path = PROJECTS_DIR / str((identity or {}).get("tenant_token", "") or "tenant")
    path.mkdir(parents=True, exist_ok=True)
    return path


def tenant_workspaces_dir() -> Path:
    path = BASE_DIR / "data" / "tenant_workspaces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _projects_root(identity: dict | None) -> Path:
    root = _tenant_root(identity)
    if not _strict_identity(identity):
        root.mkdir(parents=True, exist_ok=True)
        return root
    path = root / "projects"
    path.mkdir(parents=True, exist_ok=True)
    return path


def current_project_path(identity: dict | None = None) -> Path:
    if not _strict_identity(identity):
        CURRENT_PROJECT_PATH.parent.mkdir(parents=True, exist_ok=True)
        return CURRENT_PROJECT_PATH
    tenant_root = _tenant_root(identity)
    teacher_token = str((identity or {}).get("teacher_token", "") or "teacher")
    path = tenant_root / "current" / f"{teacher_token}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def project_dir(project_id: str, identity: dict | None = None) -> Path:
    return _projects_root(identity) / project_id


def normalize_owner(owner: dict | None) -> dict:
    if not isinstance(owner, dict):
        return {}
    if not owner.get("tenant_id") and not owner.get("teacher_id"):
        return {}
    return project_owner(owner)


def project_scope_key(project_id: str, owner: dict | None = None) -> str:
    normalized_owner = normalize_owner(owner)
    tenant_token = str(normalized_owner.get("tenant_token", "") or "").strip()
    tenant_id = str(normalized_owner.get("tenant_id", "") or "").strip()
    project_token = str(project_id or "workspace").strip() or "workspace"
    if tenant_token and tenant_id not in {"", "local-dev-tenant"}:
        return f"{tenant_token}__{project_token}"
    return project_token


def workspace_project(identity: dict | None) -> dict:
    owner = normalize_owner(project_owner(identity or {}))
    return normalize_project_meta(
        {
            "id": "workspace",
            "name": "Workspace",
            "owner": owner,
            "scope_key": project_scope_key("workspace", owner),
            "aggregate_learning": default_aggregate_learning_policy(),
        }
    )


def workspace_root(identity: dict | None = None) -> Path:
    if not _strict_identity(identity):
        return BASE_DIR.parent
    tenant_token = str((identity or {}).get("tenant_token", "") or "tenant")
    teacher_token = str((identity or {}).get("teacher_token", "") or "teacher")
    path = tenant_workspaces_dir() / tenant_token / teacher_token / "workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


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


def normalize_project_meta(meta: dict | None) -> dict:
    payload = dict(meta or {})
    owner = normalize_owner(payload.get("owner"))
    if owner:
        payload["owner"] = owner
    payload["aggregate_learning"] = normalize_aggregate_learning_policy(
        payload.get("aggregate_learning", {}) if isinstance(payload.get("aggregate_learning"), dict) else default_aggregate_learning_policy()
    )
    payload["scope_key"] = str(payload.get("scope_key", "") or project_scope_key(str(payload.get("id", "") or ""), owner)).strip()
    return payload


def get_current_project(identity: dict | None = None) -> dict | None:
    path = current_project_path(identity)
    if not path.exists():
        return None
    payload = normalize_project_meta(json.loads(path.read_text(encoding="utf-8")))
    if identity and not identity_can_access(payload.get("owner"), identity):
        return None
    return payload


def set_current_project(project: dict | None, identity: dict | None = None):
    path = current_project_path(identity)
    if project is None:
        if path.exists():
            path.unlink()
        return
    path.write_text(json.dumps(normalize_project_meta(project), indent=2), encoding="utf-8")


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


def _iter_project_meta_paths(identity: dict | None = None):
    root = _projects_root(identity)
    if not root.exists():
        return []
    paths = []
    for path in root.iterdir():
        if not path.is_dir():
            continue
        meta_path = path / "project.json"
        if meta_path.exists():
            paths.append(meta_path)
    return sorted(paths)


def list_projects(identity: dict | None = None) -> list:
    projects = []
    for meta_path in _iter_project_meta_paths(identity):
        meta = normalize_project_meta(json.loads(meta_path.read_text(encoding="utf-8")))
        if identity and not identity_can_access(meta.get("owner"), identity):
            continue
        meta["review_summary"] = review_store.review_scope_summary(BASE_DIR, str(meta.get("scope_key") or meta.get("id", "") or meta_path.parent.name), meta)
        projects.append(meta)
    projects.sort(key=lambda p: p.get("updated_at", ""), reverse=True)
    return projects


def current_project_with_review(identity: dict | None = None) -> dict | None:
    current = get_current_project(identity)
    if not current:
        return None
    enriched = dict(current)
    enriched["review_summary"] = review_store.review_scope_summary(
        BASE_DIR,
        str(current.get("scope_key") or current.get("id", "") or "workspace"),
        current,
    )
    return enriched


def project_meta_for_review(project_id: str | None, identity: dict | None = None) -> dict | None:
    if project_id:
        meta_path = project_dir(project_id, identity) / "project.json"
        if meta_path.exists():
            meta = normalize_project_meta(json.loads(meta_path.read_text(encoding="utf-8")))
        else:
            meta = normalize_project_meta({"id": project_id, "name": project_id, "owner": project_owner(identity or {})})
        if identity and not identity_can_access(meta.get("owner"), identity):
            raise HTTPException(status_code=403, detail="Project access denied")
        return meta
    current = get_current_project(identity)
    return current or workspace_project(identity)


def copy_tree(src: Path, dst: Path):
    if not src.exists():
        return
    shutil.copytree(src, dst, dirs_exist_ok=True)


def save_project_snapshot(
    root: Path,
    project_id: str,
    name: str,
    include_logs: bool = True,
    aggregate_learning: dict | None = None,
    owner: dict | None = None,
    identity: dict | None = None,
) -> dict:
    project_path = project_dir(project_id, identity)
    project_path.mkdir(parents=True, exist_ok=True)
    meta_path = project_path / "project.json"
    now = datetime.now(timezone.utc).isoformat()
    created = now
    existing = {}
    if meta_path.exists():
        existing = normalize_project_meta(json.loads(meta_path.read_text(encoding="utf-8")))
        created = existing.get("created_at", now)
        if identity and not identity_can_access(existing.get("owner"), identity):
            raise HTTPException(status_code=403, detail="Project access denied")
    owner_meta = normalize_owner(owner or existing.get("owner") or project_owner(identity or {}))
    meta = normalize_project_meta(
        {
            "id": project_id,
            "name": name,
            "created_at": created,
            "updated_at": now,
            "owner": owner_meta,
            "scope_key": project_scope_key(project_id, owner_meta),
            "aggregate_learning": aggregate_learning
            or existing.get("aggregate_learning")
            or default_aggregate_learning_policy(),
        }
    )
    folders = ["inputs", "processing", "assessments", "outputs"]
    if include_logs:
        folders.append("logs")
    for folder in folders:
        src = root / folder
        dst = project_path / folder
        if folder != "inputs":
            copy_tree(src, dst)
            continue
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
async def projects_list(request: Request):
    identity = identity_context(request)
    return {"current": current_project_with_review(identity), "projects": list_projects(identity)}


@router.post("/projects/save")
async def projects_save(payload: ProjectPayload, request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    current = get_current_project(identity)
    name = payload.name or (current.get("name") if current else None) or f"Project {datetime.now(timezone.utc).date()}"
    project_id = payload.project_id or (current.get("id") if current else None) or project_id_from_name(name)
    meta = save_project_snapshot(
        root,
        project_id,
        name,
        aggregate_learning=aggregate_learning_from_payload(payload, current),
        owner=project_owner(identity),
        identity=identity,
    )
    set_current_project(meta, identity)
    return meta


@router.post("/projects/new")
async def projects_new(payload: ProjectPayload, request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    clear_workspace(root)
    name = payload.name or f"Project {datetime.now(timezone.utc).date()}"
    project_id = payload.project_id or project_id_from_name(name)
    meta = save_project_snapshot(
        root,
        project_id,
        name,
        include_logs=False,
        aggregate_learning=aggregate_learning_from_payload(payload),
        owner=project_owner(identity),
        identity=identity,
    )
    set_current_project(meta, identity)
    return meta


@router.post("/projects/clear")
async def projects_clear(request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    clear_workspace(root)
    set_current_project(None, identity)
    return {"status": "cleared", "current": None}


@router.post("/projects/load")
async def projects_load(payload: ProjectPayload, request: Request):
    identity = identity_context(request)
    if not payload.project_id:
        raise HTTPException(status_code=400, detail="Project id required")
    project_path = project_dir(payload.project_id, identity)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    meta_path = project_path / "project.json"
    meta = normalize_project_meta(json.loads(meta_path.read_text(encoding="utf-8"))) if meta_path.exists() else normalize_project_meta({"id": payload.project_id})
    if not identity_can_access(meta.get("owner"), identity):
        raise HTTPException(status_code=403, detail="Project access denied")
    root = workspace_root(identity)
    clear_workspace(root)
    for folder in ["inputs", "processing", "assessments", "outputs"]:
        copy_tree(project_path / folder, root / folder)
    set_current_project(meta, identity)
    bundle = review_store.load_review_bundle(BASE_DIR, root, meta)
    review_store.materialize_workspace_review_state(root, bundle)
    return {"status": "ok", "project": meta}


@router.delete("/projects/{project_id}")
async def projects_delete(project_id: str, request: Request):
    identity = identity_context(request)
    project_path = project_dir(project_id, identity)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    meta_path = project_path / "project.json"
    meta = normalize_project_meta(json.loads(meta_path.read_text(encoding="utf-8"))) if meta_path.exists() else normalize_project_meta({"id": project_id})
    if not identity_can_access(meta.get("owner"), identity):
        raise HTTPException(status_code=403, detail="Project access denied")
    shutil.rmtree(project_path)
    review_store.delete_review_scope(BASE_DIR, str(meta.get("scope_key") or project_id))
    current = get_current_project(identity)
    if current and current.get("id") == project_id:
        set_current_project(None, identity)
    return {"status": "deleted"}


@router.get("/projects/review")
async def projects_review(request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    project = get_current_project(identity) or workspace_project(identity)
    review_store.ensure_draft_review(BASE_DIR, root, project)
    bundle = review_store.load_review_bundle(BASE_DIR, root, project)
    review_store.materialize_workspace_review_state(root, bundle)
    return bundle


@router.post("/projects/review")
async def projects_review_save(payload: ProjectReviewPayload, request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    project = project_meta_for_review(payload.project_id, identity)
    action = str(payload.action or "draft").strip().lower()
    stage = "final" if action in {"final", "finalize", "publish"} else "draft"
    return review_store.save_review_bundle(
        BASE_DIR,
        root,
        project,
        payload.model_dump(exclude_none=True),
        stage=stage,
    )
