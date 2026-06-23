import json

from scripts import rubric_validity as rv


def test_build_rubric_claims_ties_score_to_evidence_counter_evidence_and_uncertainty():
    row = {
        "student_id": "s1",
        "rubric_after_penalty_percent": "66",
        "adjusted_level": "2",
        "conventions_mistake_rate_percent": "11.2",
    }
    rubric = {
        "criteria": [
            {
                "id": "ideas",
                "name": "Ideas and Evidence",
                "canonical_dimension": "ideas_analysis",
                "weight": 0.5,
            },
            {
                "id": "language",
                "name": "Language Control",
                "canonical_dimension": "language_control",
                "weight": 0.5,
            },
        ]
    }
    text = "The theme is courage because the character keeps trying. Sentence errors make this less clear."

    claims = rv.build_rubric_claims(row, text, rubric, ["boundary_case", "high_disagreement"], ["near 70"])

    assert [claim["criterion_id"] for claim in claims] == ["ideas", "language"]
    assert claims[0]["claim"].startswith("Current evidence supports Level 2")
    assert claims[0]["evidence"][0]["quote"].startswith("The theme is courage")
    assert claims[0]["evidence"][0]["hash"]
    assert "near level boundary" in claims[0]["uncertainty"]["reasons"]
    assert "boundary_case" in claims[0]["instruction_tags"]
    assert any("Conventions signal" in item for item in claims[1]["counter_evidence"])


def test_instructional_summary_and_data_posture_are_teacher_safe(tmp_path):
    students = [
        {
            "student_id": "s1",
            "rubric_claims": [{"instruction_tags": ["evidence_explanation", "language_control"]}],
            "uncertainty_flags": ["boundary_case"],
        },
        {
            "student_id": "s2",
            "rubric_claims": [{"instruction_tags": ["evidence_explanation"]}],
            "uncertainty_flags": [],
        },
    ]
    summary = rv.build_instructional_summary(students)
    assert summary["misconceptions"][0]["tag"] == "evidence_explanation"
    assert summary["mini_lessons"]

    text_dir = tmp_path / "processing" / "normalized_text"
    text_dir.mkdir(parents=True)
    (text_dir / "s001.txt").write_text("Reach me at student@example.com or 416-555-0123. Long id 123456789012.", encoding="utf-8")
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "summary.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

    posture = rv.build_data_posture(tmp_path)
    assert posture["status"] == "local_private_workspace"
    assert posture["file_counts"]["processing_text"] == 1
    assert posture["pii_scan"]["email_count"] == 1
    assert posture["pii_scan"]["phone_like_count"] == 1
    assert posture["pii_scan"]["long_id_count"] == 1
    assert posture["retention_controls"]["project_delete_available"] is True
