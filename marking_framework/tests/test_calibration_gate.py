import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.calibration_gate import _parse_iso8601, calibration_gate_error, inspect_calibration_profile


def test_calibration_gate_disabled():
    assert calibration_gate_error({"calibration_gate": {"enabled": False}}, ["A"], "grade_8_10|literary_analysis") is None


def test_parse_iso8601_variants():
    assert _parse_iso8601(None) is None
    assert _parse_iso8601("not-a-date") is None
    naive = _parse_iso8601("2026-02-08T10:00:00")
    assert naive is not None and naive.tzinfo is not None


def test_calibration_gate_missing_bias_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    routing = {"calibration_gate": {"enabled": True, "bias_path": "outputs/calibration_bias.json"}}
    err = calibration_gate_error(routing, ["A"], "grade_8_10|literary_analysis")
    assert "missing bias file" in err


def test_calibration_gate_invalid_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = Path("outputs")
    out.mkdir(parents=True, exist_ok=True)
    (out / "calibration_bias.json").write_text("{bad", encoding="utf-8")
    routing = {"calibration_gate": {"enabled": True, "bias_path": "outputs/calibration_bias.json"}}
    err = calibration_gate_error(routing, ["A"], "grade_8_10|literary_analysis")
    assert "invalid JSON" in err


def test_calibration_gate_missing_timestamp_when_required(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = Path("outputs")
    out.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": "bad-date", "assessors": {}}
    (out / "calibration_bias.json").write_text(json.dumps(payload), encoding="utf-8")
    routing = {"calibration_gate": {"enabled": True, "max_age_hours": 24}}
    err = calibration_gate_error(routing, ["A"], "grade_8_10|literary_analysis")
    assert "missing valid generated_at" in err


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


def test_calibration_gate_missing_profile_and_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = Path("outputs")
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    payload = {"generated_at": now, "assessors": {"assessor_A": {"scopes": {}}}}
    (out / "calibration_bias.json").write_text(json.dumps(payload), encoding="utf-8")
    routing = {"calibration_gate": {"enabled": True}}
    err = calibration_gate_error(routing, ["B"], "grade_8_10|literary_analysis")
    assert "missing profile" in err
    err2 = calibration_gate_error(routing, ["A"], "grade_8_10|literary_analysis")
    assert "missing scoped profile" in err2


def test_calibration_gate_samples_and_weight_thresholds(tmp_path, monkeypatch):
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
                        "samples": 3,
                        "weight": 0.2,
                    }
                }
            }
        },
    }
    (out / "calibration_bias.json").write_text(json.dumps(payload), encoding="utf-8")
    routing = {"calibration_gate": {"enabled": True, "min_scope_samples": 10, "min_scope_weight": 0.6}}
    err = calibration_gate_error(routing, ["A"], "grade_8_10|literary_analysis")
    assert "observations" in err
    payload["assessors"]["assessor_A"]["scopes"]["grade_8_10|literary_analysis"]["samples"] = 12
    (out / "calibration_bias.json").write_text(json.dumps(payload), encoding="utf-8")
    err2 = calibration_gate_error(routing, ["A"], "grade_8_10|literary_analysis")
    assert "weight" in err2


def test_calibration_gate_each_quality_threshold(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = Path("outputs")
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    base = {
        "samples": 12,
        "weight": 0.9,
        "level_hit_rate": 0.9,
        "mae": 3.0,
        "pairwise_order_agreement": 0.9,
        "repeat_level_consistency": 0.95,
        "bias": 0.5,
    }
    routing = {
        "calibration_gate": {
            "enabled": True,
            "min_scope_level_hit_rate": 0.8,
            "max_scope_mae": 8.0,
            "min_scope_pairwise_order_agreement": 0.8,
            "min_scope_repeat_level_consistency": 0.8,
            "max_scope_abs_bias": 6.0,
        }
    }

    def write_scope(values):
        payload = {
            "generated_at": now,
            "assessors": {"assessor_A": {"scopes": {"grade_8_10|literary_analysis": values}}},
        }
        (out / "calibration_bias.json").write_text(json.dumps(payload), encoding="utf-8")

    bad = dict(base); bad["mae"] = 9.0
    write_scope(bad)
    assert "mae" in calibration_gate_error(routing, ["A"], "grade_8_10|literary_analysis")

    bad = dict(base); bad["pairwise_order_agreement"] = 0.7
    write_scope(bad)
    assert "pairwise_order_agreement" in calibration_gate_error(routing, ["A"], "grade_8_10|literary_analysis")

    bad = dict(base); bad["repeat_level_consistency"] = 0.7
    write_scope(bad)
    assert "repeat_level_consistency" in calibration_gate_error(routing, ["A"], "grade_8_10|literary_analysis")

    bad = dict(base); bad["bias"] = 7.0
    write_scope(bad)
    assert "|bias|" in calibration_gate_error(routing, ["A"], "grade_8_10|literary_analysis")


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


def test_calibration_gate_quality_thresholds_fail(tmp_path, monkeypatch):
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
                        "samples": 12,
                        "weight": 0.9,
                        "level_hit_rate": 0.6,
                        "mae": 9.0,
                        "pairwise_order_agreement": 0.7,
                        "repeat_level_consistency": 0.7,
                        "bias": 8.0,
                    }
                }
            }
        },
    }
    (out / "calibration_bias.json").write_text(json.dumps(payload), encoding="utf-8")
    routing = {
        "calibration_gate": {
            "enabled": True,
            "min_scope_level_hit_rate": 0.8,
            "max_scope_mae": 8.0,
            "min_scope_pairwise_order_agreement": 0.8,
            "min_scope_repeat_level_consistency": 0.8,
            "max_scope_abs_bias": 6.0,
        }
    }
    err = calibration_gate_error(routing, ["A"], "grade_8_10|literary_analysis")
    assert "level_hit_rate" in err


def test_calibration_gate_quality_thresholds_success(tmp_path, monkeypatch):
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
                        "samples": 12,
                        "weight": 0.9,
                        "level_hit_rate": 0.9,
                        "mae": 3.0,
                        "pairwise_order_agreement": 0.9,
                        "repeat_level_consistency": 0.95,
                        "bias": 1.5,
                    }
                }
            }
        },
    }
    (out / "calibration_bias.json").write_text(json.dumps(payload), encoding="utf-8")
    routing = {
        "calibration_gate": {
            "enabled": True,
            "min_scope_level_hit_rate": 0.8,
            "max_scope_mae": 8.0,
            "min_scope_pairwise_order_agreement": 0.8,
            "min_scope_repeat_level_consistency": 0.8,
            "max_scope_abs_bias": 6.0,
        }
    }
    assert calibration_gate_error(routing, ["A"], "grade_8_10|literary_analysis") is None


def test_calibration_gate_manifest_integrity_and_scope_mismatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = Path("outputs")
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assessors": {
            "assessor_A": {
                "scopes": {
                    "grade_8_10|literary_analysis": {
                        "samples": 12,
                        "weight": 0.9,
                    }
                }
            }
        },
    }
    bias_path = out / "calibration_bias.json"
    bias_path.write_text(json.dumps(payload), encoding="utf-8")
    (out / "calibration_manifest.json").write_text(
        json.dumps(
            {
                "generated_at": payload["generated_at"],
                "synthetic": False,
                "scope_coverage": [
                    {
                        "key": "grade_8_10|literary_analysis",
                        "grade_band": "grade_8_10",
                        "genre": "literary_analysis",
                        "rubric_family": "rubric_real",
                        "model_family": "gpt-5.2",
                    }
                ],
                "artifact_hashes": {"calibration_bias_sha256": "wrong"},
                "routing_profile_hash": "abc",
                "rubric_hash": "rubric",
                "source_exemplar_set_hash": "ex",
            }
        ),
        encoding="utf-8",
    )
    routing = {
        "calibration_gate": {
            "enabled": True,
            "require_manifest": True,
        }
    }
    err = calibration_gate_error(routing, ["A"], {"key": "grade_8_10|literary_analysis"})
    assert "artifact hash" in err

    report = inspect_calibration_profile(
        bias_path,
        ["A"],
        {
            "key": "grade_8_10|literary_analysis",
            "grade_band": "grade_8_10",
            "genre": "literary_analysis",
            "rubric_family": "rubric_other",
            "model_family": "gpt-5.2",
        },
    )
    assert "rubric_family" in report["scope_mismatch_fields"]
