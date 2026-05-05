import json

import scripts.runtime_profiles as rp


def test_runtime_profile_applies_deep_routing_overrides(tmp_path):
    profiles = tmp_path / "runtime_profiles.json"
    profiles.write_text(
        json.dumps(
            {
                "default_profile": "internal_codex",
                "profiles": {
                    "internal_codex": {
                        "mode": "codex_local",
                        "provider": "openai-codex",
                        "codex_cli_path": "/tmp/codex-app-cli",
                        "codex_cli_interface": "exec",
                        "billing": {"billable": False, "customer_markup_percent": 0.0},
                        "routing_overrides": {
                            "tasks": {
                                "pairwise_escalator": {"model": "gpt-5.5", "reasoning": "medium"},
                            }
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    profile = rp.resolve_runtime_profile("", profiles)
    routing = rp.apply_runtime_profile_to_routing(
        {
            "mode": "openai",
            "tasks": {
                "pairwise_escalator": {"model": "gpt-5.4", "reasoning": "low", "temperature": 0.0},
                "pass1_assessor": {"model": "gpt-5.4-mini"},
            },
        },
        profile,
    )
    assert routing["mode"] == "codex_local"
    assert routing["provider"] == "openai-codex"
    assert routing["codex_cli_path"] == "/tmp/codex-app-cli"
    assert routing["codex_cli_interface"] == "exec"
    assert routing["tasks"]["pairwise_escalator"]["model"] == "gpt-5.5"
    assert routing["tasks"]["pairwise_escalator"]["temperature"] == 0.0
    assert rp.profile_artifact(profile, routing)["task_models"] == ["gpt-5.5", "gpt-5.4-mini"]


def test_missing_priced_models_uses_effective_task_models():
    routing = {
        "tasks": {
            "a": {"model": "priced"},
            "b": {"model": "missing"},
            "c": {"model": "missing"},
        }
    }
    pricing = {"models": {"priced": {"input_per_million": 1.0, "output_per_million": 2.0}}}
    assert rp.missing_priced_models(routing, pricing) == ["missing"]


def test_public_profiles_payload_includes_effective_task_models(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "llm_routing.json").write_text(
        json.dumps({"mode": "openai", "tasks": {"pairwise_escalator": {"model": "gpt-5.4"}}}),
        encoding="utf-8",
    )
    profiles = config / "runtime_profiles.json"
    profiles.write_text(
        json.dumps(
            {
                "default_profile": "internal_codex",
                "profiles": {
                    "internal_codex": {
                        "mode": "codex_local",
                        "provider": "openai-codex",
                        "codex_cli_path": "/tmp/codex-app-cli",
                        "codex_cli_interface": "exec",
                        "billing": {"billable": False, "customer_markup_percent": 0.0},
                        "routing_overrides": {"tasks": {"pairwise_escalator": {"model": "gpt-5.5"}}},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    payload = rp.public_profiles_payload(profiles)
    assert payload["profiles"][0]["task_models"] == ["gpt-5.5"]
