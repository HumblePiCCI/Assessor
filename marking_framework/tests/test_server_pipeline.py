from fastapi.testclient import TestClient

from server.app import app
import server.app as appmod


class FakeQueue:
    def __init__(self):
        self.calls = []

    def submit(self, mode, rubric_path, outline_path, submissions_dir, extra_paths):
        payload = {
            "mode": mode,
            "rubric": rubric_path.name,
            "outline": outline_path.name,
            "subs": sorted(item.name for item in submissions_dir.glob("*") if item.is_file()),
            "extra": [str(path) for path in extra_paths],
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


def test_pipeline_run_and_v2_delegate_to_same_queue(monkeypatch):
    fake = FakeQueue()
    monkeypatch.setattr(appmod, "PIPELINE_QUEUE", fake)
    appmod.API_KEY_OVERRIDE["value"] = "test-key"
    client = TestClient(app)
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


def test_pipeline_run_codex_validation(monkeypatch):
    fake = FakeQueue()
    monkeypatch.setattr(appmod, "PIPELINE_QUEUE", fake)
    client = TestClient(app)
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
