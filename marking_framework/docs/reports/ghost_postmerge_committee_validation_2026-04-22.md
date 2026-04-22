# Ghost Post-Merge Committee Validation

Date: 2026-04-22

Branch: `codex/ghost-postmerge-validation`

Base commit under test: `f192377` (`origin/main`)

Validation status: **partial / not merge-to-default sufficient**

## Purpose

This run validates the merged Ghost literary-analysis committee-edge path after:

- PR #3: proof-quality claim-refutation guard
- PR #2: docs alignment audit

The goal was to confirm whether the current `gpt-5.4-mini` committee route can
produce a defensible Ghost final order end to end, not just pass a single-packet
guard test.

## Runtime Setup

Model route was not overridden. The live path used:

```json
{
  "task": "literary_committee",
  "model": "gpt-5.4-mini",
  "reasoning": "high",
  "max_output_tokens": 2000
}
```

Live/generated artifacts were written under `outputs/` and copied to
`outputs/live_validation/ghost_postmerge_*`. These artifacts are intentionally
not committed.

## Commands

Preflight candidate selection:

```bash
python3 scripts/committee_edge_resolver.py \
  --candidates-output outputs/live_validation/ghost_postmerge_candidates.preflight.json \
  --decisions-output outputs/live_validation/ghost_postmerge_decisions.preflight.json \
  --report-output outputs/live_validation/ghost_postmerge_report.preflight.json \
  --merged-output outputs/live_validation/ghost_postmerge_consistency_checks.preflight.json \
  --evidence-neighborhood-output outputs/live_validation/ghost_postmerge_evidence_neighborhood.preflight.json \
  --evidence-group-packets-output outputs/live_validation/ghost_postmerge_evidence_group_packets.preflight.json \
  --live-trace-output outputs/live_validation/ghost_postmerge_live_trace.preflight.json
```

Live committee-edge run:

```bash
python3 scripts/committee_edge_resolver.py --live --max-reads 12
```

The first live run hit transport failures:

- `s009::s015` Read A: `[Errno 54] Connection reset by peer`
- `s004::s023` Read B: `Remote end closed connection without response`
- group calibration: `[Errno 54] Connection reset by peer`

To avoid re-spending completed reads, completed A/B/C reads were extracted from
the partial trace into local fixtures and the missing pieces were retried:

```bash
python3 scripts/committee_edge_resolver.py \
  --live \
  --max-reads 12 \
  --blind-read-fixture outputs/live_validation/ghost_postmerge_read_a_fixture_from_partial.json \
  --read-b-fixture outputs/live_validation/ghost_postmerge_read_b_fixture_from_partial.json \
  --read-c-fixture outputs/live_validation/ghost_postmerge_read_c_fixture_from_partial.json
```

Rerank and hard-pair eval:

```bash
python3 scripts/global_rerank.py --judgments outputs/consistency_checks.committee_edge.json
python3 scripts/evaluate_pairwise_adjudicator.py \
  --judgments outputs/consistency_checks.committee_edge.json \
  --output outputs/pairwise_adjudicator_eval.json
```

## Candidate Coverage

Preflight selected all five known Ghost residuals in the `caution_ignored`
bucket:

| Pair | Expected human winner | Selection status | Committee score | Trigger summary |
|---|---|---:|---:|---|
| `s003::s009` | `s009` Jack | selected | 125 | rougher/content caution + top-10/boundary |
| `s003::s013` | `s013` Kyle | selected | 180 | polished/shallow + never-escalated + top-10/boundary |
| `s004::s008` | `s008` Hudson L | selected | 180 | rougher/content + never-escalated + top-10/boundary |
| `s009::s015` | `s009` Jack | selected | 185 | formulaic/thin + low/medium high-leverage + top-10/boundary |
| `s019::s022` | `s022` Sienna | selected | 240 | rougher/content + low/medium high-leverage + never-escalated + top-10/boundary |

## Live Committee Summary

Recovery run summary:

- Read A attempts: 12
- Read A completed: 11
- Read A transport errors: 1 (`s009::s015`)
- Read B completed from fixture: 2
- Read C completed from fixture: 2
- Group calibrations completed: 1
- Committee decisions emitted: 7
- Cycle resolution: `cycles_detected = 0`, `suppressed_count = 0`

The group calibration returned `medium` confidence. It emitted no group
overrides. It evaluated two explicit ledgers:

| Pair | Group winner | Prior winner | Ledger result | Notes |
|---|---|---|---|---|
| `s009::s015` | `s015` | `s015` | accepted as `prior_preservation_ledger_accepted` | The new claim-refutation fields were present and substantive enough for the validator. |
| `s009::s022` | `s009` | `s022` | accepted as `edge_ledger_override_allowed` | No override emitted because broader group confidence was only medium and this was not a high-confidence group edge override. |

Important: the new proof-quality guard did not fail mechanically. It forced
mini to provide `loser_interpretive_claim`, `winner_counterclaim`,
`loser_claim_refutation`, and `claim_refutation_text_moments`. The validation
problem is now judgment quality and downstream placement, not missing ledger
structure.

## Residual Outcomes

| Pair | Expected | Merged direct winner | Direct source | Final-order winner | Result |
|---|---|---|---|---|---|
| `s003::s009` | `s009` Jack | `s009` | `committee_edge` | `s009` | fixed |
| `s003::s013` | `s013` Kyle | `s003` | `cheap_pairwise` | `s003` | still wrong; A/B/C preserved prior |
| `s004::s008` | `s008` Hudson L | `s008` | `committee_edge` | `s004` | direct edge fixed, rerank violated placement |
| `s009::s015` | `s009` Jack | `s015` | `escalated_adjudication` | `s009` | direct edge still wrong due transport + accepted prior-preserving group ledger; final order corrected by other support |
| `s019::s022` | `s022` Sienna | `s022` | `committee_edge` | `s019` | direct edge fixed, rerank violated placement |

This split is important: the committee seam corrected or routed several hard
edges, but the deterministic final order can still violate direct committee
edges when broader support and movement constraints dominate.

## Final Order Snapshot

Top 12 after rerank:

| Final rank | Student | Seed rank | Level | Rerank note |
|---:|---|---:|---|---|
| 1 | Alyssa (`s002`) | 11 | 2+ | moved up 10 |
| 2 | Jacob (`s010`) | 2 | 3+ | held |
| 3 | Jack (`s009`) | 9 | 2 | moved up 6 |
| 4 | Jasmine (`s011`) | 3 | 3+ | moved down 1 |
| 5 | Easton (`s003`) | 4 | 3 | moved down 1 |
| 6 | Naomi (`s019`) | 12 | 2+ | moved up 6 |
| 7 | Graydon (`s006`) | 15 | 2 | moved up 8 |
| 8 | Alannah (`s001`) | 21 | 2+ | moved up 13 |
| 9 | Johanna (`s012`) | 5 | 2+ | moved down 4 |
| 10 | Georgia (`s005`) | 22 | 1+ | moved up 12 |
| 11 | Logan (`s015`) | 1 | 3+ | moved down 10 |
| 12 | Sienna (`s022`) | 7 | 2+ | moved down 5 |

This order is not defensible as a teacher-facing final order. It over-promotes
several high-support movers, places Alyssa above Jasmine, leaves Easton above
Kyle, places Naomi above Sienna despite a corrected direct committee edge, and
places Farris above Hudson L despite a corrected direct committee edge.

## Hard-Pair Eval

`outputs/pairwise_adjudicator_eval.json` summary:

```json
{
  "pair_count": 18,
  "evaluated_count": 18,
  "correct_count": 15,
  "missing_count": 0,
  "accuracy": 0.833333,
  "coverage": 1.0,
  "critical_pair_count": 7,
  "critical_correct_count": 5,
  "critical_accuracy": 0.714286,
  "failures": [
    "accuracy_below_threshold",
    "critical_accuracy_below_threshold",
    "possible_polish_bias_misses"
  ]
}
```

Failures:

- `ghost_top_001`: expected Jasmine (`s011`) over Alyssa (`s002`), predicted Alyssa.
- `ghost_top_003`: expected Jack (`s009`) over Logan (`s015`), predicted Logan on the direct edge.
- `ghost_top_008`: expected Kyle (`s013`) over Easton (`s003`), predicted Easton.

## Interpretation

The merged claim-refutation guard succeeded at the schema/validator level, but
the post-merge product path is not yet SOTA-safe for Ghost.

What improved:

- all five residuals route into committee candidates
- the live seam can emit committee overrides
- cycle suppression stayed clean
- proof-quality prior preservation now requires explicit claim-refutation fields
- three of five residuals have either direct-edge or final-order improvement

What still fails:

- `s009::s015` Read A repeatedly failed due transport, and group calibration
  preserved Logan with a proof-quality claim-refutation rationale
- `s003::s013` still preserves Easton through A/B/C despite the polished/shallow
  routing signal
- corrected direct committee edges are not hard enough for rerank; `s004::s008`
  and `s019::s022` are corrected in the merged judgment file but inverted in
  final order
- high-support movement can produce a distorted top pack: Alyssa, Jacob, Jack,
  Jasmine, Easton is not the independently adjudicated order

## Next Slice Recommendation

The next implementation slice should be **source-aware rerank protection for
committee-edge direct winners**, not another prompt clause.

Goal: when `adjudication_source=committee_edge` supplies a direct edge, rerank
must not invert it unless a stronger same-pair source or an explicit cycle
resolution suppresses that edge.

Suggested scope:

1. Extend `global_rerank.py` constraint building so committee-edge direct edges
   get a source-aware hard/near-hard precedence class.
2. Add diagnostics when final order violates a committee-edge direct winner.
3. Add fixture tests for `s004::s008` and `s019::s022` showing corrected direct
   committee edges survive rerank.
4. Keep cycle resolution as the escape hatch; do not let a single committee edge
   create impossible ordering.

After that, rerun this Ghost validation. If direct committee edges hold but
`s009::s015` and `s003::s013` remain wrong, the next seam is judgment quality
for those two interpretation/content decisions.
