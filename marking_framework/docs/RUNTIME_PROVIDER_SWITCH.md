# Runtime Provider Switch

State: implemented runtime contract

The product now separates model/provider selection from the base routing table.
`config/llm_routing.json` remains the default task-routing contract, while
`config/runtime_profiles.json` selects how a run is authenticated, billed, and
optionally overlaid with provider-specific model choices.

## Profiles

### `internal_codex`

- Purpose: internal testing.
- Mode: `codex_local`.
- Auth: local Codex OAuth session through the Codex app bundle CLI
  (`/Applications/Codex.app/Contents/Resources/codex`) using the modern
  `codex exec` interface.
- Billing: not customer billable.
- Routing overlay: broad routes stay on `gpt-5.4-mini`; the routed escalator
  uses `gpt-5.5` with medium reasoning.

### `teacher_payg_openai`

- Purpose: controlled teacher pilot / pay-as-you-go testing.
- Mode: `openai`.
- Auth: `OPENAI_API_KEY`.
- Billing: customer billable at raw API cost plus `10%`.
- Pricing source: `config/pricing.json`.

The server validates billable profiles before queueing a run. If any effective
task model is missing from `config/pricing.json`, the run is rejected rather
than producing an undercounted teacher bill.

### Disabled adapter profiles

`openai_compatible_payg` and `anthropic_openai_compatible_payg` are present but
disabled. They are adapter contracts for providers or self-hosted models that
expose a Responses-compatible endpoint. Native Anthropic Messages support is
not implemented in this slice; enabling Anthropic requires either an
OpenAI-compatible adapter URL or a future native client implementation.

## Runtime Artifacts

Each queue-backed run writes:

- `outputs/runtime_profile.json`
- `pipeline_manifest.json` fields:
  - `runtime_profile`
  - `billing_policy`
  - effective `model_routing`

The job workspace receives the profile-applied `config/llm_routing.json`, so
existing scripts continue to use the normal routing file and do not need to
know about the UI profile switch.

Internal Codex jobs also write `outputs/runtime_auth_audit.json`, recording
`auth_funding_source=codex_oauth`, whether `OPENAI_API_KEY` was visible to the
job, and the selected Codex CLI path/interface. This is the verification point
for confirming that internal Ghost runs are funded by Codex OAuth rather than
teacher/API-key billing.

## Billing Output

`scripts/usage_pricing.py` now reports:

- `api_cost_total`: raw provider token cost
- `service_fee`: markup amount
- `customer_total`: raw API cost plus markup
- `unpriced_models`: any usage that could not be priced

For billable profiles, unpriced usage returns nonzero and should block billing.
This preserves the cost-plus contract: do not charge a teacher from a report
that contains `unpriced_models`.

## UI/API Contract

The review UI loads profiles from:

```bash
GET /runtime/profiles
```

Pipeline submission accepts both fields:

```text
mode=<resolved mode>
profile=<runtime profile name>
```

Legacy callers may still submit only `mode=codex_local` or `mode=openai`, but
pilot and internal product runs should use explicit runtime profiles.
