#!/usr/bin/env python3
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from scripts.aggregate_review_learning import default_aggregate_learning_policy, normalize_aggregate_learning_policy
from scripts.rubric_validity import build_data_posture
from server import classroom
from server.google_classroom_adapter import GoogleClassroomAdapter, GoogleClassroomError
from server.google_oauth import GoogleOAuthError, GoogleOAuthService
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
    curve_top: float | None = None
    curve_bottom: float | None = None
    assigned_marks: list[dict] = Field(default_factory=list)
    pinned_marks: list[dict] | None = None
    accept_reorder: bool = False
    feedback_drafts: list[dict] = Field(default_factory=list)


class CurveReflowPayload(BaseModel):
    pinned_marks: list[dict] = Field(default_factory=list)
    curve_top: float | None = None
    curve_bottom: float | None = None
    accept_reorder: bool = False


class ClassroomLinkPayload(BaseModel):
    course_id: str
    coursework_id: str
    course_name: str | None = None
    coursework_title: str | None = None
    assignment_title: str | None = None
    selected_rubric_source: str | None = None
    google_integration_path: str | None = None
    passback_mode: str | None = None
    policy: dict = Field(default_factory=dict)


class ClassroomSnapshotPayload(BaseModel):
    roster: list[dict] = Field(default_factory=list)
    submissions: list[dict] = Field(default_factory=list)


class ClassroomReadSyncPayload(BaseModel):
    adapter: str | None = None
    course_id: str | None = None
    course_name: str | None = None
    coursework_id: str | None = None
    coursework_title: str | None = None
    assignment_title: str | None = None
    passback_mode: str | None = None
    policy: dict = Field(default_factory=dict)
    roster: list[dict] = Field(default_factory=list)
    submissions: list[dict] = Field(default_factory=list)


class ClassroomEventPayload(BaseModel):
    event_id: str | None = None
    event_type: str | None = None
    course_id: str | None = None
    coursework_id: str | None = None
    submission_id: str | None = None
    submission: dict | None = None


class ClassroomAuditPayload(BaseModel):
    audit_revision_id: int | None = None
    gate_status: str | None = None
    blocked_reasons: list[str] = Field(default_factory=list)
    audit_artifact_hash: str | None = None


class ClassroomPassbackPreflightPayload(BaseModel):
    mode: str


class ClassroomPassbackConfirmPayload(BaseModel):
    preflight_id: str
    confirmed: bool = False


class GoogleClassroomSelectPayload(BaseModel):
    course_id: str
    coursework_id: str
    course_name: str | None = None
    coursework_title: str | None = None
    passback_mode: str | None = "csv_export"


class GoogleClassroomReadSyncPayload(BaseModel):
    course_id: str | None = None
    coursework_id: str | None = None
    course_name: str | None = None
    coursework_title: str | None = None
    passback_mode: str | None = "csv_export"


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


def project_meta_for_product(identity: dict | None = None) -> dict:
    return get_current_project(identity) or workspace_project(identity)


def classroom_error_response(exc: classroom.ClassroomStateError):
    raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from exc


def google_error_response(exc: Exception):
    code = getattr(exc, "code", "google_classroom_error")
    raise HTTPException(status_code=400, detail={"code": code, "message": str(exc)}) from exc


def google_oauth_service() -> GoogleOAuthService:
    return GoogleOAuthService(BASE_DIR)


def google_classroom_adapter(identity: dict, project: dict) -> tuple[GoogleClassroomAdapter, dict]:
    service = google_oauth_service()
    token, status = service.fresh_access_token(identity, project)
    return GoogleClassroomAdapter(token), status


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


@router.get("/projects/data-posture")
async def projects_data_posture(request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    project = get_current_project(identity) or workspace_project(identity)
    posture = build_data_posture(root)
    posture["project"] = {
        "id": project.get("id"),
        "name": project.get("name"),
        "aggregate_learning": project.get("aggregate_learning", {}),
    }
    posture["auth"] = {
        "strict_identity": _strict_identity(identity),
        "tenant_scoped": bool((identity or {}).get("tenant_id")),
        "teacher_scoped": bool((identity or {}).get("teacher_id")),
    }
    return posture


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
    request_payload = payload.model_dump(exclude_none=True)
    try:
        bundle = review_store.save_review_bundle(
            BASE_DIR,
            root,
            project,
            request_payload,
            stage=stage,
        )
    except review_store.ReviewReorderPending as pending:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "reorder_confirmation_required",
                "message": "Pinned marks imply rank changes. Confirm the reorder before finalizing.",
                "implied_moves": pending.implied_moves,
            },
        )
    classroom.record_review_revision(BASE_DIR, root, project, identity, request_payload, stage=stage)
    return bundle


@router.post("/projects/curve/reflow")
async def projects_curve_reflow(payload: CurveReflowPayload, request: Request):
    """Stateless pin & re-flow preview over the current workspace machine curve."""
    identity = identity_context(request)
    root = workspace_root(identity)
    dashboard = review_store.load_dashboard(root)
    if not review_store.dashboard_students_in_rank_order(dashboard):
        raise HTTPException(status_code=409, detail="No cohort results to re-flow yet")
    return review_store.compute_curve_reflow(
        root,
        dashboard,
        payload.pinned_marks,
        curve_top=payload.curve_top,
        curve_bottom=payload.curve_bottom,
        accept_reorder=payload.accept_reorder,
    )


@router.get("/projects/classroom")
async def projects_classroom_state(request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    project = project_meta_for_product(identity)
    return classroom.state_bundle(BASE_DIR, root, project, identity)


@router.post("/projects/classroom/link")
async def projects_classroom_link(payload: ClassroomLinkPayload, request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    project = project_meta_for_product(identity)
    try:
        return classroom.link_assignment(BASE_DIR, root, project, identity, payload.model_dump(exclude_none=True))
    except classroom.ClassroomStateError as exc:
        classroom_error_response(exc)


@router.post("/projects/classroom/reconcile")
async def projects_classroom_reconcile(payload: ClassroomSnapshotPayload, request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    project = project_meta_for_product(identity)
    try:
        return classroom.reconcile_snapshot(BASE_DIR, root, project, identity, payload.model_dump(exclude_none=True))
    except classroom.ClassroomStateError as exc:
        classroom_error_response(exc)


@router.post("/projects/classroom/read-sync")
async def projects_classroom_read_sync(payload: ClassroomReadSyncPayload, request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    project = project_meta_for_product(identity)
    try:
        return classroom.read_only_sync(BASE_DIR, root, project, identity, payload.model_dump(exclude_none=True))
    except classroom.ClassroomStateError as exc:
        classroom_error_response(exc)


@router.get("/projects/classroom/google/courses")
async def projects_classroom_google_courses(request: Request):
    identity = identity_context(request)
    project = project_meta_for_product(identity)
    try:
        adapter, status = google_classroom_adapter(identity, project)
        return {"google_auth": status, "courses": adapter.list_courses()}
    except (GoogleOAuthError, GoogleClassroomError) as exc:
        google_error_response(exc)


@router.get("/projects/classroom/google/courses/{course_id}/coursework")
async def projects_classroom_google_coursework(course_id: str, request: Request, include_drafts: bool = False):
    identity = identity_context(request)
    project = project_meta_for_product(identity)
    if include_drafts and _strict_identity(identity) and str(identity.get("role", "")) != "admin":
        raise HTTPException(status_code=403, detail={"code": "admin_required", "message": "Draft coursework visibility is admin-only."})
    try:
        adapter, status = google_classroom_adapter(identity, project)
        return {"google_auth": status, "course_id": course_id, "coursework": adapter.list_coursework(course_id, include_drafts=include_drafts)}
    except (GoogleOAuthError, GoogleClassroomError) as exc:
        google_error_response(exc)


@router.post("/projects/classroom/google/select")
async def projects_classroom_google_select(payload: GoogleClassroomSelectPayload, request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    project = project_meta_for_product(identity)
    try:
        status = google_oauth_service().status(identity, project)
        link_payload = {
            "course_id": payload.course_id,
            "course_name": payload.course_name or payload.course_id,
            "coursework_id": payload.coursework_id,
            "coursework_title": payload.coursework_title or payload.coursework_id,
            "google_integration_path": "live_google",
            "passback_mode": payload.passback_mode or "csv_export",
            "policy": {
                "policy_state": "operator_supervised_pilot",
                "app_approval_status": "operator_supervised_pilot",
                "oauth_scope_posture": "connected_read_only" if status.get("connected") else "not_connected",
                "classroom_write_adapter_status": "not_configured",
                "external_writes_enabled": False,
                "read_only_first": True,
            },
        }
        return classroom.link_assignment(BASE_DIR, root, project, identity, link_payload)
    except classroom.ClassroomStateError as exc:
        classroom_error_response(exc)


@router.post("/projects/classroom/google/read-sync")
async def projects_classroom_google_read_sync(payload: GoogleClassroomReadSyncPayload, request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    project = project_meta_for_product(identity)
    course_id = str(payload.course_id or "").strip()
    coursework_id = str(payload.coursework_id or "").strip()
    current_state = classroom.state_bundle(BASE_DIR, root, project, identity)
    link = current_state.get("classroom_link", {}) if isinstance(current_state.get("classroom_link"), dict) else {}
    course_id = course_id or str(link.get("course_id", "") or "")
    coursework_id = coursework_id or str(link.get("coursework_id", "") or "")
    if not course_id or not coursework_id:
        raise HTTPException(status_code=400, detail={"code": "classroom_link_required", "message": "Select a Google course and assignment before syncing."})
    service = google_oauth_service()
    status = service.status(identity, project)
    try:
        adapter, status = google_classroom_adapter(identity, project)
        snapshot = adapter.read_snapshot(
            course_id,
            coursework_id,
            course_name=payload.course_name or str(link.get("course_name", "") or ""),
            coursework_title=payload.coursework_title or str(link.get("coursework_title", "") or ""),
        )
        snapshot.update(
            {
                "adapter": "live_google",
                "google_integration_path": "live_google",
                "passback_mode": payload.passback_mode or link.get("passback_mode") or "csv_export",
                "google_auth": status,
                "policy": {
                    "policy_state": "operator_supervised_pilot",
                    "app_approval_status": "operator_supervised_pilot",
                    "oauth_scope_posture": "connected_read_only",
                    "classroom_write_adapter_status": "not_configured",
                    "external_writes_enabled": False,
                    "read_only_first": True,
                },
            }
        )
    except (GoogleOAuthError, GoogleClassroomError) as exc:
        snapshot = {
            "adapter": "live_google",
            "google_integration_path": "live_google",
            "course_id": course_id,
            "course_name": payload.course_name or str(link.get("course_name", "") or course_id),
            "coursework_id": coursework_id,
            "coursework_title": payload.coursework_title or str(link.get("coursework_title", "") or coursework_id),
            "passback_mode": payload.passback_mode or link.get("passback_mode") or "csv_export",
            "google_auth": status,
            "platform_errors": [{"code": getattr(exc, "code", "google_classroom_error"), "message": str(exc)}],
            "roster": [],
            "submissions": [],
            "policy": {
                "policy_state": "operator_supervised_pilot",
                "app_approval_status": "operator_supervised_pilot",
                "oauth_scope_posture": "not_connected" if getattr(exc, "code", "") == "missing_oauth_grant" else "connected_read_only",
                "classroom_write_adapter_status": "not_configured",
                "external_writes_enabled": False,
                "read_only_first": True,
            },
        }
    try:
        return classroom.read_only_sync(BASE_DIR, root, project, identity, snapshot)
    except classroom.ClassroomStateError as exc:
        classroom_error_response(exc)


@router.post("/projects/classroom/events")
async def projects_classroom_events(payload: ClassroomEventPayload, request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    project = project_meta_for_product(identity)
    try:
        return classroom.record_event_hint(BASE_DIR, root, project, identity, payload.model_dump(exclude_none=True))
    except classroom.ClassroomStateError as exc:
        classroom_error_response(exc)


@router.post("/projects/classroom/audit/complete")
async def projects_classroom_audit_complete(payload: ClassroomAuditPayload, request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    project = project_meta_for_product(identity)
    try:
        return classroom.complete_background_audit(BASE_DIR, root, project, identity, payload.model_dump(exclude_none=True))
    except classroom.ClassroomStateError as exc:
        classroom_error_response(exc)


@router.post("/projects/classroom/finalize")
async def projects_classroom_finalize(request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    project = project_meta_for_product(identity)
    try:
        return classroom.finalize_by_teacher(BASE_DIR, root, project, identity)
    except classroom.ClassroomStateError as exc:
        classroom_error_response(exc)


@router.get("/projects/classroom/evidence-packet")
async def projects_classroom_evidence_packet(request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    project = project_meta_for_product(identity)
    try:
        return classroom.assessment_evidence_packet(BASE_DIR, root, project, identity)
    except classroom.ClassroomStateError as exc:
        classroom_error_response(exc)


@router.post("/projects/classroom/passback/preflight")
async def projects_classroom_passback_preflight(payload: ClassroomPassbackPreflightPayload, request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    project = project_meta_for_product(identity)
    try:
        return classroom.passback_preflight(BASE_DIR, root, project, identity, payload.model_dump(exclude_none=True))
    except classroom.ClassroomStateError as exc:
        classroom_error_response(exc)


@router.post("/projects/classroom/passback/confirm")
async def projects_classroom_passback_confirm(payload: ClassroomPassbackConfirmPayload, request: Request):
    identity = identity_context(request)
    root = workspace_root(identity)
    project = project_meta_for_product(identity)
    try:
        return classroom.confirm_passback(BASE_DIR, root, project, identity, payload.model_dump(exclude_none=True))
    except classroom.ClassroomStateError as exc:
        classroom_error_response(exc)


@router.get("/projects/classroom/passback/exports/{action_id}")
async def projects_classroom_passback_export(action_id: str, request: Request):
    identity = identity_context(request)
    project = project_meta_for_product(identity)
    scope_id = review_store.review_scope_id(project)
    state = classroom.load_state(BASE_DIR, scope_id, project, identity)
    for action in state.get("passback", {}).get("actions", []) or []:
        if not isinstance(action, dict) or str(action.get("action_id", "") or "") != action_id:
            continue
        artifact = action.get("export_artifact", {}) if isinstance(action.get("export_artifact"), dict) else {}
        path = Path(str(artifact.get("path", "") or ""))
        if path.exists() and review_store.exports_dir(BASE_DIR, scope_id) in path.parents:
            return FileResponse(path, filename=artifact.get("filename") or path.name, media_type="text/csv")
    raise HTTPException(status_code=404, detail="Export not found")
