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

## Roadmap Overview

The roadmap is split into six workstreams:

1. Runtime provisional/cohort-confidence gate
2. Cold-start anchor calibration
3. Rerank damping under disagreement
4. Committee consensus for novel scopes
5. Retrieval-backed scope grounding
6. Governed post-release calibration learning

Each workstream is designed to integrate with the current repo, not replace it.

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
  "recommended_action": "collect_teacher_anchors"
}
```

### Likely Implementation Surface

- `scripts/publish_gate.py`
- `scripts/sota_gate.py`
- new `scripts/cohort_confidence.py`
- `server/step_runner.py`
- `scripts/build_dashboard_data.py`
- `ui/app.js`

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

### Acceptance Criteria

- runtime state is available in dashboard data and UI
- unfamiliar cohorts no longer appear equally trustworthy as benchmark-supported scopes
- teachers see one clear next action, not a wall of metrics

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

### Calibration Mechanics

Do not retrain globally at this stage.
Apply a local run-scoped patch:
- local level offsets by assessor
- local boundary centering
- local rank correction near anchor neighborhoods
- local trust uplift only for the current cohort and matching scope

### Teacher UX Requirement

Keep this simple:
- "Please score 5 anchor papers so I can calibrate this class."
- one paper at a time
- level plus optional mark
- no survey, no justification required

### Acceptance Criteria

- anchor workflow runs from provisional live cohorts only
- `4-6` teacher judgments materially reduce SD and swap rate on rerun
- workflow is optional when confidence is already high

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

Add a `stability_gate_weight` per student:

```text
stability_gate_weight
= f(rubric_sd, rank_sd, disagreement_flags, pairwise_conflict_density)
```

Then apply it to:
- pairwise support weight
- incident weight
- max displacement
- boundary calibration freedom

### Concrete Rule Direction

- low SD, high agreement:
  - normal rerank behavior
- medium SD:
  - movement only inside local neighborhoods
- high SD:
  - hold seed rank unless committee consensus or teacher anchors support movement

### Acceptance Criteria

- swap rate falls materially on novel cohorts
- top-of-cohort churn across repeated runs decreases
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

### Cost Control

Committee mode should be conditional on:
- scope novelty
- rubric ambiguity
- disagreement after first pass

This avoids multiplying cost on already-supported cohorts.

### Acceptance Criteria

- novel-scope level/rank variance decreases
- latency remains acceptable under conditional activation
- committee mode is not activated on all normal cohorts

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

### Proposed Retrieval Inputs

Build embeddings or deterministic feature vectors from:
- normalized rubric criteria and weights
- assignment outline
- grade level / band
- genre / form
- evidence expectations
- discourse markers from writing samples

### Retrieved Objects

For each live cohort, return:
- nearest rubric family
- nearest exemplar set
- nearest calibrated cohort scopes
- nearest successful calibration profile

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
  ]
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

## Workstream 6: Governed Post-Release Calibration Learning

### Problem

Once we release, the best future signal will come from real teacher-reviewed cohorts.
But this must be governed. Most project traffic should not become training data.

### Core Rule

Only retain cohorts for product learning when teacher engagement appears intentional and substantial.

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

### Proposed Data Tiers

1. `discarded`
   - no meaningful teacher engagement
2. `local_only`
   - supports only local teacher personalization
3. `aggregate_candidate`
   - anonymized, governed, eligible for adjudication
4. `promoted_asset`
   - human-approved benchmark / calibration / exemplar asset

### Likely Implementation Surface

- `server/review_store.py`
- `server/projects.py`
- `scripts/aggregate_review_learning.py`
- `scripts/export_aggregate_feedback.py`
- `scripts/ingest_aggregate_feedback.py`
- `scripts/promote_aggregate_learning.py`
- new `scripts/anonymize_teacher_cohort.py`
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

## Concrete Build Sequence

### Phase R1: Cohort Confidence Gate

Build:
- `scripts/cohort_confidence.py`
- dashboard + UI exposure
- runtime states: auto / provisional / anchor required

Exit:
- every live cohort now has an explicit confidence status

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
- retrieval over rubric contract + exemplars + prior calibrated cohorts

Exit:
- fewer runs depend on generic `rubric_unknown` behavior

### Phase R6: Governed Release Learning

Build:
- engagement gate
- anonymization package
- promotion rules for real teacher-reviewed data

Exit:
- post-release learning is real, privacy-aware, and quality-controlled

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

## Immediate Recommendation

If work starts now, the right next implementation order is:

1. runtime cohort-confidence gate
2. cold-start anchor calibration flow
3. rerank damping under high assessor SD

Those three together are the shortest path from the current benchmark-strong system to a live teacher product that fails safely and improves quickly.
