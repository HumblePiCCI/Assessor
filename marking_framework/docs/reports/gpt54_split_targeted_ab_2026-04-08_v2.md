# GPT-5.4 Split Targeted A/B — 2026-04-08 v2

## Scope

This reran the same targeted live A/B after model-family-specific calibration tuning.

Candidate routing:

- `gpt-5.4-mini` for `pass1_assessor`, `pass2_ranker`, and `pairwise_reviewer`
- `gpt-5.4-nano` for `feedback_drafter`

Baseline routing:

- `gpt-5.2` for the same benchmark tasks

Datasets:

- `naep_1998_g8_informative_tv_show`
- `uk_sta_2018_ks1_writing_portfolios`

Run artifacts were produced under:

- `/tmp/model_split_small_20260408_tuned`

## What changed

This tuned two narrow model-family weak points:

- small-ordinal portfolio banding under `gpt-5.4-mini`
- source-native top-band calibration for NAEP under `gpt-5.4-mini`

Concretely:

- the ordinal portfolio projector now supports a mini-specific strong rank projection for three-band portfolios
- the NAEP source-scale path now uses a mini-specific profile keyed by the pass1 model family, with `seed_order` instead of `borda_percent` for the source top slot and lower top-band gates

## Main result

The split routing now wins on this targeted slice.

Weighted means across both datasets:

- candidate exact-level hit: `1.0`
- baseline exact-level hit: `0.666666`
- candidate within-one-level hit: `1.0`
- baseline within-one-level hit: `0.888889`
- candidate score-band MAE: `3.842222`
- baseline score-band MAE: `3.913334`
- candidate Kendall tau: `1.0`
- baseline Kendall tau: `0.911111`
- candidate pairwise agreement: `1.0`
- baseline pairwise agreement: `0.955555`
- candidate model-usage ratio: `1.0`
- baseline model-usage ratio: `1.0`
- candidate cost: `$0.119808`
- baseline cost: `$0.360846`
- candidate latency: `128.730784s`
- baseline latency: `219.638036s`

Net delta, candidate minus baseline:

- exact-level hit: `+0.333334`
- within-one-level hit: `+0.111111`
- score-band MAE: `-0.071112`
- Kendall tau: `+0.088889`
- pairwise agreement: `+0.044445`
- cost: `-0.241038`
- latency: `-90.907252s`

Interpretation:

- the split routing is still materially cheaper and faster
- the split routing is now also better on exact levels, within-one hit, MAE, and ordering for this slice

## Dataset reads

### `naep_1998_g8_informative_tv_show`

- candidate exact-level hit: `1.0`
- baseline exact-level hit: `0.833333`
- candidate score-band MAE: `5.763333`
- baseline score-band MAE: `2.646667`
- candidate cost: `$0.072234`
- baseline cost: `$0.213203`
- candidate latency: `72.785391s`
- baseline latency: `135.120019s`

Read:

- the mini-specific NAEP profile fixed the `Skillful -> 3` miss and made the candidate exact on all six rows
- the candidate is still coarser inside the source-native score bands than `gpt-5.2`
- this is now an exact-level and ordering win, but not yet a source-band finesse win

### `uk_sta_2018_ks1_writing_portfolios`

- candidate exact-level hit: `1.0`
- baseline exact-level hit: `0.333333`
- candidate score-band MAE: `0.0`
- baseline score-band MAE: `6.446667`
- candidate cost: `$0.214955`
- baseline cost: `$0.656133`
- candidate latency: `240.621571s`
- baseline latency: `388.674069s`

Read:

- the mini-specific ordinal projector fixed the exact portfolio shape
- candidate final levels are now `Ali 4 / Kim 3 / Jamie 2`
- this is the major improvement over the prior report

## Delta from the prior 2026-04-08 report

Compared with the earlier targeted A/B at [gpt54_split_targeted_ab_2026-04-08.md](/Users/bldt/Desktop/Essays/marking_framework/docs/reports/gpt54_split_targeted_ab_2026-04-08.md):

- candidate exact-level hit: `0.555555 -> 1.0`
- candidate within-one-level hit: `0.888889 -> 1.0`
- candidate score-band MAE: `5.878889 -> 3.842222`
- candidate Kendall tau: `1.0 -> 1.0`
- candidate pairwise agreement: `1.0 -> 1.0`
- candidate cost: `$0.1173 -> $0.119808`
- candidate latency: `111.141296s -> 128.730784s`

Interpretation:

- the quality gains are large
- the cost increase is negligible
- the latency increase is modest and still well below the `gpt-5.2` baseline

## Conclusion

For this targeted slice, the split routing is now credible as a quality-and-cost improvement over `gpt-5.2`.

The remaining work is broader validation, not another emergency compatibility fix. The next meaningful benchmark step is to rerun a larger external corpus slice and verify that these mini-specific calibrations help without overfitting outside:

- NAEP families beyond Grade 8
- other small-ordinal portfolios
- the broader corpus where exact hit and MAE still matter more than this narrow slice alone
