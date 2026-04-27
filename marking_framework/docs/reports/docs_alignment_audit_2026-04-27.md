# Docs Alignment Audit

Date: 2026-04-27

## Superseding Post-Merge Update

The source-family branch discussed below has since landed through PR `#9` at
merge commit `d75649389b9b9409fdba29a1f1cf754817e58a55`.

The recommended broad external-corpus packet has also been run from a fresh
post-merge worktree. It improved aggregate MAE, Kendall tau, pairwise
agreement, and rank displacement, but did not clear the teacher-pilot gate
because it exposed:

- a deterministic rank/level regression in `internet_samples_eqao_orq`
- level-only regressions in
  `thoughtful_assessment_grade6_8_instructions_hydrochloric` and
  `thoughtful_assessment_grade6_8_persuasive_letter`

The current decision is therefore to refine that source-scale floor preservation
cluster before teacher pilot expansion. See
`docs/reports/external_corpus_post_source_family_2026-04-27.md`.

Audited branch: `codex/source-family-ranking-challenge`

Base checked:

- `origin/main`: `4c379dd2cbda3cfbdd6fe04ef746efac12dd7087`
- source-family branch head: `99419f7f37319d668ac28ef00f3b518c9737cc5c`
- GitHub open PRs at audit time: none

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
- `docs/reports/source_family_ranking_challenge_2026-04-27.md`

## Findings

### 1. Main Is Behind The Latest Green Validation Branch

`origin/main` is still at the proof-quality/committee-withheld merge base. The
source-family ranking branch is pushed but not opened as a PR and not merged.

Current latest branch evidence:

- branch: `codex/source-family-ranking-challenge`
- commit: `99419f7f37319d668ac28ef00f3b518c9737cc5c`
- focused live packet:
  `outputs/source_family_ranking_challenge/source_family_20260426T_focused_runs1_final2/`
- targeted datasets all reached exact `1.0`, Kendall `1.0`, pairwise `1.0`,
  and score-band MAE `0.0`

Documentation now distinguishes branch-current evidence from merged-main truth.

### 2. Committee-Withheld Semantics Were Under-Documented

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

### 3. The SOTA Plan Was Still Pointing At Completed Work

`docs/SOTA_BUILD_PLAN.md` still framed the next decision as Ghost hard-pair live
validation, then broad external-corpus rerun, then Phase 11 form calibration.
That sequence is stale.

Current state:

- Ghost committee-withheld eval semantics are implemented and documented.
- Source-family ranking hardening for speech, persuasive-letter, NAEP, and UK
  portfolio residuals is complete on the pushed branch.
- The missing proof is a broad external-corpus rerun from the merged state.

`docs/SOTA_BUILD_PLAN.md` now points to:

1. open/review/merge `codex/source-family-ranking-challenge`
2. run one fresh release-comparable broad external-corpus packet from the merged
   state
3. start controlled teacher pilot testing if the broad packet is neutral or
   positive on accuracy and rank-order deltas
4. refine only if that packet exposes a new concentrated regression cluster

### 4. The Runtime Roadmap Needed A Teacher-Pilot Decision Boundary

`docs/ROADMAP.md` still described the active live-cohort issue as whether
committee decisions should become protected evidence. That is no longer the
current blocker.

The roadmap now states the current product question directly:

- does the source-family branch hold up after a merged broad-corpus rerun?
- do real teachers find the current human-in-the-loop flow useful, trustworthy,
  and efficient on their own cohorts?

This keeps teacher testing separate from production launch. Teacher pilot can
begin after merged broad-corpus non-regression; production launch still requires
strict identity, deployment, rollback, and launch-validator proof.

### 5. Coverage-Gate Docs Are Aligned

`docs/COMPLIANCE_REPORT.md` already retired the stale 100% default coverage
claim. It now also records the source-family slice evidence and explicitly says
that the focused packet is not a substitute for the next broad corpus packet.

## Files Updated

- `docs/SOTA_BUILD_PLAN.md`
- `docs/ROADMAP.md`
- `docs/WORKFLOW.md`
- `docs/DATA_FORMATS.md`
- `docs/COMPLIANCE_REPORT.md`
- `docs/reports/docs_alignment_audit_2026-04-27.md`

## State Of Play

The project is no longer blocked on the known Ghost committee-withheld seam or
the focused source-family ranking cluster. It is also not production-launch
ready in the strict deployment sense.

Current state:

- Merged `main`: behind latest focused ranking evidence.
- Pushed branch: green focused source-family validation, no open PR.
- Quality gates: local tests are green on the source-family branch.
- Missing evidence before broader teacher exposure: merged broad external-corpus
  rerun.
- Missing evidence before production launch: strict identity/staging launch
  validator and rollback rehearsal.

## Recommendation

Do not continue speculative refinement before teachers see the product.

The next right step is:

1. open/review/merge `codex/source-family-ranking-challenge`
2. run one fresh broad external-corpus packet from merged `main`
3. if the packet is neutral or positive, put the product in front of a small
   controlled teacher pilot

Teacher pilot should be framed as supervised product validation, not launch:

- teachers keep final authority
- collect qualitative trust/usability feedback
- capture finalized review deltas only when engagement is real
- monitor cohort confidence, override rate, rank moves, and feedback edits
- stop and refine only if the pilot or broad corpus exposes a concrete failure
