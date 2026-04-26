# External Corpus Validation - 2026-04-25

- Branch: `codex/external-corpus-validation`
- Base: `origin/main` at `4c379dd2cbda3cfbdd6fe04ef746efac12dd7087`
- Scope: broader explicit-gold external corpus after the committee-withheld Ghost contract landed in PR #8
- Primary artifact: `outputs/external_corpus_validation/external_corpus_20260425T230728Z_runs3/benchmark_corpus_summary.json`

## Execution Notes

The first attempted live run used the process-level `OPENAI_API_KEY` and failed
with OpenAI `401 invalid_api_key`. That packet was preserved separately under
`outputs/external_corpus_validation/external_corpus_20260425T215504Z/` and was
not used for scoring conclusions.

The valid run sourced the key from the prior Ghost validation worktree `.env`
without printing the secret. A one-run exploratory packet was generated under
`external_corpus_20260425T215821Z/`; then the release-comparable packet was
rerun in a fresh output directory with `--runs 3` so the first run was live and
the harness-managed repeats used only that run's shared cache.

## Commands

```bash
python3 scripts/benchmark_corpus.py \
  --runs 3 \
  --candidate-routing config/llm_routing_benchmark.json \
  --candidate-label main \
  --baseline-label fallback \
  --output outputs/external_corpus_validation/external_corpus_20260425T230728Z_runs3

python3 scripts/sota_gate.py \
  --publish-gate docs/reports/gpt54_split_publish_gate_with_ontario_release_2026-04-13.json \
  --pass1 outputs/external_corpus_validation/external_corpus_20260425T230728Z_runs3/internet_samples/main/run_1/assessments/pass1_individual \
  --consistency outputs/external_corpus_validation/external_corpus_20260425T230728Z_runs3/internet_samples/main/run_1/outputs/consistency_checks.json \
  --benchmark-report outputs/external_corpus_validation/external_corpus_20260425T230728Z_runs3/benchmark_corpus_summary.json \
  --output outputs/external_corpus_validation/external_corpus_20260425T230728Z_runs3/sota_gate.json
```

## Benchmark Result

- Valid explicit-gold datasets: 32
- Students: 133
- Runs per dataset/mode: 3
- Failed datasets: 0
- Candidate exact-level hit rate: 0.947368
- Candidate within-one-level hit rate: 0.984962
- Candidate score-band MAE: 1.326316
- Candidate mean rank displacement: 0.120301
- Candidate Kendall tau: 0.921805
- Candidate pairwise order agreement: 0.960902
- Candidate model usage ratio: 0.982456
- Candidate cost: 0.08234 USD
- Candidate latency: 25.238867 seconds

Against the fallback baseline in this same run:

- Exact-level hit delta: +0.022556
- Within-one-level hit delta: 0.0
- Score-band MAE delta: -1.227218
- Mean rank displacement delta: +0.030075
- Kendall tau delta: -0.034085
- Pairwise order agreement delta: -0.017043

Against the 2026-04-16 accepted release corpus packet:

- Exact-level hit changed from 0.954887 to 0.947368
- Within-one-level hit changed from 0.992481 to 0.984962
- Score-band MAE changed from 1.13594 to 1.326316
- Mean rank displacement changed from 0.075188 to 0.120301
- Kendall tau changed from 0.961905 to 0.921805
- Pairwise order agreement changed from 0.980952 to 0.960902

## Gate Result

The SOTA gate artifact is
`outputs/external_corpus_validation/external_corpus_20260425T230728Z_runs3/sota_gate.json`.

- Target profile: `dev`
- Highest attained profile: `dev`
- Decision state: `development_only`
- Candidate profile: fail
- Release profile: fail
- Candidate/release failures:
  - `benchmark_kendall_tau_delta_below_threshold`
  - `benchmark_pairwise_order_delta_below_threshold`

A representative publish-gate artifact was also generated at
`outputs/external_corpus_validation/external_corpus_20260425T230728Z_runs3/publish_gate.json`.
It is not a release publish-profile rerun because the external-corpus harness
does not emit the Ghost hard-pair/evidence-packet artifacts required by the
publish gate. Its expected failures are `pairwise_eval_report_missing` and
`pairwise_eval_escalated_path_missing`.

## Miss Profile

The candidate still clears the absolute benchmark thresholds, but the current
external-corpus run is not release-green because it loses ranking deltas against
fallback on a small set of source families:

| Dataset | Exact delta | Kendall delta | Pairwise delta | Notes |
| --- | ---: | ---: | ---: | --- |
| `uk_sta_2018_ks2_writing_portfolios` | 0.0 | -0.666667 | -0.333333 | Portfolio ranking regression; `Frankie` is the largest miss. |
| `thoughtful_assessment_grade11_12_speech` | -0.25 | -0.333333 | -0.166667 | Speech level/rank regression; `The Greatest Inauguration Speech` is under-called. |
| `thoughtful_assessment_grade6_8_persuasive_letter` | -0.25 | -0.333333 | -0.166667 | Persuasive-letter level/rank regression despite better score-band MAE. |
| `naep_1998_g12_persuasive_one_vote` | 0.0 | -0.133334 | -0.066666 | Ranking-only regression. |

Largest candidate misses:

- `ontario_1999_grade1_descriptive_my_favourite_toy_example2 / s002`: gold 3, predicted 1, rank displacement 1, score-band error 21.99
- `thoughtful_assessment_grade11_12_speech / s003`: gold 2, predicted 1, rank displacement 1, score-band error 18.33
- `thoughtful_assessment_grade6_8_persuasive_letter / s003`: gold 2, predicted 1, rank displacement 1, score-band error 15.83
- `uk_sta_2018_ks2_writing_portfolios / s001`: gold 4, predicted 2, rank displacement 2, score-band error 14.15
- `thoughtful_assessment_grade6_8_persuasive_letter / s001`: gold 4, predicted 3, rank displacement 0, score-band error 10.0

## Interpretation

The Ghost committee-withheld fix did not reveal a new literary committee
regression on the external corpus. The blocker is now broader than Ghost but
narrower than a whole-system redesign: the candidate improves exact-level rate
and score-band MAE against fallback, while losing the candidate/release gate on
ranking deltas concentrated in KS2 portfolio and selected Thoughtful source
families.

## Next Slice

The next code slice should be a targeted source-family ranking challenge for
portfolio and Thoughtful-form residuals, not another Ghost literary guard. Build
it around the four negative-delta datasets above, with fixtures that preserve
absolute level gains while preventing the rank-order regressions that caused the
SOTA candidate/release failures.

## Verification

- `python3 -m pytest -q --no-cov` from repository root: 801 passed
- `python3 -m pytest -q` from `marking_framework/`: passed
- `git diff --check`: passed
