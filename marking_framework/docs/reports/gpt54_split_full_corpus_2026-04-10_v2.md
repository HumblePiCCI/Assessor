# GPT-5.4 Split Full Corpus Report

- Generated: 2026-04-11T03:17:21.797271+00:00
- Branch: codex/stable-bell-curve
- Candidate: gpt54_split
- Baseline: gpt52_legacy
- Datasets: 16
- Students: 69

## Current Split vs Baseline
- Candidate exact-level hit: 0.8406 vs baseline 0.6522
- Candidate within-one hit: 0.9275 vs baseline 0.9565
- Candidate score-band MAE: 3.4819 vs baseline 2.8919
- Candidate Kendall tau: 0.8242 vs baseline 0.8725
- Candidate pairwise agreement: 0.9121 vs baseline 0.9362
- Candidate cost: 0.0811 vs baseline 0.2493
- Candidate latency: 110.3621s vs baseline 165.2732s

## Change Vs Prior 2026-04-10 Split Corpus
- Exact-level hit: 0.6377 -> 0.8406
- Within-one hit: 0.9710 -> 0.9275
- Score-band MAE: 4.0823 -> 3.4819
- Kendall tau: 0.7894 -> 0.8242
- Pairwise agreement: 0.8947 -> 0.9121
- Cost: 0.0820 -> 0.0811
- Latency: 75.9929s -> 110.3621s

## Biggest Current Dataset Gaps Vs Baseline
- thoughtful_assessment_grade4_5_research: exact delta -0.2500, MAE delta +0.2500, candidate exact 0.7500, candidate MAE 0.2500
- thoughtful_assessment_grade6_8_persuasive_letter: exact delta +0.0000, MAE delta +4.7600, candidate exact 0.5000, candidate MAE 7.9775
- thoughtful_assessment_grade6_8_summary_iron: exact delta +0.0000, MAE delta +3.8050, candidate exact 0.7500, candidate MAE 4.0625
- naep_1998_g12_persuasive_one_vote: exact delta +0.0000, MAE delta +3.6233, candidate exact 0.8333, candidate MAE 6.3583
- naep_1998_g4_narrative_castle: exact delta +0.1667, MAE delta +4.4200, candidate exact 0.6667, candidate MAE 10.5317
- thoughtful_assessment_grade2_book_review: exact delta +0.2500, MAE delta +4.6950, candidate exact 0.7500, candidate MAE 8.8625
- thoughtful_assessment_grade3_personal_narrative: exact delta +0.2500, MAE delta +1.2075, candidate exact 1.0000, candidate MAE 1.4575
- uk_sta_2018_ks2_writing_portfolios: exact delta +0.2500, MAE delta +1.1075, candidate exact 0.7500, candidate MAE 4.1850

## Largest Candidate Misses
- thoughtful_assessment_grade6_8_persuasive_letter / Dear Dr. Larson (Okay): gold 2 (canon 2), predicted 1, score-band error 30.91, rank displacement 1
- naep_1998_g4_narrative_castle / NAEP Sufficient: gold Sufficient (canon 3), predicted 1, score-band error 26.11, rank displacement 1
- naep_1998_g12_persuasive_one_vote / NAEP Excellent: gold Excellent (canon 4), predicted 2, score-band error 21.18, rank displacement 2
- naep_1998_g4_narrative_castle / NAEP Uneven: gold Uneven (canon 2), predicted 1, score-band error 18.64, rank displacement 1
- uk_sta_2018_ks1_writing_portfolios / Ali: gold Working at greater depth within the expected standard (canon 4), predicted 2, score-band error 17.19, rank displacement 1
- uk_sta_2018_ks2_writing_portfolios / Frankie: gold Working at greater depth within the expected standard (canon 4), predicted 2, score-band error 16.74, rank displacement 2
- thoughtful_assessment_grade6_8_summary_iron / Iron Summary (Okay): gold 2 (canon 2), predicted 4, score-band error 16.25, rank displacement 1
- thoughtful_assessment_grade2_book_review / Julius the Baby of the World: gold 4 (canon 4), predicted 3, score-band error 10.00, rank displacement 0
- thoughtful_assessment_grade9_10_argument / The Right to Dress: gold 2 (canon 2), predicted 1, score-band error 2.72, rank displacement 0
- thoughtful_assessment_grade6_8_persuasive_letter / Dear Dr. Larson (Poor): gold 1 (canon 1), predicted 2, score-band error 1.00, rank displacement 1
- thoughtful_assessment_grade4_5_research / The Great Pyramid of Giza: gold 3 (canon 3), predicted 4, score-band error 1.00, rank displacement 0
