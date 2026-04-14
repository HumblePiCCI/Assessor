import json
from pathlib import Path

from server.bootstrap import ensure_bootstrap_calibration, ensure_class_metadata


def test_ensure_class_metadata_existing_and_bootstrap(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    existing = {"grade_level": 10, "genre": "argumentative"}
    (inputs / "class_metadata.json").write_text(json.dumps(existing), encoding="utf-8")
    out = ensure_class_metadata(inputs)
    assert out["grade_level"] == 10
    (inputs / "class_metadata.json").write_text("{bad", encoding="utf-8")
    repaired = ensure_class_metadata(inputs)
    assert repaired["grade_level"] == 7
    assert (inputs / "class_metadata.json").exists()


def test_ensure_bootstrap_calibration_writes_once(tmp_path):
    root = tmp_path / "root"
    (root / "outputs").mkdir(parents=True, exist_ok=True)
    metadata = {"grade_level": 7, "genre": "literary_analysis"}
    path = ensure_bootstrap_calibration(root, metadata, assessors=["A", "B"])
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    manifest = json.loads((root / "outputs" / "calibration_manifest.json").read_text(encoding="utf-8"))
    scope = "grade_6_7|literary_analysis"
    assert payload["assessors"]["assessor_A"]["scopes"][scope]["samples"] == 10
    assert payload["summary"]["scope_coverage"][scope] == 20
    assert payload["synthetic"] is True
    assert manifest["synthetic"] is True
    assert manifest["scope_coverage"][0]["key"] == scope
    marker = path.read_text(encoding="utf-8")
    same = ensure_bootstrap_calibration(root, metadata, assessors=["A", "B"])
    assert same == path
    assert path.read_text(encoding="utf-8") == marker


def test_ensure_bootstrap_calibration_scope_fallback(tmp_path):
    root = tmp_path / "root"
    path = ensure_bootstrap_calibration(root, {"grade_level": "x", "genre": None}, assessors=["assessor_A"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "grade_6_7|literary_analysis" in payload["summary"]["scope_coverage"]


def test_ensure_bootstrap_calibration_uses_rubric_manifest_scope(tmp_path):
    root = tmp_path / "root"
    (root / "outputs").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "llm_routing.json").write_text(
        json.dumps({"tasks": {"pass1_assessor": {"model": "gpt-5.4-mini"}}}),
        encoding="utf-8",
    )
    (root / "outputs" / "rubric_manifest.json").write_text(
        json.dumps({"genre": "argumentative", "rubric_family": "rubric_unknown"}),
        encoding="utf-8",
    )
    path = ensure_bootstrap_calibration(
        root,
        {"grade_level": 7, "genre": "literary_analysis", "generated_by": "bootstrap"},
        assessors=["assessor_A"],
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    manifest = json.loads((root / "outputs" / "calibration_manifest.json").read_text(encoding="utf-8"))
    assert "grade_6_7|argumentative" in payload["summary"]["scope_coverage"]
    assert manifest["scope_coverage"][0]["key"] == "grade_6_7|argumentative"


def test_ensure_bootstrap_calibration_rewrites_synthetic_scope_mismatch(tmp_path):
    root = tmp_path / "root"
    (root / "outputs").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "llm_routing.json").write_text(
        json.dumps({"tasks": {"pass1_assessor": {"model": "gpt-5.4-mini"}}}),
        encoding="utf-8",
    )
    (root / "outputs" / "rubric_manifest.json").write_text(
        json.dumps({"genre": "argumentative", "rubric_family": "rubric_unknown"}),
        encoding="utf-8",
    )
    stale_payload = {
        "method": "bootstrap_neutral",
        "synthetic": True,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "scope_template": "<grade_band>|<genre>",
        "assessors": {
            "assessor_A": {
                "global": {"samples": 10},
                "scopes": {"grade_6_7|literary_analysis": {"samples": 10}},
            }
        },
        "summary": {"samples": 10, "assessors": 1, "scope_coverage": {"grade_6_7|literary_analysis": 10}},
    }
    (root / "outputs" / "calibration_bias.json").write_text(json.dumps(stale_payload), encoding="utf-8")
    (root / "outputs" / "calibration_manifest.json").write_text(
        json.dumps({"synthetic": True, "scope_coverage": [{"key": "grade_6_7|literary_analysis"}]}),
        encoding="utf-8",
    )
    path = ensure_bootstrap_calibration(
        root,
        {"grade_level": 7, "genre": "literary_analysis", "generated_by": "bootstrap"},
        assessors=["assessor_A"],
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    manifest = json.loads((root / "outputs" / "calibration_manifest.json").read_text(encoding="utf-8"))
    assert "grade_6_7|argumentative" in payload["summary"]["scope_coverage"]
    assert manifest["scope_coverage"][0]["key"] == "grade_6_7|argumentative"
