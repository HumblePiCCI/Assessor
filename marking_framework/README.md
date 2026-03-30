Standardized Marking Workspace

Purpose
- Provide a repeatable, multi-pass marking workflow using a rubric, an assignment outline, and a set of student submissions.
- Enforce conventions tracking, rubric adherence, comparative ranking, and consensus ordering before curve-based grades.

Quick Start
0) Optional Hero Path orchestration
   - `python3 scripts/hero_path.py --verify-consistency --apply-consistency --build-dashboard`
   - LLM assessors: add `--llm-assessors` (requires OPENAI_API_KEY)

1) Place inputs
   - Rubric: `inputs/rubric.docx` or `inputs/rubric.md`
   - Assignment outline: `inputs/assignment_outline.docx` or `inputs/assignment_outline.md`
   - Student work: `inputs/submissions/`
   - Optional class metadata: `inputs/class_metadata.json` (e.g., {"grade_level": 7})
   - Validate metadata: `python3 scripts/validate_metadata.py`

2) Normalize submissions
   - `python3 scripts/extract_text.py --inputs inputs/submissions --output processing/normalized_text`

3) Conventions scan (baseline)
   - `python3 scripts/conventions_scan.py --inputs processing/normalized_text --output processing/conventions_report.csv`

4) Assessor passes (LLM agents)
   - Use prompts in `prompts/`.
   - Save outputs to:
     - `assessments/pass1_individual/` (per-assessor JSON)
     - `assessments/pass2_comparative/` (per-assessor rank list)

5) Aggregate to consensus
   - `python3 scripts/aggregate_assessments.py --config config/marking_config.json`

6) Collect pairwise consistency evidence and rerank globally
   - `python3 scripts/verify_consistency.py`
   - `python3 scripts/global_rerank.py`
   - Or via Hero Path: `python3 scripts/hero_path.py --verify-consistency --apply-consistency`

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
   - Saved review feedback is versioned and exported for replay, but runtime personalization from teacher feedback is still a planned follow-on step

10) Pay-as-you-go job runner (optional)
   - `python3 scripts/payg_job.py --rubric inputs/rubric.md --outline inputs/assignment_outline.md --submissions inputs/submissions --llm --pricing`
   - Minimal API server: `python3 -m uvicorn server.app:app --reload`

Key Outputs
- `outputs/ranked_list.md` (consensus order + confidence signals)
- `outputs/consensus_scores.csv` (rubric means, conventions, Borda, composite scores)
- `outputs/irr_metrics.json` (inter-rater reliability: ICC, Kendall's W)
- `outputs/grade_curve.csv` (level-aware bell-curve grades based on the resolved order)
- `outputs/pairwise_matrix.json` (normalized pairwise evidence and support/opposition weights)
- `outputs/consistency_report.json` (rerank diagnostics, movements, and uncertainty details)
- `outputs/final_order.csv` (post global rerank order)
- `outputs/feedback_summaries/` (two stars and a wish with validated quotes)
- `outputs/dashboard_data.json` (UI data)
- `outputs/review_feedback_latest.json` (latest persisted teacher review snapshot)
- `outputs/local_learning_profile.json` (local review summary and future runtime-prior seed)
- `outputs/usage_log.jsonl` (LLM token usage, if enabled)
- `outputs/usage_costs.json` (cost report, if enabled)

Notes
- The conventions scan is a heuristic baseline. For high-stakes marking, replace with a dedicated grammar engine.
- The consensus step is required before curve-based grading.
- Saved teacher review feedback is persisted and exported for replay into benchmarks and calibration candidates. The production plan still needs to add finalized-review-only learning before those signals are applied back into runtime ranking.
- See `docs/LEGAL_NOTES.md` before production use.
- LLM routing: `config/llm_routing.json`
- Pricing config: `config/pricing.json`
- Cost limits: `config/cost_limits.json`
