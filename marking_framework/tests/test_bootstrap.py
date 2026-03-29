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
    scope = "grade_6_7|literary_analysis"
    assert payload["assessors"]["assessor_A"]["scopes"][scope]["samples"] == 10
    assert payload["summary"]["scope_coverage"][scope] == 20
    marker = path.read_text(encoding="utf-8")
    same = ensure_bootstrap_calibration(root, metadata, assessors=["A", "B"])
    assert same == path
    assert path.read_text(encoding="utf-8") == marker


def test_ensure_bootstrap_calibration_scope_fallback(tmp_path):
    root = tmp_path / "root"
    path = ensure_bootstrap_calibration(root, {"grade_level": "x", "genre": None}, assessors=["assessor_A"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "grade_6_7|literary_analysis" in payload["summary"]["scope_coverage"]
