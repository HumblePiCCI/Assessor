Workflow

Note: You can run the full orchestration with `python3 scripts/hero_path.py` and flags.

1) Ingest Inputs
- Rubric: place in `inputs/`
- Assignment outline: place in `inputs/`
- Student submissions: place in `inputs/submissions/`

2) Normalize Text
- Convert submissions to plain text:
  - `python3 scripts/extract_text.py --inputs inputs/submissions --output processing/normalized_text`

3) Baseline Conventions Scan
- Run the conventions heuristic:
  - `python3 scripts/conventions_scan.py --inputs processing/normalized_text --output processing/conventions_report.csv`

4) Assessor Pass 1 (Independent)
- Use `prompts/assessor_pass1.md` with each assessor role.
- Save per-assessor JSON to `assessments/pass1_individual/`.

5) Assessor Pass 2 (Comparative)
- Use `prompts/assessor_pass2.md` with each assessor role.
- Save per-assessor rank list to `assessments/pass2_comparative/`.

Optional LLM assessors:
- `python3 scripts/run_llm_assessors.py`
- Generates Pass 1 and Pass 2 outputs automatically (requires OPENAI_API_KEY).
- Usage is logged in `outputs/usage_log.jsonl`.
- Cost caps are enforced via `config/cost_limits.json` (override with `--ignore-cost-limits`).

6) Aggregate & Flag Disagreements
- `python3 scripts/aggregate_assessments.py --config config/marking_config.json`
- Review `assessments/pass3_reconcile/disagreements.md`.

7) Assessor Pass 3 (Reconcile)
- Re-read only flagged essays.
- Update scores or rankings if needed.
- Re-run aggregation.

8) Pairwise Evidence And Global Rerank
- Collect pairwise evidence: `python3 scripts/verify_consistency.py`
- Apply deterministic rerank: `python3 scripts/global_rerank.py`
- Review `outputs/pairwise_matrix.json` for normalized pairwise evidence.
- Review `outputs/consistency_report.json` for movements, uncertainty flags, and rerank diagnostics.
- Review `outputs/final_order.csv` for the resolved order used by grading.

Legacy optional tooling:
- `python3 scripts/generate_pairwise_review.py`
- `python3 scripts/apply_pairwise_adjustments.py --min-confidence med`
- These older swap-based tools still exist, but the canonical pipeline now uses pairwise evidence plus global rerank.

9) Review and Configure Curve (Interactive)
- Review `outputs/ranked_list.md` and flags in `assessments/pass3_reconcile/disagreements.md`.
- Run: `python3 scripts/review_and_grade.py`
- Adjust top/bottom curve values and confirm the preview.
- This produces `outputs/grade_curve.csv`.

Optional cost report:
- `python3 scripts/usage_pricing.py`
- Update model prices in `config/pricing.json` as needed.

10) Two Stars and a Wish (Post-Curve)
- After curve grades are finalized, generate "Two Stars and a Wish" feedback.
- Run: `python3 scripts/generate_feedback.py --grades outputs/grade_curve.csv --texts processing/normalized_text --output outputs/feedback_summaries`
- This creates feedback templates for each student.
- Fill in the templates with specific strengths and improvements.
- Each star must cite a direct quote as evidence.
- The wish must cite a direct quote and target the highest-leverage fix.
- Validate quotes: `python3 scripts/generate_feedback.py --validate`
- This ensures all quoted text actually appears in student essays.

11) Teacher Review UI
- Build data: `python3 scripts/build_dashboard_data.py`
- Serve UI: `python3 scripts/serve_ui.py`
- Saved review feedback is versioned and exported for replay, but finalized-review-only runtime learning remains a follow-on production task

12) Final Outputs
- `outputs/ranked_list.md`
- `outputs/consensus_scores.csv`
- `outputs/pairwise_matrix.json`
- `outputs/consistency_report.json`
- `outputs/final_order.csv`
- `outputs/grade_curve.csv`
- `outputs/feedback_summaries/`
