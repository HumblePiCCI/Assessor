Prepaid Pay-As-You-Go Mode (Teacher Billing)

Goal
- Run the grading pipeline through a metered LiteLLM proxy, with teacher/tester
  spend prepaid through fixed Stripe credit packs.

What This Repo Provides
- Usage logging: `outputs/usage_log.jsonl`
- Cost calculator: `scripts/usage_pricing.py` + `config/pricing.json`
- Optional job runner: `scripts/payg_job.py` (batch execution)
- Opt-in LiteLLM provider config: `config/llm_routing.json` provider
  `metered`
- Pre-run prepaid credit gate for API-provider cohort starts
- Pilot webhook/self-service credit service:
  `deploy/prepaid_litellm/credit_service.py`

Suggested Deployment Pattern
1) Frontend uploads rubric/outline/submissions or imports read-only Classroom
   submissions through the pilot sync seam.
2) Backend estimates the cohort cost before queueing the paid API run.
3) If `LLM_API_PROVIDER=metered`, the backend queries the configured prepaid
   credit endpoint and rejects the run with HTTP `402` when credit is too low.
4) Backend creates a job workspace and runs the fast teacher-review phase first.
5) `outputs/dashboard_data.json` is published as soon as review is ready.
6) Background validation continues and writes
   `outputs/background_validation_summary.json`.
7) Compute final cost via `scripts/usage_pricing.py` for audit/reconciliation.

Pilot Billing Pattern
- Sell fixed Stripe Payment Links for `$25` and `$50` credit packs.
- Fulfill `checkout.session.completed` by generating or topping up a LiteLLM
  virtual key.
- Configure LiteLLM model prices at `1.15x` OpenAI list price, so a user's
  prepaid budget depletes at the marked-up rate without separate invoicing.
- Give testers only their `LITELLM_VIRTUAL_KEY`; the real `OPENAI_API_KEY` and
  `LITELLM_MASTER_KEY` stay in the hosted LiteLLM/credit-service environment.

Notes
- Pricing is set in `config/pricing.json` and must be kept in sync with model pricing.
- The cost calculator uses input/output token usage returned by the API.
- Cost caps are configured in `config/cost_limits.json`.
- `mode=api`, `mode=api_provider`, and the legacy `mode=openai` all select the
  configured API provider path.
- The active provider comes from `LLM_API_PROVIDER`, `API_PROVIDER`, or
  `config/llm_routing.json`.
- Provider keys are read from `LLM_API_KEY` first, then the provider-specific
  key env (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `KIMI_API_KEY`, etc.).
- For prepaid tester installs, use `LITELLM_VIRTUAL_KEY` through the `metered`
  provider instead of `OPENAI_API_KEY`.
- Teacher review feedback can be persisted as draft or finalized state. Only finalized reviews feed learning.
- Aggregate cross-teacher learning now requires anonymized finalized-only records plus project-level opt-in or policy-compliant collection before export.

Minimal server (optional)
- `server/app.py` provides a minimal FastAPI endpoint for synchronous jobs.
- `/pipeline/v2/run` is the recommended shipped path. Legacy `/jobs` remains
  available for local non-strict compatibility and uses generic provider key
  handling, but it is not the teacher product path.
- `/pipeline/v2/run-project-inputs` runs from server-side project inputs. The
  Google Classroom read-sync path uses this after supported submissions have
  been materialized into `inputs/submissions`; rubric and assignment outline
  still must be present through upload or saved project inputs.
- Use `server/requirements.txt` to install dependencies.
