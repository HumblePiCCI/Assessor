Pay-As-You-Go Mode (Teacher Billing)

Goal
- Run the grading pipeline using a configured API provider key and bill teachers
  at cost (1-to-1 token pricing).

What This Repo Provides
- Usage logging: `outputs/usage_log.jsonl`
- Cost calculator: `scripts/usage_pricing.py` + `config/pricing.json`
- Optional job runner: `scripts/payg_job.py` (batch execution)

Suggested Deployment Pattern
1) Frontend uploads rubric/outline/submissions or imports read-only Classroom
   submissions through the pilot sync seam.
2) Backend creates a job workspace and runs the fast teacher-review phase first.
3) `outputs/dashboard_data.json` is published as soon as review is ready.
4) Background validation continues and writes
   `outputs/background_validation_summary.json`.
5) Compute cost via `scripts/usage_pricing.py`.
6) Bill the user using your payment processor (e.g., Stripe) at cost.

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
