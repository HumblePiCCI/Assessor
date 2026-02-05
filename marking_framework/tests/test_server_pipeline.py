import json
import types
from pathlib import Path

from fastapi.testclient import TestClient

from server.app import app
import server.app as appmod


def test_pipeline_run_codex_success(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    appmod.API_KEY_OVERRIDE["value"] = None
    subs_dir = tmp_path / "inputs" / "submissions"
    subs_dir.mkdir(parents=True)
    (subs_dir / "old.txt").write_text("old", encoding="utf-8")
    (tmp_path / "processing").mkdir()
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(json.dumps({"tokens": {"access_token": "x"}}), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(appmod.shutil, "which", lambda _: "/usr/bin/codex")
    called = {}

    def fake_run(cmd, env=None, cwd=None, **kwargs):
        called["cmd"] = cmd
        called["env"] = env
        called["cwd"] = cwd
        out_dir = Path(cwd) / "outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "dashboard_data.json").write_text("{}", encoding="utf-8")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(appmod, "run", fake_run)
    client = TestClient(app)
    files = [
        ("rubric", ("rubric.md", b"rubric")),
        ("outline", ("outline.md", b"outline")),
        ("submissions", ("s1.txt", b"text1")),
        ("submissions", ("s2.txt", b"text2")),
    ]
    resp = client.post("/pipeline/run", data={"mode": "codex_local"}, files=files)
    assert resp.status_code == 200
    assert (tmp_path / "inputs" / "rubric.md").exists()
    assert (tmp_path / "inputs" / "assignment_outline.md").exists()
    assert (tmp_path / "inputs" / "submissions" / "s1.txt").exists()
    assert called["env"]["LLM_MODE"] == "codex_local"
    assert called["cwd"] == str(tmp_path)


def test_pipeline_run_openai_success(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    appmod.API_KEY_OVERRIDE["value"] = "test-key"
    called = {}

    def fake_run(cmd, env=None, cwd=None, **kwargs):
        called["env"] = env
        out_dir = Path(cwd) / "outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "dashboard_data.json").write_text("{}", encoding="utf-8")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(appmod, "run", fake_run)
    client = TestClient(app)
    files = [
        ("rubric", ("rubric.md", b"rubric")),
        ("outline", ("outline.md", b"outline")),
        ("submissions", ("s1.txt", b"text1")),
    ]
    resp = client.post("/pipeline/run", data={"mode": "openai"}, files=files)
    assert resp.status_code == 200
    assert called["env"]["OPENAI_API_KEY"] == "test-key"


def test_pipeline_run_openai_missing_key(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    appmod.API_KEY_OVERRIDE["value"] = None
    client = TestClient(app)
    files = [
        ("rubric", ("rubric.md", b"rubric")),
        ("outline", ("outline.md", b"outline")),
        ("submissions", ("s1.txt", b"text1")),
    ]
    resp = client.post("/pipeline/run", data={"mode": "openai"}, files=files)
    assert resp.status_code == 400


def test_pipeline_run_codex_not_connected(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(appmod.shutil, "which", lambda _: "/usr/bin/codex")
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    client = TestClient(app)
    files = [
        ("rubric", ("rubric.md", b"rubric")),
        ("outline", ("outline.md", b"outline")),
        ("submissions", ("s1.txt", b"text1")),
    ]
    resp = client.post("/pipeline/run", data={"mode": "codex_local"}, files=files)
    assert resp.status_code == 400


def test_pipeline_run_codex_not_available(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(appmod.shutil, "which", lambda _: None)
    client = TestClient(app)
    files = [
        ("rubric", ("rubric.md", b"rubric")),
        ("outline", ("outline.md", b"outline")),
        ("submissions", ("s1.txt", b"text1")),
    ]
    resp = client.post("/pipeline/run", data={"mode": "codex_local"}, files=files)
    assert resp.status_code == 400


def test_pipeline_run_invalid_mode(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    client = TestClient(app)
    files = [
        ("rubric", ("rubric.md", b"rubric")),
        ("outline", ("outline.md", b"outline")),
        ("submissions", ("s1.txt", b"text1")),
    ]
    resp = client.post("/pipeline/run", data={"mode": "weird"}, files=files)
    assert resp.status_code == 400


def test_pipeline_run_missing_submissions(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(json.dumps({"tokens": {"access_token": "x"}}), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(appmod.shutil, "which", lambda _: "/usr/bin/codex")
    client = TestClient(app)
    files = [
        ("rubric", ("rubric.md", b"rubric")),
        ("outline", ("outline.md", b"outline")),
    ]
    resp = client.post("/pipeline/run", data={"mode": "codex_local"}, files=files)
    assert resp.status_code == 400


def test_pipeline_run_failure(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(json.dumps({"tokens": {"access_token": "x"}}), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(appmod.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(appmod, "run", lambda *a, **k: types.SimpleNamespace(returncode=1, stderr="boom", stdout=""))
    client = TestClient(app)
    files = [
        ("rubric", ("rubric.md", b"rubric")),
        ("outline", ("outline.md", b"outline")),
        ("submissions", ("s1.txt", b"text1")),
    ]
    resp = client.post("/pipeline/run", data={"mode": "codex_local"}, files=files)
    assert resp.status_code == 500


def test_pipeline_run_failure_stdout_only(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(json.dumps({"tokens": {"access_token": "x"}}), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(appmod.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(appmod, "run", lambda *a, **k: types.SimpleNamespace(returncode=1, stderr="", stdout="boom"))
    client = TestClient(app)
    files = [
        ("rubric", ("rubric.md", b"rubric")),
        ("outline", ("outline.md", b"outline")),
        ("submissions", ("s1.txt", b"text1")),
    ]
    resp = client.post("/pipeline/run", data={"mode": "codex_local"}, files=files)
    assert resp.status_code == 500


def test_pipeline_run_missing_dashboard(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(json.dumps({"tokens": {"access_token": "x"}}), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(appmod.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(appmod, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stderr="", stdout=""))
    client = TestClient(app)
    files = [
        ("rubric", ("rubric.md", b"rubric")),
        ("outline", ("outline.md", b"outline")),
        ("submissions", ("s1.txt", b"text1")),
    ]
    resp = client.post("/pipeline/run", data={"mode": "codex_local"}, files=files)
    assert resp.status_code == 500


def test_pipeline_run_unhandled_exception_logs(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(json.dumps({"tokens": {"access_token": "x"}}), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(appmod.shutil, "which", lambda _: "/usr/bin/codex")

    def boom(_root):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(appmod, "reset_workspace", boom)
    client = TestClient(app)
    files = [
        ("rubric", ("rubric.md", b"rubric")),
        ("outline", ("outline.md", b"outline")),
        ("submissions", ("s1.txt", b"text1")),
    ]
    resp = client.post("/pipeline/run", data={"mode": "codex_local"}, files=files)
    assert resp.status_code == 500
    log_path = tmp_path / "logs" / "pipeline.log"
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "ERROR unhandled" in content
