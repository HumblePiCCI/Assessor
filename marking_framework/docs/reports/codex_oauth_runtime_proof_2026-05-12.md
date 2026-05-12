# Codex OAuth Runtime Proof

Date: 2026-05-12

## Result

The local product runtime now supports two separate execution paths:

- `codex_local`: local development and smoke testing through the Codex app OAuth runtime, with no API key.
- `openai`: pay-as-you-go API provider mode, configurable for OpenAI Responses, OpenAI-compatible chat providers, and Anthropic Messages.

## OAuth Runtime Proof

Command:

```bash
env -u OPENAI_API_KEY -u LLM_API_KEY ./.venv/bin/python - <<'PY'
import json
from scripts.codex_runtime import codex_status_payload
print(json.dumps(codex_status_payload(), indent=2, sort_keys=True))
PY
```

Observed result:

```json
{
  "auth_source": "codex_oauth",
  "available": true,
  "connected": true,
  "oauth_supported": true,
  "oauth_tokens_present": true,
  "reason": "Codex OAuth runtime ready",
  "runtime_kind": "exec",
  "runtime_path": "/Applications/Codex.app/Contents/Resources/codex",
  "version": "codex-cli 0.130.0-alpha.5"
}
```

Product client proof:

```bash
env -u OPENAI_API_KEY -u LLM_API_KEY LLM_MODE=codex_local LLM_CACHE=0 LLM_TIMEOUT_SECONDS=90 ./.venv/bin/python - <<'PY'
from scripts.openai_client import extract_text, responses_create
resp = responses_create(
    'gpt-5.4-mini',
    [{'role': 'user', 'content': 'Return exactly: product-oauth-ok'}],
    routing_path='config/llm_routing.json',
)
print(extract_text(resp))
PY
```

Observed result:

```text
product-oauth-ok
```

This proves the product code path, not only the raw CLI, can execute through Codex OAuth with API keys removed from the environment.

## API Provider Path

API mode remains selected with `mode: "openai"` for backward compatibility, but now means "API provider path." The active provider is selected by:

- `api_provider` in `config/llm_routing.json`, or
- `LLM_API_PROVIDER` in the environment.

Provider keys are resolved in this order:

1. `LLM_API_KEY`
2. the provider-specific `api_key_env`, such as `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `KIMI_API_KEY`

Supported adapter kinds:

- `openai_responses`
- `openai_chat`
- `anthropic_messages`

## Verification

```bash
./.venv/bin/python -m pytest --no-cov
```

Result:

```text
829 passed
```
