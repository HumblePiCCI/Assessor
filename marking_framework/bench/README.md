# Benchmark Datasets

Benchmark-ready datasets live under `bench/<dataset>/` and use this schema:

- `inputs/`
- `submissions/`
- `gold.jsonl` or `gold.csv`

Required gold fields:

- `student_id`
- `gold_level`
- `gold_band_min`
- `gold_band_max`
- `gold_rank`

Optional gold fields:

- `gold_neighbors`
- `boundary_flag`
- `adjudication_notes`
- `source_file`
- `display_name`

Notes:

- `student_id` must match the deterministic IDs produced by `scripts/extract_text.py`. For a dataset with lexicographically sorted submissions, that means `s001`, `s002`, and so on in sorted filename order.
- `gold_rank` is `1` for the strongest submission in the cohort.
- `gold_neighbors` should be a JSON array in `gold.jsonl`, or a JSON array string in `gold.csv`.
- Datasets without explicit gold are not valid release benchmarks and should not be used for gating.
- For reproducible internet-corpus sweeps, use `scripts/benchmark_corpus.py`.
- The benchmark-specific routing profile is `config/llm_routing_benchmark.json`; it disables calibration freshness enforcement so isolated benchmark workspaces can score without inheriting a stale repo-level calibration gate.
- Governed review-learning promotions stage benchmark assets under `bench/promoted/benchmark_gold/<proposal_id>/gold.jsonl`.
- Governed review-learning promotions stage boundary challenge assets under `bench/promoted/boundary_challenges/<proposal_id>/boundary_challenges.jsonl`.
- Promoted assets require a proposal manifest plus human adjudication metadata before they should be treated as official candidate data.

Current public benchmark families in this repo include:

- `internet_samples`
- `internet_samples_eqao_orq`
- `internet_samples_thoughtful`
- `thoughtful_assessment_grade2_book_review`
- `thoughtful_assessment_grade3_personal_narrative`
- `thoughtful_assessment_grade4_5_research`
- `thoughtful_assessment_grade6_8_summary_iron`
- `thoughtful_assessment_grade6_8_instructions_hydrochloric`
- `thoughtful_assessment_grade6_8_persuasive_letter`
- `thoughtful_assessment_grade9_10_argument`
- `thoughtful_assessment_grade11_12_speech`
