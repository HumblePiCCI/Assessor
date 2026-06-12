#!/usr/bin/env python3
"""Preflight prepaid LiteLLM credit before API-provider cohort runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from scripts.llm_assessors_core import load_json, load_routing, preflight_costs


TEXT_SUFFIXES = {".csv", ".json", ".md", ".rtf", ".text", ".tsv", ".txt", ".xml", ".yaml", ".yml"}


class BalanceGateError(RuntimeError):
    """Raised when a prepaid credit gate is enabled but cannot pass."""


def _active_provider(routing: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    name = (
        os.environ.get("LLM_API_PROVIDER")
        or os.environ.get("API_PROVIDER")
        or routing.get("api_provider")
        or routing.get("provider")
        or "openai"
    )
    provider_name = str(name or "openai").strip() or "openai"
    providers = routing.get("providers", {}) if isinstance(routing.get("providers"), dict) else {}
    provider = providers.get(provider_name)
    if not isinstance(provider, dict) and provider_name == "openai":
        provider = dict(routing.get("openai", {}) if isinstance(routing.get("openai"), dict) else {})
        provider.setdefault("kind", "openai_responses")
        provider.setdefault("api_key_env", "OPENAI_API_KEY")
    if not isinstance(provider, dict):
        return provider_name, {}
    provider = dict(provider)
    provider.setdefault("name", provider_name)
    return provider_name, provider


def active_balance_check(routing: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    provider_name, provider = _active_provider(routing)
    check = provider.get("balance_check", {})
    if not isinstance(check, dict):
        check = {}
    return provider_name, provider, check


def balance_check_enabled(routing: dict[str, Any]) -> bool:
    _, _, check = active_balance_check(routing)
    return bool(check.get("enabled", False))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_cost_text(path: Path) -> str:
    suffix = path.suffix.lower()
    try:
        decoded = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        decoded = ""
    if suffix in TEXT_SUFFIXES:
        return decoded
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if len(decoded) >= size:
        return decoded
    return decoded + ("\n" + ("x" * max(0, size - len(decoded))))


def _submission_texts(submissions_dir: Path) -> dict[str, str]:
    texts: dict[str, str] = {}
    if not submissions_dir.exists():
        return texts
    for path in sorted(item for item in submissions_dir.iterdir() if item.is_file()):
        texts[path.stem.strip() or path.name] = _read_cost_text(path)
    return texts


def estimate_run_cost_usd(
    *,
    root: Path,
    rubric_path: Path,
    outline_path: Path,
    submissions_dir: Path,
    routing_path: Path | None = None,
    pricing_path: Path | None = None,
    cost_limits_path: Path | None = None,
) -> dict[str, Any]:
    routing = load_routing(routing_path or (root / "config" / "llm_routing.json"))
    pricing = load_json(pricing_path or (root / "config" / "pricing.json"))
    limits = load_json(cost_limits_path or (root / "config" / "cost_limits.json"))
    texts = _submission_texts(submissions_dir)
    rubric = _read_cost_text(rubric_path)
    outline = _read_cost_text(outline_path)
    summaries = [
        {"student_id": student_id, "summary": text[:1200].replace("\n", " ")}
        for student_id, text in texts.items()
    ]
    estimate = preflight_costs(texts, rubric, outline, summaries, routing, pricing, limits)
    estimate["student_count"] = len(texts)
    return estimate


def _parse_litellm_balance(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if not isinstance(payload, dict):
        raise BalanceGateError("Credit endpoint returned a non-object response")
    candidates: list[dict[str, Any]] = []
    candidates.append(payload)
    for key in ("info", "key", "data", "token"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
    remaining = None
    for item in candidates:
        for key in ("remaining_budget", "remaining_balance", "remaining", "balance", "available_budget"):
            if key in item:
                remaining = _safe_float(item.get(key), 0.0)
                break
        if remaining is not None:
            break
    spend = max(_safe_float(item.get("spend"), 0.0) for item in candidates)
    max_budget = max(_safe_float(item.get("max_budget"), 0.0) for item in candidates)
    if remaining is None and max_budget > 0:
        remaining = max(0.0, max_budget - spend)
    if remaining is None:
        raise BalanceGateError("Credit endpoint did not include remaining budget or max_budget/spend")
    return {
        "remaining_budget": round(float(remaining), 6),
        "spend": round(float(spend), 6),
        "max_budget": round(float(max_budget), 6) if max_budget else None,
        "currency": str(payload.get("currency") or "USD"),
    }


def _get_json(url: str, token: str, timeout_seconds: float) -> Any:
    request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else str(exc)
        raise BalanceGateError(f"Credit endpoint returned HTTP {exc.code}: {detail[:200]}") from exc
    except URLError as exc:
        raise BalanceGateError(f"Credit endpoint is unreachable: {exc.reason}") from exc
    except TimeoutError as exc:
        raise BalanceGateError("Credit endpoint timed out") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BalanceGateError("Credit endpoint returned invalid JSON") from exc


def fetch_credit_status(provider: dict[str, Any], check: dict[str, Any], api_key: str) -> dict[str, Any]:
    timeout_seconds = _safe_float(check.get("timeout_seconds"), 5.0)
    self_service_endpoint = str(check.get("self_service_endpoint") or check.get("status_endpoint") or "").strip()
    if self_service_endpoint:
        return _parse_litellm_balance(_get_json(self_service_endpoint, api_key, timeout_seconds))

    key_info_endpoint = str(check.get("key_info_endpoint") or "").strip()
    admin_base_url = str(check.get("admin_base_url") or "").rstrip("/")
    if not key_info_endpoint and admin_base_url:
        key_info_endpoint = f"{admin_base_url}/key/info"
    if not key_info_endpoint:
        raise BalanceGateError("Balance check is enabled but no self_service_endpoint or key_info_endpoint is configured")

    master_key_env = str(check.get("master_key_env") or "LITELLM_MASTER_KEY")
    master_key = os.environ.get(master_key_env, "").strip()
    if not master_key:
        raise BalanceGateError(
            f"Balance check requires {master_key_env}; tester-local installs should use a self_service_endpoint instead"
        )
    sep = "&" if "?" in key_info_endpoint else "?"
    url = f"{key_info_endpoint}{sep}{urlencode({'key': api_key})}"
    return _parse_litellm_balance(_get_json(url, master_key, timeout_seconds))


def validate_credit_balance_for_run(
    *,
    root: Path,
    rubric_path: Path,
    outline_path: Path,
    submissions_dir: Path,
    api_key: str | None,
) -> dict[str, Any]:
    routing_path = root / "config" / "llm_routing.json"
    if not routing_path.exists():
        return {"enabled": False, "ok": True, "provider": ""}
    routing = load_routing(routing_path)
    provider_name, provider, check = active_balance_check(routing)
    if not check.get("enabled", False):
        return {"enabled": False, "ok": True, "provider": provider_name}
    if not api_key:
        raise BalanceGateError(f"{provider_name} balance check is enabled but no provider key is configured")

    estimate = estimate_run_cost_usd(
        root=root,
        rubric_path=rubric_path,
        outline_path=outline_path,
        submissions_dir=submissions_dir,
    )
    if not estimate.get("ok", False):
        raise BalanceGateError(str(estimate.get("reason") or "Cost preflight failed"))
    total_cost = _safe_float(estimate.get("total_cost"), 0.0)
    markup = _safe_float(check.get("cost_markup_multiplier"), 1.0)
    safety = _safe_float(check.get("safety_multiplier"), 1.2)
    floor = _safe_float(check.get("minimum_remaining_usd"), 0.0)
    required = max(floor, total_cost * markup * safety)
    credit = fetch_credit_status(provider, check, api_key)
    remaining = _safe_float(credit.get("remaining_budget"), 0.0)
    if remaining + 1e-9 < required:
        raise BalanceGateError(
            f"Insufficient prepaid LLM credit: ${remaining:.2f} remaining, ${required:.2f} required before starting this cohort"
        )
    return {
        "enabled": True,
        "ok": True,
        "provider": provider_name,
        "student_count": estimate.get("student_count", 0),
        "estimated_cost_usd": round(total_cost, 6),
        "required_credit_usd": round(required, 6),
        "remaining_credit_usd": round(remaining, 6),
    }
