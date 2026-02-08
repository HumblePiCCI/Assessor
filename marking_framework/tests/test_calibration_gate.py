import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.calibration_gate import calibration_gate_error


def test_calibration_gate_disabled():
    assert calibration_gate_error({"calibration_gate": {"enabled": False}}, ["A"], "grade_8_10|literary_analysis") is None


def test_calibration_gate_missing_bias_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    routing = {"calibration_gate": {"enabled": True, "bias_path": "outputs/calibration_bias.json"}}
    err = calibration_gate_error(routing, ["A"], "grade_8_10|literary_analysis")
    assert "missing bias file" in err


def test_calibration_gate_stale_timestamp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = Path("outputs")
    out.mkdir(parents=True, exist_ok=True)
    stale = (datetime.now(timezone.utc) - timedelta(hours=200)).isoformat()
    payload = {"generated_at": stale, "assessors": {}}
    (out / "calibration_bias.json").write_text(json.dumps(payload), encoding="utf-8")
    routing = {"calibration_gate": {"enabled": True, "max_age_hours": 24}}
    err = calibration_gate_error(routing, ["A"], "grade_8_10|literary_analysis")
    assert "stale" in err


def test_calibration_gate_requires_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = Path("outputs")
    out.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "assessors": {}}
    (out / "calibration_bias.json").write_text(json.dumps(payload), encoding="utf-8")
    routing = {"calibration_gate": {"enabled": True}}
    err = calibration_gate_error(routing, ["A"], "")
    assert "missing grade/genre scope" in err


def test_calibration_gate_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = Path("outputs")
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "generated_at": now,
        "assessors": {
            "assessor_A": {
                "scopes": {
                    "grade_8_10|literary_analysis": {"samples": 12, "weight": 0.9}
                }
            }
        },
    }
    (out / "calibration_bias.json").write_text(json.dumps(payload), encoding="utf-8")
    routing = {"calibration_gate": {"enabled": True, "max_age_hours": 48, "min_scope_samples": 10, "min_scope_weight": 0.6}}
    assert calibration_gate_error(routing, ["A"], "grade_8_10|literary_analysis") is None


def test_calibration_gate_uses_observations_when_present(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = Path("outputs")
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "generated_at": now,
        "assessors": {
            "assessor_A": {
                "scopes": {
                    "grade_8_10|literary_analysis": {
                        "samples": 5,
                        "observations": 15,
                        "weight": 0.9,
                    }
                }
            }
        },
    }
    (out / "calibration_bias.json").write_text(json.dumps(payload), encoding="utf-8")
    routing = {"calibration_gate": {"enabled": True, "min_scope_samples": 10, "min_scope_weight": 0.6}}
    assert calibration_gate_error(routing, ["A"], "grade_8_10|literary_analysis") is None
