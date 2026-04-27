# Source-Scale Floor Preservation Report

Date: 2026-04-27

Branch: `codex/source-scale-floor-preservation`

Base: fresh worktree from current `origin/main`
(`d75649389b9b9409fdba29a1f1cf754817e58a55`)

## Why This Slice Exists

After the source-family ranking branch merged, the remaining broad-corpus
uncertainty was not structural. The live rerun exposed a narrow calibration
cluster where routed evidence could still compress source-authored scale
positions even when the source rank was the strongest available evidence.

The failed cluster was:

- `internet_samples_eqao_orq`
- `thoughtful_assessment_grade6_8_instructions_hydrochloric`
- `thoughtful_assessment_grade6_8_persuasive_letter`

This was a general calibration problem, not a Ghost-only special case. The
resolver needed a bounded way to preserve source-scale floors for supported
profiles without letting source metadata overrule stronger live evidence in
unsupported contexts.

## Implementation

`scripts/boundary_calibrator.py` now separates ordinary source-scale support
from floor-preservation support.

The source profile can opt into rank-specific floor preservation with:

- `preserve_floor_by_rank`
- `preserve_floor_min_current_score_by_rank`
- `preserve_floor_min_base_score_by_rank`
- `preserve_floor_min_borda_percent_by_rank`
- `preserve_floor_max_rank_sd`
- `preserve_floor_max_rubric_sd_points`

When the normal source-support contract fails but the bounded preservation
contract passes, floors can still apply and the calibration reason records
`source_scale_floor_preserved`. Ceilings and anchor movements still require the
ordinary source-support path.

`config/marking_config.json` now opts in only the affected source-family
profiles:

- `eqao_anchor_4pt_gpt54mini`
- `thoughtful_persuasive_letter_same_prompt_grade6_8_gpt54mini`
- `thoughtful_informational_same_prompt_grade6_8_gpt54mini`

The informational profile also recognizes the `instructions` form so the
hydrochloric-acid instruction set routes through the intended same-prompt
calibration contract.

## Regression Coverage

Targeted tests were added in `tests/test_boundary_calibrator.py` for:

- EQAO top-source-rank floor preservation under routed rank spread
- persuasive-letter rank-two floor preservation under Borda compression
- instructions matching into the thoughtful informational floor profile

Two path-sensitive tests now resolve `config/marking_config.json` from the
package root so they behave the same from the repository root and the
`marking_framework/` package directory.

## Focused Live Validation

Final focused packet:

`outputs/source_scale_floor_preservation/source_scale_floor_20260427T_negative_cluster_runs3_final/`

Command shape:

```bash
python3 scripts/benchmark_corpus.py \
  --runs 3 \
  --candidate-routing config/llm_routing_benchmark.json \
  --candidate-label main \
  --baseline-label fallback \
  --dataset internet_samples_eqao_orq \
  --dataset thoughtful_assessment_grade6_8_instructions_hydrochloric \
  --dataset thoughtful_assessment_grade6_8_persuasive_letter \
  --output outputs/source_scale_floor_preservation/source_scale_floor_20260427T_negative_cluster_runs3_final
```

Result:

- datasets: `3`
- students: `12`
- exact-level hit delta: `0.0000`
- within-one-level hit delta: `0.0000`
- score-band MAE delta: `0.0000`
- mean rank displacement delta: `0.0000`
- Kendall tau delta: `0.0000`
- pairwise order agreement delta: `0.0000`
- no hidden `llm_failures.jsonl` files in the focused final packet

## Broad Live Validation

Final broad packet:

`outputs/source_scale_floor_preservation/source_scale_floor_20260427T_broad_runs3_final/`

Result:

- datasets: `32`
- students: `133`
- runs per dataset mode: `3`
- candidate exact-level hit rate: `0.9549`
- candidate within-one-level hit rate: `1.0000`
- candidate score-band MAE: `0.6216`
- candidate mean rank displacement: `0.0301`
- candidate Kendall tau: `0.9789`
- candidate pairwise order agreement: `0.9895`

Candidate versus fallback deltas:

- exact-level hit rate: `+0.0602`
- within-one-level hit rate: `+0.0226`
- score-band MAE: `-1.4389`
- mean rank displacement: `-0.0752`
- Kendall tau: `+0.0501`
- pairwise order agreement: `+0.0251`

Dataset classification:

- positive: `9`
- neutral: `23`
- negative: `0`

The three original negative-cluster datasets are all neutral after this slice:

- `internet_samples_eqao_orq`
- `thoughtful_assessment_grade6_8_instructions_hydrochloric`
- `thoughtful_assessment_grade6_8_persuasive_letter`

Broad-run failure logs are limited to retryable assessor evidence-validation
failures and one timeout in otherwise neutral or positive datasets. They did
not create a surviving quality-regression cluster.

## Local Verification

Commands run:

- `git diff --check`
- `python3 -m pytest -q --no-cov marking_framework/tests/test_boundary_calibrator.py marking_framework/tests/test_aggregate_assessments.py marking_framework/tests/test_rubric_criteria.py marking_framework/tests/test_assessor_context.py marking_framework/tests/test_run_llm_assessors_helpers.py`
- `python3 -m pytest -q --no-cov`
- `python3 -m pytest -q` from `marking_framework/`
- `python3 -m pytest --cov=scripts --cov=server --cov-branch --cov-report=term-missing --no-cov-on-fail` from `marking_framework/`

Results:

- root fast suite: `814 passed`
- package-local suite: passed
- explicit coverage report: `814 passed`, total coverage `82%`
- coverage run warnings: existing sqlite `ResourceWarning` messages from
  queue/replay tests; no test failures

## Conclusion

This slice preserves valid source-authored scale positions without widening the
source-family hardening into benchmark-specific rewrites. The broad corpus is
now positive overall and has no negative dataset cluster.

After this branch merges, the next right product step is a controlled teacher
pilot following `docs/TEACHER_PILOT_RUNBOOK.md`. Production launch remains a
separate operational gate requiring real identity wiring, launch-validator
proof, and rollback rehearsal against the deployment environment.
