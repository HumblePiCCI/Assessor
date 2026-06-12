#!/usr/bin/env python3
"""Stripe prepaid credit webhook plus safe LiteLLM balance endpoint."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request


app = FastAPI(title="Assessor prepaid LiteLLM credits")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _state_path() -> Path:
    return Path(_env("CREDIT_STATE_PATH", "credit_state.json")).expanduser()


def _outbox_path() -> Path:
    return Path(_env("NEW_KEY_OUTBOX_PATH", "new_virtual_keys.jsonl")).expanduser()


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {"emails": {}, "events": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"emails": {}, "events": {}}
    if not isinstance(state, dict):
        return {"emails": {}, "events": {}}
    state.setdefault("emails", {})
    state.setdefault("events", {})
    return state


def _write_private(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _save_state(state: dict[str, Any]):
    _write_private(_state_path(), json.dumps(state, indent=2, sort_keys=True))


def _append_new_key(record: dict[str, Any]):
    path = _outbox_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _bearer_token(authorization: str) -> str:
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization[len(prefix) :].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return token


def _litellm_base_url() -> str:
    value = _env("LITELLM_ADMIN_BASE_URL", "http://localhost:4000").rstrip("/")
    if not value:
        raise HTTPException(status_code=500, detail="LITELLM_ADMIN_BASE_URL is not configured")
    return value


def _litellm_master_key() -> str:
    key = _env("LITELLM_MASTER_KEY")
    if not key:
        raise HTTPException(status_code=500, detail="LITELLM_MASTER_KEY is not configured")
    return key


def _allowed_models() -> list[str]:
    raw = _env("LITELLM_ALLOWED_MODELS", "gpt-5.4,gpt-5.4-mini,gpt-5.4-nano")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_balance(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="LiteLLM returned a non-object key info response")
    candidates = [payload]
    for key in ("info", "key", "data", "token"):
        if isinstance(payload.get(key), dict):
            candidates.append(payload[key])

    def number(name: str) -> float:
        values = []
        for item in candidates:
            try:
                values.append(float(item.get(name) or 0.0))
            except (TypeError, ValueError):
                values.append(0.0)
        return max(values) if values else 0.0

    spend = number("spend")
    max_budget = number("max_budget")
    remaining = 0.0
    for name in ("remaining_budget", "remaining_balance", "remaining", "balance", "available_budget"):
        value = number(name)
        if value > 0:
            remaining = value
            break
    if remaining <= 0 and max_budget > 0:
        remaining = max(0.0, max_budget - spend)
    return {
        "spend": round(spend, 6),
        "max_budget": round(max_budget, 6) if max_budget else None,
        "remaining_budget": round(remaining, 6),
        "currency": "USD",
    }


async def _litellm_get_key_info(key: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=float(_env("LITELLM_TIMEOUT_SECONDS", "10"))) as client:
        response = await client.get(
            f"{_litellm_base_url()}/key/info",
            params={"key": key},
            headers={"Authorization": f"Bearer {_litellm_master_key()}"},
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"LiteLLM key info failed: HTTP {response.status_code}")
    return _parse_balance(response.json())


async def _litellm_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=float(_env("LITELLM_TIMEOUT_SECONDS", "10"))) as client:
        response = await client.post(
            f"{_litellm_base_url()}{path}",
            json=payload,
            headers={"Authorization": f"Bearer {_litellm_master_key()}"},
        )
    if response.status_code >= 400:
        detail = response.text[:300]
        raise HTTPException(status_code=502, detail=f"LiteLLM {path} failed: HTTP {response.status_code}: {detail}")
    return response.json()


def _key_from_generate_response(payload: dict[str, Any]) -> str:
    for name in ("key", "token", "virtual_key"):
        value = str(payload.get(name) or "").strip()
        if value:
            return value
    nested = payload.get("data")
    if isinstance(nested, dict):
        for name in ("key", "token", "virtual_key"):
            value = str(nested.get(name) or "").strip()
            if value:
                return value
    raise HTTPException(status_code=502, detail="LiteLLM key generation did not return a key")


async def _generate_key(email: str, credit_usd: float) -> str:
    payload = {
        "models": _allowed_models(),
        "user_id": email,
        "max_budget": round(credit_usd, 6),
        "metadata": {"source": "assessor_prepaid_stripe", "email": email},
    }
    return _key_from_generate_response(await _litellm_post("/key/generate", payload))


async def _top_up_key(key: str, credit_usd: float) -> dict[str, Any]:
    current = await _litellm_get_key_info(key)
    spend = float(current.get("spend") or 0.0)
    current_max = float(current.get("max_budget") or 0.0)
    new_max = max(current_max, spend) + credit_usd
    await _litellm_post("/key/update", {"key": key, "max_budget": round(new_max, 6)})
    return await _litellm_get_key_info(key)


def _verify_stripe_signature(payload: bytes, signature_header: str | None) -> str:
    secret = _env("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="STRIPE_WEBHOOK_SECRET is not configured")
    if not signature_header:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")
    parts: dict[str, list[str]] = {}
    for item in signature_header.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        parts.setdefault(key, []).append(value)
    timestamp = (parts.get("t") or [""])[0]
    signatures = parts.get("v1") or []
    if not timestamp or not signatures:
        raise HTTPException(status_code=400, detail="Malformed Stripe-Signature header")
    tolerance = int(_env("STRIPE_SIGNATURE_TOLERANCE_SECONDS", "300"))
    try:
        signed_at = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Malformed Stripe-Signature timestamp") from exc
    if abs(int(time.time()) - signed_at) > tolerance:
        raise HTTPException(status_code=400, detail="Expired Stripe-Signature timestamp")
    expected = hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8") + b"." + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise HTTPException(status_code=400, detail="Invalid Stripe-Signature")
    return timestamp


def _session_email(session: dict[str, Any]) -> str:
    customer_details = session.get("customer_details") if isinstance(session.get("customer_details"), dict) else {}
    email = str(customer_details.get("email") or session.get("customer_email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Checkout session did not include a customer email")
    return email


def _credit_amount_usd(session: dict[str, Any]) -> float:
    metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    configured = metadata.get("credit_usd") or metadata.get("credits_usd")
    try:
        credit = float(configured) if configured not in (None, "") else 0.0
    except (TypeError, ValueError):
        credit = 0.0
    if credit <= 0:
        amount = session.get("amount_subtotal") or session.get("amount_total") or 0
        credit = float(amount) / 100.0
    if credit <= 0:
        raise HTTPException(status_code=400, detail="Checkout session did not include a positive credit amount")
    return round(credit, 6)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/credits/me")
async def credits_me(authorization: str = Header("")):
    key = _bearer_token(authorization)
    return await _litellm_get_key_info(key)


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str | None = Header(None, alias="Stripe-Signature")):
    payload = await request.body()
    _verify_stripe_signature(payload, stripe_signature)
    try:
        event = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe event JSON") from exc
    event_id = str(event.get("id") or "").strip()
    event_type = str(event.get("type") or "")
    if event_type != "checkout.session.completed":
        return {"status": "ignored", "event_type": event_type}
    session = ((event.get("data") or {}).get("object") or {}) if isinstance(event.get("data"), dict) else {}
    if not isinstance(session, dict):
        raise HTTPException(status_code=400, detail="Stripe event missing checkout session object")
    if str(session.get("payment_status") or "").lower() not in {"paid", "no_payment_required"}:
        return {"status": "ignored", "reason": "checkout session not paid"}

    state = _load_state()
    if event_id and event_id in state.get("events", {}):
        return {"status": "duplicate", "event_id": event_id}

    email = _session_email(session)
    credit_usd = _credit_amount_usd(session)
    emails = state.setdefault("emails", {})
    record = emails.get(email) if isinstance(emails.get(email), dict) else None
    generated = False
    if record and str(record.get("key") or "").strip():
        key = str(record["key"]).strip()
    else:
        key = await _generate_key(email, credit_usd)
        generated = True
        record = {"email": email, "key": key, "created_at": _utc_now(), "total_credit_usd": 0.0}
        _append_new_key({"email": email, "key": key, "credit_usd": credit_usd, "created_at": record["created_at"]})

    balance = {"remaining_budget": credit_usd} if generated else await _top_up_key(key, credit_usd)
    record["updated_at"] = _utc_now()
    record["last_credit_usd"] = credit_usd
    record["total_credit_usd"] = round(float(record.get("total_credit_usd") or 0.0) + credit_usd, 6)
    emails[email] = record
    if event_id:
        state.setdefault("events", {})[event_id] = {
            "email": email,
            "credit_usd": credit_usd,
            "processed_at": record["updated_at"],
            "generated_key": generated,
        }
    _save_state(state)
    return {
        "status": "credited",
        "email": email,
        "credit_usd": credit_usd,
        "generated_key": generated,
        "remaining_budget": balance.get("remaining_budget"),
    }
