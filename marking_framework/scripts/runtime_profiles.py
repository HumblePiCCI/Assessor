#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
from pathlib import Path


DEFAULT_PROFILES_PATH = Path("config/runtime_profiles.json")
DEFAULT_ROUTING_PATH = Path("config/llm_routing.json")
DEFAULT_PROFILE_ARTIFACT = Path("outputs/runtime_profile.json")


def load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_runtime_profiles(path: Path = DEFAULT_PROFILES_PATH) -> dict:
    payload = load_json(path)
    profiles = payload.get("profiles", {})
    if not isinstance(profiles, dict):
        payload["profiles"] = {}
    return payload


def normalize_profile_name(name: str | None, payload: dict) -> str:
    candidate = str(name or "").strip()
    if candidate:
        return candidate
    return str(payload.get("default_profile") or "").strip()


def resolve_runtime_profile(name: str | None = None, path: Path = DEFAULT_PROFILES_PATH) -> dict:
    payload = load_runtime_profiles(path)
    profile_name = normalize_profile_name(name, payload)
    profiles = payload.get("profiles", {})
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        raise KeyError(f"Unknown runtime profile: {profile_name or '<default>'}")
    resolved = copy.deepcopy(profile)
    resolved["name"] = profile_name
    resolved.setdefault("enabled", True)
    resolved.setdefault("mode", "openai")
    resolved.setdefault("provider", "openai")
    resolved.setdefault("billing", {})
    resolved.setdefault("routing_overrides", {})
    return resolved


def _deep_merge(base: dict, override: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def apply_runtime_profile_to_routing(routing: dict, profile: dict | None) -> dict:
    effective = copy.deepcopy(routing or {})
    if not profile:
        return effective
    effective["mode"] = str(profile.get("mode") or effective.get("mode") or "openai")
    effective["provider"] = str(profile.get("provider") or effective.get("provider") or "openai")
    for key in ("api_key_env", "base_url_env", "responses_endpoint", "codex_cli_path", "codex_cli_interface"):
        if profile.get(key):
            effective[key] = profile[key]
    overrides = profile.get("routing_overrides", {})
    if isinstance(overrides, dict):
        effective = _deep_merge(effective, overrides)
    return effective


def effective_routing_for_profile(
    profile_name: str | None,
    *,
    root: Path = Path("."),
    profiles_path: Path = DEFAULT_PROFILES_PATH,
    routing_path: Path = DEFAULT_ROUTING_PATH,
) -> tuple[dict, dict]:
    profile = resolve_runtime_profile(profile_name, root / profiles_path if not profiles_path.is_absolute() else profiles_path)
    routing = load_json(root / routing_path if not routing_path.is_absolute() else routing_path)
    return profile, apply_runtime_profile_to_routing(routing, profile)


def billing_policy(profile: dict | None) -> dict:
    billing = (profile or {}).get("billing", {})
    if not isinstance(billing, dict):
        billing = {}
    markup = billing.get("customer_markup_percent", 0.0)
    try:
        markup = float(markup)
    except (TypeError, ValueError):
        markup = 0.0
    return {
        "billable": bool(billing.get("billable", False)),
        "customer_markup_percent": markup,
    }


def collect_task_models(routing: dict) -> list[str]:
    tasks = routing.get("tasks", {})
    if not isinstance(tasks, dict):
        return []
    models = []
    for task_cfg in tasks.values():
        if not isinstance(task_cfg, dict):
            continue
        model = str(task_cfg.get("model") or "").strip()
        if model and model not in models:
            models.append(model)
    return models


def missing_priced_models(routing: dict, pricing: dict) -> list[str]:
    priced = pricing.get("models", {})
    if not isinstance(priced, dict):
        priced = {}
    return [model for model in collect_task_models(routing) if model not in priced]


def profile_artifact(profile: dict | None, routing: dict | None = None) -> dict:
    if not profile:
        return {}
    policy = billing_policy(profile)
    return {
        "name": profile.get("name", ""),
        "label": profile.get("label", ""),
        "mode": profile.get("mode", ""),
        "provider": profile.get("provider", ""),
        "enabled": bool(profile.get("enabled", True)),
        "api_key_env": profile.get("api_key_env", ""),
        "base_url_env": profile.get("base_url_env", ""),
        "responses_endpoint": profile.get("responses_endpoint", ""),
        "codex_cli_path": profile.get("codex_cli_path", ""),
        "codex_cli_interface": profile.get("codex_cli_interface", ""),
        "billable": bool(policy.get("billable", False)),
        "billing": policy,
        "task_models": collect_task_models(routing or {}),
    }


def public_profiles_payload(path: Path = DEFAULT_PROFILES_PATH) -> dict:
    payload = load_runtime_profiles(path)
    routing_path = path.parent / "llm_routing.json"
    base_routing = load_json(routing_path)
    profiles = []
    for name, profile in sorted((payload.get("profiles", {}) or {}).items()):
        if not isinstance(profile, dict):
            continue
        resolved_profile = {"name": name, **profile}
        artifact = profile_artifact(resolved_profile, apply_runtime_profile_to_routing(base_routing, resolved_profile))
        artifact["description"] = profile.get("description", "")
        profiles.append(artifact)
    return {
        "default_profile": normalize_profile_name("", payload),
        "profiles": profiles,
    }


def write_runtime_profile_artifact(
    profile: dict | None,
    routing: dict | None = None,
    output_path: Path = DEFAULT_PROFILE_ARTIFACT,
) -> dict:
    artifact = profile_artifact(profile, routing)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    return artifact
