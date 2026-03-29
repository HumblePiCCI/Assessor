import json

import scripts.sota_gate as sg


def _write_pass1(path, assessor_id, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"assessor_id": assessor_id, "scores": rows}
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_helpers_and_core_metrics(tmp_path):
    assert sg.load_json(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{bad", encoding="utf-8")
    assert sg.load_json(bad) == {}
    assert sg.model_coverage([]) == 0.0
    assert sg.score_rate([]) == 0.0
    assert sg.criteria_coverage([]) == 0.0
    assert sg.evidence_coverage([]) == 0.0

    pass1_file = tmp_path / "assessments/pass1_individual/assessor_A.json"
    _write_pass1(
        pass1_file,
        "assessor_A",
        [
            {
                "student_id": "s1",
                "rubric_total_points": 80,
                "criteria_points": {"K1": 70},
                "criteria_evidence": [{"criterion_id": "K1"}],
                "notes": "Model score",
            },
            {
                "student_id": "s2",
                "rubric_total_points": 0,
                "criteria_points": {},
                "criteria_evidence": [],
                "notes": "Fallback deterministic score",
            },
        ],
    )
    rows = sg.load_pass1_rows(pass1_file.parent)
    assert len(rows) == 2
    assert all(row["assessor_id"] == "assessor_A" for row in rows)
    assert sg.model_coverage(rows) == 0.5
    assert sg.score_rate(rows) == 0.5
    assert sg.criteria_coverage(rows) == 0.5
    assert sg.evidence_coverage(rows) == 0.5
    assert round(sg.score_rate(rows + [{"rubric_total_points": "oops"}]), 5) == round(1 / 3, 5)

    assert sg._stdev([]) == 0.0
    assert sg._stdev([1.0]) == 0.0
    assert round(sg._stdev([0.0, 2.0]), 5) == 1.0
    assert sg._percentile([], 0.95) == 0.0
    assert sg._percentile([1.0, 2.0, 3.0], 0.0) == 1.0
    assert sg._percentile([1.0, 2.0, 3.0], 0.95) == 3.0


def test_assessor_spread_and_consistency_metrics(tmp_path):
    _write_pass1(
        tmp_path / "assessments/pass1_individual/assessor_A.json",
        "assessor_A",
        [{"student_id": "s1", "rubric_total_points": 70, "notes": "ok"}],
    )
    _write_pass1(
        tmp_path / "assessments/pass1_individual/assessor_B.json",
        "assessor_B",
        [{"student_id": "s1", "rubric_total_points": 90, "notes": "ok"}],
    )
    rows = sg.load_pass1_rows(tmp_path / "assessments/pass1_individual")
    mean_sd, p95_sd = sg.assessor_spread(rows)
    assert mean_sd > 0
    assert p95_sd >= mean_sd
    assert sg.assessor_spread([{"student_id": "", "rubric_total_points": 70}, {"student_id": "s1", "rubric_total_points": "oops"}]) == (0.0, 0.0)

    assert sg.consistency_metrics(tmp_path / "missing.json") == (0, 0.0, 0.0)
    checks_path = tmp_path / "outputs/consistency_checks.json"
    checks_path.parent.mkdir(parents=True, exist_ok=True)
    checks_path.write_text(
        json.dumps(
            {
                "checks": [
                    {"decision": "KEEP", "confidence": "high"},
                    {"decision": "SWAP", "confidence": "low"},
                    {"decision": "SWAP", "confidence": "medium"},
                ]
            }
        ),
        encoding="utf-8",
    )
    total, swap_rate, low_rate = sg.consistency_metrics(checks_path)
    assert total == 3
    assert round(swap_rate, 5) == round(2 / 3, 5)
    assert round(low_rate, 5) == round(1 / 3, 5)


def test_evaluate_covers_failure_codes():
    metrics = {
        "publish_gate_present": False,
        "publish_gate_ok": False,
        "assessor_files": 1,
        "model_coverage": 0.1,
        "nonzero_score_rate": 0.1,
        "criteria_coverage": 0.1,
        "evidence_coverage": 0.1,
        "mean_assessor_sd": 20.0,
        "p95_assessor_sd": 25.0,
        "consistency_swap_rate": 0.9,
        "consistency_low_confidence_rate": 0.9,
    }
    thresholds = {
        "require_publish_gate_ok": True,
        "min_assessor_files": 3,
        "min_model_coverage": 0.9,
        "min_nonzero_score_rate": 0.9,
        "min_criteria_coverage": 0.9,
        "min_evidence_coverage": 0.8,
        "max_mean_assessor_sd": 10.0,
        "max_p95_assessor_sd": 15.0,
        "max_consistency_swap_rate": 0.3,
        "max_consistency_low_confidence_rate": 0.5,
    }
    failures = sg.evaluate(metrics, thresholds)
    assert "publish_gate_not_ok" in failures
    assert "publish_gate_missing" in failures
    assert "assessor_count_below_threshold" in failures
    assert "model_coverage_below_threshold" in failures
    assert "nonzero_score_rate_below_threshold" in failures
    assert "criteria_coverage_below_threshold" in failures
    assert "evidence_coverage_below_threshold" in failures
    assert "mean_assessor_sd_above_threshold" in failures
    assert "p95_assessor_sd_above_threshold" in failures
    assert "consistency_swap_rate_above_threshold" in failures
    assert "consistency_low_confidence_rate_above_threshold" in failures


def test_main_success_and_failure(tmp_path, monkeypatch):
    pass1_dir = tmp_path / "assessments/pass1_individual"
    rows_a = [
        {
            "student_id": "s1",
            "rubric_total_points": 82,
            "criteria_points": {"K1": 81},
            "criteria_evidence": [{"criterion_id": "K1"}],
            "notes": "Model score",
        },
        {
            "student_id": "s2",
            "rubric_total_points": 74,
            "criteria_points": {"K1": 73},
            "criteria_evidence": [{"criterion_id": "K1"}],
            "notes": "Model score",
        },
    ]
    rows_b = [dict(item, rubric_total_points=item["rubric_total_points"] + 1) for item in rows_a]
    rows_c = [dict(item, rubric_total_points=item["rubric_total_points"] - 1) for item in rows_a]
    _write_pass1(pass1_dir / "assessor_A.json", "assessor_A", rows_a)
    _write_pass1(pass1_dir / "assessor_B.json", "assessor_B", rows_b)
    _write_pass1(pass1_dir / "assessor_C.json", "assessor_C", rows_c)

    publish = tmp_path / "outputs/publish_gate.json"
    publish.parent.mkdir(parents=True, exist_ok=True)
    publish.write_text(json.dumps({"ok": True}), encoding="utf-8")
    consistency = tmp_path / "outputs/consistency_checks.json"
    consistency.write_text(json.dumps({"checks": [{"decision": "KEEP", "confidence": "high"}]}), encoding="utf-8")

    config = tmp_path / "config/sota_gate.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "thresholds": {
                    "require_publish_gate_ok": True,
                    "min_assessor_files": 3,
                    "min_model_coverage": 0.8,
                    "min_nonzero_score_rate": 1.0,
                    "min_criteria_coverage": 1.0,
                    "min_evidence_coverage": 1.0,
                    "max_mean_assessor_sd": 5.0,
                    "max_p95_assessor_sd": 6.0,
                    "max_consistency_swap_rate": 0.2,
                    "max_consistency_low_confidence_rate": 0.2,
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "sota_gate",
            "--publish-gate",
            "outputs/publish_gate.json",
            "--pass1",
            "assessments/pass1_individual",
            "--consistency",
            "outputs/consistency_checks.json",
            "--gate-config",
            "config/sota_gate.json",
            "--output",
            "outputs/sota_gate.json",
        ],
    )
    assert sg.main() == 0
    payload = json.loads((tmp_path / "outputs/sota_gate.json").read_text(encoding="utf-8"))
    assert payload["ok"] is True

    (tmp_path / "outputs/publish_gate.json").write_text(json.dumps({"ok": False}), encoding="utf-8")
    assert sg.main() == 2
    failed = json.loads((tmp_path / "outputs/sota_gate.json").read_text(encoding="utf-8"))
    assert failed["ok"] is False
    assert "publish_gate_not_ok" in failed["failures"]
