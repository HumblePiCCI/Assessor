#!/usr/bin/env python3
import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from subprocess import DEVNULL, Popen, run
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from server.projects import router as projects_router
from server.pipeline_queue import PipelineQueue
app = FastAPI()
app.include_router(projects_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:7860", "http://127.0.0.1:7860"],
    allow_methods=["*"],
    allow_headers=["*"],
)
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
API_KEY_OVERRIDE = {"value": None}
UI_DIR = BASE_DIR.parent / "ui"
DATA_JSON_PATH = BASE_DIR.parent / "outputs" / "dashboard_data.json"
PIPELINE_EXTRA_PATHS = (
    "config/llm_routing.json",
    "config/marking_config.json",
    "config/rubric_criteria.json",
    "config/accuracy_gate.json",
    "config/sota_gate.json",
)
class AuthPayload(BaseModel):
    api_key: str
def save_upload(upload: UploadFile, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
def workspace_root() -> Path:
    return BASE_DIR.parent
def current_api_key() -> str | None:
    return API_KEY_OVERRIDE["value"] or os.environ.get("OPENAI_API_KEY")
def reset_workspace(root: Path):
    inputs_dir = root / "inputs"
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
        path = root / name
        if path.exists():
            shutil.rmtree(path)
def log_pipeline(root: Path, run_id: str, message: str, detail: str | None = None):
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "pipeline.log"
    stamp = datetime.now(timezone.utc).isoformat()
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"{stamp} [{run_id}] {message}\n")
        if detail:
            f.write(detail.strip() + "\n")
            f.write("---\n")
def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
def codex_auth_path() -> Path:
    return codex_home() / "auth.json"
def codex_status_payload() -> dict:
    available = bool(shutil.which("codex"))
    connected = False
    if available:
        auth_path = codex_auth_path()
        if auth_path.exists():
            try:
                data = json.loads(auth_path.read_text(encoding="utf-8"))
                connected = bool(data.get("OPENAI_API_KEY") or data.get("tokens"))
            except json.JSONDecodeError:
                connected = False
    return {"available": available, "connected": connected}


def codex_login_supported() -> bool:
    if not shutil.which("codex"):
        return False
    try:
        result = run(["codex", "--help"], capture_output=True, text=True)
    except Exception:
        return False
    text = ((result.stdout or "") + "\n" + (result.stderr or "")).lower()
    return "codex login" in text or "\n    login " in text
PIPELINE_QUEUE = PipelineQueue(
    root=workspace_root(),
    data_dir=DATA_DIR,
    reset_workspace_fn=reset_workspace,
    run_fn=run,
    log_fn=log_pipeline,
    api_key_fn=current_api_key,
)
@app.get("/auth/status")
async def auth_status():
    key = API_KEY_OVERRIDE["value"] or os.environ.get("OPENAI_API_KEY")
    return {"connected": bool(key)}
def ui_file_response(name: str, media_type: str | None = None):
    path = UI_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="UI asset not found")
    return FileResponse(path, media_type=media_type)
@app.get("/data.json")
async def ui_data_json():
    if not DATA_JSON_PATH.exists():
        return {"students": []}
    return json.loads(DATA_JSON_PATH.read_text(encoding="utf-8"))
@app.get("/")
async def ui_index():
    return ui_file_response("index.html")
@app.get("/app.js")
async def ui_app_js():
    return ui_file_response("app.js", media_type="application/javascript")
@app.get("/progress_stream.js")
async def ui_progress_stream_js():
    return ui_file_response("progress_stream.js", media_type="application/javascript")
@app.get("/grade_adjust.js")
async def ui_grade_adjust_js():
    return ui_file_response("grade_adjust.js", media_type="application/javascript")
@app.get("/feedback_generate.js")
async def ui_feedback_generate_js():
    return ui_file_response("feedback_generate.js", media_type="application/javascript")
@app.get("/style.css")
async def ui_style_css():
    return ui_file_response("style.css", media_type="text/css")
@app.post("/auth")
async def set_auth(payload: AuthPayload):
    if not payload.api_key or len(payload.api_key) < 10:
        raise HTTPException(status_code=400, detail="Invalid API key")
    API_KEY_OVERRIDE["value"] = payload.api_key.strip()
    return {"status": "ok"}
@app.get("/codex/status")
async def codex_status():
    return codex_status_payload()
@app.post("/codex/login")
async def codex_login():
    if not shutil.which("codex"):
        raise HTTPException(status_code=400, detail="Codex CLI not found")
    # Some local Codex CLIs are already authenticated but do not expose a browser login subcommand.
    status = codex_status_payload()
    if status.get("connected"):
        return {"status": "already_connected"}
    if not codex_login_supported():
        raise HTTPException(
            status_code=400,
            detail="Installed Codex CLI does not support browser login. Use API key connect or upgrade Codex CLI.",
        )
    Popen(["codex", "login"], stdout=DEVNULL, stderr=DEVNULL)
    return {"status": "started"}


def validate_pipeline_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized not in {"codex_local", "openai"}:
        raise HTTPException(status_code=400, detail="Invalid mode")
    if normalized == "codex_local":
        status = codex_status_payload()
        if not status["available"]:
            raise HTTPException(status_code=400, detail="Codex CLI not found")
        if not status["connected"]:
            raise HTTPException(status_code=400, detail="Codex not connected")
    if normalized == "openai" and not current_api_key():
        raise HTTPException(status_code=400, detail="OpenAI API key not configured")
    return normalized


def submit_pipeline_job(
    rubric: UploadFile,
    outline: UploadFile,
    submissions: Optional[List[UploadFile]],
    mode: str,
):
    if not submissions:
        raise HTTPException(status_code=400, detail="No submissions provided")
    mode = validate_pipeline_mode(mode)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        rubric_path = tmp_dir / f"rubric{Path(rubric.filename).suffix or '.md'}"
        outline_path = tmp_dir / f"assignment_outline{Path(outline.filename).suffix or '.md'}"
        submissions_dir = tmp_dir / "submissions"
        submissions_dir.mkdir(parents=True, exist_ok=True)
        save_upload(rubric, rubric_path)
        save_upload(outline, outline_path)
        for upload in submissions:
            save_upload(upload, submissions_dir / upload.filename)
        root = workspace_root()
        return PIPELINE_QUEUE.submit(
            mode=mode,
            rubric_path=rubric_path,
            outline_path=outline_path,
            submissions_dir=submissions_dir,
            extra_paths=[root / rel_path for rel_path in PIPELINE_EXTRA_PATHS],
        )


@app.post("/pipeline/run")
async def run_pipeline(
    rubric: UploadFile = File(...),
    outline: UploadFile = File(...),
    submissions: Optional[List[UploadFile]] = File(None),
    mode: str = Form("codex_local"),
):
    return submit_pipeline_job(rubric=rubric, outline=outline, submissions=submissions, mode=mode)


@app.post("/pipeline/v2/run")
async def run_pipeline_v2(
    rubric: UploadFile = File(...),
    outline: UploadFile = File(...),
    submissions: Optional[List[UploadFile]] = File(None),
    mode: str = Form("codex_local"),
):
    return submit_pipeline_job(rubric=rubric, outline=outline, submissions=submissions, mode=mode)
@app.get("/pipeline/v2/jobs/{job_id}")
async def pipeline_v2_status(job_id: str):
    job = PIPELINE_QUEUE.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
@app.get("/pipeline/v2/jobs/{job_id}/data")
async def pipeline_v2_data(job_id: str):
    data = PIPELINE_QUEUE.load_dashboard_data(job_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Dashboard data not ready")
    return data
@app.get("/pipeline/v2/jobs/{job_id}/events")
async def pipeline_v2_events(job_id: str, after: int = -1, limit: int = 200):
    payload = PIPELINE_QUEUE.get_events(job_id, after=after, limit=limit)
    if payload is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return payload
@app.post("/jobs")
async def create_job(
    rubric: UploadFile = File(...),
    outline: UploadFile = File(...),
    submissions_zip: UploadFile = File(...),
):
    job_id = str(uuid.uuid4())
    job_dir = DATA_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    rubric_path = job_dir / rubric.filename
    outline_path = job_dir / outline.filename
    zip_path = job_dir / submissions_zip.filename
    save_upload(rubric, rubric_path)
    save_upload(outline, outline_path)
    save_upload(submissions_zip, zip_path)
    # Extract submissions zip
    submissions_dir = job_dir / "submissions"
    submissions_dir.mkdir(parents=True, exist_ok=True)
    shutil.unpack_archive(str(zip_path), str(submissions_dir))
    # Run job
    cmd = [
        "python3",
        str((BASE_DIR.parent / "scripts" / "payg_job.py").resolve()),
        "--rubric",
        str(rubric_path),
        "--outline",
        str(outline_path),
        "--submissions",
        str(submissions_dir),
        "--llm",
        "--pricing",
        "--workdir",
        str(job_dir / "workspace"),
    ]
    api_key = API_KEY_OVERRIDE["value"] or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="OpenAI API key not configured")
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = api_key
    result = run(cmd, env=env)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail="Job failed")
    # Package outputs
    outputs_dir = job_dir / "workspace" / "outputs"
    if not outputs_dir.exists():
        raise HTTPException(status_code=500, detail="Outputs not found")
    archive_path = job_dir / "outputs.zip"
    shutil.make_archive(str(archive_path).replace(".zip", ""), "zip", str(outputs_dir))
    return {"job_id": job_id, "outputs_zip": f"/jobs/{job_id}/outputs"}
@app.get("/jobs/{job_id}/outputs")
async def get_outputs(job_id: str):
    job_dir = DATA_DIR / job_id
    archive_path = job_dir / "outputs.zip"
    if not archive_path.exists():
        raise HTTPException(status_code=404, detail="Outputs not found")
    return FileResponse(archive_path, filename="outputs.zip")
