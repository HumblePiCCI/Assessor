import hashlib

from fastapi.testclient import TestClient

from server.app import app
import server.app as appmod
import server.google_session as google_session


def attach_google_session(client: TestClient, base_dir, email="teacher@example.com"):
    clean = email.strip().lower()
    session_id, identity = google_session.create_session(
        base_dir,
        {
            "teacher_display_email": clean,
            "teacher_identity_hash": hashlib.sha256(clean.encode("utf-8")).hexdigest()[:24],
        },
    )
    client.cookies.set(google_session.COOKIE_NAME, session_id)
    return identity


def signed_client(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    client = TestClient(app)
    attach_google_session(client, server_dir)
    return client


class FakeQueue:
    def __init__(self):
        self.calls = []

    def submit(self, mode, rubric_path, outline_path, submissions_dir, extra_paths, identity=None, project_id=""):
        payload = {
            "mode": mode,
            "rubric": rubric_path.name,
            "outline": outline_path.name,
            "subs": sorted(item.name for item in submissions_dir.glob("*") if item.is_file()),
            "extra": [str(path) for path in extra_paths],
            "identity": dict(identity or {}),
            "project_id": project_id,
        }
        self.calls.append(payload)
        return {
            "job_id": f"job-{len(self.calls)}",
            "status": "queued",
            "cached": False,
            "snapshot_hash": "abc123",
            "manifest_hash": "abc123",
        }


def _files():
    return [
        ("rubric", ("rubric.md", b"rubric")),
        ("outline", ("outline.md", b"outline")),
        ("submissions", ("s1.txt", b"text1")),
        ("submissions", ("s2.txt", b"text2")),
    ]


def test_pipeline_run_and_v2_delegate_to_same_queue(tmp_path, monkeypatch):
    fake = FakeQueue()
    monkeypatch.setattr(appmod, "PIPELINE_QUEUE", fake)
    appmod.API_KEY_OVERRIDE["value"] = "test-key"
    client = signed_client(tmp_path, monkeypatch)
    direct = client.post("/pipeline/run", data={"mode": "openai"}, files=_files())
    queued = client.post("/pipeline/v2/run", data={"mode": "openai"}, files=_files())
    assert direct.status_code == 200
    assert queued.status_code == 200
    assert direct.json()["status"] == "queued"
    assert queued.json()["status"] == "queued"
    assert direct.json()["snapshot_hash"] == queued.json()["snapshot_hash"]
    assert len(fake.calls) == 2
    assert fake.calls[0] == fake.calls[1]
    assert fake.calls[0]["mode"] == "openai"
    assert fake.calls[0]["subs"] == ["s1.txt", "s2.txt"]
    assert fake.calls[0]["project_id"] == ""
    assert any(path.endswith("config/accuracy_gate.json") for path in fake.calls[0]["extra"])
    assert any(path.endswith("config/sota_gate.json") for path in fake.calls[0]["extra"])


def test_pipeline_run_openai_validation(monkeypatch):
    fake = FakeQueue()
    monkeypatch.setattr(appmod, "PIPELINE_QUEUE", fake)
    appmod.API_KEY_OVERRIDE["value"] = None
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = TestClient(app)
    no_subs = client.post("/pipeline/run", data={"mode": "openai"}, files=[("rubric", ("r.md", b"r")), ("outline", ("o.md", b"o"))])
    assert no_subs.status_code == 400
    bad_mode = client.post("/pipeline/run", data={"mode": "bad"}, files=_files())
    assert bad_mode.status_code == 400
    no_key = client.post("/pipeline/run", data={"mode": "openai"}, files=_files())
    assert no_key.status_code == 400
    assert fake.calls == []


def test_pipeline_run_codex_validation(tmp_path, monkeypatch):
    fake = FakeQueue()
    monkeypatch.setattr(appmod, "PIPELINE_QUEUE", fake)
    client = signed_client(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod, "codex_status_payload", lambda: {"available": False, "connected": False})
    resp = client.post("/pipeline/run", data={"mode": "codex_local"}, files=_files())
    assert resp.status_code == 400
    monkeypatch.setattr(appmod, "codex_status_payload", lambda: {"available": True, "connected": False})
    resp2 = client.post("/pipeline/run", data={"mode": "codex_local"}, files=_files())
    assert resp2.status_code == 400
    monkeypatch.setattr(appmod, "codex_status_payload", lambda: {"available": True, "connected": True})
    ok = client.post("/pipeline/run", data={"mode": "codex_local"}, files=_files())
    assert ok.status_code == 200
    assert fake.calls[-1]["mode"] == "codex_local"
