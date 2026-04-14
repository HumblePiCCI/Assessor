# Family Stability Benchmark

- Generated: 2026-04-12T10:55:31.329452+00:00
- Datasets: 6
- Students: 27
- Runs per dataset mode: 3
- Candidate label: gpt54_split
- Baseline label: gpt52_legacy

## Overall Candidate Summary
- Exact-level hit rate: 0.8148
- Within-one-level hit rate: 0.8889
- Score-band MAE: 3.8853
- Kendall tau: 0.7119
- Pairwise agreement: 0.8560
- Mean student level variance: 0.164609
- Mean student rank variance: 0.082304
- Mean student score variance: 20.775268


## Candidate vs Baseline Delta
- Exact-level hit delta: 0.2099
- Within-one-level hit delta: -0.0864
- Score-band MAE delta: 0.2927
- Kendall tau delta: -0.2091
- Pairwise agreement delta: -0.1045
- Mean student level variance delta: 0.082304
- Mean student rank variance delta: 0.049383
- Mean student score variance delta: 17.416811

## Lagging Families

### thoughtful_learning_assessment_models | summary_report | same_prompt
- Datasets: thoughtful_assessment_grade6_8_summary_iron
- Students: 4
- Candidate exact-level hit: 0.8333
- Candidate score-band MAE: 1.4400
- Candidate Kendall tau: 0.8889
- Candidate pairwise agreement: 0.9444
- Candidate mean student rank variance: 0.111111
- Exact delta vs baseline: -0.1667
- MAE delta vs baseline: 1.4400
- Pairwise delta vs baseline: -0.0556
- Most unstable candidate students:
  - thoughtful_assessment_grade6_8_summary_iron / s003: level_var 0.888889, rank_var 0.222222, score_var 58.680556
  - thoughtful_assessment_grade6_8_summary_iron / s002: level_var 0.222222, rank_var 0.222222, score_var 0.235756
  - thoughtful_assessment_grade6_8_summary_iron / s001: level_var 0.000000, rank_var 0.000000, score_var 0.025689

### NAEP / NCES | argumentative | unknown
- Datasets: naep_1998_g12_persuasive_one_vote
- Students: 6
- Candidate exact-level hit: 0.9444
- Candidate score-band MAE: 4.4389
- Candidate Kendall tau: 0.8222
- Candidate pairwise agreement: 0.9111
- Candidate mean student rank variance: 0.074074
- Exact delta vs baseline: 0.2222
- MAE delta vs baseline: 1.2239
- Pairwise delta vs baseline: 0.0222
- Most unstable candidate students:
  - naep_1998_g12_persuasive_one_vote / s001: level_var 0.222222, rank_var 0.222222, score_var 5.826489
  - naep_1998_g12_persuasive_one_vote / s003: level_var 0.000000, rank_var 0.222222, score_var 0.000000
  - naep_1998_g12_persuasive_one_vote / s006: level_var 0.000000, rank_var 0.000000, score_var 158.377689

### NAEP / NCES | narrative | unknown
- Datasets: naep_1998_g4_narrative_castle
- Students: 6
- Candidate exact-level hit: 0.7222
- Candidate score-band MAE: 6.4383
- Candidate Kendall tau: 0.7333
- Candidate pairwise agreement: 0.8667
- Candidate mean student rank variance: 0.222222
- Exact delta vs baseline: 0.2222
- MAE delta vs baseline: 0.6972
- Pairwise delta vs baseline: -0.0667
- Most unstable candidate students:
  - naep_1998_g4_narrative_castle / s001: level_var 2.000000, rank_var 0.000000, score_var 129.819756
  - naep_1998_g4_narrative_castle / s003: level_var 0.888889, rank_var 0.000000, score_var 74.664200
  - naep_1998_g4_narrative_castle / s005: level_var 0.000000, rank_var 0.888889, score_var 11.588822

### Standards and Testing Agency / GOV.UK | portfolio | same grade band + same STA framework + same portfolio collection form
- Datasets: uk_sta_2018_ks1_writing_portfolios, uk_sta_2018_ks2_writing_portfolios
- Students: 7
- Candidate exact-level hit: 0.7143
- Candidate score-band MAE: 4.5090
- Candidate Kendall tau: 0.3333
- Candidate pairwise agreement: 0.6667
- Candidate mean student rank variance: 0.000000
- Exact delta vs baseline: 0.3333
- MAE delta vs baseline: -0.4514
- Pairwise delta vs baseline: -0.3333
- Most unstable candidate students:
  - uk_sta_2018_ks1_writing_portfolios / s001: level_var 0.000000, rank_var 0.000000, score_var 0.132067
  - uk_sta_2018_ks2_writing_portfolios / s001: level_var 0.000000, rank_var 0.000000, score_var 0.004356
  - uk_sta_2018_ks1_writing_portfolios / s002: level_var 0.000000, rank_var 0.000000, score_var 0.000000
