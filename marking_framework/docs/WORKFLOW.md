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

8) Pairwise Evidence, Escalation, And Global Rerank
- Collect broad cheap pairwise evidence: `python3 scripts/verify_consistency.py`
- Escalate only unstable/high-leverage edges: `python3 scripts/escalate_pairwise_adjudications.py`
- Resolve residual committee-edge overrides: `python3 scripts/committee_edge_resolver.py`
- Apply deterministic rerank with committee-edge direct edges preferred: `python3 scripts/global_rerank.py --judgments outputs/consistency_checks.committee_edge.json`
- Review `outputs/pairwise_escalation_candidates.json` for the routed hard-pair selection.
- Review `outputs/pairwise_escalations.json` for stronger-model teacher-grade decisions.
- Review `outputs/consistency_checks.escalated.json` for the merged evidence file consumed by rerank.
- Review `outputs/committee_edge_candidates.json` for residual unstable edges, including polish-bias, rougher-but-stronger, and bell-curve-leverage risks.
- Phase 1 of the committee-edge resolver is scaffold only: it emits candidates and passes the merged judgments file through unchanged when no decisions are produced.
- Live committee reads are opt-in with `python3 scripts/committee_edge_resolver.py --live --max-reads 12`; default pipeline runs remain deterministic/model-free at this seam. Live mode runs Read A for selected candidates and, unless `--no-live-read-b` is passed, runs capped Read B polish-trap audits for Read-A outcomes that request an audit.
- Offline committee-read fixtures can be replayed with `--blind-read-fixture` and `--read-b-fixture` to test precedence, A/B resolution, and rerank behavior without API calls.
- The escalation step keeps skipped candidates in the candidate artifact when budget caps apply; skipped pairs are not marked as teacher-grade evidence.
- Cross-band challengers just below the top pack are prioritized inside the escalation budget, because a flawed seam can otherwise hide the exact papers that need teacher-grade comparison against top anchors.
- High-disagreement non-top-pack papers are also checked against top post-seam anchors, so rank/rubric variance can surface long-gap challengers before the final rerank.
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
- Save exploratory edits as draft state
- Finalize the review only when the curve is settled
- Only finalized reviews feed the local runtime teacher prior
- Product-wide aggregate learning uses governed anonymized exports and adjudication-required promotion staging

12) Final Outputs
- `outputs/ranked_list.md`
- `outputs/consensus_scores.csv`
- `outputs/pairwise_matrix.json`
- `outputs/consistency_report.json`
- `outputs/final_order.csv`
- `outputs/grade_curve.csv`
- `outputs/feedback_summaries/`
