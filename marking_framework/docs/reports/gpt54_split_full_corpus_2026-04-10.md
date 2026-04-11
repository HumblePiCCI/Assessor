# GPT-5.4 Split Full Corpus Report

- Generated: 2026-04-11T00:30:47.420788+00:00
- Branch: codex/stable-bell-curve
- Candidate: gpt54_split
- Baseline: gpt52_legacy
- Datasets: 16
- Students: 69

## Current Split vs Baseline
- Candidate exact-level hit: 0.6377 vs baseline 0.6667
- Candidate within-one hit: 0.9710 vs baseline 0.9855
- Candidate score-band MAE: 4.0823 vs baseline 2.5326
- Candidate Kendall tau: 0.7894 vs baseline 0.9034
- Candidate pairwise agreement: 0.8947 vs baseline 0.9517
- Candidate cost: 0.0820 vs baseline 0.2457
- Candidate latency: 75.9929s vs baseline 161.2235s

## Change Vs 2026-04-09 Split Corpus
- Exact-level hit: 0.7101 -> 0.6377
- Within-one hit: 0.9130 -> 0.9710
- Score-band MAE: 3.4284 -> 4.0823
- Kendall tau: 0.6889 -> 0.7894
- Pairwise agreement: 0.8444 -> 0.8947

## Biggest Current Dataset Gaps Vs Baseline
- internet_samples: exact delta -0.7500, MAE delta +2.2125, candidate exact 0.0000, candidate MAE 4.8225
- thoughtful_assessment_grade6_8_instructions_hydrochloric: exact delta -0.7500, MAE delta +0.7500, candidate exact 0.2500, candidate MAE 0.7500
- internet_samples_eqao_orq: exact delta -0.5000, MAE delta +2.7500, candidate exact 0.5000, candidate MAE 2.7500
- thoughtful_assessment_grade6_8_summary_iron: exact delta -0.5000, MAE delta +2.7500, candidate exact 0.5000, candidate MAE 2.7500
- thoughtful_assessment_grade11_12_speech: exact delta -0.2500, MAE delta +3.6450, candidate exact 0.5000, candidate MAE 4.1025
- naep_1998_g12_persuasive_one_vote: exact delta -0.1667, MAE delta +2.7317, candidate exact 0.3333, candidate MAE 5.8017
- naep_1998_g8_informative_tv_show: exact delta +0.0000, MAE delta +6.8050, candidate exact 0.8333, candidate MAE 8.4717
- thoughtful_assessment_grade3_personal_narrative: exact delta +0.0000, MAE delta +4.7275, candidate exact 0.7500, candidate MAE 4.9775

## Largest Candidate Misses
- uk_sta_2018_ks1_writing_portfolios / Ali: gold Working at greater depth within the expected standard (canon 4), predicted 2, score-band error 18.32, rank displacement 1
- uk_sta_2018_ks2_writing_portfolios / Frankie: gold Working at greater depth within the expected standard (canon 4), predicted 2, score-band error 16.69, rank displacement 2
- naep_1998_g12_persuasive_one_vote / NAEP Excellent: gold Excellent (canon 4), predicted 3, score-band error 15.00, rank displacement 2
- naep_1998_g4_narrative_castle / NAEP Uneven: gold Uneven (canon 2), predicted 1, score-band error 14.00, rank displacement 0
- naep_1998_g12_persuasive_one_vote / NAEP Uneven: gold Uneven (canon 2), predicted 1, score-band error 11.67, rank displacement 0
- internet_samples_eqao_orq / sample_level3_eqao_orq: gold 3 (canon 3), predicted 2, score-band error 10.00, rank displacement 1
- thoughtful_assessment_grade6_8_summary_iron / Iron Summary (Okay): gold 2 (canon 2), predicted 3, score-band error 10.00, rank displacement 1
- naep_1998_g8_informative_tv_show / NAEP Skillful: gold Skillful (canon 4), predicted 3, score-band error 10.00, rank displacement 0
- thoughtful_assessment_grade11_12_speech / The Greatest Inauguration Speech: gold 2 (canon 2), predicted 1, score-band error 9.58, rank displacement 1
- internet_samples / sample_level4_internet: gold 4 (canon 4), predicted 3, score-band error 9.12, rank displacement 1
- thoughtful_assessment_grade3_personal_narrative / The Sled Run: gold 4 (canon 4), predicted 3, score-band error 9.08, rank displacement 0
- thoughtful_assessment_grade11_12_speech / What I Will Do for This Country: gold 1 (canon 1), predicted 2, score-band error 6.83, rank displacement 1
