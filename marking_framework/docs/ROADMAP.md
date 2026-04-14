# Live Cohort Roadmap

Status
- State: draft for review
- Last updated: 2026-04-14
- Intended use: technical roadmap for moving from benchmark-green to live-cohort-stable

## Purpose

This document is the next planning layer after [`SOTA_BUILD_PLAN.md`](./SOTA_BUILD_PLAN.md).

The build plan explains how the repo became benchmarked, gated, releaseable, and production-shaped.
This roadmap focuses on the remaining hard problem:

- making the product stable, trustworthy, and calibration-aware on new teacher cohorts that do not come with gold labels

The immediate trigger for this roadmap is the Grade 7 smoke test on a novel live set:
- fresh project flow worked after pipeline fixes
- teacher workflow completed end to end
- benchmark and release gates remain green on the frozen public corpus
- but the live cohort still showed high assessor spread, high rerank swap rate, and noticeable rerun drift

That is the real gap between "benchmark SOTA" and "teacher-world SOTA."

## Current Live-Cohort Read

From the live Grade 7 smoke/stress run:
- publish gate blocked on [`publish_gate.json`](../outputs/publish_gate.json) style metrics for the cohort
- scope resolved to `grade_6_7|literary_analysis|rubric_unknown|gpt-5.4-mini`
- calibration artifact existed, but it was synthetic bootstrap only
- mean assessor rubric SD was about `6.87`
- consistency swap rate was about `0.51`
- top-of-cohort order moved materially across reruns

Interpretation:
- the current system can process a new class
- the current system is not yet stable enough to auto-finalize unfamiliar live scopes without extra controls

## Product Goal

Serve tens of thousands of teachers across grades, countries, prompts, and rubric styles with:
- strong first-pass automated ordering
- bounded confidence-aware grade suggestions
- minimal teacher effort focused only on unstable decisions
- governed improvement from real teacher interaction after release

That implies five non-negotiable properties:

1. Cold-start safety
   - new scopes must degrade into a controlled review flow, not false confidence
2. Stability
   - repeated runs on the same cohort must stay materially consistent
3. Calibration awareness
   - the system must know when it is operating inside or outside supported scope
4. Sparse teacher burden
   - teacher attention should be used on anchor papers and unstable boundaries, not full regrading
5. Governed learning
   - post-release learning must be privacy-preserving, engagement-filtered, and promotion-controlled

## Working Principles

1. Benchmark gates remain the regression contract.
   - no live-cohort improvement work is allowed to break the frozen benchmark corpus
2. Bootstrap calibration is not enough for unfamiliar scopes.
   - it is a startup aid, not a trust signal
3. Reranking must become less aggressive under disagreement.
   - high assessor variance should reduce movement, not amplify it
4. Real teacher interaction is the highest-value future data.
   - not all project traffic is equally meaningful
5. The system should surface uncertainty operationally.
   - the right output is not always "final answer"; sometimes it is "teacher anchor required"

## Existing Systems To Extend, Not Replace

This roadmap is not proposing a second architecture beside the current one.
It should extend the repo's existing subsystems.

### Existing Rerank Damping Base

`scripts/global_rerank.py` already has:
- incident-weight-based support accounting
- displacement caps from `compute_displacement_caps()`
- support tiers (`low_support`, `medium_support`, `high_support`)
- a crossing margin guard (`min_crossing_margin`)

Workstream 3 is therefore not a fresh damping subsystem.
It is an extension of the existing reranker:
- feed per-student stability signals into incident-weight and cap calculation
- reduce the effectively unbounded `high_support` movement behavior for live cohorts
- scale crossing margin with disagreement instead of using one fixed number

### Existing Learning And Governance Base

The post-release learning stack already exists:
- `server/review_store.py`
  - anonymization helpers
  - text redaction
  - retention and tombstone deletion
- `scripts/local_teacher_prior.py`
  - local preference learning
  - bounded adjustments
- `scripts/aggregate_review_learning.py`
  - governed learning summaries
- `scripts/export_aggregate_feedback.py`
- `scripts/ingest_aggregate_feedback.py`
- `scripts/promote_aggregate_learning.py`

Workstream 6 is therefore not a greenfield learning system.
The genuinely new layer is:
- an engagement gate that decides whether a cohort is meaningful enough to keep
- cohort-level packaging rules that decide whether data remains local, becomes aggregate-eligible, or is discarded

### Existing Gate Pattern To Reuse

`scripts/publish_gate.py` and `scripts/sota_gate.py` already implement:
- profile thresholds
- multi-profile pass/fail evaluation
- structured reports

Workstream 1 should reuse that pattern for live cohort confidence.
It should not invent a wholly separate gate style.

## Roadmap Overview

The roadmap is split into six workstreams:

1. Runtime provisional/cohort-confidence gate
2. Cold-start anchor calibration
3. Rerank damping under disagreement
4. Committee consensus for novel scopes
5. Retrieval-backed scope grounding
6. Governed post-release calibration learning

Each workstream is designed to integrate with the current repo, not replace it.

## Workstream Interaction Model

The workstreams are not independent.
They change one another's inputs and thresholds.

Primary interactions:
- Workstream 3 lowers rerank movement and should reduce swap rate.
  - that directly changes Workstream 1 cohort-confidence decisions
- Workstream 4 lowers variance and should reduce assessor SD.
  - that also changes Workstream 1 thresholds in practice
- Workstream 5 changes scope resolution and calibration-family matching.
  - that changes Workstream 1 familiarity signals and Workstream 2 anchor need
- Workstream 2 can move a cohort from `anchor_calibration_required` to `provisional` or `auto_publish_ready`
- Workstream 6 creates the future calibration substrate that improves Workstreams 1, 2, and 5 over time

Because of that, threshold calibration must be staged:
- initial thresholds are set from the current smoke baseline
- after Workstream 3 and Workstream 4 ship in shadow mode, thresholds are recalibrated from observed post-change distributions
- only then should the confidence gate become a blocking runtime control

## Hold-Harmless Rules

Every intervention in this roadmap must be reversible.

1. Anchor calibration must not silently replace the pre-anchor run.
   - store a pre-anchor snapshot
   - accept the anchor patch only if stability improves or remains neutral
   - otherwise revert to the pre-anchor state
2. Committee consensus must not always override single-pass.
   - if committee variance or ordering quality is worse, fall back to single-pass outputs
3. Retrieval grounding must be allowed to abstain.
   - if match confidence is below threshold, do not inject the retrieved family into prompting or calibration
4. Rerank damping must not degrade benchmark corpora.
   - benchmark non-regression remains mandatory before promotion

Every new artifact should therefore include:
- `accepted: true|false`
- `fallback_used: true|false`
- `fallback_reason`

## Workstream 1: Runtime Provisional / Cohort-Confidence Gate

### Problem

Current gates are mostly release and benchmark gates.
They tell us whether a model/config branch should ship.
They do not yet tell a live teacher project whether this specific cohort is safe to auto-grade.

### Target Behavior

Every live project run should end in one of three runtime states:
- `auto_publish_ready`
- `provisional_review_recommended`
- `anchor_calibration_required`

This decision should be emitted before the teacher starts making adjustments.

### Proposed Artifact

Add:
- `outputs/cohort_confidence.json`

Suggested schema:

```json
{
  "status": "provisional_review_recommended",
  "scope_id": "grade_6_7|literary_analysis|rubric_unknown|gpt-5.4-mini",
  "confidence_score": 0.58,
  "reasons": [
    "synthetic_calibration_only",
    "scope_support_low",
    "assessor_sd_high",
    "rerank_swap_rate_high"
  ],
  "metrics": {
    "mean_assessor_sd": 6.87,
    "p95_assessor_sd": 11.89,
    "swap_rate": 0.51,
    "scope_support_reviews": 0,
    "scope_support_observations": 0,
    "rubric_parse_confidence": 0.93,
    "model_coverage": 1.0
  },
  "recommended_action": "collect_teacher_anchors",
  "accepted": true,
  "fallback_used": false,
  "fallback_reason": ""
}
```

### Likely Implementation Surface

- `scripts/publish_gate.py`
- `scripts/sota_gate.py`
- new `scripts/cohort_confidence.py`
- `server/step_runner.py`
- `scripts/build_dashboard_data.py`
- `ui/app.js`

### Gate Precedence Rule

`cohort_confidence` is a live-runtime tightening gate, not a replacement for the existing publish/SOTA gates.

Execution rule:
1. `quality_gate`
2. `sota_gate`
3. `cohort_confidence`

Authority rule:
- if `quality_gate` or `sota_gate` blocks, the cohort is not auto-publish-ready regardless of `cohort_confidence`
- `cohort_confidence` may tighten the runtime outcome
  - for example: convert a publish/SOTA-passing run into `provisional_review_recommended` or `anchor_calibration_required`
- `cohort_confidence` may never loosen a publish/SOTA failure

### Decision Inputs

Start with:
- calibration scope support
- synthetic vs calibrated profile
- rubric parse confidence from `rubric_verification.json`
- pass1 assessor SD
- pass2 rank SD
- consistency swap rate
- pairwise concentration near boundaries
- model coverage
- scope familiarity by grade band + genre + rubric family + model family

### Initial Thresholds

These are the initial operating thresholds for shadow mode.
They are intentionally anchored to the current Grade 7 smoke baseline and existing gate conventions.

| Runtime state | Mean assessor SD | P95 assessor SD | Swap rate | Scope support | Calibration type | Rubric parse confidence |
|---|---:|---:|---:|---|---|---:|
| `auto_publish_ready` | `<= 3.0` | `<= 6.0` | `<= 0.15` | real scoped support present | non-synthetic | `>= 0.85` |
| `provisional_review_recommended` | `<= 5.0` | `<= 10.0` | `<= 0.35` | partial or sparse support | synthetic allowed | `>= 0.70` |
| `anchor_calibration_required` | `> 5.0` or | `> 10.0` or | `> 0.35` or | no real scoped support | synthetic only | `< 0.70` |

Additional hard triggers for `anchor_calibration_required`:
- `rubric_family == rubric_unknown` plus synthetic-only calibration
- no scoped observations and no nearest-family retrieval above confidence threshold
- model coverage below `0.9`

### Operational Rule

- `auto_publish_ready`
  - calibrated scope support exists
  - disagreement below threshold
  - swap rate below threshold
  - no bootstrap-only dependence
- `provisional_review_recommended`
  - usable run, but one or more stability indicators are weak
- `anchor_calibration_required`
  - unfamiliar scope plus weak stability plus no real scope calibration support

### Shadow-Mode Rollout

This gate should not block teacher workflow immediately.

Initial rollout:
- emit `outputs/cohort_confidence.json`
- expose status in dashboard and UI
- do not block or reroute the workflow yet

Promotion criteria from shadow mode to blocking mode:
- at least `50` live cohorts observed
- false-positive rate for `anchor_calibration_required` below `10%`
- missed-unstable-cohort rate below `5%`
- thresholds recalibrated after Workstream 3 and Workstream 4 land

### Acceptance Criteria

- runtime state is available in dashboard data and UI
- unfamiliar cohorts no longer appear equally trustworthy as benchmark-supported scopes
- teachers see one clear next action, not a wall of metrics
- gate starts in shadow mode and only becomes blocking after validation

## Workstream 2: Cold-Start Anchor Calibration

### Problem

The current system can start a new cohort with synthetic bootstrap calibration, but that does not create defensible local trust.
For novel scopes, we need a fast teacher calibration loop that uses a few real papers from the current class.

### Target Workflow

1. Full cohort runs once in provisional mode.
2. System chooses `4-6` anchor candidates.
3. Teacher scores only those anchor papers.
4. System fits a local cohort calibration patch.
5. Ranking and banding rerun using those anchors.
6. Final teacher review sees a much more stable curve.

### Anchor Selection Strategy

Choose anchors to maximize information:
- one predicted top-band paper
- one predicted bottom-band paper
- two boundary-near papers around Level 2/3 and 3/4
- one high-disagreement paper
- optional one atypical-form or style outlier if cohort variance is high

### Proposed Artifacts

Add:
- `outputs/anchor_candidates.json`
- `outputs/teacher_anchor_packet.json`
- `outputs/cohort_anchor_calibration.json`
- `outputs/pre_anchor_snapshot.json`
- `outputs/post_anchor_snapshot.json`

### Suggested Schema

```json
{
  "selected_student_ids": ["s011", "s014", "s004", "s020", "s009"],
  "selection_reasons": {
    "s011": ["predicted_top_band"],
    "s014": ["predicted_bottom_band"],
    "s004": ["boundary_2_3", "high_disagreement"],
    "s020": ["boundary_3_4"],
    "s009": ["style_outlier"]
  }
}
```

### Likely Implementation Surface

- new `scripts/select_anchor_candidates.py`
- new `scripts/apply_anchor_calibration.py`
- `server/projects.py`
- `server/review_store.py`
- `scripts/calibrate_assessors.py`
- `scripts/aggregate_assessments.py`
- `scripts/global_rerank.py`
- `ui/app.js`

### Runtime Architecture Requirement

This workstream requires a conditional project state machine.
The current fixed linear step graph is not enough.

Add explicit job/project modes:
- `full_run`
- `awaiting_anchor_scores`
- `anchor_resume`
- `anchor_reverted`

The anchor flow should:
1. execute the normal run once
2. stop after dashboard build if cohort confidence requires anchors
3. persist a pre-anchor snapshot
4. wait for teacher anchor scores
5. resume from post-assessment steps only

The resume path should re-execute:
- `aggregate_1`
- `boundary`
- `aggregate_2`
- `consistency`
- `rerank`
- `quality_gate`
- `sota_gate`
- `grade`
- `dashboard`

The resume path should not re-execute:
- `rubric`
- `extract`
- `conventions`
- `assess`
- `pairwise`

`pairwise` is explicitly skipped on anchor resume.
Reason:
- the reranker already consumes the existing pairwise evidence collected during the first full run
- anchor resume should re-center aggregation and banding without paying the full pairwise recomputation cost unless a later failure mode proves it necessary

That means this is a runtime state-machine change spanning:
- `server/step_runner.py`
- `server/pipeline_queue.py`
- `server/projects.py`

### Calibration Mechanics

Do not retrain globally at this stage.
Apply a local run-scoped patch:
- local level offsets by assessor
- local boundary centering
- local rank correction near anchor neighborhoods
- local trust uplift only for the current cohort and matching scope

### Interaction With `local_teacher_prior`

Anchor calibration and `local_teacher_prior` are different mechanisms and should not both drive the same rerun independently.

Rule:
- for the current anchor rerun, anchor calibration supersedes `local_teacher_prior`
- after the teacher finalizes the anchored cohort, the resulting finalized deltas remain eligible to feed `local_teacher_prior` for future cohorts in the same scope

### Teacher UX Requirement

Keep this simple:
- "Please score 5 anchor papers so I can calibrate this class."
- one paper at a time
- level plus optional mark
- no survey, no justification required

### Hold-Harmless Rule

Anchor calibration is accepted only if:
- swap rate does not increase
- top-5 rerun overlap does not decrease
- boundary disagreement concentration does not increase

Reason:
- raw `rubric_sd_points` comes from pass1 assessor spread and does not materially change if anchor calibration only re-centers aggregation and banding
- anchor acceptance should therefore be judged on metrics that are expected to move on rerun

Otherwise:
- mark anchor patch `accepted: false`
- revert to pre-anchor outputs
- surface `fallback_reason: anchor_patch_not_helpful`

### Acceptance Criteria

- anchor workflow runs from provisional live cohorts only
- `4-6` teacher judgments reduce swap rate from `0.51` baseline toward `< 0.15`
- `4-6` teacher judgments reduce boundary disagreement concentration from the pre-anchor snapshot
- workflow is optional when confidence is already high
- anchor rerun completes without re-running assessor passes

## Workstream 3: Rerank Damping Under High Assessor SD

### Problem

The current rerank logic can still move papers too much when assessor disagreement is high.
That is the wrong behavior.
High disagreement should collapse movement, not encourage it.

### Target Change

When assessor SD or rank instability is high:
- reduce pairwise movement budgets
- reduce displacement caps
- increase seed-rank stickiness
- require stronger evidence to cross positions

### Current Relevant Surface

- `scripts/verify_consistency.py`
- `scripts/global_rerank.py`
- `scripts/aggregate_assessments.py`
- `scripts/boundary_calibrator.py`

### Proposed Mechanics

Extend the existing `global_rerank.py` mechanics rather than creating a parallel damping layer.

Specifically:
- feed per-student `rubric_sd`, `rank_sd`, and disagreement density into incident support classification
- scale `incident_weight` downward when disagreement is high
- make `compute_displacement_caps()` stability-aware
- scale `min_crossing_margin` upward when disagreement is high

Add a per-student stability penalty:

```text
stability_penalty
= f(rubric_sd, rank_sd, disagreement_flags, pairwise_conflict_density)
```

Apply it to the current reranker inputs:
- effective pairwise support weight
- effective incident weight
- displacement-cap tier selection
- crossing-margin multiplier

### Concrete Parameter Direction

For live cohorts:
- `low_support` cap remains `1`
- `medium_support` cap reduces from `3` to `2` when stability penalty is high
- `high_support` cap must become bounded for live cohorts
  - initial target: `5`, not unlimited
- `min_crossing_margin`
  - baseline: current value
  - noisy cohorts: multiply toward `2.0x`

### Concrete Rule Direction

- low SD, high agreement:
  - normal rerank behavior
- medium SD:
  - movement only inside local neighborhoods
- high SD:
  - hold seed rank unless committee consensus or teacher anchors support movement

### Acceptance Criteria

- swap rate falls from the current `0.51` smoke baseline to `< 0.30` after damping alone
- top-5 rerun overlap increases from the observed `0.40` baseline to `>= 0.70`
- benchmark corpus does not regress

## Workstream 4: Committee Consensus For Novel Scopes

### Problem

Single-run committee outputs can still be too noisy on unfamiliar grade/genre/rubric combinations.
We need a controlled way to stabilize novel scopes without exploding cost everywhere.

### Target Change

For novel or low-support scopes only:
- run repeated pass1 committees or multi-seed committees
- aggregate before pass2 and reranking
- keep this off for familiar calibrated scopes where it is unnecessary

### Modes

1. `single_pass`
   - default for familiar, stable scopes
2. `committee_pass`
   - multiple assessor samples in one run
3. `repeat_run_consensus`
   - repeat the cohort run `N` times and aggregate intermediate outputs

### Recommended Initial Policy

Use `committee_pass` first.
Reserve full `repeat_run_consensus` for:
- `anchor_calibration_required`
- high-stakes exports
- debugging and family stability benchmarking

### Proposed Artifact

Add:
- `outputs/committee_consensus_report.json`

### Likely Implementation Surface

- `scripts/run_llm_assessors.py`
- `scripts/llm_assessors_core.py`
- `scripts/aggregate_assessments.py`
- `scripts/benchmark_family_stability.py`
- `config/llm_routing.json`

### Budget

Committee mode must stay inside existing product budgets unless the teacher explicitly opts into a higher-cost diagnostic run.

Default budget:
- total projected cost must remain `<= $0.25` per student
- total projected cost must remain `<= $10.00` per job
- committee uplift is whatever remains under the hard `$0.25` per-student cap after projected single-pass actual

Hard rule:
- the absolute cap governs
- there is no separate uplift allowance that may exceed the absolute per-student limit

Latency target:
- no more than `1.5x` single-pass live latency for a novel cohort
- anchor resume path should remain cheaper than a full committee rerun

### Hold-Harmless Rule

Committee consensus is accepted only if:
- mean student level variance decreases
- mean student rank variance decreases
- Kendall and pairwise agreement are non-worse in repeated-run evaluation

Otherwise:
- fall back to single-pass outputs
- emit `fallback_reason: committee_not_helpful`

### Acceptance Criteria

- novel-scope level/rank variance decreases
- latency remains acceptable under conditional activation
- committee mode is not activated on all normal cohorts
- committee mode stays inside the live budget envelope by default

## Workstream 5: Retrieval-Backed Scope Grounding

### Problem

Current scope resolution is still too metadata-heavy.
A live cohort often lands in a broad bucket like:
- `grade_6_7|literary_analysis|rubric_unknown`

That is not enough context for stable scoring.

### Target Change

Before pass1 scoring, retrieve nearest grounded references from:
- normalized rubric contract
- exemplar bank
- prior calibrated cohorts
- source-family calibration profiles
- prior teacher-reviewed finalized cohorts

### Retrieval Architecture Decision

Phase 1 should use deterministic retrieval, not embeddings.

Reason:
- current server architecture is local FastAPI + subprocess oriented
- deterministic retrieval fits the existing `build_run_scope()` style matching
- it avoids introducing vector infrastructure before the feature is proven

Phase-1 retrieval features:
- normalized rubric criteria and weights
- assignment outline
- grade level / band
- genre / form
- evidence expectations
- rubric-family alias overlap
- prompt/form terminology overlap

Embeddings can be reconsidered later if deterministic retrieval saturates.

### Retrieved Objects

For each live cohort, return:
- nearest rubric family
- nearest exemplar set
- nearest calibrated cohort scopes
- nearest successful calibration profile

### Coverage Constraint

Retrieval should only influence scoring when support is real.

Phase-1 activation rule:
- use retrieval hints only when there are at least:
  - `2` prior calibrated cohorts in the candidate family, or
  - `3` grounded exemplar hits in the candidate family
- otherwise abstain

This prevents sparse-bank false positives.

### Proposed Artifact

Add:
- `outputs/scope_grounding.json`

Suggested schema:

```json
{
  "resolved_scope": {
    "grade_band": "grade_6_7",
    "genre": "literary_analysis",
    "rubric_family": "theme_analysis_5paragraph"
  },
  "retrieval_hits": [
    {
      "type": "calibrated_cohort",
      "scope_id": "grade_6_7|literary_analysis|theme_analysis_5paragraph|gpt-5.4-mini",
      "distance": 0.11
    },
    {
      "type": "exemplar_family",
      "path": "inputs/exemplars/grade_6_7/literary_analysis",
      "distance": 0.16
    }
  ],
  "accepted": true,
  "fallback_used": false,
  "fallback_reason": ""
}
```

### Likely Implementation Surface

- new `scripts/scope_retrieval.py`
- `scripts/rubric_contract.py`
- `scripts/build_dashboard_data.py`
- `scripts/run_llm_assessors.py`
- `server/bootstrap.py`
- `config/marking_config.json`

### Acceptance Criteria

- fewer live runs end up in `rubric_unknown`
- cold-start cohorts receive stronger grounded prompts and calibration hints
- benchmark performance does not regress due to over-broad retrieval
- phase 1 uses deterministic feature retrieval only
- uncovered exemplar territory results in abstention, not forced grounding

## Workstream 6: Governed Post-Release Calibration Learning

### Problem

Once we release, the best future signal will come from real teacher-reviewed cohorts.
But this must be governed. Most project traffic should not become training data.

### Core Rule

Only retain cohorts for product learning when teacher engagement appears intentional and substantial.

### Mapping To Existing Infrastructure

This workstream extends the current learning stack rather than replacing it.

Mapping:
- `discarded`
  - new outcome from the engagement gate
  - not retained beyond local transient runtime artifacts
- `local_only`
  - existing `local_only` mode
  - eligible for local teacher priors only
- `aggregate_candidate`
  - existing `opt_in` or `policy_compliant` records that also pass the new engagement gate
- `promoted_asset`
  - existing promotion pipeline output after adjudication

Anonymization base already exists in:
- `server/review_store.py`
  - `hash_identifier()`
  - `redact_text()`
  - deletion/tombstone semantics

So the truly new components are:
- `scripts/engagement_gate.py`
- optional cohort-level packaging glue
  - not a separate anonymization subsystem

### Retention Rule

Keep only cohorts where the teacher:
- opened and reviewed the results
- spent meaningful time in the review flow
- made finalized decisions or substantive interactions

Automatically discard cohorts where:
- the teacher never reviewed the cohort
- the teacher clicked through too quickly to suggest real reading
- there was no finalized interaction signal
- the system was used as a passive one-click export only

### Proposed Engagement Heuristics

Promote to governed candidate data only if all are true:
- finalized review exists
- review dwell time exceeds threshold
- at least `N` essay opens or compare interactions
- interaction pattern is not bot-like or near-instant
- optional: at least one substantive change, anchor score, or review confirmation action

### Privacy Requirement

Before any upload or retention beyond local project scope:
- scrub names from essay text where feasible
- remove filenames that contain student identifiers
- strip project, teacher, and school identifiers
- hash stable student IDs per cohort
- store only anonymized rubric, scope, features, final teacher outputs, and minimally needed text payloads

### Important Constraint

Do not use all raw essays as product-wide training data by default.
Prefer:
- structured features
- teacher deltas
- boundary decisions
- selected anonymized examples promoted through governance

### Likely Implementation Surface

- `server/review_store.py`
- `server/projects.py`
- `scripts/aggregate_review_learning.py`
- `scripts/export_aggregate_feedback.py`
- `scripts/ingest_aggregate_feedback.py`
- `scripts/promote_aggregate_learning.py`
- new `scripts/engagement_gate.py`

### Proposed Artifact

Add:
- `outputs/engagement_signal.json`
- `outputs/anonymized_cohort_package.json`

### Acceptance Criteria

- non-engaged cohorts are automatically forgotten
- engaged cohorts can be anonymized and promoted safely
- product learning remains opt-in or policy-compliant
- all promoted data retain provenance and deletion semantics

## Quantitative Targets

These are the working numeric targets for the live-cohort hardening track.
They should be updated when enough post-change live cohorts exist, but they should not stay vague.

| Metric | Current smoke baseline | Target after R3 | Target after R2+R3+R4 |
|---|---:|---:|---:|
| Mean assessor SD | `6.87` | `< 4.5` | `< 3.0` |
| P95 assessor SD | `11.89` | `< 8.0` | `< 6.0` |
| Swap rate | `0.51` | `< 0.30` | `< 0.15` |
| Top-5 rerun overlap | `0.40` | `>= 0.70` | `>= 0.85` |
| Cohort confidence false-anchor rate | unknown | shadow only | `< 10%` |
| Missed-unstable-cohort rate | unknown | shadow only | `< 5%` |
| Anchor burden | n/a | n/a | `<= 6 papers` |
| Anchor rerun incremental latency | n/a | n/a | `<= 45s` |

## Concrete Build Sequence

### Phase R0: Conditional Pipeline State Machine

Build:
- paused/resumable project execution states
- pre/post intervention snapshots
- partial rerun path for anchor resume
- fallback/revert semantics

Before implementation starts, write a short design sketch for R0 covering:
- where paused project state is persisted on disk
- which artifacts belong in a snapshot
- how paused state is exposed to the UI
- how resume/revert survives server restart
- how queue jobs map onto paused/resumed project state

Exit:
- runtime can pause for teacher input and resume from post-assessment steps only

### Phase R1: Cohort Confidence Gate

Build:
- `scripts/cohort_confidence.py`
- dashboard + UI exposure
- runtime states: auto / provisional / anchor required
- shadow-mode logging only
- threshold report against live cohort outcomes

Exit:
- every live cohort now has an explicit confidence status
- no blocking behavior yet

### Phase R2: Cold-Start Anchors

Build:
- anchor candidate selector
- teacher anchor packet flow
- local anchor calibration rerun

Exit:
- unfamiliar scopes can be stabilized with `4-6` teacher judgments

### Phase R3: Rerank Damping

Build:
- SD-aware displacement caps
- disagreement-aware pairwise weighting
- dynamic crossing-margin scaling

Exit:
- swap rate drops materially on novel live cohorts

### Phase R4: Committee Consensus

Build:
- conditional committee mode for novel scopes
- committee consensus report

Exit:
- repeated-run variance drops without turning all cohorts into expensive workflows

### Phase R5: Retrieval Scope Grounding

Build:
- deterministic retrieval over rubric contract + exemplars + prior calibrated cohorts

Exit:
- fewer runs depend on generic `rubric_unknown` behavior

### Phase R6: Governed Release Learning

Build:
- engagement gate
- cohort-level anonymized packaging
- promotion rules for real teacher-reviewed data

Exit:
- post-release learning is real, privacy-aware, and quality-controlled

### Threshold Recalibration Step

After Phase R3 and Phase R4:
- recompute live-cohort distributions for SD, swap rate, and rerun overlap
- revise Workstream 1 thresholds from observed post-change behavior
- only then promote cohort confidence from shadow mode to blocking mode

## Metrics That Matter

For benchmark corpora:
- exact level hit
- within-one hit
- score-band MAE
- Kendall tau
- pairwise agreement
- cost
- latency

For live cohorts:
- mean assessor SD
- p95 assessor SD
- rerank swap rate
- top-k rerun overlap
- boundary disagreement concentration
- anchor rerun uplift
- teacher override rate after anchor calibration
- time to trustworthy cohort

For post-release data quality:
- kept vs discarded cohort ratio
- anonymization success rate
- promoted candidate acceptance rate
- deletion compliance rate

## Guardrails Against Overfitting

1. Keep the frozen public benchmark corpus as the release contract.
2. Do not tune globally against one live cohort.
3. Use family-level repeated-run stability before promoting scope-specific profiles.
4. Restrict local anchor calibration to local cohort scope unless promoted deliberately.
5. Treat teacher interaction as calibration data only when engagement passes policy thresholds.

## Additional Risks Not In The First Six Workstreams

These are important, but they are not the first build items.

1. Locale and jurisdiction policy normalization
   - worldwide teacher use will eventually require stronger handling of:
     - local achievement-level semantics
     - conventions tolerance by grade and region
     - mark-band translation across systems
2. Teacher-facing explanation quality
   - if the product says "anchor calibration required", the explanation must be short, specific, and trustworthy
3. Exemplar-bank density outside covered families
   - retrieval and cold-start support will only be as good as the exemplar/calibration coverage underneath them

## Immediate Recommendation

If work starts now, the right next implementation order is:

1. conditional pipeline state machine
2. runtime cohort-confidence gate in shadow mode
3. cold-start anchor calibration flow
4. rerank damping under high assessor SD

Those four together are the shortest path from the current benchmark-strong system to a live teacher product that fails safely and improves quickly.
