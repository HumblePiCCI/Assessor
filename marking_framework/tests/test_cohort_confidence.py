import json
from pathlib import Path

import scripts.cohort_confidence as cc


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_csv(path: Path, header: str, rows: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def test_cohort_confidence_requires_anchor_for_synthetic_unknown_scope(tmp_path):
    rows = tmp_path / "outputs" / "final_order.csv"
    consistency = tmp_path / "outputs" / "consistency_report.json"
    publish = tmp_path / "outputs" / "publish_gate.json"
    sota = tmp_path / "outputs" / "sota_gate.json"
    scope = tmp_path / "outputs" / "scope_grounding.json"
    validation = tmp_path / "outputs" / "rubric_validation_report.json"
    verification = tmp_path / "outputs" / "rubric_verification.json"
    calibration = tmp_path / "outputs" / "calibration_manifest.json"
    pass1 = tmp_path / "assessments" / "pass1_individual" / "assessor_a.json"
    config = tmp_path / "config" / "marking_config.json"

    _write_csv(
        rows,
        "student_id,final_rank,rubric_sd_points,rank_sd,adjusted_level,rubric_after_penalty_percent",
        ["s1,1,6.8,1.4,4,82", "s2,2,6.9,1.2,3,74"],
    )
    _write_json(consistency, {"summary": {"swap_rate": 0.52, "boundary_disagreement_concentration": 0.4}})
    _write_json(publish, {"ok": True})
    _write_json(sota, {"ok": True})
    _write_json(scope, {"accepted": False, "resolved_scope": {"rubric_family": "rubric_unknown"}})
    _write_json(validation, {"confidence": {"score": 0.92}})
    _write_json(verification, {"status": "confirmed"})
    _write_json(calibration, {"synthetic": True})
    _write_json(pass1, {"scores": [{"student_id": "s1", "notes": ""}, {"student_id": "s2", "notes": ""}]})
    _write_json(config, {"live_cohort": {"shadow_mode": False}})

    metrics = cc.build_metrics(
        rows=cc.load_rows(rows),
        consistency_report=cc.load_json(consistency),
        publish_gate=cc.load_json(publish),
        sota_gate=cc.load_json(sota),
        scope_grounding=cc.load_json(scope),
        rubric_validation=cc.load_json(validation),
        rubric_verification=cc.load_json(verification),
        calibration_manifest=cc.load_json(calibration),
        pass1_dir=pass1.parent,
    )
    state, reasons = cc.evaluate_state(metrics, cc.load_live_config(config))
    assert state == "anchor_calibration_required"
    assert "synthetic_only_scope_support" in reasons
