import asyncio
import io
import json
import shutil
import types
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from server.app import app
import server.app as appmod
import server.classroom as classroommod
import server.projects as projmod


def make_zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("s1.txt", "hello")
    buf.seek(0)
    return buf


def test_create_job_success(tmp_path, monkeypatch):
    # Redirect DATA_DIR to temp
    appmod.DATA_DIR = tmp_path / "data"
    appmod.DATA_DIR.mkdir(parents=True, exist_ok=True)
    appmod.API_KEY_OVERRIDE["value"] = "test-key"

    def fake_run(cmd, env=None):
        # Create expected outputs directory
        if "--workdir" in cmd:
            idx = cmd.index("--workdir") + 1
            workdir = Path(cmd[idx])
            out_dir = workdir / "outputs"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "dummy.txt").write_text("ok", encoding="utf-8")
        return types.SimpleNamespace(returncode=0)

    fake_run(["--workdir", str(tmp_path / "job")])
    fake_run(["echo"])
    monkeypatch.setattr(appmod, "run", fake_run)

    client = TestClient(app)
    files = {
        "rubric": ("rubric.md", b"rubric"),
        "outline": ("outline.md", b"outline"),
        "submissions_zip": ("subs.zip", make_zip_bytes().read(), "application/zip"),
    }
    resp = client.post("/jobs", files=files)
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    out_resp = client.get(f"/jobs/{job_id}/outputs")
    assert out_resp.status_code == 200


def test_create_job_failure(tmp_path, monkeypatch):
    appmod.DATA_DIR = tmp_path / "data"
    appmod.DATA_DIR.mkdir(parents=True, exist_ok=True)
    appmod.API_KEY_OVERRIDE["value"] = "test-key"

    def fail_run(cmd, env=None):
        return types.SimpleNamespace(returncode=1)

    monkeypatch.setattr(appmod, "run", fail_run)
    client = TestClient(app)
    files = {
        "rubric": ("rubric.md", b"rubric"),
        "outline": ("outline.md", b"outline"),
        "submissions_zip": ("subs.zip", make_zip_bytes().read(), "application/zip"),
    }
    resp = client.post("/jobs", files=files)
    assert resp.status_code == 500


def test_get_outputs_missing(tmp_path):
    appmod.DATA_DIR = tmp_path / "data"
    appmod.DATA_DIR.mkdir(parents=True, exist_ok=True)
    appmod.API_KEY_OVERRIDE["value"] = "test-key"
    client = TestClient(app)
    resp = client.get("/jobs/missing/outputs")
    assert resp.status_code == 404


def test_create_job_missing_outputs(tmp_path, monkeypatch):
    appmod.DATA_DIR = tmp_path / "data"
    appmod.DATA_DIR.mkdir(parents=True, exist_ok=True)
    appmod.API_KEY_OVERRIDE["value"] = "test-key"

    def fake_run(cmd, env=None):
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(appmod, "run", fake_run)
    client = TestClient(app)
    files = {
        "rubric": ("rubric.md", b"rubric"),
        "outline": ("outline.md", b"outline"),
        "submissions_zip": ("subs.zip", make_zip_bytes().read(), "application/zip"),
    }
    resp = client.post("/jobs", files=files)
    assert resp.status_code == 500


def test_auth_status_and_set(monkeypatch):
    client = TestClient(app)
    appmod.API_KEY_OVERRIDE["value"] = None
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    resp = client.get("/auth/status")
    assert resp.status_code == 200
    assert resp.json()["connected"] is False

    bad = client.post("/auth", json={"api_key": "short"})
    assert bad.status_code == 400

    good = client.post("/auth", json={"api_key": "test-key-12345"})
    assert good.status_code == 200
    resp2 = client.get("/auth/status")
    assert resp2.json()["connected"] is True


def test_validate_pipeline_mode_accepts_provider_generic_api_alias(monkeypatch):
    appmod.API_KEY_OVERRIDE["value"] = None
    monkeypatch.setenv("LLM_API_KEY", "generic-key")
    assert appmod.validate_pipeline_mode("api") == "openai"
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    try:
        appmod.validate_pipeline_mode("api")
    except Exception as exc:
        assert "API" in str(exc.detail) or "key not configured" in str(exc.detail)
        assert "OpenAI API key not configured" not in str(exc.detail)
    else:
        raise AssertionError("missing provider key should fail")


def test_validate_pipeline_mode_codex_local_does_not_require_api_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(appmod, "codex_status_payload", lambda: {"available": True, "connected": True})
    assert appmod.validate_pipeline_mode("codex_local") == "codex_local"


def test_reset_workspace_preserves_exemplars_and_clears_inputs(tmp_path):
    root = tmp_path
    exemplars = root / "inputs" / "exemplars"
    exemplars.mkdir(parents=True)
    (exemplars / "level_3.md").write_text("X", encoding="utf-8")
    (root / "inputs" / "rubric.md").write_text("rubric", encoding="utf-8")
    extra_dir = root / "inputs" / "tmpdir"
    extra_dir.mkdir(parents=True)
    (extra_dir / "x.txt").write_text("x", encoding="utf-8")
    subs = root / "inputs" / "submissions"
    subs.mkdir(parents=True)
    (subs / "keep.docx").write_text("y", encoding="utf-8")
    out_dir = root / "outputs"
    out_dir.mkdir()
    (out_dir / "o.txt").write_text("o", encoding="utf-8")

    appmod.reset_workspace(root)

    assert (exemplars / "level_3.md").exists()
    assert not (root / "inputs" / "rubric.md").exists()
    assert not extra_dir.exists()
    assert subs.exists()
    assert not any(subs.iterdir())
    assert not out_dir.exists()


def test_create_job_missing_key(tmp_path, monkeypatch):
    appmod.DATA_DIR = tmp_path / "data"
    appmod.DATA_DIR.mkdir(parents=True, exist_ok=True)
    appmod.API_KEY_OVERRIDE["value"] = None
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = TestClient(app)
    files = {
        "rubric": ("rubric.md", b"rubric"),
        "outline": ("outline.md", b"outline"),
        "submissions_zip": ("subs.zip", make_zip_bytes().read(), "application/zip"),
    }
    resp = client.post("/jobs", files=files)
    assert resp.status_code == 400


def test_codex_status_unavailable(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(appmod, "codex_status_payload", lambda: {"available": False, "connected": False, "reason": "Codex CLI not found"})
    resp = client.get("/codex/status")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["available"] is False
    assert payload["connected"] is False
    assert payload["reason"] == "Codex CLI not found"


def test_codex_status_oauth_exec_ready(monkeypatch):
    monkeypatch.setattr(
        appmod,
        "codex_status_payload",
        lambda: {
            "available": True,
            "connected": True,
            "auth_source": "codex_oauth",
            "oauth_tokens_present": True,
            "oauth_supported": True,
            "runtime_kind": "exec",
            "runtime_path": "/Applications/Codex.app/Contents/Resources/codex",
            "reason": "Codex OAuth runtime ready",
        },
    )
    client = TestClient(app)
    resp = client.get("/codex/status")
    assert resp.status_code == 200
    assert resp.json()["available"] is True
    assert resp.json()["connected"] is True
    assert resp.json()["auth_source"] == "codex_oauth"
    assert resp.json()["oauth_tokens_present"] is True
    assert resp.json()["runtime_kind"] == "exec"


def test_codex_status_connected_with_api_key(monkeypatch):
    monkeypatch.setattr(
        appmod,
        "codex_status_payload",
        lambda: {"available": True, "connected": True, "auth_source": "auth_file_api_key", "reason": "Codex CLI ready"},
    )
    client = TestClient(app)
    resp = client.get("/codex/status")
    assert resp.status_code == 200
    assert resp.json()["connected"] is True
    assert resp.json()["auth_source"] == "auth_file_api_key"


def test_codex_status_bad_json(monkeypatch):
    monkeypatch.setattr(appmod, "codex_status_payload", lambda: {"available": True, "connected": False, "reason": "Invalid Codex auth file"})
    client = TestClient(app)
    resp = client.get("/codex/status")
    assert resp.status_code == 200
    assert resp.json()["connected"] is False


def test_codex_status_missing_auth_file(monkeypatch):
    monkeypatch.setattr(appmod, "codex_status_payload", lambda: {"available": True, "connected": False, "reason": "Codex not connected"})
    client = TestClient(app)
    resp = client.get("/codex/status")
    assert resp.status_code == 200
    assert resp.json()["connected"] is False


def test_codex_login_starts(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(appmod.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(appmod, "codex_status_payload", lambda: {"available": True, "connected": False})
    monkeypatch.setattr(appmod, "codex_login_supported", lambda: True)
    started = {}

    def fake_popen(cmd, stdout=None, stderr=None):
        started["cmd"] = cmd
        return types.SimpleNamespace()

    monkeypatch.setattr(appmod, "Popen", fake_popen)
    resp = client.post("/codex/login")
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    assert started["cmd"][0] == "/usr/bin/codex"
    assert started["cmd"][1] == "login"


def test_codex_login_missing(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(appmod.shutil, "which", lambda _: None)
    monkeypatch.setattr(appmod, "codex_status_payload", lambda: {"available": False, "connected": False})
    resp = client.post("/codex/login")
    assert resp.status_code == 400


def test_codex_login_unsupported(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(appmod.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(appmod, "codex_status_payload", lambda: {"available": True, "connected": False})
    monkeypatch.setattr(appmod, "codex_login_supported", lambda: False)
    resp = client.post("/codex/login")
    assert resp.status_code == 400


def test_codex_login_already_connected(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(appmod.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(appmod, "codex_status_payload", lambda: {"available": True, "connected": True})
    monkeypatch.setattr(appmod, "codex_login_supported", lambda: False)
    resp = client.post("/codex/login")
    assert resp.status_code == 200
    assert resp.json()["status"] == "already_connected"


def test_ui_routes(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    (ui_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (ui_dir / "app.js").write_text("console.log('hi')", encoding="utf-8")
    (ui_dir / "grade_adjust.js").write_text("window.gradeAdjust={};", encoding="utf-8")
    (ui_dir / "feedback_generate.js").write_text("window.feedbackGenerate={};", encoding="utf-8")
    (ui_dir / "style.css").write_text("body {}", encoding="utf-8")
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(appmod, "UI_DIR", ui_dir)
    monkeypatch.setattr(appmod, "DATA_JSON_PATH", tmp_path / "outputs" / "dashboard_data.json")
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    resp_js = client.get("/app.js")
    assert resp_js.status_code == 200
    resp_grade = client.get("/grade_adjust.js")
    assert resp_grade.status_code == 200
    resp_feedback = client.get("/feedback_generate.js")
    assert resp_feedback.status_code == 200
    resp_css = client.get("/style.css")
    assert resp_css.status_code == 200
    data_resp = client.get("/data.json")
    assert data_resp.status_code == 200
    assert data_resp.json() == {"students": []}
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()
    data_path = out_dir / "dashboard_data.json"
    data_path.write_text(json.dumps({"students": [{"student_id": "s1"}]}), encoding="utf-8")
    data_resp2 = client.get("/data.json")
    assert data_resp2.json()["students"][0]["student_id"] == "s1"
    (ui_dir / "app.js").unlink()
    resp_missing = client.get("/app.js")
    assert resp_missing.status_code == 404


def test_data_json_hydrates_numeric_classroom_labels(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projmod, "CURRENT_PROJECT_PATH", projects_dir / "current.json")
    project = {"id": "project-a", "name": "Project A", "scope_key": "project-a"}
    projmod.CURRENT_PROJECT_PATH.write_text(json.dumps(project), encoding="utf-8")
    workspace = projmod.workspace_root(None)
    outputs = workspace / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    raw_google_user_id = "123456789012345678901"
    (outputs / "dashboard_data.json").write_text(
        json.dumps(
            {
                "students": [
                    {
                        "student_id": "s014",
                        "display_name": raw_google_user_id,
                        "source_file": f"{raw_google_user_id}.txt",
                    }
                ],
                "class_metadata": {"source": "google_classroom_read_only_sync"},
            }
        ),
        encoding="utf-8",
    )
    state_dir = server_dir / "data" / "classroom" / "project-a"
    state_dir.mkdir(parents=True)
    classroommod.write_json(
        state_dir / "classroom_state.json",
        {
            "classroom_link": {"course_id": "course-1", "coursework_id": "cw-1"},
            "submissions": {
                "sub-1": {
                    "submission_id": "sub-1",
                    "student_id": raw_google_user_id,
                    "display_name": "Alice Example",
                }
            },
        },
    )

    response = TestClient(app).get("/data.json")

    assert response.status_code == 200
    student = response.json()["students"][0]
    assert student["display_name"] == "Alice - s014"
    assert student["student_label"] == "Alice - s014"
    assert "Example" not in json.dumps(response.json())
    assert raw_google_user_id not in student["display_name"]


def test_projects_endpoints(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    current_path = projects_dir / "current.json"
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projmod, "CURRENT_PROJECT_PATH", current_path)
    client = TestClient(app)
    (projects_dir / "empty").mkdir()
    resp = client.get("/projects")
    assert resp.json() == {"current": None, "projects": []}
    workspace = projmod.workspace_root(None)
    (workspace / "inputs").mkdir(parents=True)
    (workspace / "inputs" / "exemplars").mkdir()
    (workspace / "inputs" / "exemplars" / "level_3.md").write_text("X", encoding="utf-8")
    (workspace / "inputs" / "rubric.md").write_text("rubric", encoding="utf-8")
    save_resp = client.post("/projects/save", json={"name": "Class A", "aggregate_learning_mode": "opt_in", "aggregate_retention_days": 90})
    assert save_resp.status_code == 200
    project_id = save_resp.json()["id"]
    assert save_resp.json()["aggregate_learning"]["mode"] == "opt_in"
    assert not (projects_dir / project_id / "inputs" / "exemplars").exists()
    save_resp2 = client.post("/projects/save", json={"project_id": project_id, "name": "Class A"})
    assert save_resp2.status_code == 200
    list_resp = client.get("/projects")
    assert list_resp.json()["current"]["id"] == project_id
    (workspace / "outputs").mkdir(parents=True)
    (workspace / "outputs" / "latest-pass.txt").write_text("latest", encoding="utf-8")
    new_resp = client.post("/projects/new", json={"name": "New Project"})
    assert new_resp.status_code == 200
    assert (projects_dir / project_id / "outputs" / "latest-pass.txt").read_text(encoding="utf-8") == "latest"
    assert not (workspace / "inputs" / "rubric.md").exists()
    assert (workspace / "inputs" / "exemplars" / "level_3.md").exists()
    clear_file = workspace / "outputs"
    clear_file.mkdir()
    (clear_file / "x.txt").write_text("x", encoding="utf-8")
    current_path.write_text(json.dumps({"id": project_id, "name": "Class A"}), encoding="utf-8")
    clear_resp = client.post("/projects/clear")
    assert clear_resp.json()["status"] == "cleared"
    assert clear_resp.json()["current"] is None
    assert not (workspace / "outputs").exists()
    assert not current_path.exists()
    assert (workspace / "inputs" / "exemplars" / "level_3.md").exists()
    proj_dir = projects_dir / project_id
    (proj_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (proj_dir / "outputs" / "y.txt").write_text("y", encoding="utf-8")
    load_resp = client.post("/projects/load", json={"project_id": project_id})
    assert load_resp.status_code == 200
    assert (workspace / "outputs" / "y.txt").exists()
    current_path.write_text(json.dumps({"id": project_id}), encoding="utf-8")
    del_resp = client.delete(f"/projects/{project_id}")
    assert del_resp.status_code == 200
    assert not proj_dir.exists()


def test_projects_review_endpoints(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    current_path = projects_dir / "current.json"
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projmod, "CURRENT_PROJECT_PATH", current_path)
    workspace = projmod.workspace_root(None)
    outputs = workspace / "outputs"
    outputs.mkdir()
    (workspace / "pipeline_manifest.json").write_text(json.dumps({"manifest_hash": "manifest-1"}), encoding="utf-8")
    (outputs / "calibration_manifest.json").write_text(json.dumps({"model_version": "gpt-5.4"}), encoding="utf-8")
    (outputs / "dashboard_data.json").write_text(
        json.dumps(
            {
                "students": [
                    {
                        "student_id": "s1",
                        "display_name": "Student One",
                        "source_file": "student_one.txt",
                        "level_with_modifier": "3",
                        "rank": 2,
                        "uncertainty_flags": ["boundary_case"],
                    },
                    {
                        "student_id": "s2",
                        "display_name": "Student Two",
                        "source_file": "student_two.txt",
                        "level_with_modifier": "4",
                        "rank": 1,
                        "uncertainty_flags": ["high_disagreement"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(app)
    save_resp = client.post("/projects/save", json={"name": "Class A", "aggregate_learning_mode": "opt_in", "aggregate_retention_days": 120})
    assert save_resp.status_code == 200
    project_id = save_resp.json()["id"]
    review_resp = client.post(
        "/projects/review",
        json={
            "action": "draft",
            "students": [
                {
                    "student_id": "s1",
                    "level_override": "4",
                    "desired_rank": 1,
                    "evidence_quality": "thin",
                    "evidence_comment": "Student One needs clearer evidence.",
                }
            ],
            "pairwise": [
                {
                    "student_id": "s1",
                    "other_student_id": "s2",
                    "preferred_student_id": "s1",
                    "confidence": "high",
                    "rationale": "Student One should be above Student Two.",
                }
            ],
            "curve_top": 96,
            "curve_bottom": 64,
            "assigned_marks": [
                {"student_id": "s2", "mark": 96},
                {"student_id": "s1", "mark": 88},
            ],
            "feedback_drafts": [
                {"student_id": "s1", "star1": "Clear claim.", "star2": "Uses detail.", "wish": "Tighten conclusion."},
            ],
        },
    )
    assert review_resp.status_code == 200
    payload = review_resp.json()
    assert payload["scope_id"] == project_id
    assert payload["draft_review"]["students"][0]["level_override"] == "4"
    assert payload["draft_review"]["curve_top"] == 96.0
    assert payload["draft_review"]["assigned_marks"][0]["mark"] == 96.0
    assert payload["latest_review"]["students"] == []
    assert payload["aggregate_learning"]["mode"] == "opt_in"
    get_resp = client.get("/projects/review")
    assert get_resp.status_code == 200
    assert get_resp.json()["draft_review"]["review_state"] == "draft"
    assert get_resp.json()["local_learning_profile"]["student_review_count"] == 0
    finalize_resp = client.post(
        "/projects/review",
        json={
            "action": "finalize",
            "students": [
                {
                    "student_id": "s1",
                    "level_override": "4",
                    "desired_rank": 1,
                    "evidence_quality": "thin",
                    "evidence_comment": "Student One needs clearer evidence.",
                }
            ],
            "pairwise": [
                {
                    "student_id": "s1",
                    "other_student_id": "s2",
                    "preferred_student_id": "s1",
                    "confidence": "high",
                    "rationale": "Student One should be above Student Two.",
                }
            ],
            "curve_top": 96,
            "curve_bottom": 64,
            "assigned_marks": [
                {"student_id": "s2", "mark": 96},
                {"student_id": "s1", "mark": 88},
            ],
            "feedback_drafts": [
                {"student_id": "s1", "star1": "Clear claim.", "star2": "Uses detail.", "wish": "Tighten conclusion."},
            ],
        },
    )
    assert finalize_resp.status_code == 200
    finalize_payload = finalize_resp.json()
    assert finalize_payload["latest_review"]["students"][0]["level_override"] == "4"
    assert finalize_payload["latest_review"]["curve_bottom"] == 64.0
    assert finalize_payload["latest_review"]["feedback_drafts"][0]["wish"] == "Tighten conclusion."
    assert finalize_payload["replay_exports"]["benchmark_gold_count"] == 2
    assert finalize_payload["latest_delta"]["summary"]["rank_movement_count"] >= 1
    assert finalize_payload["aggregate_learning"]["scope_record_count"] == 1
    list_resp = client.get("/projects")
    assert list_resp.json()["current"]["review_summary"]["student_review_count"] == 1
    assert list_resp.json()["current"]["review_summary"]["aggregate_record_count"] == 1


def test_projects_load_errors(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    current_path = projects_dir / "current.json"
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projmod, "CURRENT_PROJECT_PATH", current_path)
    client = TestClient(app)
    resp_missing = client.post("/projects/load", json={})
    assert resp_missing.status_code == 400
    resp_not_found = client.post("/projects/load", json={"project_id": "nope"})
    assert resp_not_found.status_code == 404
    resp_delete = client.delete("/projects/nope")
    assert resp_delete.status_code == 404


def test_projects_delete_clears_current(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    current_path = projects_dir / "current.json"
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projmod, "CURRENT_PROJECT_PATH", current_path)
    project_id = "p1"
    other_id = "p2"
    for pid, label in [(project_id, "P"), (other_id, "O")]:
        proj_dir = projects_dir / pid
        proj_dir.mkdir()
        (proj_dir / "project.json").write_text(json.dumps({"id": pid, "name": label}), encoding="utf-8")
    projmod.set_current_project({"id": project_id, "name": "P"})
    assert current_path.exists()
    projmod.set_current_project(None)
    assert not current_path.exists()
    projmod.set_current_project(None)
    assert not current_path.exists()
    projmod.set_current_project({"id": other_id, "name": "O"})
    request = types.SimpleNamespace(headers={})
    asyncio.run(projmod.projects_delete(project_id, request))
    assert current_path.exists()
    asyncio.run(projmod.projects_delete(other_id, request))
    assert not current_path.exists()


def test_clear_workspace_inputs_missing(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    projmod.clear_workspace(root)
    assert (root / "inputs" / "submissions").exists()


def test_save_project_snapshot_skips_inputs_when_missing(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    current_path = projects_dir / "current.json"
    monkeypatch.setattr(projmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projmod, "CURRENT_PROJECT_PATH", current_path)
    root = tmp_path / "workspace"
    root.mkdir()
    meta = projmod.save_project_snapshot(root, "pid", "Name", include_logs=False)
    assert meta["id"] == "pid"


def test_projects_save_promotes_unsaved_workspace_review_and_classroom_scopes(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    current_path = projects_dir / "current.json"
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projmod, "CURRENT_PROJECT_PATH", current_path)
    client = TestClient(app)
    workspace = projmod.workspace_root(None)
    (workspace / "outputs").mkdir(parents=True)
    (workspace / "outputs" / "dashboard_data.json").write_text(json.dumps({"students": [{"student_id": "s1"}]}), encoding="utf-8")
    review_path = server_dir / "data" / "reviews" / "workspace" / "draft_review.json"
    review_path.parent.mkdir(parents=True)
    review_path.write_text(json.dumps({"review_state": "draft", "students": [{"student_id": "s1"}]}), encoding="utf-8")
    classroom_path = server_dir / "data" / "classroom" / "workspace" / "classroom_state.json"
    classroom_path.parent.mkdir(parents=True)
    classroom_path.write_text(json.dumps({"scope_id": "workspace", "classroom_link": {"course_id_hash": "abc"}}), encoding="utf-8")

    save_resp = client.post("/projects/save", json={"name": "Saved Workspace"})
    assert save_resp.status_code == 200
    project_id = save_resp.json()["id"]
    assert (projects_dir / project_id / "outputs" / "dashboard_data.json").exists()
    assert (server_dir / "data" / "reviews" / project_id / "draft_review.json").exists()
    assert (server_dir / "data" / "classroom" / project_id / "classroom_state.json").exists()


def test_strict_auth_requires_identity_and_uses_scoped_workspace(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "BASE_DIR", server_dir)
    monkeypatch.setenv("MARKING_RUNTIME_MODE", "production")
    monkeypatch.delenv("MARKING_STRICT_AUTH", raising=False)
    client = TestClient(app)

    unauthorized = client.get("/auth/context")
    assert unauthorized.status_code == 401

    headers = {"x-tenant-id": "tenant-a", "x-teacher-id": "teacher-a", "x-teacher-role": "teacher"}
    context = client.get("/auth/context", headers=headers)
    assert context.status_code == 200
    assert context.json()["strict_auth"] is True

    identity = appmod.request_identity(types.SimpleNamespace(headers=headers))
    data_root = projmod.workspace_root(identity)
    (data_root / "outputs").mkdir(parents=True, exist_ok=True)
    (data_root / "outputs" / "dashboard_data.json").write_text(json.dumps({"students": [{"student_id": "s1"}]}), encoding="utf-8")

    data_resp = client.get("/data.json", headers=headers)
    assert data_resp.status_code == 200
    assert data_resp.json()["students"][0]["student_id"] == "s1"

    blocked = client.post(
        "/jobs",
        headers=headers,
        files={
            "rubric": ("rubric.md", b"rubric"),
            "outline": ("outline.md", b"outline"),
            "submissions_zip": ("subs.zip", make_zip_bytes().read(), "application/zip"),
        },
    )
    assert blocked.status_code == 403


def test_strict_project_visibility_and_ops_admin_gate(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "PROJECTS_DIR", projects_dir)
    monkeypatch.setenv("MARKING_RUNTIME_MODE", "production")
    monkeypatch.delenv("MARKING_STRICT_AUTH", raising=False)

    class OpsQueue:
        def ops_summary(self, identity=None):
            return {"queue_depth": 0, "identity": identity}

        def prune_retention(self, dry_run=True):
            return {"dry_run": dry_run}

    monkeypatch.setattr(appmod, "PIPELINE_QUEUE", OpsQueue())
    client = TestClient(app)
    teacher_headers = {"x-tenant-id": "tenant-a", "x-teacher-id": "teacher-a", "x-teacher-role": "teacher"}
    other_headers = {"x-tenant-id": "tenant-a", "x-teacher-id": "teacher-b", "x-teacher-role": "teacher"}
    admin_headers = {"x-tenant-id": "tenant-a", "x-teacher-id": "admin-a", "x-teacher-role": "admin"}

    save_resp = client.post("/projects/save", headers=teacher_headers, json={"name": "Strict Class"})
    assert save_resp.status_code == 200
    project_id = save_resp.json()["id"]

    teacher_list = client.get("/projects", headers=teacher_headers)
    assert len(teacher_list.json()["projects"]) == 1

    other_list = client.get("/projects", headers=other_headers)
    assert other_list.status_code == 200
    assert other_list.json()["projects"] == []

    admin_list = client.get("/projects", headers=admin_headers)
    assert len(admin_list.json()["projects"]) == 1

    denied = client.post("/projects/load", headers=other_headers, json={"project_id": project_id})
    assert denied.status_code == 403

    teacher_ops = client.get("/pipeline/v2/ops/status", headers=teacher_headers)
    assert teacher_ops.status_code == 403
    admin_ops = client.get("/pipeline/v2/ops/status", headers=admin_headers)
    assert admin_ops.status_code == 200
    assert admin_ops.json()["queue_depth"] == 0
