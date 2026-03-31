#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy


DEFAULT_PROFILE_ORDER = ("dev", "candidate", "release")


def _merge_dicts(base: dict, override: dict) -> dict:
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _profile_thresholds(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    thresholds = payload.get("thresholds")
    if isinstance(thresholds, dict):
        return thresholds
    return payload


def resolve_gate_profiles(config: dict, *, fallback_profile: str = "dev") -> tuple[list[str], str, dict[str, dict]]:
    if not isinstance(config, dict):
        config = {}
    raw_profiles = config.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        thresholds = _profile_thresholds(config.get("thresholds", config))
        target_profile = str(config.get("target_profile", fallback_profile) or fallback_profile)
        return [target_profile], target_profile, {target_profile: deepcopy(thresholds)}

    configured_order = [str(name).strip() for name in config.get("profile_order", []) if str(name).strip()]
    seen = set()
    order = []
    for name in list(DEFAULT_PROFILE_ORDER) + configured_order + sorted(raw_profiles):
        if name in raw_profiles and name not in seen:
            order.append(name)
            seen.add(name)
    target_profile = str(config.get("target_profile", order[0] if order else fallback_profile) or fallback_profile)
    if target_profile not in seen and target_profile in raw_profiles:
        order.append(target_profile)
    resolved = {}

    def resolve_profile(name: str, stack: tuple[str, ...] = ()) -> dict:
        if name in resolved:
            return resolved[name]
        if name in stack:
            raise ValueError(f"Cyclic gate profile inheritance detected: {' -> '.join(stack + (name,))}")
        payload = raw_profiles.get(name)
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid gate profile '{name}'")
        base = {}
        parent = str(payload.get("inherits", "") or "").strip()
        if parent:
            if parent not in raw_profiles:
                raise ValueError(f"Gate profile '{name}' inherits missing profile '{parent}'")
            base = resolve_profile(parent, stack + (name,))
        resolved[name] = _merge_dicts(base, _profile_thresholds(payload))
        return resolved[name]

    for name in order:
        resolve_profile(name)
    return order, target_profile, resolved


def profile_rank(order: list[str], profile: str | None) -> int:
    if not profile:
        return -1
    try:
        return order.index(profile)
    except ValueError:
        return -1


def highest_passing_profile(order: list[str], profile_results: dict[str, dict]) -> str:
    highest = ""
    best_rank = -1
    for name in order:
        result = profile_results.get(name, {})
        if not result.get("ok", False):
            continue
        rank = profile_rank(order, name)
        if rank >= best_rank:
            highest = name
            best_rank = rank
    return highest


def decision_state(order: list[str], highest_profile: str) -> str:
    if not highest_profile:
        return "blocked"
    if highest_profile == "release":
        return "release_ready"
    if highest_profile == "candidate":
        return "candidate_ready"
    if "release" in order or "candidate" in order:
        return "development_only"
    return highest_profile
