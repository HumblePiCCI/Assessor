import json

import server.review_store as rs


def _write_workspace(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (tmp_path / "pipeline_manifest.json").write_text(
        json.dumps(
            {
                "manifest_hash": "manifest-123",
                "generated_at": "2026-03-29T00:00:00+00:00",
                "execution_mode": "openai",
                "run_scope": {
                    "grade_band": "grade_6_8",
                    "genre": "literary_analysis",
                    "rubric_family": "rubric_123",
                    "model_family": "gpt-5.4",
                    "scope_id": "grade_6_8|literary_analysis|rubric_123|gpt-5.4",
                },
            }
        ),
        encoding="utf-8",
    )
    (outputs / "calibration_manifest.json").write_text(
        json.dumps({"model_version": "gpt-5.4", "generated_at": "2026-03-29T00:00:00+00:00"}),
        encoding="utf-8",
    )
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
                        "uncertainty_flags": ["boundary_case", "low_confidence_rerank_move"],
                        "uncertainty_reasons": ["Near level boundary"],
                    },
                    {
                        "student_id": "s2",
                        "display_name": "Student Two",
                        "source_file": "student_two.txt",
                        "level_with_modifier": "4",
                        "rank": 1,
                        "uncertainty_flags": ["high_disagreement"],
                        "uncertainty_reasons": ["Split pairwise evidence"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (outputs / "final_order.csv").write_text("student_id,final_rank\ns2,1\ns1,2\n", encoding="utf-8")
    (outputs / "grade_curve.csv").write_text("student_id,final_grade\ns2,90\ns1,82\n", encoding="utf-8")
    (outputs / "consistency_report.json").write_text(json.dumps({"summary": {"pairwise_agreement_with_final_order": 0.95}}), encoding="utf-8")


def test_review_store_saves_draft_without_creating_learning_signal_and_finalizes_with_delta(tmp_path):
    base_dir = tmp_path / "server"
    base_dir.mkdir()
    _write_workspace(tmp_path)
    draft = rs.ensure_draft_review(base_dir=base_dir, root=tmp_path, current_project={"id": "project-a", "name": "Project A"})
    assert draft["review_state"] == "draft"
    assert [row["student_id"] for row in draft["review_session"]["machine_proposal"]["students"]] == ["s2", "s1"]

    draft_bundle = rs.save_review_bundle(
        base_dir=base_dir,
        root=tmp_path,
        current_project={"id": "project-a", "name": "Project A"},
        payload={
            "students": [
                {
                    "student_id": "s1",
                    "level_override": "4",
                    "desired_rank": 1,
                    "evidence_quality": "thin",
                    "evidence_comment": "Student One needs clearer evidence in the middle paragraph.",
                }
            ],
            "pairwise": [
                {
                    "student_id": "s1",
                    "other_student_id": "s2",
                    "preferred_student_id": "s1",
                    "confidence": "high",
                    "rationale": "Student One should outrank Student Two on analysis.",
                }
            ],
            "review_notes": "Teacher override after manual inspection.",
        },
        stage="draft",
    )
    assert draft_bundle["draft_review"]["students"][0]["level_override"] == "4"
    assert draft_bundle["latest_review"]["students"] == []
    assert draft_bundle["local_learning_profile"]["student_review_count"] == 0

    bundle = rs.save_review_bundle(
        base_dir=base_dir,
        root=tmp_path,
        current_project={"id": "project-a", "name": "Project A"},
        payload={
            "students": [
                {
                    "student_id": "s1",
                    "level_override": "4",
                    "desired_rank": 1,
                    "evidence_quality": "thin",
                    "evidence_comment": "Student One needs clearer evidence in the middle paragraph.",
                }
            ],
            "pairwise": [
                {
                    "student_id": "s1",
                    "other_student_id": "s2",
                    "preferred_student_id": "s1",
                    "confidence": "high",
                    "rationale": "Student One should outrank Student Two on analysis.",
                }
            ],
            "review_notes": "Teacher override after manual inspection.",
        },
        stage="final",
    )
    latest = bundle["latest_review"]
    assert latest["version_context"]["pipeline_manifest"]["manifest_hash"] == "manifest-123"
    assert latest["review_state"] == "final"
    assert latest["students"][0]["level_override"] == "4"
    assert latest["pairwise"][0]["reversed_machine_order"] is True
    assert latest["review_session"]["source_rank_artifact_hash"] != ""
    assert bundle["local_learning_profile"]["student_review_count"] == 1
    assert bundle["latest_delta"]["summary"]["rank_movement_count"] >= 1
    assert bundle["replay_exports"]["benchmark_gold_count"] == 2
    assert (base_dir / "data" / "reviews" / "project-a" / "exports" / "calibration_exemplars.jsonl").exists()
    assert (tmp_path / "outputs" / "local_learning_profile.json").exists()
    assert (tmp_path / "outputs" / "local_teacher_prior.json").exists()
    assert (tmp_path / "outputs" / "review_delta_latest.json").exists()
    analytics_log = base_dir / "data" / "review_analytics" / "anonymized_feedback.jsonl"
    assert analytics_log.exists()
    analytics_text = analytics_log.read_text(encoding="utf-8")
    assert "Student One" not in analytics_text
    assert "student_one.txt" not in analytics_text


def test_review_store_loads_missing_and_legacy_records(tmp_path):
    base_dir = tmp_path / "server"
    base_dir.mkdir()
    empty = rs.load_review_bundle(base_dir=base_dir, root=tmp_path, current_project=None)
    assert empty["scope_id"] == "workspace"
    assert empty["draft_review"]["students"] == []
    assert empty["latest_review"]["students"] == []

    scope = base_dir / "data" / "reviews" / "legacy-project"
    (scope / "history").mkdir(parents=True, exist_ok=True)
    (scope / "latest_review.json").write_text(json.dumps({"review_id": "old", "students": [{"student_id": "s1"}]}), encoding="utf-8")
    bundle = rs.load_review_bundle(base_dir=base_dir, root=tmp_path, current_project={"id": "legacy-project", "name": "Legacy"})
    assert bundle["latest_review"]["review_id"] == "old"
    assert bundle["latest_review"]["pairwise"] == []
