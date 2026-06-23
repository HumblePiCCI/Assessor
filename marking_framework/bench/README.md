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

- `gold_canonical_level`
- `gold_neighbors`
- `boundary_flag`
- `adjudication_notes`
- `source_file`
- `display_name`

Notes:

- `student_id` must match the deterministic IDs produced by `scripts/extract_text.py`. For a dataset with lexicographically sorted submissions, that means `s001`, `s002`, and so on in sorted filename order.
- `gold_rank` is `1` for the strongest submission in the cohort.
- `gold_level` should preserve the source-native label when the external benchmark uses a different scale. In those cases, set `gold_canonical_level` to the app's canonical comparison level (`1`, `2`, `3`, `4`, or `4+`) so the harness can score the dataset without discarding the original source label.
- `gold_neighbors` should be a JSON array in `gold.jsonl`, or a JSON array string in `gold.csv`.
- Datasets without explicit gold are not valid release benchmarks and should not be used for gating.
- For reproducible internet-corpus sweeps, use `scripts/benchmark_corpus.py`.
- The benchmark-specific routing profile is `config/llm_routing_benchmark.json`; it disables calibration freshness enforcement so isolated benchmark workspaces can score without inheriting a stale repo-level calibration gate.
- Governed review-learning promotions stage benchmark assets under `bench/promoted/benchmark_gold/<proposal_id>/gold.jsonl`.
- Governed review-learning promotions stage boundary challenge assets under `bench/promoted/boundary_challenges/<proposal_id>/boundary_challenges.jsonl`.
- Promoted assets require a proposal manifest plus human adjudication metadata before they should be treated as official candidate data.
- Do not commit raw owner/classroom/student run directories under `bench/runs/`. That path is ignored for local experiments and smoke evidence. Any cohort promoted into the repo must have a license/privacy review, a source manifest, and redacted teacher-adjudication metadata.
- Benchmark packs should deliberately cover rough-but-strong, polished-but-thin, ELL/accommodation, off-task, incomplete, prompt-injection, and formulaic submissions so release gates measure the cases that routinely fool rank-only graders.

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
- `naep_1998_g4_narrative_castle`
- `naep_1998_g8_informative_tv_show`
- `naep_1998_g12_persuasive_one_vote`
- `uk_sta_2018_ks1_writing_portfolios`
- `uk_sta_2018_ks2_writing_portfolios`

Holdout families (release validation only — never use for prompt, calibration, or engine tuning):

- `holdout_asap2_g6_cowboy_waves` (ASAP 2.0, grade 6, source-based argumentative, CC BY 4.0)
- `holdout_asap2_g8_face_on_mars` (ASAP 2.0, grade 8)
- `holdout_asap2_g9_electoral_college` (ASAP 2.0, grade 9)
- `holdout_asap2_g10_driverless_cars` (ASAP 2.0, grade 10)

Holdout policy: these cohorts were sampled deterministically from the ASAP 2.0 train split
(`scripts/import_asap2_cohorts.py`; blind-scored 1-6 by trained state-assessment raters,
github.com/scrosseye/ASAP_2.0, CC BY 4.0). They exist to provide virgin territory for release
validation. Tuning iterations should exclude them (use `--dataset` filters); release gates should
include them. Candidate NC-licensed corpora (PERSUADE 2.0, ELLIPSE — CC BY-NC-SA) were deliberately
NOT committed; if licensing is cleared, fetch them at eval time instead of committing.
