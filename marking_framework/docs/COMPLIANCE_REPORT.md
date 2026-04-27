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

The focused live benchmark artifact was
`outputs/source_family_ranking_challenge/source_family_20260426T_focused_runs1_final2/`.
It reports exact `1.0`, Kendall `1.0`, pairwise `1.0`, and score-band MAE
`0.0` for the four targeted source-family datasets. This is focused
non-regression evidence, not a substitute for the next broad external-corpus
packet after merge.

The source-family branch landed through PR `#9` at merge commit
`d75649389b9b9409fdba29a1f1cf754817e58a55`.

The post-merge broad external-corpus packet was run from fresh branch
`codex/external-corpus-post-source-family` with:

```bash
python3 scripts/benchmark_corpus.py --runs 3 \
  --candidate-routing config/llm_routing_benchmark.json \
  --candidate-label main \
  --baseline-label fallback \
  --output outputs/external_corpus_validation/external_corpus_20260427T_post_source_family_runs3
```

Aggregate deltas were neutral or positive on the main quality metrics:

- exact-level hit delta: `0.0000`
- within-one-level hit delta: `+0.0075`
- score-band MAE delta: `-0.7463`
- Kendall tau delta: `+0.0261`
- pairwise-order agreement delta: `+0.0130`

The packet is not a teacher-pilot clearance because it exposed a deterministic
EQAO ORQ source-scale top-anchor regression and two level-only Thoughtful
Learning regressions. Current report:
`docs/reports/external_corpus_post_source_family_2026-04-27.md`.

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
