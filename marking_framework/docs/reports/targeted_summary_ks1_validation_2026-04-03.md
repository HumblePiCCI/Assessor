# Targeted Summary and KS1 Validation — 2026-04-03

## Scope

This report captures the focused live reruns used to validate two targeted fixes on branch `codex/stable-bell-curve`:

- summary-family top/mid separation for `bench/thoughtful_assessment_grade6_8_summary_iron`
- middle-band assignment for `bench/uk_sta_2018_ks1_writing_portfolios`

## Code changes validated

- same-prompt summary seed ordering from consensus summary-quality signals in [`run_llm_assessors.py`](/Users/bldt/Desktop/Essays/marking_framework/scripts/run_llm_assessors.py)
- stronger summary source-scale downward reach for the Thoughtful summary profile in [`marking_config.json`](/Users/bldt/Desktop/Essays/marking_framework/config/marking_config.json)
- early-grade ordinal-portfolio middle-band promotion margin in [`portfolio_aggregation.py`](/Users/bldt/Desktop/Essays/marking_framework/scripts/portfolio_aggregation.py)

## Dataset: Thoughtful Summary Iron

Live run output:
- `/tmp/targeted_rerun_summary_2026-04-03_v4/benchmark_report.json`

Candidate (`main`)
- exact-level hit: `1.0`
- within-one-level hit: `1.0`
- score-band MAE: `0.0`
- mean rank displacement: `0.0`
- Kendall tau: `1.0`
- pairwise order agreement: `1.0`
- model usage ratio: `1.0`

Baseline (`fallback`)
- exact-level hit: `1.0`
- within-one-level hit: `1.0`
- score-band MAE: `0.0`
- mean rank displacement: `0.0`
- Kendall tau: `1.0`
- pairwise order agreement: `1.0`

Candidate final order and levels:
- `s001` Strong -> `4`
- `s002` Good -> `3`
- `s003` Okay -> `2`
- `s004` Poor -> `1`

Interpretation:
- The summary-family fix is now clean on the targeted benchmark.
- The same-prompt summary seed order produced stable pass2 rankings `s001 > s002 > s003 > s004`.

## Dataset: UK STA KS1 Writing Portfolios

Live run output:
- `/tmp/targeted_rerun_ks1_2026-04-03_v2/benchmark_report.json`

Candidate (`main`)
- exact-level hit: `1.0`
- within-one-level hit: `1.0`
- score-band MAE: `0.0`
- mean rank displacement: `0.0`
- Kendall tau: `1.0`
- pairwise order agreement: `1.0`
- model usage ratio: `1.0`

Baseline (`fallback`)
- exact-level hit: `1.0`
- within-one-level hit: `1.0`
- score-band MAE: `0.0`
- mean rank displacement: `0.0`
- Kendall tau: `1.0`
- pairwise order agreement: `1.0`

Candidate final order and levels:
- `s001` Ali -> `4`
- `s002` Kim -> `3`
- `s003` Jamie -> `2`

Interpretation:
- The portfolio middle-band fix worked.
- The candidate path now preserves the corrected order `Ali > Kim > Jamie` and lands `Kim` in the correct band instead of under-leveling to `2`.

## Takeaway

Both targeted weak spots addressed in this slice now validate cleanly on live reruns:

- summary-family top/mid separation: fixed on the targeted Thoughtful summary set
- KS1 correctly ranked middle-case banding: fixed on the targeted STA KS1 portfolio set
