# Compliance Report - Hero Path Grading Platform

**Last reviewed:** 2026-04-27
**Status:** Current test gates are green; historical LOC and 100% coverage claims are retired.

## Current Verification Contract

The project has outgrown the January 2026 point-in-time report that claimed
100% coverage and a 350-line aggregate module cap over a much smaller codebase.
The maintained verification contract is now:

- Run the fast deterministic suite from the repository root:
  `python3 -m pytest -q --no-cov`
- Run the package-local suite from `marking_framework/`:
  `python3 -m pytest -q`
- Generate package coverage as an explicit report:
  `python3 -m pytest --cov=scripts --cov=server --cov-branch --cov-report=term-missing --no-cov-on-fail`
- For launch readiness, use the production launch validator:
  `python3 scripts/validate_production_launch.py`

Coverage and legacy LOC metrics remain useful release evidence, but this
repository no longer advertises default gates requiring 100% coverage or a
350-line aggregate module cap. Any future threshold should be introduced as a
deliberate policy change with matching tests and updated release documentation.

## Current Local Evidence

The 2026-04-25 committee-edge validation slice was verified with:

- `python3 -m pytest -q --no-cov`
- `python3 -m pytest -q` from `marking_framework/`
- `python3 -m pytest --cov=scripts --cov=server --cov-branch --cov-report=term-missing --no-cov-on-fail` from `marking_framework/`
- `git diff --check`

The relevant Ghost hard-pair gate artifact for this slice is
`outputs/live_validation/consistency_checks.committee_edge.withheld_eval_contract_20260425T210609Z.json`.
It reports full critical accuracy after committee-withheld pairs are counted as
explicitly unresolved rather than falling back to stale lower-authority winners.

The 2026-04-27 source-family ranking slice was verified on branch
`codex/source-family-ranking-challenge` with:

- `python3 -m pytest -q --no-cov`
- `python3 -m pytest -q` from `marking_framework/`
- `git diff --check`

The focused live benchmark artifact is
`outputs/source_family_ranking_challenge/source_family_20260426T_focused_runs1_final2/`.
It reports exact `1.0`, Kendall `1.0`, pairwise `1.0`, and score-band MAE
`0.0` for the four targeted source-family datasets.

The 2026-04-27 source-scale floor preservation slice was verified on branch
`codex/source-scale-floor-preservation` with:

- `python3 -m pytest -q --no-cov marking_framework/tests/test_boundary_calibrator.py marking_framework/tests/test_aggregate_assessments.py marking_framework/tests/test_rubric_criteria.py marking_framework/tests/test_assessor_context.py marking_framework/tests/test_run_llm_assessors_helpers.py`
- `python3 -m pytest -q --no-cov` from the repository root
- `python3 -m pytest -q` from `marking_framework/`
- `python3 -m pytest --cov=scripts --cov=server --cov-branch --cov-report=term-missing --no-cov-on-fail` from `marking_framework/`
- `git diff --check`
- focused live validation over the post-merge regression cluster
- broad live validation over the full external corpus

The explicit coverage report passes and reports total coverage of `82%`. It
also emits pre-existing sqlite `ResourceWarning` noise from queue/replay tests;
those warnings do not fail the suite.

The focused live benchmark artifact is
`outputs/source_scale_floor_preservation/source_scale_floor_20260427T_negative_cluster_runs3_final/`.
It reports `0.0000` deltas for exact-level hit rate, within-one-level hit rate,
score-band MAE, mean rank displacement, Kendall tau, and pairwise order
agreement across:

- `internet_samples_eqao_orq`
- `thoughtful_assessment_grade6_8_instructions_hydrochloric`
- `thoughtful_assessment_grade6_8_persuasive_letter`

The broad live benchmark artifact is
`outputs/source_scale_floor_preservation/source_scale_floor_20260427T_broad_runs3_final/`.
It reports:

- datasets: `32`
- students: `133`
- exact-level hit delta: `+0.0602`
- within-one-level hit delta: `+0.0226`
- score-band MAE delta: `-1.4389`
- mean rank displacement delta: `-0.0752`
- Kendall tau delta: `+0.0501`
- pairwise order agreement delta: `+0.0251`
- negative dataset clusters: `0`

This is the current broad non-regression evidence for moving from speculative
calibration refinement to controlled teacher pilot testing. It is not a
production-launch certificate.

## Production Readiness References

Current production readiness must be evaluated from:

- `docs/LAUNCH_CONTRACT.md`
- `docs/PRODUCTION_OPERATIONS.md`
- `docs/INCIDENT_RESPONSE.md`
- `python3 scripts/validate_production_launch.py`

## Historical Note

The previous report was generated on 2026-01-31 against a 141-test codebase and
claimed 100% statement and branch coverage plus a 350-line aggregate module cap.
That snapshot is no longer the active project state and must not be used as
current release evidence.
