import json
from pathlib import Path

import server.review_store as rs
import scripts.export_aggregate_feedback as export_feedback
import scripts.ingest_aggregate_feedback as ingest_feedback
import scripts.promote_aggregate_learning as promote_learning


def _write_workspace(tmp_path: Path):
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
                        "text": "Student One wrote a very complete and insightful essay with strong voice.",
                        "uncertainty_flags": ["boundary_case", "low_confidence_rerank_move"],
                        "uncertainty_reasons": ["Near level boundary"],
                    },
                    {
                        "student_id": "s2",
                        "display_name": "Student Two",
                        "source_file": "student_two.txt",
                        "level_with_modifier": "4",
                        "rank": 1,
                        "text": "Student Two wrote a shorter but organized essay.",
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


def _finalize_review(base_dir: Path, root: Path, project_id: str = "project-a"):
    project = {
        "id": project_id,
        "name": project_id,
        "aggregate_learning": {"mode": "opt_in", "retention_days": 180},
    }
    return rs.save_review_bundle(
        base_dir=base_dir,
        root=root,
        current_project=project,
        payload={
            "students": [
                {
                    "student_id": "s1",
                    "level_override": "4",
                    "desired_rank": 1,
                    "evidence_quality": "thin",
                    "evidence_comment": "Student One is more insightful and complete.",
                }
            ],
            "pairwise": [
                {
                    "student_id": "s1",
                    "other_student_id": "s2",
                    "preferred_student_id": "s1",
                    "confidence": "high",
                    "rationale": "Student One should be above Student Two on insight and completeness.",
                }
            ],
            "review_notes": "Teacher prioritized insight and completeness.",
        },
        stage="final",
    )


def test_export_and_ingest_governed_feedback_package(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_server = source_root / "server"
    source_server.mkdir()
    _write_workspace(source_root)
    _finalize_review(source_server, source_root, project_id="class-a")

    outbox = source_server / "data" / "review_aggregate" / "custom_outbox"
    monkeypatch.chdir(source_root)
    monkeypatch.setattr("sys.argv", ["export", "--server-dir", str(source_server), "--output-root", str(outbox)])
    assert export_feedback.main() == 0

    packages = list(outbox.glob("aggregate_feedback_*"))
    assert len(packages) == 1
    package = packages[0]
    exported_text = (package / "eligible_records.jsonl").read_text(encoding="utf-8")
    assert "Student One" not in exported_text
    assert "student_one.txt" not in exported_text
    exported_row = json.loads(exported_text.strip().splitlines()[0])
    assert "scope_id" not in exported_row
    assert exported_row["collection_policy"]["mode"] == "opt_in"
    assert "insight" in exported_row["normalized_reason_codes"]

    product_root = tmp_path / "product"
    product_root.mkdir()
    product_server = product_root / "server"
    product_server.mkdir()
    monkeypatch.setattr("sys.argv", ["ingest", "--server-dir", str(product_server), "--package-dir", str(package)])
    assert ingest_feedback.main() == 0
    receipts = list((product_server / "data" / "review_aggregate" / "ingested").glob("*/ingest_receipt.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["record_count"] == 1


def test_promotion_workflow_requires_adjudication_and_writes_staged_assets(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_server = source_root / "server"
    source_server.mkdir()
    _write_workspace(source_root)
    _finalize_review(source_server, source_root, project_id="class-b")

    outbox = source_server / "data" / "review_aggregate" / "custom_outbox"
    monkeypatch.chdir(source_root)
    monkeypatch.setattr("sys.argv", ["export", "--server-dir", str(source_server), "--output-root", str(outbox)])
    assert export_feedback.main() == 0
    package = next(outbox.glob("aggregate_feedback_*"))

    product_root = tmp_path / "product"
    product_root.mkdir()
    (product_root / "bench").mkdir()
    (product_root / "inputs" / "exemplars").mkdir(parents=True)
    product_server = product_root / "server"
    product_server.mkdir()
    monkeypatch.setattr("sys.argv", ["ingest", "--server-dir", str(product_server), "--package-dir", str(package)])
    assert ingest_feedback.main() == 0

    monkeypatch.chdir(product_root)
    monkeypatch.setattr("sys.argv", ["promote", "--server-dir", str(product_server), "propose"])
    assert promote_learning.main() == 0
    proposal_dir = next((product_server / "data" / "review_aggregate" / "promotions" / "proposals").glob("aggregate_promotion_*"))

    bad_adjudication = product_root / "bad_adjudication.json"
    bad_adjudication.write_text(json.dumps({"decision": "approve"}), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["promote", "--server-dir", str(product_server), "promote", "--proposal-dir", str(proposal_dir), "--adjudication", str(bad_adjudication)],
    )
    assert promote_learning.main() == 1

    good_adjudication = product_root / "good_adjudication.json"
    good_adjudication.write_text(
        json.dumps(
            {
                "decision": "approve",
                "approved_by": "review.board@example.org",
                "approved_at": "2026-03-30T12:00:00+00:00",
                "approve_benchmark_gold": True,
                "approve_boundary_challenges": True,
                "approve_calibration_exemplars": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["promote", "--server-dir", str(product_server), "promote", "--proposal-dir", str(proposal_dir), "--adjudication", str(good_adjudication)],
    )
    assert promote_learning.main() == 0

    assert next((product_root / "bench" / "promoted" / "benchmark_gold").glob("*/gold.jsonl")).exists()
    assert next((product_root / "bench" / "promoted" / "boundary_challenges").glob("*/boundary_challenges.jsonl")).exists()
    assert next((product_root / "inputs" / "exemplars" / "promoted").glob("*/calibration_exemplars.jsonl")).exists()
    audit_log = product_server / "data" / "review_aggregate" / "promotions" / "promotion_audit.jsonl"
    assert audit_log.exists()
