# External Benchmark Corpus Summary (2026-04-02 v2)

- Source summary: `/tmp/external_corpus_2026-04-02_v2/benchmark_corpus_summary.json`
- Compared to: `/Users/bldt/Desktop/Essays/marking_framework/docs/reports/external_benchmark_corpus_2026-04-02.json`
- Datasets: 16
- Students: 69

## Net Delta Vs 2026-04-02

- Candidate Exact-level hit rate: 0.5652 -> 0.6087 (+0.0435)
- Candidate Within-one-level hit rate: 0.9565 -> 0.8551 (-0.1014)
- Candidate Score-band MAE: 3.2912 -> 1.8504 (-1.4407)
- Candidate Mean rank displacement: 0.1739 -> 0.1739 (+0.0000)
- Candidate Kendall tau: 0.8995 -> 0.7739 (-0.1256)
- Candidate Pairwise order agreement: 0.9498 -> 0.8290 (-0.1208)
- Candidate Cost (USD): 0.3122 -> 0.3005 (-0.0117)
- Candidate Latency (s): 245.9912 -> 212.9783 (-33.0128)

- Candidate vs baseline exact-level gap: -0.0435 -> -0.1014 (-0.0580)
- Candidate vs baseline score-band MAE gap: 0.7130 -> 0.1210 (-0.5920)
- Candidate vs baseline Kendall gap: 0.0464 -> -0.1449 (-0.1913)

## Key Family Changes

- internet_samples_eqao_orq: exact 0.5000 -> 1.0000, MAE 4.7525 -> 0.0000, Kendall 0.6667 -> 1.0000
- naep_1998_g12_persuasive_one_vote: exact 0.5000 -> 1.0000, MAE 3.5917 -> 0.0000, Kendall 1.0000 -> 0.8667
- naep_1998_g8_informative_tv_show: exact 0.5000 -> 0.8333, MAE 3.7033 -> 1.6667, Kendall 1.0000 -> 1.0000
- naep_1998_g4_narrative_castle: exact 0.3333 -> 0.6667, MAE 8.0000 -> 4.5400, Kendall 0.7333 -> 0.8667
- thoughtful_assessment_grade3_personal_narrative: exact 0.7500 -> 0.5000, MAE 2.5000 -> 5.8325, Kendall 1.0000 -> 0.6667
- uk_sta_2018_ks1_writing_portfolios: exact 1.0000 -> 0.6667, MAE 0.0000 -> 0.8333, Kendall 1.0000 -> 0.3333
- uk_sta_2018_ks2_writing_portfolios: exact 1.0000 -> 1.0000, MAE 0.0000 -> 0.0000, Kendall 1.0000 -> 1.0000
- thoughtful_assessment_grade6_8_instructions_hydrochloric: exact 0.5000 -> 0.5000, MAE 5.6875 -> 5.4925, Kendall 0.3333 -> 0.3333

## Caveats

- thoughtful_assessment_grade6_8_persuasive_letter (main) failed the benchmark run: cmd=python3 scripts/run_llm_assessors.py --texts processing/normalized_text --rubric inputs/rubric.md --outline inputs/assignment_outline.md --routing routing_main.json --grade-profiles config/grade_level_profiles.json --class-metadata inputs/class_metadata.json --exemplars inputs/exemplars --rubric-criteria config/rubric_criteria.json --fallback deterministic --ignore-cost-limits --require-model-usage
- thoughtful_assessment_grade6_8_summary_iron (main) failed the benchmark run: cmd=python3 scripts/run_llm_assessors.py --texts processing/normalized_text --rubric inputs/rubric.md --outline inputs/assignment_outline.md --routing routing_main.json --grade-profiles config/grade_level_profiles.json --class-metadata inputs/class_metadata.json --exemplars inputs/exemplars --rubric-criteria config/rubric_criteria.json --fallback deterministic --ignore-cost-limits --require-model-usage
- The raw corpus summary treats failed candidate dataset runs as zero-valued summaries, so the weighted candidate metrics in this v2 report are punitive and not directly comparable to a clean all-success run.
- UK KS1 portfolio and Grade 3 narrative regressed sharply in the full-corpus orchestration even though earlier focused validation looked stronger; that instability is now a top debugging target.

## Raw Summary

- Generated: 2026-04-03T01:19:19.427324+00:00
- Datasets: 16
- Students: 69
- Runs per dataset mode: 1

## Candidate Summary
- Exact-level hit rate: 0.6087
- Within-one-level hit rate: 0.8551
- Score-band MAE: 1.8504
- Mean rank displacement: 0.1739
- Kendall tau: 0.7739
- Pairwise order agreement: 0.8290
- Cost (USD): 0.3005
- Latency (s): 212.9783

## Candidate vs Baseline Delta
- Exact-level hit delta: -0.1014
- Within-one-level hit delta: -0.1304
- Score-band MAE delta: 0.1210
- Mean rank displacement delta: 0.0290
- Kendall tau delta: -0.1449
- Pairwise order agreement delta: -0.1304

## Dataset Summaries

## Failures
- thoughtful_assessment_grade6_8_persuasive_letter (main): cmd=python3 scripts/run_llm_assessors.py --texts processing/normalized_text --rubric inputs/rubric.md --outline inputs/assignment_outline.md --routing routing_main.json --grade-profiles config/grade_level_profiles.json --class-metadata inputs/class_metadata.json --exemplars inputs/exemplars --rubric-criteria config/rubric_criteria.json --fallback deterministic --ignore-cost-limits --require-model-usage
stdout:
Model coverage: 7/15 successful structured outputs.
Model coverage 46.67% below gate 80.00%. Failing run.

stderr:
- thoughtful_assessment_grade6_8_summary_iron (main): cmd=python3 scripts/run_llm_assessors.py --texts processing/normalized_text --rubric inputs/rubric.md --outline inputs/assignment_outline.md --routing routing_main.json --grade-profiles config/grade_level_profiles.json --class-metadata inputs/class_metadata.json --exemplars inputs/exemplars --rubric-criteria config/rubric_criteria.json --fallback deterministic --ignore-cost-limits --require-model-usage
stdout:
Model coverage: 8/15 successful structured outputs.
Model coverage 53.33% below gate 80.00%. Failing run.

stderr:

### internet_samples
- Students: 4
- Candidate exact-level hit rate: 0.2500
- Candidate within-one-level hit rate: 1.0000
- Candidate score-band MAE: 3.1825
- Candidate Kendall tau: 1.0000
- Candidate pairwise agreement: 1.0000
- Candidate cost (USD): 0.1489
- Candidate latency (s): 102.3476

### internet_samples_eqao_orq
- Students: 4
- Candidate exact-level hit rate: 1.0000
- Candidate within-one-level hit rate: 1.0000
- Candidate score-band MAE: 0.0000
- Candidate Kendall tau: 1.0000
- Candidate pairwise agreement: 1.0000
- Candidate cost (USD): 0.1403
- Candidate latency (s): 89.4605

### internet_samples_thoughtful
- Students: 4
- Candidate exact-level hit rate: 0.7500
- Candidate within-one-level hit rate: 1.0000
- Candidate score-band MAE: 0.3500
- Candidate Kendall tau: 1.0000
- Candidate pairwise agreement: 1.0000
- Candidate cost (USD): 0.1532
- Candidate latency (s): 115.6165

### naep_1998_g12_persuasive_one_vote
- Students: 6
- Candidate exact-level hit rate: 1.0000
- Candidate within-one-level hit rate: 1.0000
- Candidate score-band MAE: 0.0000
- Candidate Kendall tau: 0.8667
- Candidate pairwise agreement: 0.9333
- Candidate cost (USD): 0.3434
- Candidate latency (s): 231.2479

### naep_1998_g4_narrative_castle
- Students: 6
- Candidate exact-level hit rate: 0.6667
- Candidate within-one-level hit rate: 0.8333
- Candidate score-band MAE: 4.5400
- Candidate Kendall tau: 0.8667
- Candidate pairwise agreement: 0.9333
- Candidate cost (USD): 0.2397
- Candidate latency (s): 156.4691

### naep_1998_g8_informative_tv_show
- Students: 6
- Candidate exact-level hit rate: 0.8333
- Candidate within-one-level hit rate: 1.0000
- Candidate score-band MAE: 1.6667
- Candidate Kendall tau: 1.0000
- Candidate pairwise agreement: 1.0000
- Candidate cost (USD): 0.2729
- Candidate latency (s): 206.0951

### thoughtful_assessment_grade11_12_speech
- Students: 4
- Candidate exact-level hit rate: 0.5000
- Candidate within-one-level hit rate: 1.0000
- Candidate score-band MAE: 0.6675
- Candidate Kendall tau: 1.0000
- Candidate pairwise agreement: 1.0000
- Candidate cost (USD): 0.2406
- Candidate latency (s): 156.1233

### thoughtful_assessment_grade2_book_review
- Students: 4
- Candidate exact-level hit rate: 0.5000
- Candidate within-one-level hit rate: 1.0000
- Candidate score-band MAE: 3.1650
- Candidate Kendall tau: 1.0000
- Candidate pairwise agreement: 1.0000
- Candidate cost (USD): 0.2310
- Candidate latency (s): 168.3677

### thoughtful_assessment_grade3_personal_narrative
- Students: 4
- Candidate exact-level hit rate: 0.5000
- Candidate within-one-level hit rate: 1.0000
- Candidate score-band MAE: 5.8325
- Candidate Kendall tau: 0.6667
- Candidate pairwise agreement: 0.8333
- Candidate cost (USD): 0.1878
- Candidate latency (s): 139.7547

### thoughtful_assessment_grade4_5_research
- Students: 4
- Candidate exact-level hit rate: 1.0000
- Candidate within-one-level hit rate: 1.0000
- Candidate score-band MAE: 0.0000
- Candidate Kendall tau: 1.0000
- Candidate pairwise agreement: 1.0000
- Candidate cost (USD): 0.2296
- Candidate latency (s): 167.7470

### thoughtful_assessment_grade6_8_instructions_hydrochloric
- Students: 4
- Candidate exact-level hit rate: 0.5000
- Candidate within-one-level hit rate: 0.7500
- Candidate score-band MAE: 5.4925
- Candidate Kendall tau: 0.3333
- Candidate pairwise agreement: 0.6667
- Candidate cost (USD): 0.2371
- Candidate latency (s): 176.3843

### thoughtful_assessment_grade6_8_persuasive_letter
- Students: 4
- Candidate exact-level hit rate: 0.0000
- Candidate within-one-level hit rate: 0.0000
- Candidate score-band MAE: 0.0000
- Candidate Kendall tau: 0.0000
- Candidate pairwise agreement: 0.0000
- Candidate cost (USD): 0.0000
- Candidate latency (s): 0.0000

### thoughtful_assessment_grade6_8_summary_iron
- Students: 4
- Candidate exact-level hit rate: 0.0000
- Candidate within-one-level hit rate: 0.0000
- Candidate score-band MAE: 0.0000
- Candidate Kendall tau: 0.0000
- Candidate pairwise agreement: 0.0000
- Candidate cost (USD): 0.0000
- Candidate latency (s): 0.0000

### thoughtful_assessment_grade9_10_argument
- Students: 4
- Candidate exact-level hit rate: 0.2500
- Candidate within-one-level hit rate: 1.0000
- Candidate score-band MAE: 3.2950
- Candidate Kendall tau: 1.0000
- Candidate pairwise agreement: 1.0000
- Candidate cost (USD): 0.2306
- Candidate latency (s): 153.5518

### uk_sta_2018_ks1_writing_portfolios
- Students: 3
- Candidate exact-level hit rate: 0.6667
- Candidate within-one-level hit rate: 1.0000
- Candidate score-band MAE: 0.8333
- Candidate Kendall tau: 0.3333
- Candidate pairwise agreement: 0.6667
- Candidate cost (USD): 0.9371
- Candidate latency (s): 684.7143

### uk_sta_2018_ks2_writing_portfolios
- Students: 4
- Candidate exact-level hit rate: 1.0000
- Candidate within-one-level hit rate: 1.0000
- Candidate score-band MAE: 0.0000
- Candidate Kendall tau: 1.0000
- Candidate pairwise agreement: 1.0000
- Candidate cost (USD): 1.3979
- Candidate latency (s): 1000.2690

## Largest Candidate Misses
- thoughtful_assessment_grade6_8_instructions_hydrochloric / Using Hydrochloric Acid (Strong) (s001): gold 4, predicted 1, score-band error 20.97, rank displacement 2
- thoughtful_assessment_grade3_personal_narrative / Texas (s003): gold 2, predicted 1, score-band error 13.33, rank displacement 1
- naep_1998_g4_narrative_castle / NAEP Sufficient (s003): gold Sufficient (canon 3), predicted 1, score-band error 12.24, rank displacement 1
- naep_1998_g4_narrative_castle / NAEP Skillful (s002): gold Skillful (canon 4), predicted 3, score-band error 10.00, rank displacement 0
- naep_1998_g8_informative_tv_show / NAEP Skillful (s002): gold Skillful (canon 4), predicted 3, score-band error 10.00, rank displacement 0
- thoughtful_assessment_grade2_book_review / Julius the Baby of the World (s001): gold 4, predicted 3, score-band error 10.00, rank displacement 0
- thoughtful_assessment_grade3_personal_narrative / The Sled Run (s001): gold 4, predicted 3, score-band error 10.00, rank displacement 0
- thoughtful_assessment_grade9_10_argument / The Right to Dress (s003): gold 2, predicted 3, score-band error 9.10, rank displacement 0
- internet_samples / sample_level2_internet (s002): gold 2, predicted 3, score-band error 6.25, rank displacement 0
- internet_samples / sample_level4_internet (s004): gold 4, predicted 3, score-band error 4.75, rank displacement 0
- thoughtful_assessment_grade9_10_argument / Grading Students on Effort (s004): gold 1, predicted 2, score-band error 3.08, rank displacement 0
- thoughtful_assessment_grade2_book_review / Dear Mr. Marc Brown (s003): gold 2, predicted 1, score-band error 2.66, rank displacement 0
- uk_sta_2018_ks1_writing_portfolios / Jamie (s003): gold Working towards the expected standard (canon 2), predicted 3, score-band error 2.50, rank displacement 1
- internet_samples / sample_level1_internet (s001): gold 1, predicted 2, score-band error 1.73, rank displacement 0
- thoughtful_assessment_grade11_12_speech / What I Will Do for This Country (s004): gold 1, predicted 2, score-band error 1.67, rank displacement 0
- internet_samples_thoughtful / sample_level2_internet_thoughtful (s002): gold 2, predicted 3, score-band error 1.40, rank displacement 0
- thoughtful_assessment_grade6_8_instructions_hydrochloric / Using Hydrochloric Acid (Okay) (s003): gold 2, predicted 3, score-band error 1.00, rank displacement 1
- thoughtful_assessment_grade11_12_speech / Inauguration Speech of the 49th U.S. President (s002): gold 3, predicted 4, score-band error 1.00, rank displacement 0
- thoughtful_assessment_grade9_10_argument / Lack of Respect a Growing Problem (s002): gold 3, predicted 4, score-band error 1.00, rank displacement 0
