# Docs Alignment Audit

Date: 2026-04-22

Branch audited: `main` at `f93edd4`

Audit branch: `codex/docs-alignment-audit`

## Source Of Truth Checked

- `server/step_runner.py`
- `scripts/hero_path.py`
- `config/llm_routing.json`
- `config/accuracy_gate.json`
- `config/marking_config.json`
- `scripts/publish_gate.py`
- `scripts/sota_gate.py`
- `scripts/committee_edge_resolver.py`
- `scripts/evidence_map.py`
- `scripts/evaluate_pairwise_adjudicator.py`

## Findings

### 1. README Pairwise Path Was Stale

`README.md` still described pairwise consistency as `verify_consistency.py` plus
`global_rerank.py`, and it pointed hard-pair evals at
`outputs/consistency_checks.json`.

Current code routes the canonical path through:

1. `band_seam_adjudication.py`
2. `verify_consistency.py`
3. `escalate_pairwise_adjudications.py`
4. `evidence_map.py`
5. `committee_edge_resolver.py`
6. `global_rerank.py --judgments outputs/consistency_checks.committee_edge.json`
7. `evaluate_pairwise_adjudicator.py --judgments outputs/consistency_checks.committee_edge.json`

Updated `README.md` to describe the current route and key artifacts.

### 2. LLM Routing Doc Missed New Task Routes

`docs/LLM_ROUTING.md` listed only the original pass1/pass2/pairwise/feedback
tasks.

Current routing includes:

- `pairwise_escalator`
- `literary_committee`

Updated the doc to list the current task map, including that
`literary_committee` intentionally uses `gpt-5.4-mini` at high reasoning and is
only invoked when live committee reads are explicitly enabled.

### 3. Quality Gates Doc Preceded Publish/SOTA Evidence-Packet Checks

`docs/QUALITY_GATES.md` described aggregation and re-read checks but did not
cover the current publish/SOTA profile gates, routed hard-pair eval, or
evidence-neighborhood and evidence-group-packet readiness.

Updated it to separate:

- aggregation completeness gates
- re-read/boundary quality signals
- publish/SOTA release gates

### 4. Live Cohort Runtime Anchor Resume Path Was Missing New Seams

`docs/LIVE_COHORT_RUNTIME.md` listed the older anchor resume sequence and did
not include:

- `band_seam`
- `pairwise_escalation`
- `evidence_map`
- `committee_edge_resolver`
- `pairwise_eval`

Updated the anchor resume path and documented routed committee-edge calibration.

### 5. Data Formats Still Centered Legacy Pairwise Review Artifacts

`docs/DATA_FORMATS.md` still treated `assessments/final_review_pairs.json` and
legacy keep/swap files as the main final pairwise artifacts.

Updated it to document:

- `outputs/consistency_checks.json`
- `outputs/consistency_checks.escalated.json`
- `outputs/consistency_checks.committee_edge.json`
- committee-edge artifacts
- evidence-map and group-packet artifacts
- pairwise adjudicator eval

Legacy pairwise-review artifacts remain documented as optional tooling.

### 6. Marking Model Doc Understated Current Rerank Inputs

`docs/MARKING_MODEL.md` described pairwise rerank but not band seam,
escalation, evidence maps, committee-edge merge, or routed hard-pair eval.

Updated the pairwise/rerank section to describe the current canonical judgment
file and default model-free committee-edge behavior.

### 7. SOTA And Live Roadmap Next Steps Were Behind The Current Failure Mode

`docs/SOTA_BUILD_PLAN.md` and `docs/ROADMAP.md` still pointed the immediate
next work mainly at broad Phase 11 scope-routing and early-grade calibration.

That work remains valid, but the current concrete failure after the merged
committee-edge seam is narrower:

- the right Ghost hard pairs are selected
- the right packet is shown to `gpt-5.4-mini`
- mechanics blocker abuse is now rejected
- mini can still preserve wrong prior winners through proof-quality language
  against interpretation/content cautions

Updated both docs to name the next slice: challenge proof-quality prior
preservation against interpretation/content cautions before returning to broader
external corpus work.

## Historical Reports Intentionally Left Unchanged

Files under `docs/reports/` that describe prior dated validation runs were not
rewritten, even when they mention older artifact paths such as
`outputs/consistency_checks.json`. Those reports are historical evidence, not
live operating instructions.

The one exception is this audit report, which records the current alignment
state.

## Verification

```bash
python3 -m pytest -q --no-cov tests/test_hero_path.py tests/test_step_runner.py tests/test_publish_gate.py tests/test_sota_gate.py tests/test_committee_edge_resolver.py
# 165 passed in 0.74s

python3 -m pytest -q --no-cov
# 772 passed in 3.18s

git diff --check
# passed
```

Active-doc stale-reference sweep:

```bash
rg -n "codex/stable-bell-curve|committee_consensus_report|final_review_pairs|outputs/consistency_checks\\.json|gpt-5\\.4-mini|literary_committee|pairwise_escalator" marking_framework/README.md marking_framework/docs/*.md
```

Result: remaining active-doc hits are intentional current artifacts, current
model-routing references, or explicitly marked legacy optional files. Dated
historical reports still contain older paths and branch names by design.

## Next Slice

Implement proof-quality preservation challenge in
`scripts/committee_edge_resolver.py`.

The guard should reject prior-preserving group edges when the model merely says
the prior winner has more evidence, more concrete plot events, or clearer proof
without directly refuting the loser-side interpretive/content claim that caused
the caution route.
