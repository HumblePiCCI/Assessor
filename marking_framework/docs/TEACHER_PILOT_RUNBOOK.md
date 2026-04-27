# Teacher Pilot Runbook

Status
- State: ready on merged `main`
- Scope: controlled teacher pilot, not production launch
- Last updated: 2026-04-27

## Purpose

The benchmark and broad-corpus evidence now supports moving from speculative
calibration refinement to supervised teacher testing. This runbook defines the
pilot boundary so the first teacher cohorts produce useful product evidence
without being mistaken for an unattended launch.

The pilot asks:

- Can a teacher complete the upload, rubric confirmation, scoring, review,
  adjustment, feedback, and finalization flow?
- Do the confidence, anchor, and disagreement surfaces point the teacher to the
  right places?
- Do teacher overrides concentrate around a specific failure mode that should
  become the next engineering slice?

## Current Evidence Before Pilot

The pilot is justified by:

- Ghost committee-withheld hard pairs now report withheld/unresolved outcomes
  instead of stale lower-authority winners.
- Source-family ranking hardening is merged for speech, persuasive letter,
  NAEP, and UK STA portfolio cases.
- Source-scale floor preservation on
  `codex/source-scale-floor-preservation` fixes the post-merge broad-corpus
  regression cluster.
- Full external-corpus packet:
  `outputs/source_scale_floor_preservation/source_scale_floor_20260427T_broad_runs3_final/`
- Broad packet deltas: exact `+0.0602`, within-one `+0.0226`, MAE `-1.4389`,
  mean rank displacement `-0.0752`, Kendall `+0.0501`, pairwise `+0.0251`.
- Negative dataset clusters: `0`.

The pilot is still not a production-launch certificate. Launch requires real
auth integration, strict launch-validator proof, and rollback rehearsal in a
staging or production-like environment.

## Pilot Preconditions

Before the first teacher cohort:

- Current `main` includes source-scale floor preservation.
- The operator starts from a fresh, clean `main` checkout.
- `python3 -m pytest -q --no-cov` passes from the repository root.
- `python3 -m pytest -q` passes from `marking_framework/`.
- The teacher understands that they retain final grading authority.
- The cohort has permission for supervised product testing.
- No grades are published to students, guardians, or school systems directly
  from the pilot output.
- Any retained aggregate-learning record must pass the engagement and collection
  policy gates already implemented in `server/review_store.py`.

Recommended cohort shape:

- `2-4` teachers for the first pass.
- `1` class project per teacher.
- `10-30` submissions per project.
- Known assignment outline and teacher-owned rubric.
- Prefer ordinary classroom assignments before high-stakes assessments.

## Operator Workflow

1. Refresh the repo.

   ```bash
   git checkout main
   git pull --ff-only origin main
   cd marking_framework
   ```

2. Set the runtime environment.

   ```bash
   export OPENAI_API_KEY=<key>
   export APP_MODE=codex_local
   ```

3. Start a fresh server process.

   ```bash
   python3 -m uvicorn server.app:app --host 127.0.0.1 --port 8002
   ```

4. Create a new project in the UI and upload:

   - rubric
   - assignment outline
   - class metadata if available
   - student submissions

5. Run the full queue-backed pipeline.

6. If the job pauses for rubric confirmation:

   - teacher reviews `outputs/rubric_verification.json` through the UI
   - teacher confirms or makes a small correction
   - job resumes

7. If the job pauses for anchor calibration:

   - teacher reviews the proposed anchors
   - teacher supplies anchor levels and optional marks only
   - job resumes from the post-assessment steps
   - hold-harmless metrics decide whether the anchor patch is retained

8. Teacher reviews:

   - final order
   - level/mark suggestions
   - disagreement and confidence signals
   - generated feedback
   - curve top/bottom settings

9. Teacher saves draft changes as needed, then finalizes only when the curve and
   review decisions are settled.

10. Operator records pilot evidence before moving to the next cohort.

## Evidence To Capture Per Cohort

Keep the project and job identifiers with these artifacts:

- `outputs/scope_grounding.json`
- `outputs/cohort_confidence.json`
- `outputs/rubric_verification.json`
- `outputs/consistency_report.json`
- `outputs/final_order.csv`
- `outputs/grade_curve.csv`
- `outputs/dashboard_data.json`
- `outputs/review_feedback_latest.json`
- `outputs/engagement_signal.json`
- `outputs/local_learning_profile.json`
- `server/data/reviews/<project_id>/latest_review.json`

When present, also capture:

- `outputs/teacher_anchor_packet.json`
- `outputs/cohort_anchor_calibration.json`
- `anchor_state/pre_anchor_metrics.json`
- `anchor_state/post_anchor_metrics.json`
- `outputs/committee_edge_report.json`
- `outputs/committee_edge_live_trace.json`
- `outputs/pairwise_adjudicator_eval.json`

Collect short qualitative notes from the teacher:

- Was the proposed order broadly credible?
- Which papers did they move, and why?
- Did the system surface the right uncertain cases?
- Was rubric confirmation understandable?
- Was anchor calibration useful or confusing?
- Was generated feedback usable after teacher review?

## Metrics To Watch

Primary product signals:

- teacher completion rate
- time from upload to reviewable dashboard
- number of rubric-confirmation edits
- anchor-calibration required rate
- anchor patch accepted/reverted rate
- teacher override rate
- top-pack movement after teacher review
- final-order moves concentrated by grade band, genre, rubric family, or source
  family
- feedback edit rate
- quote-validation failures
- teacher trust/usability notes

Runtime signals:

- `cohort_confidence.effective_state`
- `consistency_report.swap_rate`
- `consistency_report.boundary_disagreement_concentration`
- `committee_direct_edge_violation_count`
- model usage and cost from `outputs/usage_costs.json`
- queue failure or pause/resume errors

## Stop Rules

Pause pilot expansion and open a targeted engineering slice if any of these
occur:

- upload, rubric confirmation, anchor resume, or finalization fails for reasons
  unrelated to local operator setup
- the UI hides a required teacher action or makes the next action ambiguous
- a cohort is presented as high confidence but teacher review requires broad
  reordering
- teacher overrides concentrate around one grade band, genre, source family, or
  rubric family
- protected committee edges produce surviving direct-edge violations
- source-scale floors create a new negative validation cluster
- feedback quote validation fails after normal generation
- teachers cannot explain or trust why the top-pack order was proposed

Continue the controlled pilot when issues are isolated to teacher preference,
ordinary rubric interpretation, or expected cold-start uncertainty that the UI
surfaces clearly and the teacher can resolve.

## Hard Boundaries

Do not treat pilot success as production launch.

Do not:

- auto-publish grades externally
- bypass teacher final authority
- treat draft review edits as learning signal
- retain product-wide aggregate data unless engagement and collection-policy
  gates pass
- tune globally from one teacher or one cohort
- run live committee reads unless the operator has explicitly opted into the
  additional model cost and audit trace

## Post-Cohort Review

After each cohort:

1. Archive the evidence packet with project ID, job ID, branch SHA, and date.
2. Summarize teacher notes and override concentration.
3. Classify outcome as:
   - `pilot_continue`
   - `pilot_continue_with_watch_item`
   - `engineering_slice_required`
4. If a slice is required, ground it in the specific artifacts and teacher
   decisions that exposed the failure.

The next engineering slice should come from this evidence, not from speculative
calibration work.
