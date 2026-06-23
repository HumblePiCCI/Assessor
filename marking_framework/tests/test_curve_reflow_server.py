import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server.app as appmod
import server.projects as projmod
import server.review_store as rs
from server.app import app


def write_workspace(root: Path):
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (root / "pipeline_manifest.json").write_text(json.dumps({"manifest_hash": "manifest-1"}), encoding="utf-8")
    (outputs / "calibration_manifest.json").write_text(json.dumps({"model_version": "gpt-5.4"}), encoding="utf-8")
    students = [
        {"student_id": "s1", "display_name": "One", "rank": 1, "final_grade": 91, "adjusted_level": "4"},
        {"student_id": "s2", "display_name": "Two", "rank": 2, "final_grade": 86, "adjusted_level": "4"},
        {"student_id": "s3", "display_name": "Three", "rank": 3, "final_grade": 78, "adjusted_level": "3"},
        {"student_id": "s4", "display_name": "Four", "rank": 4, "final_grade": 72, "adjusted_level": "3"},
        {"student_id": "s5", "display_name": "Five", "rank": 5, "final_grade": 63, "adjusted_level": "2"},
    ]
    (outputs / "dashboard_data.json").write_text(json.dumps({"students": students}), encoding="utf-8")
    (outputs / "final_order.csv").write_text(
        "student_id,final_rank\n" + "".join(f"s{i},{i}\n" for i in range(1, 6)), encoding="utf-8"
    )
    (outputs / "grade_curve.csv").write_text(
        "student_id,final_grade\ns1,91\ns2,86\ns3,78\ns4,72\ns5,63\n", encoding="utf-8"
    )


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projmod, "CURRENT_PROJECT_PATH", projects_dir / "current.json")
    write_workspace(tmp_path)
    return tmp_path


def test_save_with_pins_recomputes_assigned_marks_server_side(tmp_path):
    base_dir = tmp_path / "server"
    base_dir.mkdir()
    write_workspace(tmp_path)
    project = {"id": "project-a", "name": "Project A"}
    bundle = rs.save_review_bundle(
        base_dir=base_dir,
        root=tmp_path,
        current_project=project,
        payload={
            "pinned_marks": [{"student_id": "s3", "mark": 82}],
            # Client-sent assigned marks must be ignored when pins are present.
            "assigned_marks": [{"student_id": "s1", "mark": 1}],
        },
        stage="draft",
    )
    draft = bundle["draft_review"]
    marks = {item["student_id"]: item["mark"] for item in draft["assigned_marks"]}
    assert marks["s3"] == 82.0
    assert marks["s1"] == 91.0  # top of curve unchanged
    assert marks["s5"] == 63.0  # bottom unchanged
    assert 82.0 < marks["s2"] < 91.0  # cascaded between pin and top
    assert 63.0 < marks["s4"] < 82.0  # cascaded between bottom and pin
    assert draft["pinned_marks"] == [{"student_id": "s3", "mark": 82.0}]
    assert draft["curve_reflow"]["anchors"]


def test_save_without_pins_keeps_legacy_assigned_marks(tmp_path):
    base_dir = tmp_path / "server"
    base_dir.mkdir()
    write_workspace(tmp_path)
    project = {"id": "project-a", "name": "Project A"}
    bundle = rs.save_review_bundle(
        base_dir=base_dir,
        root=tmp_path,
        current_project=project,
        payload={"assigned_marks": [{"student_id": "s1", "mark": 94}]},
        stage="draft",
    )
    assert bundle["draft_review"]["assigned_marks"] == [{"student_id": "s1", "mark": 94.0}]


def test_finalize_with_conflicting_pins_requires_confirmation(tmp_path):
    base_dir = tmp_path / "server"
    base_dir.mkdir()
    write_workspace(tmp_path)
    project = {"id": "project-a", "name": "Project A"}
    payload = {
        "pinned_marks": [
            {"student_id": "s2", "mark": 75},
            {"student_id": "s4", "mark": 84},
        ]
    }
    with pytest.raises(rs.ReviewReorderPending) as exc:
        rs.save_review_bundle(base_dir=base_dir, root=tmp_path, current_project=project, payload=payload, stage="final")
    assert any(move["student_id"] == "s4" for move in exc.value.implied_moves)

    payload["accept_reorder"] = True
    bundle = rs.save_review_bundle(
        base_dir=base_dir, root=tmp_path, current_project=project, payload=payload, stage="final"
    )
    latest = bundle["latest_review"]
    assert latest["review_state"] == "final"
    assert latest["curve_reflow"]["order_changed"] is True
    ordered = [item["student_id"] for item in latest["assigned_marks"]]
    assert ordered.index("s4") < ordered.index("s2")


def test_reflow_endpoint_previews_marks(workspace):
    client = TestClient(app)
    res = client.post(
        "/projects/curve/reflow",
        json={"pinned_marks": [{"student_id": "s3", "mark": 82}]},
    )
    assert res.status_code == 200
    body = res.json()
    marks = {item["student_id"]: item["mark"] for item in body["marks"]}
    assert marks["s3"] == 82
    assert marks["s1"] == 91
    assert body["reorder_required"] is False
    pinned = [item for item in body["marks"] if item["pinned"]]
    assert [item["student_id"] for item in pinned] == ["s3"]


def test_reflow_endpoint_reports_reorder_conflict(workspace):
    client = TestClient(app)
    res = client.post(
        "/projects/curve/reflow",
        json={
            "pinned_marks": [
                {"student_id": "s2", "mark": 75},
                {"student_id": "s4", "mark": 84},
            ]
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["reorder_required"] is True
    assert any(move["student_id"] == "s4" for move in body["implied_moves"])

    accepted = client.post(
        "/projects/curve/reflow",
        json={
            "pinned_marks": [
                {"student_id": "s2", "mark": 75},
                {"student_id": "s4", "mark": 84},
            ],
            "accept_reorder": True,
        },
    )
    assert accepted.status_code == 200
    accepted_body = accepted.json()
    assert accepted_body["order_changed"] is True
    order = [item["student_id"] for item in accepted_body["marks"]]
    assert order.index("s4") < order.index("s2")


def test_review_finalize_endpoint_returns_409_on_unconfirmed_reorder(workspace):
    client = TestClient(app)
    res = client.post(
        "/projects/review",
        json={
            "action": "finalize",
            "pinned_marks": [
                {"student_id": "s2", "mark": 75},
                {"student_id": "s4", "mark": 84},
            ],
        },
    )
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["error"] == "reorder_confirmation_required"
    assert detail["implied_moves"]


def test_reflow_endpoint_409_without_cohort(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "BASE_DIR", server_dir)
    client = TestClient(app)
    res = client.post("/projects/curve/reflow", json={"pinned_marks": []})
    assert res.status_code == 409


def test_persisted_pins_survive_draft_reload(tmp_path):
    base_dir = tmp_path / "server"
    base_dir.mkdir()
    write_workspace(tmp_path)
    project = {"id": "project-a", "name": "Project A"}
    rs.save_review_bundle(
        base_dir=base_dir,
        root=tmp_path,
        current_project=project,
        payload={"pinned_marks": [{"student_id": "s3", "mark": 82}], "curve_top": 95},
        stage="draft",
    )
    bundle = rs.load_review_bundle(base_dir, tmp_path, project)
    draft = bundle["draft_review"]
    assert draft["pinned_marks"] == [{"student_id": "s3", "mark": 82.0}]
    assert draft["curve_top"] == 95.0
    marks = {item["student_id"]: item["mark"] for item in draft["assigned_marks"]}
    assert marks["s3"] == 82.0
    assert marks["s1"] == 95.0
