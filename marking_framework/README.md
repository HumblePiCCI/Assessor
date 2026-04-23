Standardized Marking Workspace

Purpose
- Provide a repeatable, multi-pass marking workflow using a rubric, an assignment outline, and a set of student submissions.
- Enforce conventions tracking, rubric adherence, comparative ranking, and consensus ordering before curve-based grades.

Quick Start
0) Optional Hero Path orchestration
   - `python3 scripts/hero_path.py --verify-consistency --apply-consistency --build-dashboard`
   - LLM assessors: add `--llm-assessors` (requires OPENAI_API_KEY)

1) Place inputs
   - Rubric: `inputs/rubric.docx`, `inputs/rubric.md`, `inputs/rubric.txt`, `inputs/rubric.rtf`, `inputs/rubric.pdf`, or an image-backed rubric file
   - Assignment outline: `inputs/assignment_outline.docx` or `inputs/assignment_outline.md`
   - Student work: `inputs/submissions/`
   - Optional class metadata: `inputs/class_metadata.json` (e.g., {"grade_level": 7})
   - Validate metadata: `python3 scripts/validate_metadata.py`

2) Normalize submissions
   - `python3 scripts/extract_text.py --inputs inputs/submissions --output processing/normalized_text`

3) Conventions scan (baseline)
   - `python3 scripts/conventions_scan.py --inputs processing/normalized_text --output processing/conventions_report.csv`

4) Assessor passes (LLM agents)
   - Normalize and verify the rubric contract first: `python3 scripts/normalize_rubric.py`
   - Low-confidence rubric parses pause for teacher confirmation or small edits before scoring continues in the queue-backed runtime.
   - Use prompts in `prompts/`.
   - Save outputs to:
     - `assessments/pass1_individual/` (per-assessor JSON)
     - `assessments/pass2_comparative/` (per-assessor rank list)

5) Aggregate to consensus
   - `python3 scripts/aggregate_assessments.py --config config/marking_config.json`

6) Collect pairwise evidence, adjudicate unstable edges, and rerank globally
   - `python3 scripts/band_seam_adjudication.py`
   - `python3 scripts/verify_consistency.py`
   - `python3 scripts/escalate_pairwise_adjudications.py`
   - `python3 scripts/evidence_map.py`
   - `python3 scripts/committee_edge_resolver.py`
   - `python3 scripts/global_rerank.py --judgments outputs/consistency_checks.committee_edge.json`
   - Or via Hero Path: `python3 scripts/hero_path.py --band-seam-adjudication --verify-consistency --apply-consistency`
   - The default resolver path is deterministic and model-free unless `--committee-edge-live` or `COMMITTEE_EDGE_LIVE=1` explicitly enables live committee reads.
   - Direct `adjudication_source="committee_edge"` winners that survive merge become protected rerank graph constraints; rerank may suppress them only for explicit graph safety/cycle reasons.
   - The consistency pass expands post-seam coverage by default: it fully compares the top pack, checks band-seam/aggregate movers against that pack, and writes an audit report.
   - Pairwise judgments include genre-aware criterion notes so reviewers can see whether the model preferred meaning, evidence, genre requirements, organization, or language control.
   - Hard-pair adjudicator evals should be run on the merged committee-edge file:
     - `python3 scripts/evaluate_pairwise_adjudicator.py --judgments outputs/consistency_checks.committee_edge.json --output outputs/pairwise_adjudicator_eval.json`
   - The default gold set targets the Ghost literary-analysis failure mode, including rougher-but-stronger and polished-but-shallow edges.

7) Review and apply grade curve
   - `python3 scripts/review_and_grade.py`
   - Or run the deterministic default directly: `python3 scripts/review_and_grade.py --non-interactive`
   - Grades are now level-locked and band-aware, then organized into a bell-shaped distribution within the resolved order

8) Generate Two Stars and a Wish feedback (post-curve)
   - `python3 scripts/generate_feedback.py`
   - Fill in generated templates with specific feedback
   - Validate quotes: `python3 scripts/generate_feedback.py --validate`

9) Teacher review UI
   - `python3 scripts/build_dashboard_data.py`
   - `python3 scripts/serve_ui.py`
   - Save exploratory edits as draft state, then finalize the review when the curve is settled
   - Only finalized reviews feed the local teacher prior used on future reranks in the same scope

10) Pay-as-you-go job runner (optional)
   - `python3 scripts/payg_job.py --rubric inputs/rubric.md --outline inputs/assignment_outline.md --submissions inputs/submissions --llm --pricing`
   - Minimal API server: `python3 -m uvicorn server.app:app --reload`

Key Outputs
- `outputs/ranked_list.md` (consensus order + confidence signals)
- `outputs/consensus_scores.csv` (rubric means, conventions, Borda, composite scores)
- `outputs/irr_metrics.json` (inter-rater reliability: ICC, Kendall's W)
- `outputs/grade_curve.csv` (level-aware bell-curve grades based on the resolved order)
- `outputs/pairwise_matrix.json` (normalized pairwise evidence and support/opposition weights)
- `outputs/consistency_report.json` (rerank diagnostics, movements, committee direct-edge protection, and uncertainty details)
- `outputs/band_seam_report.json` (evidence-aware level-boundary adjudication)
- `outputs/pairwise_escalation_candidates.json` / `outputs/pairwise_escalations.json` (high-leverage routed pairwise escalation)
- `outputs/consistency_checks.escalated.json` (cheap/orientation/escalated merged pairwise checks)
- `outputs/evidence_map.json` (deterministic claim/evidence/commentary map)
- `outputs/evidence_neighborhood_report.json` (offline local placement-neighborhood diagnostics)
- `outputs/evidence_group_calibration_packets.json` (bounded packets for group calibration)
- `outputs/committee_edge_candidates.json` / `outputs/committee_edge_report.json` (residual unstable-edge routing)
- `outputs/committee_edge_live_trace.json` (live/fixture committee read trace when enabled)
- `outputs/consistency_checks.committee_edge.json` (canonical rerank judgments after committee-edge merge)
- `outputs/post_seam_pair_expansion.json` (top-pack and large-mover pair coverage audit)
- `outputs/pairwise_adjudicator_eval.json` (hard-pair accuracy report for the pairwise adjudicator)
- `outputs/final_order.csv` (post global rerank order)
- `outputs/feedback_summaries/` (two stars and a wish with validated quotes)
- `outputs/dashboard_data.json` (UI data)
- `outputs/normalized_rubric.json` (canonical runtime rubric contract)
- `outputs/rubric_manifest.json` (rubric contract hash, family, confidence, and confirmation state)
- `outputs/rubric_validation_report.json` (parse checks, warnings, and proceed mode)
- `outputs/rubric_verification.json` (teacher-readable interpretation and confirmation/edit state)
- `outputs/review_feedback_latest.json` (latest persisted teacher review snapshot)
- `outputs/local_learning_profile.json` (local review summary and future runtime-prior seed)
- `outputs/aggregate_learning_summary.json` (governed aggregate-learning eligibility and retention summary)
- `outputs/usage_log.jsonl` (LLM token usage, if enabled)
- `outputs/usage_costs.json` (cost report, if enabled)

Notes
- The conventions scan is a heuristic baseline. For high-stakes marking, replace with a dedicated grammar engine.
- The consensus step is required before curve-based grading.
- Teacher review feedback is split into draft and finalized state. Only finalized reviews feed learning.
- Local personalization stays scoped and runtime-bounded through the local teacher prior.
- Product-wide learning now uses anonymized finalized-only records, project-level opt-in or policy-compliant collection, governed export/ingestion packages, and adjudication-required promotion staging under `bench/promoted/` and `inputs/exemplars/promoted/`.
- See `docs/LEGAL_NOTES.md` before production use.
- LLM routing: `config/llm_routing.json`
- Pricing config: `config/pricing.json`
- Cost limits: `config/cost_limits.json`
