# SOTA Build Plan

Status
- State: active working plan
- Last updated: 2026-03-29
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

## Working Definition Of SOTA For This Repo

For this project, "SOTA" means five things at once:

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
  - adjacent-pair order checks
  - local swap application
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

## Current Gaps

These are the main blockers between the current scaffold and the target system.

### Gap 1: Split Execution Paths

The repo has two materially different execution paths:
- `POST /pipeline/run` runs directly against the repo workspace
- `POST /pipeline/v2/run` uses the queue

This creates risk in three ways:
- concurrent jobs can clobber each other
- the two paths can drift in behavior
- reproducibility is harder because the mutable repo root is part of runtime state

### Gap 2: Incomplete Cache Fingerprinting

The queue caches artifacts by a limited snapshot hash. Today that hash does not fully cover:
- prompts
- exemplar content
- calibration artifacts
- grade profiles
- all relevant config files
- code version

That means "same input essays" can incorrectly reuse stale artifacts after pipeline changes.

### Gap 3: Weak Evaluation Harness

The benchmark currently infers gold labels from filenames or display names. That is not strong enough for serious comparison, release gating, or model selection.

### Gap 4: Local Consistency Repair

`verify_consistency.py` applies greedy adjacent swaps. That helps with obvious inversions, but it does not solve the global ranking problem.

### Gap 5: Bootstrap Calibration Is Not Production Calibration

The neutral bootstrap profile is useful for continuity, but it is not valid evidence that a production run is calibrated for a given scope.

### Gap 6: Gates Are Useful But Not Yet Full Release Contracts

The gate scripts exist, but they are not yet backed by a sufficiently strong benchmark, reproducibility contract, or drift policy.

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
5. Teacher review becomes training signal
   - adjudications and overrides feed back into calibration and evals

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

## Build Strategy

The build is divided into six phases. The order matters.

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
- use teacher corrections to improve future runs

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
- the system can improve from real review traffic

## Sequencing

The correct order is:

1. Phase 1: execution unification and reproducibility
2. Phase 2: benchmark replacement
3. Phase 3: global reranker
4. Phase 4: calibration versioning
5. Phase 5: release-gate hardening
6. Phase 6: teacher feedback ingestion

Why this order:
- Phase 1 is required to make any benchmark or gate results trustworthy
- Phase 2 is required before claiming improvement
- Phase 3 improves ranking quality but depends on reliable artifacts
- Phase 4 and 5 turn the improved system into a controlled release process
- Phase 6 closes the long-term quality loop

## Immediate Next Sprint

The next sprint should complete the minimum viable foundation.

### Sprint Goal

Make the pipeline isolated, reproducible, and benchmarkable enough that future improvements can be measured honestly.

### Sprint Scope

1. Unify `/pipeline/run` onto the queue-backed engine
2. Add isolated per-job workspaces
3. Add `pipeline_manifest.json`
4. Expand cache hashing to prompts, exemplars, calibration, config, and code version
5. Define the explicit benchmark gold schema
6. Refactor `verify_consistency.py` so it can emit pairwise evidence without mutating order

### Sprint Deliverables

- queue-backed authoritative execution path
- manifest-aware artifact cache
- benchmark schema committed in `bench/`
- pairwise evidence artifact design
- updated tests covering all of the above

### Sprint Exit Criteria

- a manifest-identical job rerun is byte-stable
- changing prompts or exemplars invalidates cache
- benchmark fixtures no longer rely on filename labels
- pairwise evidence can be generated independently of local swap application

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
- Phase 5: not started
- Phase 6: not started

### Latest Confirmed Improvements

- level-aware bell-curve grading was added
- aggregation now prefers stable level-first ordering
- dashboard data prefers resolved ranking artifacts
- the step graph now includes non-interactive grade generation
- queued execution now owns the authoritative production path with manifest-keyed artifacts
- benchmark datasets now use explicit human gold and benchmark reports are gate-readable
- pairwise consistency checks now feed a deterministic global reranker with explicit final-order artifacts
- calibration now ships with a versioned manifest, explicit run scope, synthetic bootstrap marking, and drift-aware release checks

### Outstanding Architectural Risks

- cache key coverage is still incomplete
- release-gate policy still needs Phase 5 profile tightening across dev, candidate, and release modes
- teacher adjudications are not yet feeding back into calibration and eval refresh

### Next Decision Point

Start Phase 5 by promoting publish and SOTA gates into explicit release contracts with stronger benchmark, reproducibility, and stability thresholds.
