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
    monkeypatch.setattr(appmod.shutil, "which", lambda _: None)
    resp = client.get("/codex/status")
    assert resp.status_code == 200
    assert resp.json() == {"available": False, "connected": False}


def test_codex_status_connected(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(json.dumps({"tokens": {"access_token": "x"}}), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(appmod.shutil, "which", lambda _: "/usr/bin/codex")
    client = TestClient(app)
    resp = client.get("/codex/status")
    assert resp.status_code == 200
    assert resp.json()["available"] is True
    assert resp.json()["connected"] is True


def test_codex_status_bad_json(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(appmod.shutil, "which", lambda _: "/usr/bin/codex")
    client = TestClient(app)
    resp = client.get("/codex/status")
    assert resp.status_code == 200
    assert resp.json()["connected"] is False


def test_codex_status_missing_auth_file(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(appmod.shutil, "which", lambda _: "/usr/bin/codex")
    client = TestClient(app)
    resp = client.get("/codex/status")
    assert resp.status_code == 200
    assert resp.json()["connected"] is False


def test_codex_login_starts(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(appmod.shutil, "which", lambda _: "/usr/bin/codex")
    started = {}

    def fake_popen(cmd, stdout=None, stderr=None):
        started["cmd"] = cmd
        return types.SimpleNamespace()

    monkeypatch.setattr(appmod, "Popen", fake_popen)
    resp = client.post("/codex/login")
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    assert started["cmd"][0] == "codex"
    assert started["cmd"][1] == "login"


def test_codex_login_missing(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(appmod.shutil, "which", lambda _: None)
    resp = client.post("/codex/login")
    assert resp.status_code == 400


def test_ui_routes(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    (ui_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (ui_dir / "app.js").write_text("console.log('hi')", encoding="utf-8")
    (ui_dir / "style.css").write_text("body {}", encoding="utf-8")
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(appmod, "UI_DIR", ui_dir)
    monkeypatch.setattr(appmod, "DATA_JSON_PATH", tmp_path / "outputs" / "dashboard_data.json")
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    resp_js = client.get("/app.js")
    assert resp_js.status_code == 200
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
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "rubric.md").write_text("rubric", encoding="utf-8")
    save_resp = client.post("/projects/save", json={"name": "Class A"})
    assert save_resp.status_code == 200
    project_id = save_resp.json()["id"]
    save_resp2 = client.post("/projects/save", json={"project_id": project_id, "name": "Class A"})
    assert save_resp2.status_code == 200
    list_resp = client.get("/projects")
    assert list_resp.json()["current"]["id"] == project_id
    new_resp = client.post("/projects/new", json={"name": "New Project"})
    assert new_resp.status_code == 200
    assert not (tmp_path / "inputs" / "rubric.md").exists()
    clear_file = tmp_path / "outputs"
    clear_file.mkdir()
    (clear_file / "x.txt").write_text("x", encoding="utf-8")
    clear_resp = client.post("/projects/clear")
    assert clear_resp.json()["status"] == "cleared"
    assert not (tmp_path / "outputs").exists()
    proj_dir = projects_dir / project_id
    (proj_dir / "outputs").mkdir(parents=True)
    (proj_dir / "outputs" / "y.txt").write_text("y", encoding="utf-8")
    load_resp = client.post("/projects/load", json={"project_id": project_id})
    assert load_resp.status_code == 200
    assert (tmp_path / "outputs" / "y.txt").exists()
    current_path.write_text(json.dumps({"id": project_id}), encoding="utf-8")
    del_resp = client.delete(f"/projects/{project_id}")
    assert del_resp.status_code == 200
    assert not proj_dir.exists()


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
    asyncio.run(projmod.projects_delete(project_id))
    assert current_path.exists()
    asyncio.run(projmod.projects_delete(other_id))
    assert not current_path.exists()
