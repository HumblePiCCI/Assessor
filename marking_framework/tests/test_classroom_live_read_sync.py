import json
import hashlib
import shutil
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

import server.app as appmod
from server.app import app
import server.projects as projmod
import server.google_session as google_session
from server.google_oauth import DEFAULT_GOOGLE_SCOPES, GoogleOAuthService
from server.google_token_store import GoogleTokenStore
from server.pipeline_queue import PipelineQueue


class FakeGoogleAdapter:
    def list_courses(self):
        return [{"course_id": "course-1", "course_name": "Period 2", "course_state": "ACTIVE"}]

    def list_coursework(self, course_id, *, include_drafts=False):
        assert course_id == "course-1"
        assert include_drafts is False
        return [{"course_id": "course-1", "coursework_id": "cw-1", "coursework_title": "Essay", "coursework_state": "PUBLISHED"}]

    def read_snapshot(self, course_id, coursework_id, *, course_name="", coursework_title=""):
        return {
            "adapter": "live_google",
            "course_id": course_id,
            "course_name": course_name or "Period 2",
            "coursework_id": coursework_id,
            "coursework_title": coursework_title or "Essay",
            "roster": [
                {"student_id": "s1", "display_name": "Student One"},
                {"student_id": "s2", "display_name": "Student Two"},
            ],
            "submissions": [
                {
                    "submission_id": "sub-1",
                    "student_id": "s1",
                    "display_name": "Student One",
                    "classroom_state": "submitted",
                    "attachments": [{"attachment_id": "a1", "mime_type": "text/plain", "text": "First imported essay."}],
                },
                {
                    "submission_id": "sub-2",
                    "student_id": "s2",
                    "display_name": "Student Two",
                    "classroom_state": "submitted",
                    "attachments": [{"attachment_id": "a2", "type": "external_link", "title": "Portfolio"}],
                },
            ],
        }


def google_public(email="teacher@example.com"):
    clean = email.strip().lower()
    return {
        "teacher_display_email": clean,
        "teacher_identity_hash": hashlib.sha256(clean.encode("utf-8")).hexdigest()[:24],
    }


def attach_google_session(client: TestClient, base_dir: Path, email="teacher@example.com") -> dict:
    session_id, identity = google_session.create_session(base_dir, google_public(email))
    client.cookies.set(google_session.COOKIE_NAME, session_id)
    client.assessor_identity = identity
    return identity


def setup_server(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projmod, "CURRENT_PROJECT_PATH", projects_dir / "current.json")
    monkeypatch.setattr(
        projmod,
        "google_classroom_adapter",
        lambda identity, project: (
            FakeGoogleAdapter(),
            {
                "connected": True,
                "granted_scopes": ["https://www.googleapis.com/auth/classroom.courses.readonly"],
                "expires_at": "2026-05-29T00:00:00+00:00",
                "teacher_identity_hash": "teacher-hash",
                "teacher_display_email": "",
            },
        ),
    )
    client = TestClient(app)
    attach_google_session(client, server_dir)
    return client


def test_live_google_read_sync_endpoint_materializes_supported_submissions_and_blocks_unsupported(tmp_path, monkeypatch):
    client = setup_server(tmp_path, monkeypatch)
    assert client.post("/projects/save", json={"name": "Classroom Live"}).status_code == 200
    assert client.get("/projects/classroom/google/courses").json()["courses"][0]["course_id"] == "course-1"
    assert client.get("/projects/classroom/google/courses/course-1/coursework").json()["coursework"][0]["coursework_id"] == "cw-1"

    selected = client.post(
        "/projects/classroom/google/select",
        json={"course_id": "course-1", "course_name": "Period 2", "coursework_id": "cw-1", "coursework_title": "Essay"},
    )
    assert selected.status_code == 200
    assert selected.json()["classroom_link"]["google_integration_path"] == "live_google"

    synced = client.post("/projects/classroom/google/read-sync", json={"course_id": "course-1", "coursework_id": "cw-1"})
    assert synced.status_code == 200
    payload = synced.json()
    assert payload["read_sync"]["adapter"] == "live_google"
    assert payload["read_sync"]["external_write_performed"] is False
    assert payload["read_sync"]["imported_submission_count"] == 1
    assert payload["read_sync"]["blocked_submission_count"] == 1
    assert "external_link_unsupported" in payload["blockers"]
    workspace = projmod.workspace_root(client.assessor_identity)
    assert (workspace / "inputs" / "submissions" / "classroom_import" / "s001.txt").read_text(encoding="utf-8").strip() == "First imported essay."
    assert not (workspace / "inputs" / "submissions" / "classroom_import" / "s002.txt").exists()
    metadata = json.loads((workspace / "inputs" / "class_metadata.json").read_text(encoding="utf-8"))
    manifest = json.loads((workspace / "inputs" / "classroom_import_manifest.json").read_text(encoding="utf-8"))
    assert metadata["adapter"] == "live_google"
    assert metadata["latest_sync"]["imported_count"] == 1
    assert metadata["latest_sync"]["blocker_count"] == 1
    assert metadata["latest_sync"]["external_write_performed"] is False
    assert metadata["imported_submissions"][0]["student_label"] == "Student - s001"
    assert manifest["current_import_ready"] is True
    assert manifest["files"][0]["student_id"] == "s001"


class FailingRefreshTransport:
    def post(self, url, *, data=None, params=None, timeout=20.0):
        return types.SimpleNamespace(status_code=400, json=lambda: {"error": "invalid_grant", "error_description": "Token expired."})


def test_live_google_courses_refresh_failure_requires_reconnect_before_adapter_use(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projmod, "CURRENT_PROJECT_PATH", projects_dir / "current.json")
    store = GoogleTokenStore(server_dir)
    client = TestClient(app)
    identity = attach_google_session(client, server_dir)
    project = projmod.workspace_project(identity)
    store.save_token(
        identity,
        project,
        {
            "access_token": "stale-token",
            "refresh_token": "refresh-token",
            "expires_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
            "scope": " ".join(DEFAULT_GOOGLE_SCOPES),
        },
        granted_scopes=list(DEFAULT_GOOGLE_SCOPES),
    )
    service = GoogleOAuthService(
        server_dir,
        token_store=store,
        transport=FailingRefreshTransport(),
        config={
            "client_id": "client-id",
            "client_secret": "client-secret",
            "redirect_uri": "http://127.0.0.1:8000/google/auth/callback",
        },
    )
    adapter_calls = []

    def forbidden_adapter(_token):
        adapter_calls.append(_token)
        raise AssertionError("Classroom adapter must not be built after refresh failure")

    monkeypatch.setattr(projmod, "google_oauth_service", lambda: service)
    monkeypatch.setattr(projmod, "GoogleClassroomAdapter", forbidden_adapter)
    response = client.get("/projects/classroom/google/courses")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "refresh_failed_reconnect_required"
    assert adapter_calls == []


def seed_runtime(root: Path):
    for dirname in ["scripts", "config", "prompts", "templates", "docs", "ui", "server", "outputs"]:
        (root / dirname).mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "placeholder.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "server" / "bootstrap.py").write_text("BOOTSTRAP=True\n", encoding="utf-8")
    (root / "server" / "pipeline_queue.py").write_text("PIPELINE=True\n", encoding="utf-8")
    (root / "server" / "step_runner.py").write_text("STEP=True\n", encoding="utf-8")
    (root / "prompts" / "assessor_pass1.md").write_text("prompt", encoding="utf-8")
    (root / "templates" / "assessor_pass1_template.json").write_text("{}", encoding="utf-8")
    (root / "docs" / "ASSESSOR_ROLES.md").write_text("roles", encoding="utf-8")
    (root / "ui" / "app.js").write_text("console.log('ui')", encoding="utf-8")
    exemplar = root / "inputs" / "exemplars" / "grade_6_7" / "literary_analysis"
    exemplar.mkdir(parents=True, exist_ok=True)
    (exemplar / "level_3.md").write_text("anchor", encoding="utf-8")
    for name, payload in {
        "llm_routing.json": {"mode": "openai", "tasks": {}},
        "marking_config.json": {"curve": {"profile": "default"}},
        "rubric_criteria.json": {"criteria": []},
        "accuracy_gate.json": {},
        "sota_gate.json": {},
        "grade_level_profiles.json": {},
        "calibration_set.json": {},
        "cost_limits.json": {},
        "pricing.json": {},
    }.items():
        (root / "config" / name).write_text(json.dumps(payload), encoding="utf-8")
    (root / "outputs" / "calibration_bias.json").write_text(json.dumps({"bias": 0}), encoding="utf-8")


def reset_workspace(root: Path):
    inputs = root / "inputs"
    (inputs / "submissions").mkdir(parents=True, exist_ok=True)
    for folder in ["processing", "assessments", "outputs"]:
        path = root / folder
        if path.exists():
            shutil.rmtree(path)


def test_classroom_project_inputs_reach_teacher_review_before_background_validation(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    seed_runtime(root)
    inputs = root / "inputs"
    (inputs / "rubric.md").write_text("rubric", encoding="utf-8")
    (inputs / "assignment_outline.md").write_text("outline", encoding="utf-8")
    (inputs / "submissions").mkdir(parents=True, exist_ok=True)
    import_dir = inputs / "submissions" / "classroom_import"
    import_dir.mkdir(parents=True, exist_ok=True)
    imported = import_dir / "s001.txt"
    imported.write_text("First imported essay.", encoding="utf-8")
    (inputs / "classroom_import_manifest.json").write_text(
        json.dumps(
            {
                "source": "google_classroom_read_only_sync",
                "current_import_ready": True,
                "imported_count": 1,
                "platform_error_count": 0,
                "files": [{"path": "inputs/submissions/classroom_import/s001.txt"}],
            }
        ),
        encoding="utf-8",
    )
    (inputs / "class_metadata.json").write_text(json.dumps({"source": "google_classroom_read_only_sync", "adapter": "live_google"}), encoding="utf-8")
    calls = []
    holder = {}

    def run_phased(cmd, env=None, cwd=None, **kwargs):
        script = " ".join(cmd)
        calls.append(script)
        workspace = Path(cwd)
        assert (workspace / "inputs" / "class_metadata.json").exists()
        out = workspace / "outputs"
        out.mkdir(parents=True, exist_ok=True)
        (out / "consensus_scores.csv").write_text("student_id,consensus_rank,adjusted_level,rubric_after_penalty_percent\ns1,1,4,88\n", encoding="utf-8")
        (out / "final_order.csv").write_text("student_id,final_rank,adjusted_level,rubric_after_penalty_percent\ns1,1,4,88\n", encoding="utf-8")
        (out / "grade_curve.csv").write_text("student_id,final_grade\ns1,92\n", encoding="utf-8")
        (out / "dashboard_data.json").write_text(json.dumps({"students": [{"student_id": "s1", "rank": 1}]}), encoding="utf-8")
        if "band_seam_adjudication.py" in script:
            job = holder["queue"].get_job(holder["job_id"])
            assert job["teacher_can_review"] is True
            assert job["validation_status"] == "running"
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    queue = PipelineQueue(
        root=root,
        data_dir=tmp_path / "data",
        reset_workspace_fn=reset_workspace,
        run_fn=run_phased,
        log_fn=lambda *_args, **_kwargs: None,
        api_key_fn=lambda: "key",
    )
    holder["queue"] = queue
    queue._start_worker = lambda: None
    submitted = queue.submit(
        "openai",
        inputs / "rubric.md",
        inputs / "assignment_outline.md",
        inputs / "submissions" / "classroom_import",
        [root / "config" / "llm_routing.json"],
        project_id="project-a",
    )
    holder["job_id"] = submitted["job_id"]
    queue._process_job(submitted["job_id"])
    job = queue.get_job(submitted["job_id"])
    assert job["status"] == "completed"
    assert job["teacher_can_review"] is True
    summary = json.loads((Path(job["workspace_dir"]) / "outputs" / "background_validation_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "complete"
    assert any("band_seam_adjudication.py" in call for call in calls)
