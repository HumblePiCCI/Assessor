# Compliance Report - Hero Path Grading Platform

**Last reviewed:** 2026-04-25
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
