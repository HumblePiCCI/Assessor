# GPT-5.4 Split NAEP Stability

- Generated: 2026-04-09T22:10:02.946916+00:00
- Datasets: 3
- Students: 18
- Runs per dataset: 2

## Final Candidate Summary
- Exact-level hit rate: 0.8611
- Within-one-level hit rate: 0.9167
- Score-band MAE: 7.5131
- Kendall tau: 0.7556
- Pairwise agreement: 0.8778
- Mean student level variance: 0.125000
- Mean student rank variance: 0.111111

## Delta Vs Pre-Retune Round
- Exact-level hit delta: 0.0833
- Score-band MAE delta: 1.5819
- Kendall tau delta: -0.0444
- Pairwise agreement delta: -0.0222
- Level variance delta: 0.069445
- Rank variance delta: 0.027778

## Cohort Readout

### naep_1998_g12_persuasive_one_vote
- Exact-level hit: 0.9167
- Score-band MAE: 6.9083
- Kendall tau: 0.6667
- Pairwise agreement: 0.8333
- Mean student level variance: 0.375000
- Mean student rank variance: 0.333333
- Top unstable students:
  - s001: level_var 2.250000, rank_var 1.000000, score_var 229.219600, levels ['1', '4']
  - s006: level_var 0.000000, rank_var 0.250000, score_var 201.924100, levels ['1', '1']
  - s005: level_var 0.000000, rank_var 0.250000, score_var 74.132100, levels ['1', '1']

### naep_1998_g4_narrative_castle
- Exact-level hit: 0.6667
- Score-band MAE: 10.6450
- Kendall tau: 0.6000
- Pairwise agreement: 0.8000
- Mean student level variance: 0.000000
- Mean student rank variance: 0.000000
- Top unstable students:
  - s003: level_var 0.000000, rank_var 0.000000, score_var 18.792225, levels ['1', '1']
  - s005: level_var 0.000000, rank_var 0.000000, score_var 0.193600, levels ['1', '1']
  - s006: level_var 0.000000, rank_var 0.000000, score_var 0.013225, levels ['1', '1']

### naep_1998_g8_informative_tv_show
- Exact-level hit: 1.0000
- Score-band MAE: 4.9858
- Kendall tau: 1.0000
- Pairwise agreement: 1.0000
- Mean student level variance: 0.000000
- Mean student rank variance: 0.000000
- Top unstable students:
  - s006: level_var 0.000000, rank_var 0.000000, score_var 334.158400, levels ['1', '1']
  - s005: level_var 0.000000, rank_var 0.000000, score_var 108.472225, levels ['1', '1']
  - s001: level_var 0.000000, rank_var 0.000000, score_var 0.000000, levels ['4', '4']
