import json
from pathlib import Path

import scripts.usage_pricing as up


def test_usage_pricing_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["up", "--usage", str(tmp_path / "missing.jsonl"), "--pricing", str(tmp_path / "pricing.json")])
    assert up.main() == 1


def test_usage_pricing_success(tmp_path, monkeypatch):
    usage = tmp_path / "usage.jsonl"
    usage.write_text(
        json.dumps({"model": "gpt-5.2", "usage": {"input_tokens": 1000, "output_tokens": 500}}) + "\n" +
        "\n" +
        json.dumps({"model": "gpt-5.2", "usage": {"input_tokens": 1, "output_tokens": 1}}) + "\n" +
        json.dumps({"model": "unknown", "usage": {"input_tokens": 1, "output_tokens": 1}}),
        encoding="utf-8"
    )
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({"currency": "USD", "models": {"gpt-5.2": {"input_per_million": 1.0, "output_per_million": 2.0}}}), encoding="utf-8")
    out = tmp_path / "out.json"

    monkeypatch.setattr("sys.argv", ["up", "--usage", str(usage), "--pricing", str(pricing), "--output", str(out)])
    assert up.main() == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["grand_total"] > 0
    assert report["api_cost_total"] == report["grand_total"]
    assert report["customer_total"] == report["grand_total"]


def test_usage_pricing_billable_profile_adds_markup_and_cached_rate(tmp_path, monkeypatch):
    usage = tmp_path / "usage.jsonl"
    usage.write_text(
        json.dumps(
            {
                "model": "gpt-5.4-mini",
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "input_tokens_details": {"cached_tokens": 400},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    pricing = tmp_path / "pricing.json"
    pricing.write_text(
        json.dumps(
            {
                "currency": "USD",
                "models": {
                    "gpt-5.4-mini": {
                        "input_per_million": 1.0,
                        "cached_input_per_million": 0.1,
                        "output_per_million": 2.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    profiles = tmp_path / "profiles.json"
    profiles.write_text(
        json.dumps(
            {
                "default_profile": "teacher_payg_openai",
                "profiles": {
                    "teacher_payg_openai": {
                        "mode": "openai",
                        "provider": "openai",
                        "billing": {"billable": True, "customer_markup_percent": 10.0},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "up",
            "--usage",
            str(usage),
            "--pricing",
            str(pricing),
            "--profiles",
            str(profiles),
            "--profile",
            "teacher_payg_openai",
            "--output",
            str(out),
        ],
    )
    assert up.main() == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["billable"] is True
    assert report["models"]["gpt-5.4-mini"]["cached_input_tokens"] == 400
    assert report["api_cost_total"] == 0.00164
    assert report["service_fee"] == 0.000164
    assert report["customer_total"] == 0.001804


def test_usage_pricing_billable_profile_fails_on_unpriced_model(tmp_path, monkeypatch):
    usage = tmp_path / "usage.jsonl"
    usage.write_text(json.dumps({"model": "unknown", "usage": {"input_tokens": 100, "output_tokens": 50}}), encoding="utf-8")
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({"currency": "USD", "models": {}}), encoding="utf-8")
    out = tmp_path / "out.json"
    monkeypatch.setattr("sys.argv", ["up", "--usage", str(usage), "--pricing", str(pricing), "--billable", "--output", str(out)])
    assert up.main() == 2
    report = json.loads(out.read_text(encoding="utf-8"))
    assert "unknown" in report["unpriced_models"]


def test_usage_pricing_empty(tmp_path, monkeypatch):
    usage = tmp_path / "usage.jsonl"
    usage.write_text("", encoding="utf-8")
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({"currency": "USD", "models": {}}), encoding="utf-8")
    out = tmp_path / "out.json"
    monkeypatch.setattr("sys.argv", ["up", "--usage", str(usage), "--pricing", str(pricing), "--output", str(out)])
    assert up.main() == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["grand_total"] == 0.0
