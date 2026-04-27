# Post-Source-Family Broad External-Corpus Validation

Date: 2026-04-27

Branch: `codex/external-corpus-post-source-family`

Merged source branch:

- PR: `#9` (`codex/source-family-ranking-challenge`)
- Merge commit: `d75649389b9b9409fdba29a1f1cf754817e58a55`

Fresh validation worktree:

- `/Users/bldt/Desktop/Essays-external-corpus-post-source-family`

## Purpose

Validate the source-family ranking hardening after merge, using a fresh
`origin/main` worktree and a release-comparable broad external-corpus packet.

The decision boundary for this run was:

- if broad accuracy and ordering deltas are neutral or positive, move to a
  controlled teacher pilot
- if the run exposes a concentrated regression cluster, refine that cluster
  before teacher pilot expansion

## Command

```bash
python3 scripts/benchmark_corpus.py --runs 3 \
  --candidate-routing config/llm_routing_benchmark.json \
  --candidate-label main \
  --baseline-label fallback \
  --output outputs/external_corpus_validation/external_corpus_20260427T_post_source_family_runs3
```

Artifact root:

- `outputs/external_corpus_validation/external_corpus_20260427T_post_source_family_runs3/`
- `outputs/external_corpus_validation/external_corpus_20260427T_post_source_family_runs3/benchmark_corpus_summary.json`
- `outputs/external_corpus_validation/external_corpus_20260427T_post_source_family_runs3/benchmark_corpus_summary.md`

## Aggregate Result

- Datasets: `32`
- Students: `133`
- Runs per dataset mode: `3`

| Metric | Candidate | Baseline | Delta |
| --- | ---: | ---: | ---: |
| Exact-level hit rate | 0.9248 | 0.9248 | 0.0000 |
| Within-one-level hit rate | 0.9774 | 0.9699 | +0.0075 |
| Score-band MAE | 0.9825 | 1.7288 | -0.7463 |
| Kendall tau | 0.9489 | 0.9228 | +0.0261 |
| Pairwise order agreement | 0.9744 | 0.9614 | +0.0130 |
| Mean rank displacement | 0.0752 | 0.1203 | -0.0451 |
| Max rank displacement | 0.1579 | 0.2632 | -0.1053 |
| Cost USD | 0.0781 | 0.0000 | +0.0781 |
| Latency seconds | 29.2798 | 24.1536 | +5.1262 |

Dataset movement:

- positive: `10`
- neutral: `19`
- negative: `3`

## Negative Clusters

| Dataset | Exact delta | Within-one delta | MAE delta | Kendall delta | Pairwise delta | Rank displacement delta | Interpretation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `internet_samples_eqao_orq` | -0.2500 | -0.2500 | +5.0050 | -0.6667 | -0.3333 | max +2.0000 / mean +1.0000 | True ordering and level regression |
| `thoughtful_assessment_grade6_8_instructions_hydrochloric` | -0.2500 | 0.0000 | +0.2075 | 0.0000 | 0.0000 | 0.0000 | Level projection regression only |
| `thoughtful_assessment_grade6_8_persuasive_letter` | -0.2500 | 0.0000 | +2.4425 | 0.0000 | 0.0000 | 0.0000 | Level projection regression only |

The regressions were deterministic across the three candidate runs: mean
student level, rank, and score variance were `0.0` in the reported summaries.

### EQAO ORQ

The EQAO packet is the release-blocking failure.

The main routed path ranked:

```text
s003, s002, s004, s001
```

Gold and fallback rank:

```text
s004, s003, s002, s001
```

The key row is `s004`, the Level 4 anchor. It carried
`source_scale_profile=eqao_anchor_4pt_gpt54mini` and `source_scale_rank=1`, but
the live routed `main` path did not apply the source-scale floor. It remained
at `59.98`, `adjusted_level=1`, and consensus rank `3`. The fallback path
applied `source_scale_floor:eqao_anchor_4pt_gpt54mini`, moved it to `80.0`,
`adjusted_level=4`, and consensus rank `1`.

That means the source-family hardening improved the broad aggregate, but the
live routed path still lets committee/pairwise evidence neutralize a supported
source-scale top anchor in this EQAO ORQ shape.

### Thoughtful Instructions

The instructions packet preserved the correct rank order:

```text
s001, s002, s003, s004
```

The regression was exact-level and score projection only. `s003` remained rank
`3`, but the candidate path scored it as Level 1 instead of the gold Level 2.
Within-one-level accuracy stayed neutral.

### Thoughtful Persuasive Letter

The persuasive-letter packet also preserved the correct rank order:

```text
s001, s002, s003, s004
```

The regression was exact-level and score projection only. `s002` carried
`source_scale_rank=2`, but the candidate path did not apply the source-scale
floor used by the fallback path, leaving it at Level 2 instead of the gold
Level 3. Within-one-level accuracy stayed neutral.

## Positive Transfer

The source-family work did transfer across several families:

- `thoughtful_assessment_grade11_12_speech` stayed neutral at exact `1.0`,
  Kendall `1.0`, pairwise `1.0`, MAE `0.0`
- `uk_sta_2018_ks2_writing_portfolios` improved exact by `+0.2500`, Kendall by
  `+0.3333`, pairwise by `+0.1667`, and MAE by `-2.5000`
- `naep_1998_g8_informative_tv_show` improved exact by `+0.1667`, Kendall by
  `+0.1333`, pairwise by `+0.0667`, and MAE by `-6.4850`
- `ontario_1999_grade2_narrative_my_adventure_example2` improved exact by
  `+0.2500`, Kendall by `+0.6667`, pairwise by `+0.3333`, and MAE by
  `-6.6150`

This supports the earlier conclusion that the hardening is product-general,
not merely sample-string overfitting. The remaining issue is narrower:
source-scale and boundary floor preservation under the live routed evidence
path.

## Hidden Failure Logs

The candidate `main` path emitted six `llm_failures.jsonl` lines total, limited
to two Ontario datasets with one line in each of three runs:

- `ontario_1999_grade6_summary_canadas_newest_territory_example1`
- `ontario_1999_grade5_report_person_i_admire_example2`

Those datasets were neutral in the corpus summary and are not the current
blocking regression cluster.

## Decision

Do not move to teacher pilot yet.

The broad aggregate is positive, but the packet is not clean enough for a
teacher pilot because `internet_samples_eqao_orq` is a deterministic rank and
level regression involving a supported source-scale top anchor.

## Next Slice

Implement a narrow source-scale floor preservation challenge against live
routed evidence:

1. Preserve supported source-scale top anchors when the source profile and
   ordinal rank are explicit, unless the routed evidence provides a documented,
   high-confidence contradiction.
2. Preserve the current speech and portfolio gains.
3. Fix the EQAO ORQ rank regression.
4. Fix or explicitly bound the level-only projection regressions in the
   Thoughtful instructions and persuasive-letter packets.
5. Rerun the focused negative cluster first, then rerun the broad corpus packet.

Teacher pilot should start only after that rerun is neutral or positive on
exact-level accuracy, score-band MAE, Kendall tau, and pairwise-order agreement
without a new concentrated regression cluster.
