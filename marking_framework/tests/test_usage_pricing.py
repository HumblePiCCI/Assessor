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
