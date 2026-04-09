# GPT-5.4 Split Full Corpus Benchmark

- Generated: 2026-04-09T17:47:47.527741+00:00
- Candidate: `gpt54_split`
- Baseline: `gpt52_legacy`

## Post-Calibration Candidate Summary
- Exact-level hit rate: 0.7101
- Within-one-level hit rate: 0.9130
- Score-band MAE: 3.4284
- Mean rank displacement: 0.4638
- Kendall tau: 0.6889
- Pairwise order agreement: 0.8444
- Model usage ratio: 1.0000
- Cost (USD): 0.0815
- Latency (s): 118.5053

## Post-Calibration Candidate vs Baseline
- Exact-level hit delta: 0.0725
- Within-one-level hit delta: 0.0000
- Score-band MAE delta: 0.4614
- Mean rank displacement delta: 0.1449
- Kendall tau delta: -0.1275
- Pairwise order agreement delta: -0.0638
- Cost delta: -0.1710
- Latency delta: -66.9905

## Candidate Change vs Pre-Calibration Full Rerun
- Exact-level hit change: 0.0870
- Within-one-level hit change: 0.0290
- Score-band MAE change: -1.2749
- Mean rank displacement change: 0.0290
- Kendall tau change: -0.0425
- Pairwise order agreement change: -0.0213
- Model usage ratio change: 0.0048
- Cost change: -0.0006
- Latency change: -15.2017

## Remaining Lagging Datasets
- internet_samples: exact delta -0.5000, MAE delta +1.2175, pre-to-post candidate exact -0.2500, pre-to-post candidate MAE +0.3325
- thoughtful_assessment_grade9_10_argument: exact delta -0.2500, MAE delta +5.3750, pre-to-post candidate exact +0.0000, pre-to-post candidate MAE +0.7500
- thoughtful_assessment_grade11_12_speech: exact delta -0.2500, MAE delta +0.2500, pre-to-post candidate exact -0.5000, pre-to-post candidate MAE +0.2925
- naep_1998_g8_informative_tv_show: exact delta -0.1667, MAE delta +0.3733, pre-to-post candidate exact -0.3333, pre-to-post candidate MAE -2.9633
- naep_1998_g4_narrative_castle: exact delta +0.0000, MAE delta +4.0517, pre-to-post candidate exact +0.1667, pre-to-post candidate MAE +0.3167
- naep_1998_g12_persuasive_one_vote: exact delta +0.0000, MAE delta +1.8467, pre-to-post candidate exact +0.3333, pre-to-post candidate MAE -2.7317
- thoughtful_assessment_grade6_8_instructions_hydrochloric: exact delta +0.0000, MAE delta +0.5150, pre-to-post candidate exact +0.2500, pre-to-post candidate MAE -0.3275
