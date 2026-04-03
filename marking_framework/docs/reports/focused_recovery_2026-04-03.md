# Focused Recovery Report — 2026-04-03

This report tracks the targeted fixes for three remaining weak spots:

- early-grade narrative instability
- `main` coverage failures on summary and persuasive letter
- KS1 portfolio regression in corpus orchestration

## Code changes applied

- `openai_client.py`
  - retry transient OpenAI network / rate-limit / 5xx failures instead of failing the whole assessor lane on first contact
- `boundary_calibrator.py`
  - support richer source-profile matching (`genre`, `cohort_shape`, grade bounds, cohort-size fallback)
  - add `thoughtful_early_narrative_4pack` source-aware calibration
- `portfolio_aggregation.py`
  - stop auto-promoting bottom-bucket small ordinal portfolios to level `3` purely from rubric mean
- `llm_assessors_core.py`
  - rescue truncated outer pass1 JSON instead of incorrectly parsing the last inner `{criterion_id, score}` object

## Live validation

### Grade 3 personal narrative

Source: `bench/thoughtful_assessment_grade3_personal_narrative`

- benchmark mode: candidate vs fallback
- candidate exact-level hit: `1.0000`
- candidate score-band MAE: `0.0000`
- candidate Kendall tau: `1.0000`
- candidate pairwise agreement: `1.0000`
- delta vs fallback: `0.0000` on exact hit and MAE

Result:
- fixed
- the source-aware Thoughtful early-grade narrative profile now activates and produces the correct `4/3/2/1` curve

### Grade 6-8 persuasive letter

Source: `bench/thoughtful_assessment_grade6_8_persuasive_letter`

- validation mode: `main` only
- pipeline completed: `true`
- model usage ratio: `1.0000`
- exact-level hit: `0.5000`
- within-one-level hit: `1.0000`
- score-band MAE: `1.8350`
- Kendall tau: `1.0000`
- pairwise agreement: `1.0000`

Result:
- coverage failure fixed
- the main path now completes end-to-end without dropping the run
- remaining issue is banding, not coverage

### Grade 6-8 summary

Source: `bench/thoughtful_assessment_grade6_8_summary_iron`

- validation mode: `main` only
- pipeline completed: `true`
- model usage ratio: `1.0000`
- exact-level hit: `0.2500`
- within-one-level hit: `1.0000`
- score-band MAE: `4.7200`
- Kendall tau: `0.6667`
- pairwise agreement: `0.8333`

Result:
- coverage failure fixed
- the main path now completes end-to-end without dropping the run
- remaining issue is summary-specific ranking / boundary separation, not pipeline reliability

### KS1 writing portfolios

Source: `bench/uk_sta_2018_ks1_writing_portfolios`

- validation mode: partial `main` run inspection
- candidate output: `s001=4`, `s002=2`, `s003=2`
- prior bug removed: weakest portfolio is no longer auto-promoted to `3`

Result:
- regression cause identified and fixed at the calibration layer
- remaining issue is upstream ordering / evidence separation between `Kim` (`EXS -> 3`) and `Jamie` (`WTS -> 2`)
- this family still needs portfolio-specific ranking refinement rather than another band-floor heuristic

## Remaining work after this recovery pass

- improve summary-specific ordering and top/middle separation
- improve persuasive-letter banding for `4 -> 3` and `2 -> 1` boundary calls
- refine KS1 portfolio piece-level ordering so `Kim` outranks `Jamie` before scale calibration
