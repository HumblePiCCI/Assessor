# SOTA Build Plan

Status
- State: active working plan
- Last updated: 2026-03-30
- Intended use: canonical continuation document for architecture, sequencing, and acceptance criteria across future sessions

## Purpose

This document turns the repo's "make it SOTA" strategy into a concrete build plan anchored to the scaffold that already exists.

It is not a vision memo. It is the working source of truth for:
- what the current system already does
- what the real gaps are
- what files and modules own each improvement
- what order the work should happen in
- what "done" means for each phase

If future work resumes after context compaction, start here.

## Current Status

The original six foundation phases are implemented in the repo:
- Phase 1: execution unification and reproducibility
- Phase 2: explicit-gold benchmark harness
- Phase 3: global reranker
- Phase 4: versioned calibration
- Phase 5: profile-based release gates
- Phase 6: teacher review persistence and replay exports

That is necessary progress, but it is not the same thing as production readiness.

The current system can:
- run through one authoritative queue-backed execution path
- emit manifest-keyed artifacts
- benchmark against explicit human gold
- rerank globally from pairwise evidence
- enforce calibration and gate contracts
- persist teacher review snapshots, local learning summaries, and anonymized aggregate logs

The current system does not yet:
- distinguish draft teacher sorting from finalized learning signal
- consume local teacher preference priors inside runtime reranking
- promote aggregate review traffic into product updates through a governed data path
- satisfy the operational, privacy, and launch requirements of a production product

## Working Definition Of SOTA For This Repo

For this project, "SOTA" means seven things at once:

1. Reproducibility
   - Same essays plus same pipeline manifest produce the same outputs.
2. Defensible accuracy
   - Outputs are benchmarked against explicit human gold, not filename heuristics.
3. Stable ranking
   - Final ordering is produced by a globally coherent reranker, not just local swaps.
4. Calibrated judgment
   - Assessor bias correction is versioned by model, rubric family, grade band, and genre.
5. Release discipline
   - Shipping is blocked unless accuracy, stability, cost, and reproducibility gates pass.
6. Bounded personalization
   - Teacher-specific preference learning is subtle, scoped, uncertainty-gated, and never allowed to override the objective backbone on clear cases.
7. Safe product learning
   - Cross-teacher improvement uses only anonymized, governed, finalized review data.

## Current Scaffold

The repo already has the right major layers. The work is to harden and unify them.

### Execution Plane

- `server/app.py`
  - two pipeline entrypoints
  - UI asset serving
  - auth handling
- `server/pipeline_queue.py`
  - queued jobs
  - job DB
  - artifact caching
  - event streaming
- `server/step_runner.py`
  - step graph and subprocess execution
- `scripts/hero_path.py`
  - CLI orchestration path for the marking pipeline

### Model And Calibration Plane

- `scripts/run_llm_assessors.py`
  - pass 1 and pass 2 generation
  - routing and fallback behavior
- `scripts/calibrate_assessors.py`
  - gold exemplar calibration
  - scoped/global bias profiles
- `server/bootstrap.py`
  - class metadata bootstrap
  - neutral bootstrap calibration
- `scripts/calibration_gate.py`
  - scope validity checks
- `scripts/publish_gate.py`
  - release readiness checks
- `scripts/sota_gate.py`
  - stricter "SOTA readiness" checks

### Ranking Plane

- `scripts/aggregate_assessments.py`
  - score aggregation
  - leveling
  - ranking seed
- `scripts/verify_consistency.py`
  - pairwise evidence collection
- `scripts/global_rerank.py`
  - deterministic rerank optimization
  - level locks
  - displacement caps
- `scripts/review_and_grade.py`
  - non-interactive or reviewed grade curve generation
- `scripts/apply_curve.py`
  - level-aware bell-curve grade assignment

### Evaluation Plane

- `scripts/benchmark_main_vs_fallback.py`
  - current benchmark harness
- `bench/`
  - sample benchmark datasets

### Product Plane

- `scripts/build_dashboard_data.py`
  - teacher-facing artifact assembly
- `server/projects.py`
  - project metadata surface
- `ui/`
  - teacher review and adjustment UI

## Remaining Production-Ready Gaps

These are the real blockers between the current branch state and a production-ready product.

### Gap 1: Review Sessions Are Not Yet Split Into Draft And Final

Today the UI can save structured review state, but the system does not yet formalize the distinction between:
- exploratory draft sorting
- finalized teacher judgment

That matters because production learning must be based on the final settled curve, not on intermediate drag-and-drop behavior.

### Gap 2: Local Learning Profiles Are Descriptive, Not Yet Operational

`server/review_store.py` produces useful summaries and replay exports, but the runtime ranking path does not yet consume a bounded teacher prior.

That means the system can observe teacher behavior but cannot yet learn from it safely inside `scripts/global_rerank.py`.

### Gap 3: Teacher Preference Reasons Are Not Yet Normalized

The system stores comments and evidence-quality flags, but it does not yet convert teacher adjustments into a stable reason vocabulary such as:
- eloquence
- insight
- completeness
- concision
- organization
- voice
- evidence fit

Without that layer, the product risks learning from raw movement without understanding why the teacher made the move.

### Gap 4: Aggregate Review Learning Is Not Yet Governed End To End

The repo can write anonymized local aggregate logs, but it does not yet define:
- finalized-only export rules
- consent and opt-out behavior
- secure upload and ingestion
- human adjudication before promotion into benchmark or calibration assets

### Gap 5: Production Ops, Privacy, And Launch Controls Are Still Missing

The branch does not yet define the operational contract for:
- teacher and tenant isolation
- retention and deletion policy
- auditability of promoted learning data
- queue health and backpressure
- rollback and incident handling
- launch checklist and go/no-go rules

## Target Architecture

The target architecture keeps the existing layers but changes the control flow and data contracts.

### Core Principles

1. Every run is job-scoped
   - inputs, intermediates, outputs, events, and manifests live under a job workspace
2. Every artifact is attributable
   - each artifact can name the exact pipeline manifest that produced it
3. Every ranking step is explicit
   - seed rank, pairwise evidence, rerank model, and final order are separate artifacts
4. Every release is benchmarked
   - prompt or model changes do not ship unless evals and gates pass
5. Teacher review is finalized before it becomes training signal
   - intermediate edits are draft state only
   - only finalized net deltas are eligible for learning
6. Learning stays bounded
   - teacher priors can only move ambiguous cases within narrow caps

### Target Run Shape

For each job, the system should produce:
- `pipeline_manifest.json`
- `job_inputs_manifest.json`
- `processing/...`
- `assessments/pass1_*`
- `assessments/pass2_*`
- `outputs/consensus_scores.csv`
- `outputs/pairwise_matrix.json`
- `outputs/final_order.csv`
- `outputs/consistency_report.json`
- `outputs/grade_curve.csv`
- `outputs/dashboard_data.json`
- `outputs/publish_gate.json`
- `outputs/sota_gate.json`

The cache key must be derived from the manifest, not just the uploaded files.

## Target Review-Learning Contract

Teacher review is part of the product, but it must not be treated as a live training stream.

### Principles

1. Draft interaction is not learning
   - teachers can drag, compare, cluster, and reorganize freely
   - no intermediate UI move should affect the model
2. Finalization is the learning boundary
   - on finalize or publish, compute the net difference between the machine proposal and the final teacher curve
3. Learn from deltas, not from motion
   - extract level overrides, material rank moves, pairwise inversions, and boundary decisions from the final landing state
4. Prefer passive inference
   - infer teacher taste from repeated finalized deltas
   - only ask for one-click reason tags when the information gain is unusually high
5. Apply locally before promoting globally
   - local teacher priors may adapt faster
   - product-wide learning requires anonymization, aggregation, and human promotion into official assets

### Target Review Artifacts

The production review system should distinguish:
- `review_draft.json`
  - mutable UI state
  - not used for learning
- `review_final.json`
  - immutable finalized teacher curve
  - attached to pipeline and calibration manifests
- `review_delta.json`
  - normalized machine-versus-final correction set
- `local_preference_prior.json`
  - scoped, bounded, uncertainty-gated teacher prior for runtime use
- `anonymized_feedback.jsonl`
  - finalized-only aggregate telemetry

## Build Strategy

The original six foundation phases are complete. The remaining work is the production-readiness track.

### Phase 1: Execution Unification And Reproducibility

Goal
- make one execution engine authoritative
- eliminate shared-root mutation as the production runtime model
- make cache correctness enforceable

Primary files
- `server/app.py`
- `server/pipeline_queue.py`
- `server/step_runner.py`
- `scripts/hero_path.py`

Build tasks

1. Make `/pipeline/run` delegate to the same queue-backed implementation as `/pipeline/v2/run`
   - keep `/pipeline/run` only as a compatibility API
   - remove bespoke direct-run behavior

2. Move job execution to isolated workspaces
   - create `server/data/workspaces/<job_id>/`
   - copy inputs there
   - run the step graph there
   - stop mutating the repo root during queued execution

3. Introduce a formal pipeline manifest
   - include:
     - git SHA if available
     - execution mode
     - uploaded input hashes
     - prompt hashes
     - config hashes
     - exemplar tree hash
     - calibration artifact hash
     - model names and routing settings
     - grade profile hash
     - gate threshold hashes
   - persist as `pipeline_manifest.json`

4. Expand cache invalidation
   - replace the current narrow snapshot hash with a manifest-derived digest
   - only reuse an artifact if the whole manifest matches

5. Make artifact storage manifest-aware
   - artifacts directory should be keyed by manifest hash
   - include a manifest copy next to the dashboard artifact

6. Standardize event and failure output
   - every step must emit:
     - start
     - complete or failed
     - stdout/stderr fragments
     - produced artifact names if any

Acceptance criteria
- direct and queued runs produce the same step graph and artifacts
- two jobs can run without input/output clobbering
- cache invalidates when prompts, exemplars, calibration, or config change
- rerunning a manifest-identical job produces byte-stable final outputs

Test plan
- add job isolation tests
- add cache-bust tests for:
  - `config/llm_routing.json`
  - `config/marking_config.json`
  - exemplar file edits
  - calibration artifact edits
- add manifest round-trip tests
- add endpoint parity tests for `/pipeline/run` and `/pipeline/v2/run`

Exit condition
- the queue becomes the only authoritative production execution path

### Phase 2: Replace The Benchmark Harness

Goal
- move from filename-derived heuristics to explicit human gold
- make model comparisons meaningful

Primary files
- `scripts/benchmark_main_vs_fallback.py`
- `bench/`
- `scripts/publish_gate.py`
- `scripts/sota_gate.py`

Build tasks

1. Define benchmark dataset schema
   - each dataset should contain:
     - `inputs/`
     - `submissions/`
     - `gold.jsonl` or `gold.csv`
   - each gold row should include:
     - `student_id`
     - `gold_level`
     - `gold_band_min`
     - `gold_band_max`
     - `gold_rank`
     - optional `gold_neighbors`
     - optional `boundary_flag`
     - optional adjudication notes

2. Rewrite the benchmark harness around explicit gold
   - stop parsing expected levels from names
   - compute:
     - exact-level hit rate
     - within-one-level hit rate
     - score-band MAE
     - rank displacement
     - Kendall correlation with gold order
     - pairwise order agreement
     - run-to-run variance
     - model usage ratio
     - cost
     - latency

3. Add repeated-run stability measurement
   - each benchmark mode should run `N` times
   - report per-student variance and whole-cohort variance

4. Emit a single benchmark report schema
   - `benchmark_report.json`
   - `benchmark_report.md`

5. Wire benchmark outputs into the gates
   - publish gate should read benchmark summaries
   - sota gate should compare current candidate against baseline/mainline

Acceptance criteria
- no benchmark logic depends on filename conventions
- benchmark report supports release gating
- benchmark runs are portable across environments

Test plan
- fixture datasets with explicit gold
- malformed gold schema tests
- repeated-run stability tests
- portability tests removing machine-specific PATH assumptions

Exit condition
- benchmark results are credible enough to arbitrate model and prompt changes

### Phase 3: Promote Consistency Checks Into A Global Reranker

Goal
- replace greedy local swaps with a globally coherent reranking stage

Primary files
- `scripts/aggregate_assessments.py`
- `scripts/verify_consistency.py`
- new `scripts/global_rerank.py`
- `scripts/review_and_grade.py`
- `scripts/build_dashboard_data.py`

Build tasks

1. Split seed ranking from final ranking
   - `aggregate_assessments.py` should continue producing the seed order
   - final order should become a separate downstream stage

2. Refactor `verify_consistency.py`
   - change its job from "apply swaps" to "collect pairwise evidence"
   - emit a normalized pairwise judgment artifact:
     - pair
     - seed order
     - decision
     - confidence
     - rationale
     - model metadata

3. Implement global reranker
   - consume:
     - seed score features
     - pairwise judgments
     - level band constraints
   - fit a globally optimized order
   - candidate methods:
     - Bradley-Terry
     - Elo-like latent score
     - regularized pairwise logistic optimization

4. Add hard constraints
   - preserve level ordering unless explicit evidence and rubric scores justify crossing a boundary
   - cap displacement for low-confidence rows
   - produce diagnostics for each movement

5. Emit rerank artifacts
   - `pairwise_matrix.json`
   - `rerank_scores.csv`
   - `final_order.csv`
   - `consistency_report.json`

6. Rewire grading and dashboard to use final order
   - prefer `final_order.csv`
   - fall back to `consistency_adjusted.csv`
   - then `consensus_scores.csv`

Acceptance criteria
- reranking is deterministic for the same evidence set
- no local oscillation across reruns
- final order is globally consistent with pairwise evidence and level locks

Test plan
- synthetic pairwise matrices with known optimum orders
- contradictory pairwise evidence tests
- level-lock monotonicity tests
- rerun determinism tests

Exit condition
- final ranking is produced by an explicit reranker, not adjacent patching

### Phase 4: Make Calibration Versioned And Enforce Scope Validity

Goal
- turn calibration from a useful helper into a release-quality contract

Primary files
- `server/bootstrap.py`
- `scripts/calibrate_assessors.py`
- `scripts/calibration_gate.py`
- `scripts/publish_gate.py`

Build tasks

1. Add calibration manifest
   - store alongside `calibration_bias.json`
   - include:
     - source exemplar set hash
     - model version
     - routing profile hash
     - rubric hash
     - scope coverage
     - generated time
     - freshness window

2. Tighten bootstrap semantics
   - bootstrap calibration remains allowed for development continuity
   - bootstrap profiles must be marked as synthetic
   - release gates must reject synthetic-only calibration for production scope

3. Expand scope resolution
   - make scope explicit in every run manifest
   - include:
     - grade band
     - genre
     - rubric family
     - model family

4. Add calibration drift policy
   - calibration must be rerun when:
     - model changes
     - rubric family changes
     - genre changes
     - grade band changes
     - exemplar bank changes materially

5. Strengthen assessor profile metrics
   - continue existing metrics
   - add:
     - boundary-specific MAE
     - rank stability under repeat runs
     - pairwise disagreement concentration near boundaries

Acceptance criteria
- every run can identify the exact calibration profile used
- scope mismatch is a hard failure for release candidates
- bootstrap-neutral profiles cannot masquerade as production calibration

Test plan
- stale calibration rejection
- synthetic calibration rejection for release mode
- scope mismatch rejection
- manifest-integrity tests

Exit condition
- calibration becomes versioned runtime state, not an opaque side artifact

### Phase 5: Upgrade Gates Into Release Contracts

Goal
- define clear dev, candidate, and release quality bars

Primary files
- `scripts/publish_gate.py`
- `scripts/sota_gate.py`
- `config/accuracy_gate.json`
- `config/sota_gate.json`

Build tasks

1. Split gate profiles
   - `dev`
   - `candidate`
   - `release`

2. Add benchmark-aware thresholds
   - exact-level hit
   - within-one-level hit
   - score-band MAE
   - pairwise agreement
   - stability SD across repeated runs

3. Add reproducibility thresholds
   - manifest-identical reruns must match exactly, or within defined tolerances for intermediate stochastic traces if any remain

4. Add calibration freshness thresholds
   - reject stale or under-scoped calibration

5. Add cost and latency thresholds
   - require candidates to stay within budget envelopes

6. Emit decision-ready reports
   - JSON for machines
   - Markdown for humans

Acceptance criteria
- the gates can decide if a build is development-only, candidate-ready, or release-ready
- gate results explain failure causes precisely enough to drive remediation

Test plan
- threshold boundary fixtures
- missing benchmark fixture tests
- stale calibration fixture tests
- reproducibility mismatch fixture tests

Exit condition
- "SOTA" is a gate state, not a claim in prose

### Phase 6: Turn Teacher Review Into Learning Signal

Goal
- capture teacher corrections as reusable structured data and replay candidates

Primary files
- `scripts/build_dashboard_data.py`
- `server/projects.py`
- `ui/app.js`
- new review persistence layer under `server/data/`

Build tasks

1. Persist structured review actions
   - level overrides
   - rank corrections
   - pairwise adjudications
   - comments on evidence quality

2. Version review feedback
   - attach every review to:
     - pipeline manifest
     - calibration manifest
     - final artifact set

3. Feed review data back into:
   - benchmark gold sets
   - boundary challenge sets
   - calibration exemplar banks

4. Surface uncertainty in the UI
   - boundary cases
   - high-disagreement cases
   - low-confidence rerank moves

Acceptance criteria
- teacher decisions become structured data, not just one-off UI adjustments
- adjudicated decisions can be replayed into evals and calibration refreshes

Test plan
- override persistence tests
- replay tests into benchmark fixtures
- migration tests for prior artifacts

Exit condition
- the system can persist, version, and replay real review traffic for future improvement cycles

### Phase 7: Finalized Review Promotion And Local Preference Prior

Goal
- separate exploratory review from committed learning
- consume teacher preference as a subtle runtime prior without destabilizing ranking quality

Primary files
- `server/review_store.py`
- `server/projects.py`
- `ui/app.js`
- `scripts/global_rerank.py`
- `scripts/build_dashboard_data.py`
- new `scripts/local_teacher_prior.py`

Build tasks

1. Split review persistence into draft and final states
   - save interactive UI state as draft only
   - write final review artifacts only on explicit finalize or publish

2. Capture the starting machine proposal for each review session
   - store the source rank artifact hash and review session metadata
   - preserve the exact machine order the teacher started from

3. Derive learning signal only from final landing spots
   - compute net level overrides
   - compute material rank displacements
   - compute implied pairwise inversions
   - compute changed boundary decisions

4. Build a scoped local teacher prior
   - scope by teacher or project, grade band, genre, rubric family, and model family
   - require minimum support before activation
   - decay stale or weakly-supported preferences toward zero

5. Integrate the local prior into runtime reranking
   - gate it by uncertainty
   - cap displacement from teacher prior alone
   - forbid level-band crossing from preference alone

6. Keep reason capture sparse
   - default to passive learning from finalized deltas
   - use optional one-click reason chips only for unusually informative cases

Acceptance criteria
- intermediate sorting does not create learning records
- finalized reviews produce deterministic delta artifacts
- local priors only affect ambiguous cases within narrow bounds
- repeated finalized patterns subtly improve local ordering without degrading benchmark accuracy

Test plan
- draft-versus-final persistence tests
- final-delta extraction tests
- local-prior activation threshold tests
- uncertainty-gated rerank tests
- no-effect-on-clear-cases regression tests

Exit condition
- the runtime learns only from finalized teacher judgment, and only in bounded ambiguous regions

### Phase 8: Aggregate Review Learning And Governance

Goal
- turn many teachers' finalized feedback into safe, governed product improvement

Primary files
- `server/review_store.py`
- `server/projects.py`
- `bench/`
- `inputs/exemplars/`
- new aggregate-learning ingestion and promotion scripts

Build tasks

1. Define aggregate-learning eligibility rules
   - finalized reviews only
   - anonymized records only
   - opt-in or policy-compliant collection only

2. Normalize teacher reasons
   - derive a small controlled vocabulary from structured tags and passive signals
   - keep free-text comments as secondary evidence, not direct weights

3. Add secure upload and ingestion
   - package anonymized eligible feedback
   - transport it to the product-improvement pipeline
   - track provenance and retention

4. Add promotion workflow for official assets
   - benchmark gold candidates
   - boundary challenge candidates
   - calibration exemplar candidates
   - require human adjudication before promotion

5. Add privacy and data-governance controls
   - retention windows
   - deletion semantics
   - audit trail for promoted data

Acceptance criteria
- global product learning consumes only anonymized finalized data
- promoted benchmark and calibration assets have provenance and human sign-off
- the repo can distinguish local personalization from product-wide learning

Test plan
- anonymization integrity tests
- finalized-only export tests
- promotion-workflow fixture tests
- retention and deletion tests

Exit condition
- cross-teacher learning is explainable, governed, and safe to use

### Phase 9: Production Hardening And Launch Contract

Goal
- make the system operable, supportable, and safe enough to launch

Primary files
- `server/app.py`
- `server/pipeline_queue.py`
- `server/projects.py`
- `config/*gate*.json`
- operational docs under `docs/`

Build tasks

1. Define production auth and isolation rules
   - teacher identity
   - project ownership
   - tenant and artifact isolation

2. Add operational observability
   - queue depth
   - job latency
   - cache-hit correctness checks
   - gate failure summaries

3. Add data and incident controls
   - retention and deletion policy
   - rollback paths for model or prompt regressions
   - incident response notes for bad releases

4. Add launch-performance validation
   - load and concurrency tests
   - large-class run tests
   - degraded-mode behavior tests

5. Freeze the production launch contract
   - required gate profiles
   - required benchmark coverage
   - required calibration freshness
   - required privacy posture

Acceptance criteria
- launch readiness is defined by documented operational and release contracts
- the service can fail safely and recover predictably
- release approval does not depend on implicit tribal knowledge

Test plan
- queue concurrency tests
- large-cohort smoke tests
- rollback and incident-runbook drills
- production config validation tests

Exit condition
- the product is technically launchable, supportable, and governable

## Sequencing

The remaining production-readiness order is:

1. Phase 7: finalized review promotion and local preference prior
2. Phase 8: aggregate review learning and governance
3. Phase 9: production hardening and launch contract

Why this order:
- Phase 7 is required before teacher feedback can safely affect runtime behavior
- Phase 8 is required before product-wide learning can use real review traffic
- Phase 9 is required before any of the above can be launched as a real product

## Immediate Next Sprint

The next sprint should start the finalized-review boundary.

### Sprint Goal

Let teachers sort and resort freely, but only let finalized landing spots become learning signal.

### Sprint Scope

1. Add review session IDs and persist draft state separately from final state
2. Store the source machine-order artifact hash at session start
3. Add explicit finalize action in the review API and UI
4. Derive `review_delta.json` from machine order versus finalized teacher order
5. Make `local_learning_profile.json` depend on finalized reviews only
6. Expose delta summaries in dashboard data for auditability

### Sprint Deliverables

- separate draft and final review artifacts
- explicit finalized-review delta artifact
- finalized-only local learning profile
- updated review API and UI state flow
- tests proving intermediate edits do not become learning data

### Sprint Exit Criteria

- a teacher can sort repeatedly without generating learning records
- finalize produces a deterministic net-delta artifact
- only finalized reviews contribute to local learning summaries

## Engineering Rules While Executing This Plan

1. Prefer additive evolution over replacement
   - preserve the current script boundaries where possible
2. Keep artifacts inspectable
   - every new stage should emit a readable JSON or CSV artifact
3. Gate before declare
   - no "SOTA" claim without passing benchmark and release gates
4. Bias toward determinism
   - if a component can be deterministic, make it deterministic
5. Make recovery easy
   - every stage should fail loudly and specifically

## Context Recovery Protocol

If work resumes after context compaction:

1. Open this file first
2. Confirm the current phase and current sprint scope
3. Read the latest git diff touching:
   - `server/`
   - `scripts/`
   - `config/*gate*.json`
   - `bench/`
4. Update the "Plan Status Ledger" below before making new architectural changes

## Plan Status Ledger

Use this section as the running status checkpoint.

### Current State

- Phase 1: completed
- Phase 2: completed
- Phase 3: completed
- Phase 4: completed
- Phase 5: completed
- Phase 6: completed
- Phase 7: pending
- Phase 8: pending
- Phase 9: pending

### Latest Confirmed Improvements

- level-aware bell-curve grading was added
- aggregation now prefers stable level-first ordering
- dashboard data prefers resolved ranking artifacts
- the step graph now includes non-interactive grade generation
- queued execution now owns the authoritative production path with manifest-keyed artifacts
- benchmark datasets now use explicit human gold and benchmark reports are gate-readable
- pairwise consistency checks now feed a deterministic global reranker with explicit final-order artifacts
- calibration now ships with a versioned manifest, explicit run scope, synthetic bootstrap marking, and drift-aware release checks
- publish and SOTA gates now evaluate explicit `dev`, `candidate`, and `release` contracts with benchmark, reproducibility, calibration freshness, and budget thresholds
- teacher review now persists as versioned structured data, emits replay artifacts for benchmark/boundary/calibration refresh, and produces both a local learning profile and an anonymized aggregate feedback log

### Outstanding Architectural Risks

- review persistence does not yet separate exploratory draft sorting from finalized learning signal
- local learning profiles are not yet consumed directly inside the scoring/reranking runtime
- aggregate review telemetry is not yet governed, transported, or promoted through a formal product-improvement workflow
- production auth, privacy, retention, and operational launch controls are not yet defined in the codebase

### Next Decision Point

Start Phase 7 by formalizing review draft versus final state, then derive finalized-only net deltas before wiring any teacher prior into runtime reranking.
