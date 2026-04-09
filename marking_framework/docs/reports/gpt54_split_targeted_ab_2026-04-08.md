# GPT-5.4 Split Targeted A/B — 2026-04-08

## Scope

This targeted live A/B compared the current split routing:

- `gpt-5.4-mini` for `pass1_assessor`, `pass2_ranker`, and `pairwise_reviewer`
- `gpt-5.4-nano` for `feedback_drafter`

against a temporary legacy routing that pinned the same tasks to `gpt-5.2`.

Datasets:

- `naep_1998_g8_informative_tv_show`
- `uk_sta_2018_ks1_writing_portfolios`

Run artifacts were produced under:

- `/tmp/model_split_small_20260408_retry`

## Main finding

The pass1 compatibility fixes worked for `gpt-5.4-mini`: model coverage reached `1.0` on both datasets, and the run completed without the earlier structured-output collapse.

However, the split routing is not yet stronger than the `gpt-5.2` baseline on grading quality for this slice.

Weighted means across both datasets:

- candidate exact-level hit: `0.555555`
- baseline exact-level hit: `0.666666`
- candidate within-one-level hit: `0.888889`
- baseline within-one-level hit: `0.888889`
- candidate score-band MAE: `5.878889`
- baseline score-band MAE: `3.3`
- candidate Kendall tau: `1.0`
- baseline Kendall tau: `1.0`
- candidate pairwise agreement: `1.0`
- baseline pairwise agreement: `1.0`
- candidate model-usage ratio: `1.0`
- baseline model-usage ratio: `1.0`
- candidate cost: `$0.1173`
- baseline cost: `$0.363498`
- candidate latency: `111.141296s`
- baseline latency: `239.242176s`

Net delta, candidate minus baseline:

- exact-level hit: `-0.111111`
- within-one-level hit: `0.0`
- score-band MAE: `+2.578889`
- Kendall tau: `0.0`
- pairwise agreement: `0.0`
- model-usage ratio: `0.0`
- cost: `-0.246198`
- latency: `-128.10088s`

Interpretation:

- the split routing is materially cheaper and faster
- ordering quality is unchanged on this slice
- banding quality is worse than `gpt-5.2`

## Dataset reads

### `naep_1998_g8_informative_tv_show`

- candidate exact-level hit: `0.833333`
- baseline exact-level hit: `0.833333`
- candidate score-band MAE: `3.611667`
- baseline score-band MAE: `1.666667`
- candidate cost: `$0.070407`
- baseline cost: `$0.217402`
- candidate latency: `63.390995s`
- baseline latency: `156.063233s`

Read:

- `gpt-5.4-mini` matched `gpt-5.2` on exact levels and ordering
- `gpt-5.4-mini` was cheaper and faster
- the remaining delta is score-band calibration, especially the `Skillful -> 3` compression

### `uk_sta_2018_ks1_writing_portfolios`

- candidate exact-level hit: `0.0`
- baseline exact-level hit: `0.333333`
- candidate score-band MAE: `10.413333`
- baseline score-band MAE: `6.566667`
- candidate cost: `$0.211086`
- baseline cost: `$0.65569`
- candidate latency: `206.641898s`
- baseline latency: `405.600063s`

Read:

- both routings preserved the correct rank order
- `gpt-5.4-mini` still under-banded the full KS1 portfolio cohort
- the candidate produced `2 / 2 / 1` style banding behavior where the legacy path still retained one `3`

## Conclusion

The compatibility pass should be kept because it fixes the `gpt-5.4-mini` structured-output reliability failure mode. The model split is now benchmarkable on live data.

But the split routing should not yet be treated as a pure upgrade over `gpt-5.2` for the assessment core. The next work should target:

- KS1 and other small-ordinal portfolio banding under `gpt-5.4-mini`
- score-band calibration for source-native top bands
- a larger A/B after those calibrations are tuned for the new model family
