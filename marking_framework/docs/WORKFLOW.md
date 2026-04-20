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
- Build deterministic claim/evidence/commentary maps: `python3 scripts/evidence_map.py`
- Resolve residual committee-edge overrides: `python3 scripts/committee_edge_resolver.py`
- Apply deterministic rerank with committee-edge direct edges preferred: `python3 scripts/global_rerank.py --judgments outputs/consistency_checks.committee_edge.json`
- Evaluate routed hard-pair performance before publish/SOTA gates: `python3 scripts/evaluate_pairwise_adjudicator.py --judgments outputs/consistency_checks.committee_edge.json --output outputs/pairwise_adjudicator_eval.json`
- Review `outputs/pairwise_escalation_candidates.json` for the routed hard-pair selection.
- Review `outputs/pairwise_escalations.json` for stronger-model teacher-grade decisions.
- Review `outputs/consistency_checks.escalated.json` for the merged evidence file consumed by rerank.
- Review `outputs/evidence_map.json` for the offline claim/evidence/commentary ledger. This artifact is model-free: it extracts central claims, text moments, commentary markers, plot-summary load, completion-floor signals, and pair-level evidence-map recommendations when run with `--candidates`; when present, committee-edge reads also use it as a narrow guard against weak prior-winner concurrence or unsupported overrides.
- Review `outputs/evidence_neighborhood_report.json` for offline local placement neighborhoods. This report is model-free and report-only: it groups selected committee candidates by evidence-map contradictions and ambiguous internal edges, then labels each neighborhood as `pair_guard_only`, `needs_group_calibration`, or `insufficient_signal`; it does not emit rerank edges or change pass-through behavior.
- Review `outputs/evidence_group_calibration_packets.json` for bounded offline calibration packets derived from those neighborhoods. Large connected components are split into deterministic local packets with capped student counts, seed/evidence order, triggering edges, ambiguous edges, priority scores, and a recommended read type; the artifact is still report-only and does not change rerank.
- Review `outputs/committee_edge_candidates.json` for residual unstable edges, including polish-bias, rougher-but-stronger, and bell-curve-leverage risks.
- Review `outputs/committee_edge_live_trace.json` after any live committee run; it records every A/B/C/group read, evidence-ledger guard status, and emitted override so failed live calibration can be debugged without rerunning model calls.
- Review `outputs/pairwise_adjudicator_eval.json`; the publish gate expects the routed committee-edge path to meet hard-pair accuracy and polish-bias thresholds.
- Publish/SOTA gates now also require the evidence-neighborhood and evidence-group-packet artifacts to be present, enabled, nonempty when group calibration is needed, and bounded by their configured packet caps whenever committee candidates exist.
- Phase 1 of the committee-edge resolver is scaffold only: it emits candidates and passes the merged judgments file through unchanged when no decisions are produced.
- Live committee reads are opt-in with `python3 scripts/committee_edge_resolver.py --live --max-reads 12`; default pipeline runs remain deterministic/model-free at this seam. Live mode runs Read A for selected candidates, capped Read B polish-trap audits for Read-A outcomes that request an audit, capped Read C placement calibration for unresolved high-leverage A/B outcomes, and one small unresolved-neighborhood group calibration unless `--no-live-read-b`, `--no-live-read-c`, or `--no-live-group-calibration` is passed. A/B/C reads must complete an evidence ledger and a source-calibration checklist before deciding; on caution-ignored edges, a medium/high prior-winner concurrence can be superseded when its own ledger or source checklist gives the other essay stronger interpretation/proof/commentary and no mechanics, observable scaffold, or completion blocker.
- When `outputs/evidence_group_calibration_packets.json` is enabled, group calibration reads use those selected packets as their neighborhood source before falling back to unresolved A/B/C read results. This lets a fixture or live group read calibrate the highest-priority local packet without first spending broad pairwise committee reads.
- Routed committee reads also load `inputs/calibration_sources/writing_assessment_sources.json` by default through `--source-calibration`. This pack contains public source links, score-scale metadata, and distilled teacher/examiner calibration rules across grade bands and writing types; it does not store full external student responses. See `docs/EXTERNAL_WRITING_CALIBRATION_SOURCES.md`.
- Offline committee-read fixtures can be replayed with `--blind-read-fixture`, `--read-b-fixture`, `--read-c-fixture`, and `--group-calibration-fixture` to test precedence, A/B/C resolution, group-neighborhood overrides, and rerank behavior without API calls.
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
