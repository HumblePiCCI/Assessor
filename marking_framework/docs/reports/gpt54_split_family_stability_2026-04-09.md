# GPT-5.4 Split Family Stability

- Generated: 2026-04-09T22:10:02.945658+00:00
- Datasets: 3
- Students: 12
- Runs per dataset: 2

## Final Candidate Summary
- Exact-level hit rate: 0.9167
- Within-one-level hit rate: 0.9167
- Score-band MAE: 1.9417
- Kendall tau: 0.7778
- Pairwise agreement: 0.8889
- Mean student level variance: 0.000000
- Mean student rank variance: 0.000000

## Delta Vs Pre-Calibrated Round
- Exact-level hit delta: 0.3333
- Within-one-level hit delta: 0.0417
- Score-band MAE delta: -2.8575
- Kendall tau delta: 0.1667
- Pairwise agreement delta: 0.0833
- Level variance delta: -0.187500
- Rank variance delta: -0.041667

## Family Readout

### thoughtful_learning_assessment_models | informational_report | same_prompt
- Datasets: thoughtful_assessment_grade6_8_instructions_hydrochloric
- Exact-level hit: 0.7500
- Score-band MAE: 5.8037
- Kendall tau: 0.3333
- Pairwise agreement: 0.6667
- Mean student level variance: 0.000000
- Mean student rank variance: 0.000000
- Top unstable students:
  - thoughtful_assessment_grade6_8_instructions_hydrochloric / s002: level_var 0.000000, rank_var 0.000000, score_var 2.044900
  - thoughtful_assessment_grade6_8_instructions_hydrochloric / s003: level_var 0.000000, rank_var 0.000000, score_var 1.322500
  - thoughtful_assessment_grade6_8_instructions_hydrochloric / s001: level_var 0.000000, rank_var 0.000000, score_var 0.024025

### thoughtful_learning_assessment_models | argumentative | same_rubric_family_cross_topic
- Datasets: thoughtful_assessment_grade11_12_speech, thoughtful_assessment_grade9_10_argument
- Exact-level hit: 1.0000
- Score-band MAE: 0.0106
- Kendall tau: 1.0000
- Pairwise agreement: 1.0000
- Mean student level variance: 0.000000
- Mean student rank variance: 0.000000
- Top unstable students:
  - thoughtful_assessment_grade9_10_argument / s003: level_var 0.000000, rank_var 0.000000, score_var 16.687225
  - thoughtful_assessment_grade11_12_speech / s003: level_var 0.000000, rank_var 0.000000, score_var 7.209225
  - thoughtful_assessment_grade11_12_speech / s002: level_var 0.000000, rank_var 0.000000, score_var 4.862025
