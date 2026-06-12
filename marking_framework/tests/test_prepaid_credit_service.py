import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient

from deploy.prepaid_litellm import credit_service as svc


def _stripe_signature(payload: bytes, secret: str) -> str:
    timestamp = str(int(time.time()))
    digest = hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8") + b"." + payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def test_stripe_webhook_generates_key_and_is_idempotent(tmp_path, monkeypatch):
    secret = "whsec_test"
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("CREDIT_STATE_PATH", str(tmp_path / "credit_state.json"))
    monkeypatch.setenv("NEW_KEY_OUTBOX_PATH", str(tmp_path / "new_virtual_keys.jsonl"))
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master")
    calls = {"generate": 0}

    async def fake_litellm_post(path, payload):
        if path == "/key/generate":
            calls["generate"] += 1
            assert payload["user_id"] == "teacher@example.com"
            assert payload["max_budget"] == 25.0
            return {"key": "sk-virtual"}
        raise AssertionError(f"unexpected LiteLLM post {path}")

    monkeypatch.setattr(svc, "_litellm_post", fake_litellm_post)
    event = {
        "id": "evt_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "payment_status": "paid",
                "amount_subtotal": 2500,
                "metadata": {"credit_usd": "25"},
                "customer_details": {"email": "Teacher@Example.com"},
            }
        },
    }
    payload = json.dumps(event).encode("utf-8")
    client = TestClient(svc.app)

    response = client.post(
        "/stripe/webhook",
        data=payload,
        headers={"Stripe-Signature": _stripe_signature(payload, secret)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "credited"
    assert body["generated_key"] is True
    assert body["credit_usd"] == 25.0
    assert calls["generate"] == 1

    state = json.loads((tmp_path / "credit_state.json").read_text(encoding="utf-8"))
    assert state["emails"]["teacher@example.com"]["key"] == "sk-virtual"
    assert state["events"]["evt_1"]["credit_usd"] == 25.0
    assert "sk-virtual" in (tmp_path / "new_virtual_keys.jsonl").read_text(encoding="utf-8")

    duplicate = client.post(
        "/stripe/webhook",
        data=payload,
        headers={"Stripe-Signature": _stripe_signature(payload, secret)},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"
    assert calls["generate"] == 1


def test_credits_me_returns_remaining_budget(monkeypatch):
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master")

    async def fake_key_info(key):
        assert key == "sk-virtual"
        return {"remaining_budget": 12.5, "spend": 2.5, "max_budget": 15.0, "currency": "USD"}

    monkeypatch.setattr(svc, "_litellm_get_key_info", fake_key_info)
    client = TestClient(svc.app)
    response = client.get("/credits/me", headers={"Authorization": "Bearer sk-virtual"})
    assert response.status_code == 200
    assert response.json()["remaining_budget"] == 12.5
