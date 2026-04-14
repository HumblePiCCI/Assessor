import json

from fastapi.testclient import TestClient

from server.app import app
import server.app as appmod


class FakeQueue:
    def __init__(self):
        self.submitted = None
        self.job = None
        self.data = None
        self.events = None
        self.rubric = None
        self.confirmed = None
        self.anchor = None

    def submit(self, mode, rubric_path, outline_path, submissions_dir, extra_paths, identity=None, project_id=""):
        self.submitted = {
            "mode": mode,
            "rubric": rubric_path.name,
            "outline": outline_path.name,
            "subs": sorted(p.name for p in submissions_dir.glob("*")),
            "extra": [str(p) for p in extra_paths],
            "identity": dict(identity or {}),
            "project_id": project_id,
        }
        return {"job_id": "j1", "status": "queued", "cached": False, "snapshot_hash": "abc", "manifest_hash": "abc"}

    def get_job(self, job_id, identity=None):
        if self.job and self.job.get("id") == job_id:
            return self.job
        return None

    def load_dashboard_data(self, job_id, identity=None):
        if self.data and job_id == "j1":
            return self.data
        return None

    def get_events(self, job_id, identity=None, after=-1, limit=200):
        if job_id != "j1":
            return None
        payload = self.events or {"events": [], "next_after": after, "done": False, "status": "running"}
        payload["job_id"] = job_id
        return payload

    def rubric_status(self, job_id, identity=None):
        if job_id != "j1":
            return None
        return self.rubric or {"job_id": job_id, "status": "awaiting_rubric_confirmation", "rubric_verification": {"status": "needs_confirmation"}}

    def confirm_rubric(self, job_id, action, teacher_edits=None, identity=None):
        if job_id != "j1":
            return None
        self.confirmed = {"action": action, "teacher_edits": teacher_edits or {}, "identity": dict(identity or {})}
        return self.rubric_status(job_id, identity=identity) | {"status": "queued"}

    def anchor_status(self, job_id, identity=None):
        if job_id != "j1":
            return None
        return self.anchor or {"job_id": job_id, "status": "awaiting_anchor_scores", "anchor_packet": {"anchors": []}}

    def confirm_anchor_scores(self, job_id, teacher_scores=None, identity=None):
        if job_id != "j1":
            return None
        self.confirmed = {"teacher_scores": teacher_scores or {}, "identity": dict(identity or {})}
        return self.anchor_status(job_id, identity=identity) | {"status": "completed"}


def _files():
    return [
        ("rubric", ("rubric.md", b"rubric")),
        ("outline", ("outline.md", b"outline")),
        ("submissions", ("s1.txt", b"text1")),
    ]


def test_pipeline_v2_run_success_openai(monkeypatch):
    fake = FakeQueue()
    monkeypatch.setattr(appmod, "PIPELINE_QUEUE", fake)
    appmod.API_KEY_OVERRIDE["value"] = "test-key"
    client = TestClient(app)
    resp = client.post("/pipeline/v2/run", data={"mode": "openai"}, files=_files())
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "j1"
    assert fake.submitted["mode"] == "openai"
    assert fake.submitted["subs"] == ["s1.txt"]


def test_pipeline_v2_run_validation(monkeypatch):
    fake = FakeQueue()
    monkeypatch.setattr(appmod, "PIPELINE_QUEUE", fake)
    appmod.API_KEY_OVERRIDE["value"] = None
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = TestClient(app)
    no_subs = client.post("/pipeline/v2/run", data={"mode": "openai"}, files=[("rubric", ("r.md", b"r")), ("outline", ("o.md", b"o"))])
    assert no_subs.status_code == 400
    bad_mode = client.post("/pipeline/v2/run", data={"mode": "bad"}, files=_files())
    assert bad_mode.status_code == 400
    no_key = client.post("/pipeline/v2/run", data={"mode": "openai"}, files=_files())
    assert no_key.status_code == 400


def test_pipeline_v2_codex_validation(monkeypatch):
    fake = FakeQueue()
    monkeypatch.setattr(appmod, "PIPELINE_QUEUE", fake)
    client = TestClient(app)
    monkeypatch.setattr(appmod, "codex_status_payload", lambda: {"available": False, "connected": False})
    resp = client.post("/pipeline/v2/run", data={"mode": "codex_local"}, files=_files())
    assert resp.status_code == 400
    monkeypatch.setattr(appmod, "codex_status_payload", lambda: {"available": True, "connected": False})
    resp2 = client.post("/pipeline/v2/run", data={"mode": "codex_local"}, files=_files())
    assert resp2.status_code == 400
    monkeypatch.setattr(appmod, "codex_status_payload", lambda: {"available": True, "connected": True})
    ok = client.post("/pipeline/v2/run", data={"mode": "codex_local"}, files=_files())
    assert ok.status_code == 200


def test_pipeline_v2_status_and_data(monkeypatch):
    fake = FakeQueue()
    fake.job = {"id": "j1", "status": "running"}
    fake.data = {"students": [{"student_id": "s1"}]}
    monkeypatch.setattr(appmod, "PIPELINE_QUEUE", fake)
    client = TestClient(app)
    status = client.get("/pipeline/v2/jobs/j1")
    assert status.status_code == 200
    assert status.json()["status"] == "running"
    missing_status = client.get("/pipeline/v2/jobs/missing")
    assert missing_status.status_code == 404
    data = client.get("/pipeline/v2/jobs/j1/data")
    assert data.status_code == 200
    assert data.json()["students"][0]["student_id"] == "s1"
    fake.data = None
    no_data = client.get("/pipeline/v2/jobs/j1/data")
    assert no_data.status_code == 404


def test_pipeline_v2_events_and_progress_asset(monkeypatch):
    fake = FakeQueue()
    fake.events = {"events": [{"index": 0, "message": "ok"}], "next_after": 0, "done": True, "status": "completed"}
    monkeypatch.setattr(appmod, "PIPELINE_QUEUE", fake)
    client = TestClient(app)
    events = client.get("/pipeline/v2/jobs/j1/events?after=-1&limit=10")
    assert events.status_code == 200
    assert events.json()["events"][0]["message"] == "ok"
    missing = client.get("/pipeline/v2/jobs/missing/events")
    assert missing.status_code == 404
    asset = client.get("/progress_stream.js")
    assert asset.status_code == 200


def test_pipeline_v2_rubric_endpoints(monkeypatch):
    fake = FakeQueue()
    fake.rubric = {
        "job_id": "j1",
        "status": "awaiting_rubric_confirmation",
        "rubric_manifest": {"rubric_family": "rubric_a"},
        "rubric_verification": {"status": "needs_confirmation", "editable_projection": {"criteria": [], "levels": []}},
    }
    monkeypatch.setattr(appmod, "PIPELINE_QUEUE", fake)
    client = TestClient(app)
    status = client.get("/pipeline/v2/jobs/j1/rubric")
    assert status.status_code == 200
    assert status.json()["rubric_manifest"]["rubric_family"] == "rubric_a"
    confirm = client.post(
        "/pipeline/v2/jobs/j1/rubric",
        json={"action": "edit", "genre": "argumentative", "criteria": [{"name": "Insight", "weight": 1.0}], "levels": [{"label": "4", "band_min": 80, "band_max": 100}]},
    )
    assert confirm.status_code == 200
    assert fake.confirmed["action"] == "edit"
    assert fake.confirmed["teacher_edits"]["genre"] == "argumentative"


def test_pipeline_v2_anchor_confirm_validation(monkeypatch):
    class RaisingQueue(FakeQueue):
        def confirm_anchor_scores(self, job_id, teacher_scores=None, identity=None):
            raise ValueError("Anchor s1 mark must be between 0 and 100.")

    monkeypatch.setattr(appmod, "PIPELINE_QUEUE", RaisingQueue())
    client = TestClient(app)
    confirm = client.post(
        "/pipeline/v2/jobs/j1/anchors",
        json={"anchors": [{"student_id": "s1", "teacher_level": "4", "teacher_mark": 150}]},
    )
    assert confirm.status_code == 400
    assert "between 0 and 100" in confirm.json()["detail"]
