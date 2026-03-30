import json

import scripts.release_rollback as rollback
import scripts.validate_production_launch as vpl


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _seed_contract(root):
    _write_json(
        root / "config/accuracy_gate.json",
        {
            "production_contract": {
                "auth": {
                    "required_mode": "strict",
                    "teacher_header": "x-teacher-id",
                    "tenant_header": "x-tenant-id",
                    "role_header": "x-teacher-role",
                    "project_owner_required": True,
                },
                "retention": {"job_days": 14, "artifact_days": 30, "workspace_days": 7},
                "observability": {"max_queue_depth_warning": 5, "max_p95_job_latency_seconds": 180.0},
                "privacy": {
                    "required_posture": "governed_finalized_anonymized",
                    "aggregate_feedback_policy": "opt_in_or_policy_compliant",
                    "delete_tombstone_days": 365,
                },
            }
        },
    )
    _write_json(
        root / "config/sota_gate.json",
        {
            "production_contract": {
                "launch": {
                    "required_publish_profile": "release",
                    "required_sota_profile": "release",
                    "required_benchmark_dataset_count": 2,
                    "required_calibration_freshness_hours": 168.0,
                    "required_privacy_posture": "governed_finalized_anonymized",
                },
                "rollback": {
                    "max_release_age_hours": 168.0,
                    "require_manifest_hash": True,
                    "require_git_sha": True,
                    "invalidate_cache_on_rollback": True,
                },
                "incident": {"require_runbook": True, "require_gate_summary": True, "max_recent_gate_failures": 2},
            }
        },
    )


def _seed_outputs(root):
    _write_json(
        root / "outputs/publish_gate.json",
        {
            "ok": True,
            "target_profile": "release",
            "highest_attained_profile": "release",
            "profile_order": ["dev", "candidate", "release"],
            "profiles": {"release": {"failures": []}},
        },
    )
    _write_json(
        root / "outputs/sota_gate.json",
        {
            "ok": True,
            "target_profile": "release",
            "highest_attained_profile": "release",
            "profile_order": ["dev", "candidate", "release"],
            "profiles": {"release": {"failures": []}},
        },
    )
    _write_json(
        root / "outputs/calibration_manifest.json",
        {
            "generated_at": "2026-03-29T00:00:00+00:00",
            "synthetic": False,
            "scope_coverage": [{"key": "grade_8_10|argumentative"}],
            "model_version": "gpt-5.4",
        },
    )
    _write_json(
        root / "server/data/pipeline_ops.json",
        {
            "cache_validation_failures": 0,
            "recent_gate_failures": [],
            "recent_incidents": [],
            "last_retention_report": {"dry_run": True},
        },
    )
    _write_json(root / "pipeline_manifest.json", {"manifest_hash": "manifest-1", "generated_at": "2026-03-29T01:00:00+00:00", "git": {"sha": "abc123"}})
    incident_doc = root / "docs/INCIDENT_RESPONSE.md"
    incident_doc.parent.mkdir(parents=True, exist_ok=True)
    incident_doc.write_text("# Incident Response\n", encoding="utf-8")
    for name in ("dataset_a", "dataset_b"):
        (root / "bench" / name / "inputs").mkdir(parents=True, exist_ok=True)
        (root / "bench" / name / "submissions").mkdir(parents=True, exist_ok=True)
        (root / "bench" / name / "gold.jsonl").write_text("{}\n", encoding="utf-8")


def test_validate_production_launch_success(tmp_path):
    _seed_contract(tmp_path)
    _seed_outputs(tmp_path)
    payload = vpl.evaluate(
        tmp_path,
        publish_path=tmp_path / "outputs/publish_gate.json",
        sota_path=tmp_path / "outputs/sota_gate.json",
        calibration_path=tmp_path / "outputs/calibration_manifest.json",
        bench_root=tmp_path / "bench",
        ops_path=tmp_path / "server/data/pipeline_ops.json",
    )
    assert payload["ok"] is True
    assert payload["decision_state"] == "launch_ready"
    assert payload["benchmark_inventory"]["count"] == 2


def test_validate_production_launch_catches_failures(tmp_path):
    _seed_contract(tmp_path)
    _seed_outputs(tmp_path)
    _write_json(tmp_path / "outputs/publish_gate.json", {"ok": False, "highest_attained_profile": "candidate", "profile_order": ["dev", "candidate", "release"]})
    _write_json(tmp_path / "outputs/calibration_manifest.json", {"generated_at": "2020-01-01T00:00:00+00:00", "synthetic": True})
    _write_json(
        tmp_path / "server/data/pipeline_ops.json",
        {"cache_validation_failures": 1, "recent_gate_failures": [{}, {}, {}], "recent_incidents": []},
    )
    payload = vpl.evaluate(
        tmp_path,
        publish_path=tmp_path / "outputs/publish_gate.json",
        sota_path=tmp_path / "outputs/sota_gate.json",
        calibration_path=tmp_path / "outputs/calibration_manifest.json",
        bench_root=tmp_path / "bench",
        ops_path=tmp_path / "server/data/pipeline_ops.json",
    )
    assert payload["ok"] is False
    assert "publish_gate_not_ok" in payload["failures"]
    assert "publish_profile_below_required" in payload["failures"]
    assert "calibration_freshness_exceeded" in payload["failures"]
    assert "synthetic_calibration_not_allowed" in payload["failures"]
    assert "cache_validation_failures_present" in payload["failures"]
    assert "recent_gate_failures_above_limit" in payload["failures"]


def test_release_rollback_plan_uses_manifest_and_contract(tmp_path):
    _seed_contract(tmp_path)
    _seed_outputs(tmp_path)
    payload = rollback.build_plan(tmp_path, reason="prompt_regression", target_git_sha="known-good-sha", target_manifest_hash="manifest-good")
    assert payload["ok"] is True
    assert payload["current_release"]["manifest_hash"] == "manifest-1"
    assert payload["target_release"]["git_sha"] == "known-good-sha"
    assert any(step["action"] == "invalidate_manifest_cache" for step in payload["steps"])


def test_release_rollback_plan_flags_missing_target_sha(tmp_path):
    _seed_contract(tmp_path)
    _seed_outputs(tmp_path)
    _write_json(tmp_path / "pipeline_manifest.json", {"manifest_hash": "manifest-1", "generated_at": "2026-03-29T01:00:00+00:00", "git": {"sha": ""}})
    payload = rollback.build_plan(tmp_path, reason="model_regression", target_git_sha="", target_manifest_hash="")
    assert payload["ok"] is False
    assert "current_git_sha_missing" in payload["failures"]
    assert "target_git_sha_missing" in payload["failures"]
