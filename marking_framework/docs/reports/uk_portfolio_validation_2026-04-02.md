# UK Portfolio Validation

- Date: 2026-04-02
- Branch: `codex/stable-bell-curve`
- Commit: `3ceca85`

## Summary
- KS1 exact-level hit: `1.0000`
- KS2 exact-level hit: `1.0000`
- Both UK STA portfolio sets now validate cleanly on canonical levels and order under the current portfolio path.

## uk_sta_2018_ks1_writing_portfolios
- Validation mode: `candidate_run_reaggregated_with_current_portfolio_calibration`
- Exact-level hit rate: 1.0000
- Within-one-level hit rate: 1.0000
- Score-band MAE: 0.0000
- Kendall tau: 1.0000
- Pairwise order agreement: 1.0000
- Student outcomes:
  - Ali (s001): gold 4, predicted 4, score 81.50, rank 1
  - Kim (s002): gold 3, predicted 3, score 71.50, rank 2
  - Jamie (s003): gold 2, predicted 2, score 62.97, rank 3
- Notes:
  - KS1 validation re-used a completed candidate workspace from the prior portfolio-piece run and re-ran aggregation with the current ordinal portfolio calibration.
  - The final canonical mapping is 4 / 3 / 2 with exact rank agreement.

## uk_sta_2018_ks2_writing_portfolios
- Validation mode: `fresh_candidate_only_run`
- Exact-level hit rate: 1.0000
- Within-one-level hit rate: 1.0000
- Score-band MAE: 0.0000
- Kendall tau: 1.0000
- Pairwise order agreement: 1.0000
- Cost (USD): 1.003046
- Latency (s): 2672.2051
- Student outcomes:
  - Frankie (s001): gold 4, predicted 4, score 81.50, rank 1
  - Leigh (s002): gold 3, predicted 3, score 71.88, rank 2
  - Morgan (s003): gold 3, predicted 3, score 71.50, rank 3
  - Dani (s004): gold 2, predicted 2, score 62.54, rank 4
- Notes:
  - KS2 validation was run end-to-end on the current branch with the candidate routing profile.
  - The candidate path completed cleanly with no observed llm_failures and perfect level/order agreement on the explicit-gold set.

## Conclusion
The piece-level portfolio scorer and ordinal portfolio calibration recover both UK STA portfolio datasets to exact 1.0 candidate alignment on canonical levels.
