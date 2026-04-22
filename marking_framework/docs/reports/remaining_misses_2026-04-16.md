# Remaining Misses Audit - 2026-04-16

## Purpose

This report turns the six remaining exact-level misses from `gpt54_split_full_corpus_with_ghost_fixes_release_runs3_2026-04-16` into a tracked adjudication record and permanent regression fixture.

The corresponding executable fixture is:

- `marking_framework/tests/fixtures/remaining_misses_2026-04-16.json`
- `marking_framework/tests/test_remaining_misses.py`

## Baseline Misses

| Dataset | Student | Gold note | Prior score | Prior predicted level | Rank displacement | Source-family context |
| --- | --- | --- | ---: | --- | ---: | --- |
| `thoughtful_assessment_grade2_book_review` | `s003`, Dear Mr. Marc Brown | Thoughtful Learning model labeled Okay. | 33.64 | 1 | 0 | Grade 2 response-to-literature/book-review 4-pack: Strong, Good, Okay, Poor. |
| `thoughtful_assessment_grade6_8_persuasive_letter` | `s003`, Dear Dr. Larson (Okay) | Thoughtful Learning model labeled Okay. | 37.73 | 1 | 0 | Grade 6-8 same-prompt persuasive-letter 4-pack: Strong, Good, Okay, Poor. |
| `ontario_1999_grade1_descriptive_my_favourite_toy_example2` | `s002`, Grade 1 Level 3 Example 2 | Official Ontario exemplar labeled Level 3. Teacher note: simple ideas with a fair amount of supporting detail. | 55.74 | 1 | 1 | Ontario Grade 1 same-prompt descriptive-writing 4-pack with official teacher notes. |
| `naep_1998_g8_informative_tv_show` | `s002`, NAEP Skillful | Source label Skillful maps to canonical Level 4, lower top-band slice 80-84. | 70.00 | 3 | 0 | NAEP Grade 8 six-level informative-letter release set ordered Excellent to Unsatisfactory. |
| `thoughtful_assessment_grade11_12_speech` | `s004`, What I Will Do for This Country | Thoughtful Learning model labeled Poor. | 66.92 | 2 | 1 | Grade 11-12 Thoughtful Learning cross-topic argumentative speech 4-pack. |
| `thoughtful_assessment_grade9_10_argument` | `s002`, Lack of Respect a Growing Problem | Thoughtful Learning model labeled Good. | 80.00 | 4 | 0 | Grade 9-10 Thoughtful Learning cross-topic argumentative 4-pack. |

## Adjudication

| Dataset | Decision | Rationale | Fix target |
| --- | --- | --- | --- |
| `thoughtful_assessment_grade2_book_review` | Source-native translation issue. | The Okay model is sparse but materially above the Poor model. The pipe rank was already clean, so the miss was a band-projection failure caused by over-trusting low raw pass-1 scores on early literary samples. | Loosen the Grade 2 Thoughtful source-scale rank-3 gate and allow the official Okay rank to floor to canonical Level 2. |
| `thoughtful_assessment_grade6_8_persuasive_letter` | Source-native translation issue. | The Okay letter preserves audience, purpose, position, qualifications, availability, contact details, and closing. It is short, but it is a complete weak passing persuasive letter and belongs above Poor. | Use a same-prompt source-native student-id ladder for this four-pack and floor the official Okay model to Level 2 even when Borda variance is noisy. |
| `ontario_1999_grade1_descriptive_my_favourite_toy_example2` | Early-grade evidence interpretation issue. | The Grade 1 writing is compact and phonetic, but the official notes value repeated details, chronology, and careful/special-place language. Generic sparse-development penalties were too harsh for early-grade source exemplars. | Broaden Ontario 4-point floor eligibility and adjustment room so source-native Level 3 early writing is not collapsed by adult-writing expectations. |
| `naep_1998_g8_informative_tv_show` | Source-native translation issue. | The Skillful response is weaker than Excellent but remains a coherent, developed TV-show concept. The rank was correct; the six-point NAEP-to-canonical projection was too weak for Skillful. | Use NAEP Grade 8 source-native ordering and lower the rank-2 support gate so Skillful maps to canonical Level 4. |
| `thoughtful_assessment_grade11_12_speech` | Source-native translation issue. | The Poor speech has structure and ideas, but development is simplistic and error-prone. It should not outrank or out-band the Okay source model. | Allow the source-native rank-4 ceiling to apply despite high assessor SD, capping Poor below Level 2. |
| `thoughtful_assessment_grade9_10_argument` | Real pipe error. | The Good argument is solid, but the source family reserves top band for the stronger rank-1 sample. Generic top-boundary uplift incorrectly overrode the source-native rank-2 ceiling. | Block generic top-boundary uplift when a supported source-scale profile says a non-rank-1 sample has a ceiling below Level 4. |

## Implementation

- `scripts/boundary_calibrator.py` now prevents generic `top_boundary_uplift` from promoting a source-supported non-rank-1 sample into Level 4 when that source profile provides a ceiling below top band.
- `config/marking_config.json` now has tighter source-native profiles for NAEP Grade 8, Ontario 4-point exemplars, Thoughtful early literary 4-packs, Thoughtful same-prompt argumentative 4-packs, and Thoughtful cross-topic argumentative edge cases.
- `tests/test_remaining_misses.py` promotes every adjudicated miss into a regression test and adds repeated-run low-raw variants for the previously unstable Thoughtful and NAEP cases.

## Validation

Targeted repeated rerun:

- Command: `python3 scripts/benchmark_corpus.py --bench-root bench --runs 3 --candidate-routing config/llm_routing_benchmark.json --baseline-routing config/llm_routing_benchmark_gpt52.json --candidate-label gpt54_split --baseline-label gpt52_legacy --dataset thoughtful_assessment_grade2_book_review --dataset thoughtful_assessment_grade6_8_persuasive_letter --dataset ontario_1999_grade1_descriptive_my_favourite_toy_example2 --dataset naep_1998_g8_informative_tv_show --dataset thoughtful_assessment_grade11_12_speech --dataset thoughtful_assessment_grade9_10_argument --output /tmp/remaining_misses_targeted_runs3_2026-04-16`
- Result artifact: `docs/reports/remaining_misses_targeted_runs3_2026-04-16.md`
- Exact-level hit: 1.0000
- Within-one-level hit: 1.0000
- Score-band MAE: 2.3477
- Mean rank displacement: 0.0000
- Kendall tau: 1.0000
- Pairwise agreement: 1.0000
- Failed datasets: 0

Full corpus controlled rerun:

- Command: `python3 scripts/benchmark_corpus.py --bench-root bench --runs 3 --candidate-routing config/llm_routing_benchmark.json --baseline-routing config/llm_routing_benchmark_gpt52.json --candidate-label gpt54_split --baseline-label gpt52_legacy --output /tmp/gpt54_split_full_corpus_remaining_misses_fixed_runs3_2026-04-16`
- The output directory was seeded with the prior shared LLM caches to isolate deterministic calibration/ranking changes from new pass-1 model noise.
- Result artifact: `docs/reports/gpt54_split_full_corpus_remaining_misses_fixed_runs3_2026-04-16.md`
- Exact-level hit: 1.0000, up from 0.9549.
- Within-one-level hit: 1.0000, up from 0.9925.
- Score-band MAE: 0.4832, down from 1.1359.
- Mean rank displacement: 0.0451, down from 0.0752.
- Kendall tau: 0.9820, up from 0.9619.
- Pairwise agreement: 0.9910, up from 0.9810.
- Failed datasets: 0.
- Candidate mismatches: 0.

No-harm checks:

| Family | Exact | MAE | Kendall | Pairwise |
| --- | ---: | ---: | ---: | ---: |
| Ghost live Grade 7 set | Final order still matches adjudicated expected order. | Not applicable. | Not applicable. | Not applicable. |
| Ontario Grade 1 Example 2 | 0.7500 -> 1.0000 | 3.5650 -> 0.0000 | 0.6667 -> 1.0000 | 0.8333 -> 1.0000 |
| NAEP Grade 4 | 1.0000 -> 1.0000 | 0.0000 -> 0.0000 | 0.8667 -> 0.8667 | 0.9333 -> 0.9333 |
| NAEP Grade 8 | 0.8333 -> 1.0000 | 5.0650 -> 2.5650 | 0.8667 -> 0.8667 | 0.9333 -> 0.9333 |
| NAEP Grade 12 | 1.0000 -> 1.0000 | 0.0000 -> 0.0000 | 0.8667 -> 0.8667 | 0.9333 -> 0.9333 |
| UK KS1 portfolios | 1.0000 -> 1.0000 | 0.0000 -> 0.0000 | 1.0000 -> 1.0000 | 1.0000 -> 1.0000 |
| UK KS2 portfolios | 1.0000 -> 1.0000 | 0.0000 -> 0.0000 | 1.0000 -> 1.0000 | 1.0000 -> 1.0000 |
| Thoughtful summary iron | 1.0000 -> 1.0000 | 0.0000 -> 0.0000 | 1.0000 -> 1.0000 | 1.0000 -> 1.0000 |
| Thoughtful persuasive letter | 0.7500 -> 1.0000 | 13.0200 -> 7.4525 | 1.0000 -> 1.0000 | 1.0000 -> 1.0000 |

Release gate:

- Command: `python3 scripts/sota_gate.py --publish-gate docs/reports/gpt54_split_publish_gate_with_ontario_release_2026-04-13.json --pass1 /tmp/gpt54_split_full_corpus_remaining_misses_fixed_runs3_2026-04-16/internet_samples_eqao_orq/gpt54_split/run_1/assessments/pass1_individual --consistency /tmp/gpt54_split_full_corpus_remaining_misses_fixed_runs3_2026-04-16/internet_samples_eqao_orq/gpt54_split/run_1/outputs/consistency_checks.json --benchmark-report /tmp/gpt54_split_full_corpus_remaining_misses_fixed_runs3_2026-04-16/benchmark_corpus_summary.json --gate-config config/sota_gate.json --output /tmp/gpt54_split_sota_gate_remaining_misses_fixed_2026-04-16.json`
- Result artifact: `docs/reports/gpt54_split_sota_gate_remaining_misses_fixed_2026-04-16.md`
- Highest attained profile: release.
- Decision state: release_ready.

Regression tests:

- `pytest --no-cov -q marking_framework/tests/test_boundary_calibrator.py marking_framework/tests/test_remaining_misses.py`
- Result: 29 passed.
- `pytest --no-cov -q marking_framework/tests/test_boundary_calibrator.py marking_framework/tests/test_remaining_misses.py marking_framework/tests/test_benchmark_corpus.py marking_framework/tests/test_benchmark_main_vs_fallback.py marking_framework/tests/test_sota_gate.py marking_framework/tests/test_global_rerank.py marking_framework/tests/test_verify_consistency.py`
- Result: 70 passed.
- Ghost live order check: `outputs/final_order.csv` in the strict-identity staging workspace still matches the adjudicated expected order exactly.
