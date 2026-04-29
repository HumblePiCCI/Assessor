Pay-As-You-Go Mode (Teacher Billing)

Goal
- Run the grading pipeline using a teacher/pay-as-you-go runtime profile and bill teachers at exact API cost plus the configured service margin.

What This Repo Provides
- Usage logging: `outputs/usage_log.jsonl`
- Cost calculator: `scripts/usage_pricing.py` + `config/pricing.json`
- Runtime profile switch: `config/runtime_profiles.json`
- Optional job runner: `scripts/payg_job.py` (batch execution)

Suggested Deployment Pattern
1) Frontend uploads rubric/outline/submissions.
2) Backend creates a job workspace and runs:
   - `scripts/run_llm_assessors.py`
   - `scripts/aggregate_assessments.py`
   - `scripts/verify_consistency.py`
   - `scripts/global_rerank.py`
   - `scripts/review_and_grade.py` (optional for interactive UI)
   - `scripts/build_dashboard_data.py` (optional for teacher review)
3) Select `teacher_payg_openai` in the UI or pass `--profile teacher_payg_openai`.
4) Compute cost via `scripts/usage_pricing.py`.
5) Bill the user using your payment processor from `customer_total`.

Notes
- `teacher_payg_openai` is configured for `10%` over raw API cost.
- Pricing is set in `config/pricing.json` and must be kept in sync with provider pricing.
- Billable runs are rejected when any effective task model is missing from `config/pricing.json`.
- The cost calculator uses input/output token usage returned by the API and separately prices cached input tokens when the provider reports them.
- Cost caps are configured in `config/cost_limits.json`.
- Teacher review feedback can be persisted as draft or finalized state. Only finalized reviews feed learning.
- Aggregate cross-teacher learning now requires anonymized finalized-only records plus project-level opt-in or policy-compliant collection before export.
- Provider switching details live in `docs/RUNTIME_PROVIDER_SWITCH.md`.

Minimal server (optional)
- `server/app.py` provides a minimal FastAPI endpoint for synchronous jobs.
- Use `server/requirements.txt` to install dependencies.
