# Docs Alignment Audit

Date: 2026-04-23

Branch audited: `main` at `15d321c`

Audit branch: `codex/docs-alignment-current`

## Source Of Truth Checked

- `scripts/committee_edge_resolver.py`
- `scripts/global_rerank.py`
- `scripts/hero_path.py`
- `server/step_runner.py`
- `config/llm_routing.json`
- `config/marking_config.json`
- `scripts/publish_gate.py`
- `scripts/sota_gate.py`
- `tests/test_committee_edge_resolver.py`
- `tests/test_global_rerank.py`
- prior Ghost validation report in PR #4

## Findings

### 1. Rerank Protection Is Now Runtime Truth

PR #5 merged source-aware rerank protection for direct committee-edge winners.
`scripts/global_rerank.py` now preserves committee trace/confidence fields,
extracts surviving direct `adjudication_source="committee_edge"` judgments, and
adds them as `committee_direct_edge` graph constraints before generic pairwise,
level-lock, and displacement-cap constraints.

Docs that mentioned committee-edge decisions only as "preferred" pairwise input
were updated to say they are protected graph constraints unless cycle-suppressed
or superseded.

Updated:

- `README.md`
- `docs/LIVE_COHORT_RUNTIME.md`
- `docs/DATA_FORMATS.md`
- `docs/QUALITY_GATES.md`

### 2. Proof-Quality Claim-Refutation Is No Longer Future Work

`scripts/committee_edge_resolver.py` already includes group-edge ledger fields
for:

- `loser_interpretive_claim`
- `winner_counterclaim`
- `loser_claim_refutation`
- `claim_refutation_text_moments`

The resolver prompt and validator require these fields for proof-quality
prior-preservation on interpretation/content caution edges, and
`tests/test_committee_edge_resolver.py` has regression coverage for missing or
generic refutation.

`docs/ROADMAP.md` and `docs/SOTA_BUILD_PLAN.md` still described this as the next
implementation slice. Those sections were updated.

### 3. The Next Slice Has Shifted Upstream

Because PR #5 makes valid committee-edge winners harder for rerank to invert,
the next product risk is not "rerank ignores committee evidence." The next risk
is "an unsafe committee decision becomes protected evidence."

The current next slice is now:

**Protected Committee Edge Audit And Suppression**

Expected behavior:

- classify emitted committee decisions as `protect`, `suppress_ambiguous`,
  `needs_retry`, or `needs_group_read`
- keep valid fixes protected
- suppress or retry decisions with unresolved transport failures, unresolved
  A/B/C disagreement, source/evidence contradiction, or weak prior-preservation
  support
- keep suppressed decisions visible in trace/report artifacts without emitting
  them as canonical protected `committee_edge` judgments

Updated:

- `docs/ROADMAP.md`
- `docs/SOTA_BUILD_PLAN.md`

### 4. PR #4 Is Historical, Not Current Operating Truth

PR #4 documents the Ghost post-merge validation before PR #5 landed. It remains
useful as dated evidence, but its main next-slice recommendation
(`source-aware rerank protection for committee-edge direct winners`) is now
complete in `main`.

The current operating docs now supersede that recommendation. PR #4 should be
closed or replaced by a refreshed validation report after the protected-edge
audit slice.

## Historical Reports Intentionally Left Unchanged

Older files under `docs/reports/` were not rewritten. They describe dated
validation runs and may contain older artifact names, failure counts, or branch
names. The active docs and this audit report carry the current operating truth.

## Verification

```bash
python3 -m pytest -q --no-cov tests/test_global_rerank.py tests/test_committee_edge_resolver.py tests/test_step_runner.py tests/test_hero_path.py tests/test_publish_gate.py tests/test_sota_gate.py
# 194 passed

python3 -m pytest -q --no-cov
# 784 passed

git diff --check
# passed
```

Active-doc stale-reference sweep:

```bash
rg -n "source-aware rerank protection|rerank protection|proof-quality preservation guard lands|next validator slice|committee-edge direct winners|rerank violated|direct edge fixed" marking_framework/docs marking_framework/README.md
```

Remaining active-doc hits after this audit are either current runtime
descriptions, current next-slice language, or dated historical reports.

## Next Slice

Implement protected committee-edge audit and suppression in
`scripts/committee_edge_resolver.py`.

This is an offline-first slice. It should use fixtures to prove that valid
committee fixes remain protected while unsafe/ambiguous/transport-compromised
committee decisions are logged but withheld from the canonical protected
judgment file.
