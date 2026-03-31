Pay-As-You-Go Mode (Teacher Billing)

Goal
- Run the grading pipeline using your API key and bill teachers at cost (1-to-1 token pricing).

What This Repo Provides
- Usage logging: `outputs/usage_log.jsonl`
- Cost calculator: `scripts/usage_pricing.py` + `config/pricing.json`
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
3) Compute cost via `scripts/usage_pricing.py`.
4) Bill the user using your payment processor (e.g., Stripe) at cost.

Notes
- Pricing is set in `config/pricing.json` and must be kept in sync with model pricing.
- The cost calculator uses input/output token usage returned by the API.
- Cost caps are configured in `config/cost_limits.json`.
- Teacher review feedback can be persisted as draft or finalized state. Only finalized reviews feed learning.
- Aggregate cross-teacher learning now requires anonymized finalized-only records plus project-level opt-in or policy-compliant collection before export.

Minimal server (optional)
- `server/app.py` provides a minimal FastAPI endpoint for synchronous jobs.
- Use `server/requirements.txt` to install dependencies.
