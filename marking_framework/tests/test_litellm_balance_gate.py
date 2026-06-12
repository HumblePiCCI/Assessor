import json
from pathlib import Path

import pytest

from scripts import litellm_balance_gate as gate


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_run_inputs(root: Path):
    (root / "inputs" / "submissions").mkdir(parents=True, exist_ok=True)
    (root / "inputs" / "rubric.md").write_text("Score with a concise rubric.", encoding="utf-8")
    (root / "inputs" / "assignment_outline.md").write_text("Write a persuasive paragraph.", encoding="utf-8")
    (root / "inputs" / "submissions" / "s1.txt").write_text("This is my paragraph.", encoding="utf-8")


def _write_metered_config(root: Path):
    _write_json(
        root / "config" / "llm_routing.json",
        {
            "api_provider": "metered",
            "tasks": {
                "pass1_assessor": {"model": "gpt-5.4-mini"},
                "pass2_ranker": {"model": "gpt-5.4-mini"},
            },
            "providers": {
                "metered": {
                    "kind": "openai_responses",
                    "base_url": "https://proxy.example.test/v1",
                    "responses_endpoint": "/responses",
                    "api_key_env": "LITELLM_VIRTUAL_KEY",
                    "balance_check": {
                        "enabled": True,
                        "self_service_endpoint": "https://credits.example.test/credits/me",
                        "cost_markup_multiplier": 1.15,
                        "safety_multiplier": 1.2,
                        "minimum_remaining_usd": 1.0,
                    },
                }
            },
        },
    )
    _write_json(
        root / "config" / "pricing.json",
        {"models": {"gpt-5.4-mini": {"input_per_million": 0.75, "output_per_million": 4.5}}},
    )
    _write_json(
        root / "config" / "cost_limits.json",
        {
            "per_call_max_tokens": 8000,
            "abort_on_limit": True,
            "estimates": {"pass1_output_tokens": 300, "pass2_output_tokens": 200},
        },
    )


def test_prepaid_balance_gate_passes_with_enough_credit(tmp_path, monkeypatch):
    _write_run_inputs(tmp_path)
    _write_metered_config(tmp_path)
    monkeypatch.setattr(
        gate,
        "fetch_credit_status",
        lambda provider, check, api_key: {"remaining_budget": 25.0, "currency": "USD"},
    )

    result = gate.validate_credit_balance_for_run(
        root=tmp_path,
        rubric_path=tmp_path / "inputs" / "rubric.md",
        outline_path=tmp_path / "inputs" / "assignment_outline.md",
        submissions_dir=tmp_path / "inputs" / "submissions",
        api_key="sk-tester",
    )

    assert result["enabled"] is True
    assert result["ok"] is True
    assert result["provider"] == "metered"
    assert result["remaining_credit_usd"] == 25.0
    assert result["required_credit_usd"] >= 1.0


def test_prepaid_balance_gate_blocks_low_credit(tmp_path, monkeypatch):
    _write_run_inputs(tmp_path)
    _write_metered_config(tmp_path)
    monkeypatch.setattr(
        gate,
        "fetch_credit_status",
        lambda provider, check, api_key: {"remaining_budget": 0.25, "currency": "USD"},
    )

    with pytest.raises(gate.BalanceGateError, match="Insufficient prepaid LLM credit"):
        gate.validate_credit_balance_for_run(
            root=tmp_path,
            rubric_path=tmp_path / "inputs" / "rubric.md",
            outline_path=tmp_path / "inputs" / "assignment_outline.md",
            submissions_dir=tmp_path / "inputs" / "submissions",
            api_key="sk-tester",
        )


def test_prepaid_balance_gate_requires_safe_endpoint_or_admin_key(tmp_path, monkeypatch):
    _write_run_inputs(tmp_path)
    _write_metered_config(tmp_path)
    routing_path = tmp_path / "config" / "llm_routing.json"
    routing = json.loads(routing_path.read_text(encoding="utf-8"))
    check = routing["providers"]["metered"]["balance_check"]
    check.pop("self_service_endpoint")
    check["key_info_endpoint"] = "https://proxy.example.test/key/info"
    routing_path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)

    with pytest.raises(gate.BalanceGateError, match="tester-local installs should use a self_service_endpoint"):
        gate.validate_credit_balance_for_run(
            root=tmp_path,
            rubric_path=tmp_path / "inputs" / "rubric.md",
            outline_path=tmp_path / "inputs" / "assignment_outline.md",
            submissions_dir=tmp_path / "inputs" / "submissions",
            api_key="sk-tester",
        )
