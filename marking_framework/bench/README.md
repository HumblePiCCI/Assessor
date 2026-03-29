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
