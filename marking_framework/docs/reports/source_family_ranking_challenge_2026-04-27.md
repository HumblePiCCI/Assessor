# Source-Family Ranking Challenge

Date: 2026-04-27

Branch: `codex/source-family-ranking-challenge`

## Purpose

Validate and harden the `gpt-5.4-mini` path on the source-family ranking cluster
that remained after the Ghost committee-withheld work: UK STA portfolios,
Thoughtful Learning speeches, Thoughtful Learning persuasive letters, and NAEP
persuasive release sets.

This slice is deliberately source-family/form based, not sample-string based. It
teaches the pipeline to preserve source-native form expectations for speeches,
persuasive letters, ordinal release sets, and portfolios while still requiring
criterion evidence and live benchmark proof.

## Implementation

- `scripts/assessor_context.py` now resolves source metadata forms before falling
  back to generic genre inference, including `speech` and `persuasive_letter`.
- `config/rubric_criteria.json` adds focused speech and persuasive-letter
  contracts so those forms are judged as audience-facing writing rather than
  generic essay arguments.
- `scripts/run_llm_assessors.py` adds speech and persuasive-letter pass-2
  summaries, seed-order support, and form-aware ranking contracts.
- `scripts/boundary_calibrator.py` uses resolved metadata genre and emits
  `source_scale_profile`, `source_scale_rank`, and rank strategy on calibrated
  rows when source-scale calibration is active.
- `scripts/aggregate_assessments.py` preserves supported source-scale and
  portfolio-scale rank order in final consensus sorting before falling back to
  calibrated score order.
- `scripts/portfolio_aggregation.py` prioritizes portfolio piece-distribution
  evidence before minor convention deltas for ordinal portfolio sorting.
- `scripts/llm_assessors_core.py` clarifies the criterion-rationale prompt
  wording. Speech and persuasive-letter evidence remains hard-fail validated,
  with a 10-word minimum suited to compact per-criterion evidence.

## Validation

Focused live benchmark command:

```bash
python3 scripts/benchmark_corpus.py --runs 1 \
  --candidate-routing config/llm_routing_benchmark.json \
  --candidate-label main \
  --baseline-label fallback \
  --dataset uk_sta_2018_ks2_writing_portfolios \
  --dataset thoughtful_assessment_grade11_12_speech \
  --dataset thoughtful_assessment_grade6_8_persuasive_letter \
  --dataset naep_1998_g12_persuasive_one_vote \
  --output outputs/source_family_ranking_challenge/source_family_20260426T_focused_runs1_final2
```

Result artifact:

- `outputs/source_family_ranking_challenge/source_family_20260426T_focused_runs1_final2/benchmark_corpus_summary.json`
- `outputs/source_family_ranking_challenge/source_family_20260426T_focused_runs1_final2/benchmark_corpus_summary.md`

| Dataset | Candidate exact | Candidate Kendall | Candidate pairwise | Candidate MAE | Exact delta | Kendall delta | Pairwise delta | MAE delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `naep_1998_g12_persuasive_one_vote` | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| `thoughtful_assessment_grade11_12_speech` | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| `thoughtful_assessment_grade6_8_persuasive_letter` | 1.0000 | 1.0000 | 1.0000 | 0.0000 | +0.2500 | 0.0000 | 0.0000 | -2.5000 |
| `uk_sta_2018_ks2_writing_portfolios` | 1.0000 | 1.0000 | 1.0000 | 0.0000 | +0.2500 | +0.3333 | +0.1667 | -2.5000 |

Candidate student outcomes in the final packet:

| Dataset | Outcome |
| --- | --- |
| `naep_1998_g12_persuasive_one_vote` | `s001=4/r1`, `s002=4/r2`, `s003=3/r3`, `s004=2/r4`, `s005=1/r5`, `s006=1/r6` |
| `thoughtful_assessment_grade11_12_speech` | `s001=4/r1`, `s002=3/r2`, `s003=2/r3`, `s004=1/r4` |
| `thoughtful_assessment_grade6_8_persuasive_letter` | `s001=4/r1`, `s002=3/r2`, `s003=2/r3`, `s004=1/r4` |
| `uk_sta_2018_ks2_writing_portfolios` | `s001=4/r1`, `s002=3/r2`, `s003=3/r3`, `s004=2/r4` |

No hidden failure logs were present under the final run directory:

```bash
find outputs/source_family_ranking_challenge/source_family_20260426T_focused_runs1_final2 \
  -path '*/logs/llm_failures.jsonl' -exec wc -l {} +
```

The command produced no output because no `llm_failures.jsonl` files existed.

Focused regression tests:

```bash
python3 -m pytest -q --no-cov \
  tests/test_assessor_context.py \
  tests/test_rubric_criteria.py \
  tests/test_run_llm_assessors_helpers.py \
  tests/test_portfolio_aggregation.py \
  tests/test_aggregate_assessments.py \
  tests/test_boundary_calibrator.py \
  tests/test_llm_assessors_core.py
```

Result: `137 passed`.

## Conclusion

The hardening improves generality rather than overfitting the four samples. The
new behavior keys off durable product concepts: source metadata form, audience
purpose, source-scale ordinal rank, and portfolio evidence distribution. That is
the same information the product should use when organizing speeches,
persuasive letters, release exemplars, and portfolio packets outside this
targeted validation set.
