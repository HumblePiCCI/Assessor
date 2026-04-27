# Docs Alignment Audit

Date: 2026-04-27

Audited branch: `codex/source-scale-floor-preservation`

Base checked:

- `origin/main`: `d75649389b9b9409fdba29a1f1cf754817e58a55`
- source-scale floor preservation branch:
  `codex/source-scale-floor-preservation`
- GitHub open PRs at audit time: none

Superseding update: the original source-family audit below is preserved as the
historical decision record for that branch. Current project state has advanced:
the source-family branch is merged, and this source-scale floor preservation
slice has generated a positive full external-corpus packet with no negative
dataset clusters.

## Source Of Truth Checked

- `scripts/committee_edge_resolver.py`
- `scripts/evaluate_pairwise_adjudicator.py`
- `scripts/run_llm_assessors.py`
- `scripts/boundary_calibrator.py`
- `scripts/aggregate_assessments.py`
- `scripts/portfolio_aggregation.py`
- `config/marking_config.json`
- `config/rubric_criteria.json`
- `tests/test_committee_edge_resolver.py`
- `tests/test_evaluate_pairwise_adjudicator.py`
- `tests/test_boundary_calibrator.py`
- `tests/test_portfolio_aggregation.py`
- `tests/test_run_llm_assessors_helpers.py`
- `README.md`
- `QUICK_START.md`
- `docs/LIVE_COHORT_RUNTIME.md`
- `docs/LAUNCH_CHECKLIST.md`
- `docs/TEACHER_PILOT_RUNBOOK.md`
- `docs/reports/source_family_ranking_challenge_2026-04-27.md`
- `docs/reports/source_scale_floor_preservation_2026-04-27.md`

## Findings

### 1. Teacher-Pilot Preparation Needed A Concrete Runbook

The top-level roadmap and SOTA plan correctly pointed toward a controlled
teacher pilot after the source-scale branch merges, but the documentation did
not yet give an operator a single pilot-ready workflow with preconditions,
evidence capture, metrics, stop rules, and hard boundaries.

Added `docs/TEACHER_PILOT_RUNBOOK.md` to define:

- pilot scope and non-launch boundary
- preconditions before first teacher cohort
- cohort-selection constraints
- operator workflow from fresh `main` through finalization
- artifacts to capture per cohort
- teacher-facing qualitative questions
- metrics to monitor
- stop rules for pausing pilot expansion and opening a targeted engineering
  slice

Linked that runbook from `README.md`, `docs/LIVE_COHORT_RUNTIME.md`, and
`docs/LAUNCH_CHECKLIST.md`.

### 2. Quick Start Was Still Pointing At Legacy Manual Pairwise Flow

`QUICK_START.md` still used the older `generate_pairwise_review.py` /
`apply_pairwise_adjustments.py` path as the main step-8 workflow. That is no
longer the canonical rank path.

Updated quick-start commands now route through:

- `band_seam_adjudication.py`
- `verify_consistency.py`
- `escalate_pairwise_adjudications.py`
- `evidence_map.py`
- `committee_edge_resolver.py`
- `global_rerank.py`
- `evaluate_pairwise_adjudicator.py`

The doc now says legacy manual pairwise files still exist, but the canonical
path is pairwise consistency, routed escalation, evidence map, committee-edge
merge, global rerank, and hard-pair eval.

### 3. SOTA And Roadmap Had One Remaining Broad-Rerun Drift

One lower SOTA section still described the merged broad-corpus refresh as
missing. One roadmap section still described full-corpus non-regression as part
of the active transfer risk. Both were stale after the source-scale floor
preservation packet.

Updated state:

- broad-corpus refresh is complete on `codex/source-scale-floor-preservation`
- full corpus packet is positive overall
- negative dataset clusters are `0`
- active risk is now teacher-world transfer: usability, trust, and override
  concentration on unfamiliar cohorts

### 4. Source-Scale Floor Preservation Supersedes The Broad-Rerun Blocker

The previous audit identified the merged broad external-corpus rerun as the
proof gap before teacher testing. That rerun has now been performed from a
fresh `origin/main` worktree after the source-family merge.

Current evidence:

- branch: `codex/source-scale-floor-preservation`
- base: `d75649389b9b9409fdba29a1f1cf754817e58a55`
- focused regression-cluster packet:
  `outputs/source_scale_floor_preservation/source_scale_floor_20260427T_negative_cluster_runs3_final/`
- full corpus packet:
  `outputs/source_scale_floor_preservation/source_scale_floor_20260427T_broad_runs3_final/`
- broad deltas: exact `+0.0602`, within-one `+0.0226`, MAE `-1.4389`,
  mean rank displacement `-0.0752`, Kendall `+0.0501`, pairwise `+0.0251`
- negative dataset clusters: `0`

Docs now reflect that the next right product step, after this branch merges, is
a controlled teacher pilot rather than another speculative calibration slice.

### 5. Main Is Behind The Latest Green Validation Branch

Historical source-family finding from the original audit: `origin/main` was
still at the proof-quality/committee-withheld merge base, while the
source-family ranking branch was pushed but not opened as a PR and not merged.

Current status: this is resolved. The source-family ranking branch has merged
to `main`, and the current branch starts from that merged base.

Current latest branch evidence:

- branch: `codex/source-family-ranking-challenge`
- commit: `99419f7f37319d668ac28ef00f3b518c9737cc5c`
- focused live packet:
  `outputs/source_family_ranking_challenge/source_family_20260426T_focused_runs1_final2/`
- targeted datasets all reached exact `1.0`, Kendall `1.0`, pairwise `1.0`,
  and score-band MAE `0.0`

Documentation now distinguishes branch-current source-scale floor preservation
evidence from merged-main truth.

### 6. Committee-Withheld Semantics Were Under-Documented

The code now uses the evaluator contract rather than canonical tombstones:

- protected committee decisions become canonical `committee_edge` evidence
- `suppress_ambiguous`, `needs_retry`, and `needs_group_read` decisions remain
  in committee metadata and trace/report artifacts
- lower-authority checks may remain available for ordinary rerank continuity
- hard-pair eval reads committee protection metadata and reports those pairs as
  `withheld`/unresolved instead of counting a stale lower-authority winner

`docs/WORKFLOW.md` and `docs/DATA_FORMATS.md` were updated so they no longer
say, without qualification, that suppressed committee decisions simply fall
back to the previous active judgment.

### 7. The SOTA Plan Was Still Pointing At Completed Work

`docs/SOTA_BUILD_PLAN.md` still framed the next decision as Ghost hard-pair live
validation, then broad external-corpus rerun, then Phase 11 form calibration.
That sequence is stale.

Historical state at the original audit:

- Ghost committee-withheld eval semantics are implemented and documented.
- Source-family ranking hardening for speech, persuasive-letter, NAEP, and UK
  portfolio residuals is complete on the pushed branch.
- The missing proof is a broad external-corpus rerun from the merged state.

Current state after this source-scale floor preservation update:

- Ghost committee-withheld eval semantics are implemented and documented.
- Source-family ranking hardening is merged.
- The broad external-corpus rerun is complete and positive overall, with no
  negative dataset clusters.

`docs/SOTA_BUILD_PLAN.md` now points to:

1. review/merge `codex/source-scale-floor-preservation`
2. start controlled teacher pilot testing
3. refine only if the pilot or a new validation packet exposes a concrete
   concentrated failure

### 8. The Runtime Roadmap Needed A Teacher-Pilot Decision Boundary

`docs/ROADMAP.md` still described the active live-cohort issue as whether
committee decisions should become protected evidence. That is no longer the
current blocker.

The roadmap now states the current product question directly:

- do real teachers find the current human-in-the-loop flow useful, trustworthy,
  and efficient on their own cohorts?
- where do real teacher overrides concentrate once the benchmark corpus is no
  longer producing a known regression cluster?

This keeps teacher testing separate from production launch. Teacher pilot can
begin after `codex/source-scale-floor-preservation` is reviewed and merged;
production launch still requires strict identity, deployment, rollback, and
launch-validator proof.

### 9. Coverage-Gate Docs Are Aligned

`docs/COMPLIANCE_REPORT.md` already retired the stale 100% default coverage
claim. It now records both the source-family slice evidence and the source-scale
floor preservation broad packet evidence, while explicitly keeping production
launch certification separate.

## Files Updated

- `docs/SOTA_BUILD_PLAN.md`
- `docs/ROADMAP.md`
- `docs/WORKFLOW.md`
- `docs/DATA_FORMATS.md`
- `docs/COMPLIANCE_REPORT.md`
- `docs/LIVE_COHORT_RUNTIME.md`
- `docs/LAUNCH_CHECKLIST.md`
- `docs/TEACHER_PILOT_RUNBOOK.md`
- `README.md`
- `QUICK_START.md`
- `docs/reports/docs_alignment_audit_2026-04-27.md`
- `docs/reports/source_scale_floor_preservation_2026-04-27.md`

## State Of Play

The project is no longer blocked on the known Ghost committee-withheld seam or
the focused source-family ranking cluster. It is also not production-launch
ready in the strict deployment sense.

Current state:

- Merged `main`: includes source-family ranking hardening.
- Active branch: source-scale floor preservation with focused and broad live
  validation artifacts.
- Quality gates: targeted tests, root fast suite, package-local suite, explicit
  coverage report, and `git diff --check` are green on the active branch.
- Missing evidence before broader teacher exposure: this branch must be
  reviewed and merged.
- Missing evidence before production launch: strict identity/staging launch
  validator and rollback rehearsal.

## Recommendation

Do not continue speculative refinement before teachers see the product.

The next right step is:

1. open/review/merge `codex/source-scale-floor-preservation`
2. put the product in front of a small controlled teacher pilot
3. stop and refine only if pilot evidence exposes a concrete failure cluster

Teacher pilot should be framed as supervised product validation, not launch:

- teachers keep final authority
- collect qualitative trust/usability feedback
- capture finalized review deltas only when engagement is real
- monitor cohort confidence, override rate, rank moves, and feedback edits
- stop and refine only if the pilot or a new validation packet exposes a
  concrete failure
