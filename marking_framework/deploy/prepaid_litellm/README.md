# Prepaid LiteLLM Credit Proxy

This folder contains the pilot-ready prepaid setup for teacher/tester API usage:

- Stripe Payment Links sell fixed credit packs.
- LiteLLM holds the real OpenAI key and enforces virtual-key budgets.
- `credit_service.py` receives Stripe webhooks, generates or tops up LiteLLM
  virtual keys, and exposes a safe `/credits/me` endpoint for local tester
  installs.
- The marking framework points at LiteLLM with `LLM_API_PROVIDER=metered` and
  the tester's `LITELLM_VIRTUAL_KEY`.

## Secret Boundary

Tester installs should only receive:

```bash
LLM_API_PROVIDER=metered
LITELLM_VIRTUAL_KEY=sk-...
```

Only the hosted LiteLLM/credit-service environment should hold:

```bash
OPENAI_API_KEY=...
LITELLM_MASTER_KEY=...
STRIPE_WEBHOOK_SECRET=...
```

Do not put `LITELLM_MASTER_KEY` in a teacher/tester `.env`.

## LiteLLM

1. Deploy LiteLLM with Postgres persistence.
2. Use `proxy_config.example.yaml` as the starting config.
3. Set `LITELLM_MASTER_KEY` and `OPENAI_API_KEY` as host secrets.
4. Replace placeholder model prices with the current OpenAI list prices times
   `1.15`. LiteLLM budgets then deplete at the marked-up credit rate.
5. Confirm the proxy serves OpenAI Responses-compatible requests at
   `https://<host>/v1/responses`.

## Stripe Payment Links

Create two one-time Payment Links in the Stripe Dashboard:

- `Assessor LLM Credits - $25`
- `Assessor LLM Credits - $50`

For each link:

- Collect customer email.
- Add metadata `credit_usd=25` or `credit_usd=50`.
- Set fulfillment to a webhook endpoint:
  `https://<credit-service-host>/stripe/webhook`.
- Subscribe the endpoint to `checkout.session.completed`.

Stripe's dashboard shows completed Payment Link sessions under payments, and
the webhook is the durable fulfillment signal. For manual pilot operation, you
can skip the webhook initially and create/top-up virtual keys in LiteLLM by hand
from Stripe's payment notification email.

## Credit Service

Install runtime deps:

```bash
python3 -m pip install fastapi uvicorn httpx
```

Run locally:

```bash
export LITELLM_ADMIN_BASE_URL=http://localhost:4000
export LITELLM_MASTER_KEY=sk-litellm-master
export STRIPE_WEBHOOK_SECRET=whsec_...
export CREDIT_STATE_PATH=/secure/path/credit_state.json
export NEW_KEY_OUTBOX_PATH=/secure/path/new_virtual_keys.jsonl
uvicorn deploy.prepaid_litellm.credit_service:app --host 0.0.0.0 --port 8080
```

`credit_state.json` stores email-to-virtual-key mappings so future purchases top
up the same key. `new_virtual_keys.jsonl` is a sensitive operator outbox for
first-purchase keys; send those keys to testers through your chosen secure
channel, then archive or remove the outbox.

## Tester App Configuration

In `config/llm_routing.json`, replace the `metered` placeholder host:

```json
"metered": {
  "kind": "openai_responses",
  "base_url": "https://<litellm-host>/v1",
  "responses_endpoint": "/responses",
  "api_key_env": "LITELLM_VIRTUAL_KEY",
  "balance_check": {
    "enabled": true,
    "self_service_endpoint": "https://<credit-service-host>/credits/me",
    "cost_markup_multiplier": 1.15,
    "safety_multiplier": 1.2,
    "minimum_remaining_usd": 1.0
  }
}
```

Then set:

```bash
export LLM_API_PROVIDER=metered
export LITELLM_VIRTUAL_KEY=sk-...
```

Before a paid cohort run is queued, the server estimates the run cost, applies
the configured markup and safety multiplier, queries `/credits/me`, and rejects
the run with HTTP `402` if the balance is too low.
