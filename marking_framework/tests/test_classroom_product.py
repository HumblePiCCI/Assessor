import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server.app as appmod
import server.classroom as classroom
import server.projects as projmod
import server.review_store as review_store
from server.app import app


def write_workspace(root: Path):
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (root / "pipeline_manifest.json").write_text(json.dumps({"manifest_hash": "manifest-1"}), encoding="utf-8")
    (outputs / "calibration_manifest.json").write_text(json.dumps({"model_version": "gpt-5.4"}), encoding="utf-8")
    (outputs / "dashboard_data.json").write_text(
        json.dumps(
            {
                "students": [
                    {"student_id": "s1", "display_name": "Student One", "rank": 1, "level_with_modifier": "4"},
                    {"student_id": "s2", "display_name": "Student Two", "rank": 2, "level_with_modifier": "3"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (outputs / "final_order.csv").write_text("student_id,final_rank\ns1,1\ns2,2\n", encoding="utf-8")
    (outputs / "grade_curve.csv").write_text("student_id,final_grade\ns1,94\ns2,82\n", encoding="utf-8")


def classroom_link_payload(passback_mode="csv_export"):
    return {
        "course_id": "course-1",
        "course_name": "Period 2",
        "coursework_id": "cw-1",
        "coursework_title": "Macbeth Essay",
        "passback_mode": passback_mode,
        "policy": {
            "policy_state": "operator_supervised_pilot",
            "app_approval_status": "operator_supervised_pilot",
            "external_writes_enabled": False,
        },
    }


def classroom_snapshot(include_blocker=False):
    s2_attachment = (
        {"attachment_id": "s2-link", "type": "external_link", "title": "External portfolio"}
        if include_blocker
        else {"attachment_id": "s2-text", "type": "text", "mime_type": "text/plain", "text": "Second essay text."}
    )
    return {
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
                "attachments": [{"attachment_id": "s1-text", "type": "text", "mime_type": "text/plain", "text": "First essay text."}],
            },
            {
                "submission_id": "sub-2",
                "student_id": "s2",
                "display_name": "Student Two",
                "classroom_state": "submitted",
                "attachments": [s2_attachment],
            },
        ],
    }


def finalize_review(base_dir: Path, root: Path, project: dict):
    payload = {
        "action": "finalize",
        "assigned_marks": [{"student_id": "s1", "mark": 94}, {"student_id": "s2", "mark": 82}],
        "feedback_drafts": [
            {"student_id": "s1", "star1": "Clear claim.", "star2": "Strong detail.", "wish": "Tighten transitions."},
            {"student_id": "s2", "star1": "Good structure.", "star2": "Relevant example.", "wish": "Explain the quote."},
        ],
    }
    review_store.save_review_bundle(base_dir, root, project, payload, stage="final")
    classroom.record_review_revision(base_dir, root, project, {}, payload, stage="final")


def test_classroom_state_tracks_reconciliation_revisions_evidence_and_passback(tmp_path):
    root = tmp_path
    base_dir = root / "server"
    base_dir.mkdir()
    write_workspace(root)
    project = {"id": "project-a", "name": "Project A"}

    linked = classroom.link_assignment(base_dir, root, project, {}, classroom_link_payload())
    assert linked["product_state"] == "review_ready"
    assert linked["classroom_link"]["passback_mode"] == "csv_export"

    blocked = classroom.reconcile_snapshot(base_dir, root, project, {}, classroom_snapshot(include_blocker=True))
    assert blocked["product_state"] == "blocked"
    assert "external_link_unsupported" in blocked["blockers"]

    deduped = classroom.record_event_hint(
        base_dir,
        root,
        project,
        {},
        {"event_id": "evt-1", "event_type": "submission_changed", "submission_id": "sub-1"},
    )
    assert deduped["event_counters"]["accepted"] == 1
    deduped_again = classroom.record_event_hint(
        base_dir,
        root,
        project,
        {},
        {"event_id": "evt-1", "event_type": "submission_changed", "submission_id": "sub-1"},
    )
    assert deduped_again["event_counters"]["duplicate"] == 1

    clear = classroom.reconcile_snapshot(base_dir, root, project, {}, classroom_snapshot(include_blocker=False))
    assert clear["summary"]["attachment_blocker_count"] == 0
    assert clear["blockers"] == []

    finalize_review(base_dir, root, project)
    stale = classroom.state_bundle(base_dir, root, project, {})
    assert stale["product_state"] == "background_validating"
    assert stale["latest_human_revision_id"] == 1

    current = classroom.complete_background_audit(base_dir, root, project, {}, {"gate_status": "pass"})
    assert current["product_state"] == "final_ready"
    assert current["launch_gates"]["full_validation_current"] is True

    packet = classroom.assessment_evidence_packet(base_dir, root, project, {})
    assert packet["packet_type"] == "assessment_evidence_packet"
    assert packet["submission_hashes"]["sub-1"]["text_hash"]
    assert (root / "outputs" / "assessment_evidence_packet.json").exists()

    preflight = classroom.passback_preflight(base_dir, root, project, {}, {"mode": "csv_export"})
    assert preflight["blocked"] is False
    assert preflight["row_count"] == 2
    assert preflight["evidence_packet_id"]
    action = classroom.confirm_passback(base_dir, root, project, {}, {"preflight_id": preflight["preflight_id"], "confirmed": True})
    assert action["status"] == "prepared_for_export"
    assert action["external_write_performed"] is False
    assert action["export_artifact"]["sha256"]
    assert Path(action["export_artifact"]["path"]).exists()
    packet_after_export = classroom.assessment_evidence_packet(base_dir, root, project, {})
    assert packet_after_export["export_and_passback"]["export_artifacts"][0]["sha256"] == action["export_artifact"]["sha256"]


def test_classroom_read_only_sync_materializes_supported_text_and_blocks_unsupported(tmp_path):
    root = tmp_path
    base_dir = root / "server"
    base_dir.mkdir()
    project = {"id": "project-a", "name": "Project A"}
    payload = {
        "course_id": "course-1",
        "course_name": "Period 2",
        "coursework_id": "cw-1",
        "coursework_title": "Macbeth Essay",
        "passback_mode": "csv_export",
        "roster": [
            {"student_id": "s1", "display_name": "Student One"},
            {"student_id": "s2", "display_name": "Student Two"},
        ],
        "submissions": [
            {
                "submission_id": "sub-1",
                "student_id": "s1",
                "display_name": "Student One",
                "attachments": [{"attachment_id": "a1", "mime_type": "text/plain", "text": "First essay text."}],
            },
            {
                "submission_id": "sub-2",
                "student_id": "s2",
                "display_name": "Student Two",
                "attachments": [{"attachment_id": "a2", "type": "external_link", "title": "Portfolio"}],
            },
        ],
    }

    bundle = classroom.read_only_sync(base_dir, root, project, {}, payload)
    assert bundle["read_sync"]["external_write_performed"] is False
    assert bundle["read_sync"]["imported_submission_count"] == 1
    assert bundle["read_sync"]["blocked_submission_count"] == 1
    assert (root / "inputs" / "submissions" / "s1.txt").read_text(encoding="utf-8").strip() == "First essay text."
    assert not (root / "inputs" / "submissions" / "s2.txt").exists()
    assert "external_link_unsupported" in bundle["blockers"]
    metadata = json.loads((root / "inputs" / "class_metadata.json").read_text(encoding="utf-8"))
    assert metadata["source"] == "google_classroom_read_only_sync"
    assert metadata["imported_submission_count"] == 1
    assert metadata["assignment"]["course_id_hash"] != "course-1"
    assert "course_id" not in metadata["assignment"]


def test_read_sync_zero_imports_and_mixed_attachments_block_without_materializing(tmp_path):
    root = tmp_path
    base_dir = root / "server"
    base_dir.mkdir()
    project = {"id": "project-a", "name": "Project A"}
    payload = {
        "course_id": "course-1",
        "course_name": "Period 2",
        "coursework_id": "cw-1",
        "coursework_title": "Macbeth Essay",
        "passback_mode": "csv_export",
        "roster": [{"student_id": "s1", "display_name": "Student One"}],
        "submissions": [
            {
                "submission_id": "sub-1",
                "student_id": "s1",
                "display_name": "Student One",
                "attachments": [
                    {"attachment_id": "a1", "mime_type": "text/plain", "text": "Supported essay text."},
                    {"attachment_id": "a2", "type": "external_link", "title": "Portfolio"},
                ],
            }
        ],
    }

    bundle = classroom.read_only_sync(base_dir, root, project, {}, payload)
    assert bundle["read_sync"]["imported_submission_count"] == 0
    assert bundle["read_sync"]["blocked_submission_count"] == 1
    assert bundle["product_state"] == "blocked"
    assert "partial_unsupported_attachments" in bundle["blockers"]
    assert "external_link_unsupported" in bundle["blockers"]
    assert "zero_imports_no_supported_submissions" in bundle["blockers"]
    assert not any((root / "inputs" / "submissions").glob("*.txt"))
    metadata = json.loads((root / "inputs" / "class_metadata.json").read_text(encoding="utf-8"))
    assert metadata["counts"]["imported_count"] == 0
    assert metadata["latest_sync"]["platform_error_count"] == 1


def test_classroom_finalization_is_reopened_by_later_teacher_revision(tmp_path):
    root = tmp_path
    base_dir = root / "server"
    base_dir.mkdir()
    write_workspace(root)
    project = {"id": "project-a", "name": "Project A"}

    classroom.link_assignment(base_dir, root, project, {}, classroom_link_payload())
    classroom.reconcile_snapshot(base_dir, root, project, {}, classroom_snapshot(include_blocker=False))
    finalize_review(base_dir, root, project)
    classroom.complete_background_audit(base_dir, root, project, {}, {"gate_status": "pass"})

    finalized = classroom.finalize_by_teacher(base_dir, root, project, {})
    assert finalized["product_state"] == "finalized_by_teacher"
    assert finalized["finalization"]["finalized_revision_id"] == 1

    revised_payload = {
        "action": "finalize",
        "assigned_marks": [{"student_id": "s1", "mark": 95}, {"student_id": "s2", "mark": 82}],
        "feedback_drafts": [
            {"student_id": "s1", "star1": "Sharper claim.", "star2": "Strong detail.", "wish": "Tighten transitions."},
            {"student_id": "s2", "star1": "Good structure.", "star2": "Relevant example.", "wish": "Explain the quote."},
        ],
    }
    review_store.save_review_bundle(base_dir, root, project, revised_payload, stage="final")
    classroom.record_review_revision(base_dir, root, project, {}, revised_payload, stage="final")

    stale = classroom.state_bundle(base_dir, root, project, {})
    assert stale["product_state"] == "background_validating"
    assert stale["finalization"]["status"] == "stale"
    assert stale["launch_gates"]["full_validation_current"] is False

    preflight = classroom.passback_preflight(base_dir, root, project, {}, {"mode": "csv_export"})
    assert preflight["blocked"] is True
    assert "full_validation_current_required" in preflight["blockers"]
    assert "final_ready_required" in preflight["blockers"]

    classroom.complete_background_audit(base_dir, root, project, {}, {"gate_status": "pass"})
    ready = classroom.state_bundle(base_dir, root, project, {})
    assert ready["product_state"] == "final_ready"


def test_csv_preflight_blocks_when_attachment_blockers_remain(tmp_path):
    root = tmp_path
    base_dir = root / "server"
    base_dir.mkdir()
    write_workspace(root)
    project = {"id": "project-a", "name": "Project A"}
    classroom.link_assignment(base_dir, root, project, {}, classroom_link_payload())
    classroom.reconcile_snapshot(base_dir, root, project, {}, classroom_snapshot(include_blocker=True))
    finalize_review(base_dir, root, project)
    classroom.complete_background_audit(base_dir, root, project, {}, {"gate_status": "pass"})

    preflight = classroom.passback_preflight(base_dir, root, project, {}, {"mode": "csv_export"})
    assert preflight["blocked"] is True
    assert "external_link_unsupported" in preflight["blockers"]


def test_classroom_api_endpoints_preserve_teacher_review_gate(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projmod, "CURRENT_PROJECT_PATH", projects_dir / "current.json")
    write_workspace(tmp_path)

    client = TestClient(app)
    save = client.post("/projects/save", json={"name": "Classroom Pilot"})
    assert save.status_code == 200

    link = client.post("/projects/classroom/link", json=classroom_link_payload(passback_mode="draft_grade"))
    assert link.status_code == 200
    assert link.json()["classroom_link"]["coursework_title"] == "Macbeth Essay"

    reconcile = client.post("/projects/classroom/reconcile", json=classroom_snapshot())
    assert reconcile.status_code == 200
    assert reconcile.json()["summary"]["submitted_count"] == 2

    early_preflight = client.post("/projects/classroom/passback/preflight", json={"mode": "draft_grade"})
    assert early_preflight.status_code == 200
    assert "finalized_teacher_review_required" in early_preflight.json()["blockers"]

    review = client.post(
        "/projects/review",
        json={
            "action": "finalize",
            "assigned_marks": [{"student_id": "s1", "mark": 94}, {"student_id": "s2", "mark": 82}],
            "feedback_drafts": [{"student_id": "s1", "star1": "Clear claim."}],
        },
    )
    assert review.status_code == 200
    state = client.get("/projects/classroom").json()
    assert state["product_state"] == "background_validating"

    audit = client.post("/projects/classroom/audit/complete", json={"gate_status": "pass"})
    assert audit.status_code == 200
    assert audit.json()["product_state"] == "final_ready"

    draft_preflight = client.post("/projects/classroom/passback/preflight", json={"mode": "draft_grade"})
    assert draft_preflight.status_code == 200
    assert "external_writes_disabled" in draft_preflight.json()["blockers"]

    csv_preflight = client.post("/projects/classroom/passback/preflight", json={"mode": "csv_export"})
    assert csv_preflight.status_code == 200
    assert csv_preflight.json()["blocked"] is False

    confirm = client.post(
        "/projects/classroom/passback/confirm",
        json={"preflight_id": csv_preflight.json()["preflight_id"], "confirmed": True},
    )
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "prepared_for_export"
    assert confirm.json()["export_artifact"]["row_count"] == 2
    download = client.get(confirm.json()["download_url"])
    assert download.status_code == 200
    assert "student_display_name" in download.text


def test_tampered_live_write_preflight_still_fails_closed_at_confirm(tmp_path):
    root = tmp_path
    base_dir = root / "server"
    base_dir.mkdir()
    project = {"id": "project-a", "name": "Project A"}
    classroom.link_assignment(base_dir, root, project, {}, classroom_link_payload(passback_mode="draft_grade"))
    scope_id = review_store.review_scope_id(project)
    state = classroom.load_state(base_dir, scope_id, project, {})
    state.setdefault("passback", {}).setdefault("preflights", {})["tampered-live"] = {
        "preflight_id": "tampered-live",
        "mode": "draft_grade",
        "blocked": False,
        "external_write_would_occur": True,
        "row_count": 1,
        "diff_rows": [],
    }
    classroom.save_state(base_dir, scope_id, state, root)
    with pytest.raises(classroom.ClassroomStateError) as exc:
        classroom.confirm_passback(base_dir, root, project, {}, {"preflight_id": "tampered-live", "confirmed": True})
    assert exc.value.code == "external_writes_disabled"


def test_classroom_read_sync_endpoint_uses_fixture_snapshot_without_live_writes(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(appmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "BASE_DIR", server_dir)
    monkeypatch.setattr(projmod, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projmod, "CURRENT_PROJECT_PATH", projects_dir / "current.json")

    client = TestClient(app)
    save = client.post("/projects/save", json={"name": "Read Sync Pilot"})
    assert save.status_code == 200
    resp = client.post(
        "/projects/classroom/read-sync",
        json={
            "course_id": "course-1",
            "course_name": "Period 2",
            "coursework_id": "cw-1",
            "coursework_title": "Macbeth Essay",
            "passback_mode": "csv_export",
            "roster": [{"student_id": "s1", "display_name": "Student One"}],
            "submissions": [
                {
                    "submission_id": "sub-1",
                    "student_id": "s1",
                    "display_name": "Student One",
                    "attachments": [{"attachment_id": "a1", "mime_type": "text/plain", "text": "Essay text."}],
                }
            ],
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["read_sync"]["imported_submission_count"] == 1
    assert payload["read_sync"]["external_write_performed"] is False
    assert (tmp_path / "inputs" / "submissions" / "s1.txt").exists()
