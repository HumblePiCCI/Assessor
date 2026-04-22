# Live Cohort Runtime

Status
- Branch target: `main`
- Scope: runtime behavior for unfamiliar teacher cohorts after the benchmark-green release path

## What Landed

The live-cohort roadmap is now implemented as a real runtime flow, not just a planning artifact.

Core additions:
- deterministic scope grounding before extraction/scoring
- runtime cohort-confidence classification
- anchor-calibration pause/resume workflow
- live rerank stability metrics in `consistency_report.json`
- committee-consensus reporting from the existing multi-assessor panel
- routed pairwise escalation, evidence mapping, committee-edge resolution, and hard-pair eval before final grade/dashboard output
- engagement-gated aggregate-learning retention

## Runtime Outputs

The pipeline now emits these live-cohort artifacts when available:

- `outputs/scope_grounding.json`
- `outputs/cohort_confidence.json`
- `outputs/band_seam_report.json`
- `outputs/pairwise_escalation_candidates.json`
- `outputs/pairwise_escalations.json`
- `outputs/consistency_checks.escalated.json`
- `outputs/evidence_map.json`
- `outputs/evidence_neighborhood_report.json`
- `outputs/evidence_group_calibration_packets.json`
- `outputs/committee_edge_candidates.json`
- `outputs/committee_edge_report.json`
- `outputs/committee_edge_live_trace.json` when live committee reads are enabled
- `outputs/consistency_checks.committee_edge.json`
- `outputs/pairwise_adjudicator_eval.json`
- `outputs/anchor_candidates.json`
- `outputs/teacher_anchor_packet.json`
- `outputs/cohort_anchor_calibration.json`
- `outputs/committee_consensus_report.json`
- `outputs/engagement_signal.json`

These are surfaced into:
- `outputs/dashboard_data.json`
- the teacher UI
- review-store materialization

## Queue States

The job queue now supports more than a single fire-and-forget run.

Statuses:
- `queued`
- `running`
- `awaiting_rubric_confirmation`
- `awaiting_anchor_scores`
- `completed`
- `failed`

Anchor flow:
1. Full run completes normally through dashboard build.
2. `cohort_confidence.json` is inspected.
3. If blocking is enabled and the effective state is `anchor_calibration_required`, the queue:
   - stores a pre-anchor snapshot
   - syncs the provisional dashboard to the active project
   - pauses the job as `awaiting_anchor_scores`
4. Teacher submits anchor scores.
5. The queue applies `cohort_anchor_calibration.json`.
6. It reruns only:
   - `aggregate_1`
   - `boundary`
   - `aggregate_2`
   - `band_seam`
   - `consistency`
   - `pairwise_escalation`
   - `evidence_map`
   - `committee_edge_resolver`
   - `rerank`
   - `pairwise_eval`
   - `quality_gate`
   - `sota_gate`
   - `cohort_confidence`
   - `grade`
   - `dashboard`
7. The anchor patch is accepted only if pre/post hold-harmless checks pass.
8. Otherwise the pre-anchor snapshot is restored and the run finalizes with the reverted state.

The legacy manual `pairwise` review-prep step is intentionally skipped on anchor
resume. The canonical pairwise consistency, escalation, evidence-map,
committee-edge, rerank, and pairwise-eval seam still runs so the post-anchor
order and gates consume the same judgment path as a full run.

## Hold-Harmless Metrics

Live anchor acceptance uses the live-cohort metrics from `outputs/consistency_report.json`, not calibration-benchmark metrics.

Compared pre/post anchor:
- `swap_rate`
- `boundary_disagreement_concentration`
- top-5 overlap from `final_order.csv`

Current acceptance rule:
- swap rate must not increase
- boundary disagreement concentration must not increase
- top-5 overlap must preserve at least 4 of 5 students when both reruns have 5 ranked papers; smaller cohorts require full overlap

The queue persists:
- `anchor_state/pre_anchor_metrics.json`
- `anchor_state/post_anchor_metrics.json`

## Rerank Stability

`scripts/global_rerank.py` now exposes live stability features directly in `consistency_report.json`.

New summary fields:
- `swap_rate`
- `low_confidence_rate`
- `pairwise_conflict_density`
- `boundary_disagreement_concentration`
- `mean_stability_penalty`

New movement fields:
- `pairwise_conflict_density`
- `boundary_conflict_pairs`
- `stability_penalty`

The reranker now:
- extends the existing incident-weight displacement caps instead of replacing them
- scales effective support down for unstable rows
- bounds formerly unbounded `high_support` movement on noisy rows
- scales crossing margin with local stability penalty
- suppresses `local_teacher_prior` when `ANCHOR_CALIBRATION_ACTIVE=1`

## Scope Grounding

`scripts/scope_retrieval.py` is deterministic-first.

Inputs:
- class metadata
- rubric manifest
- normalized rubric criteria
- exemplar-bank families
- calibration manifest coverage
- local teacher prior
- cost limits

Outputs:
- nearest grounded hits
- accepted vs sparse vs novel familiarity
- suggested scope
- whether committee mode is recommended inside the remaining live budget

## Committee Reporting

`scripts/run_llm_assessors.py` now writes `outputs/committee_consensus_report.json`.

Current implementation:
- uses the existing multi-assessor panel as the committee surface
- summarizes pass1 rubric spread and pass2 rank spread per student
- records whether committee mode was recommended by scope grounding

This is the artifact base for later conditional repeated-run committee execution.

## Routed Committee-Edge Calibration

`scripts/committee_edge_resolver.py` is now the residual hard-edge seam after
pairwise escalation and evidence mapping.

Default behavior:
- model-free
- writes `outputs/committee_edge_candidates.json`,
  `outputs/committee_edge_report.json`, and
  `outputs/consistency_checks.committee_edge.json`
- preserves passthrough behavior when no committee decisions are supplied

Live behavior:
- opt-in with `--live`, `--committee-edge-live`, or `COMMITTEE_EDGE_LIVE=1`
- uses `config/llm_routing.json` task `literary_committee`
- current default model for that route is `gpt-5.4-mini`
- records A/B/C/group read traces in `outputs/committee_edge_live_trace.json`

Guardrails:
- committee-edge decisions have source precedence over escalated and cheap
  pairwise judgments for the same pair
- group calibration edge decisions must pass structured ledger validation before
  emitting overrides
- routed caution edges require caution-specific substantive validation, including
  side-aware mechanics blocker proof when mechanics is decisive
- rejected explicit group edges cannot re-enter through broad group-order support

## Review Learning

`server/review_store.py` now integrates the engagement gate before writing governed aggregate-learning records.

Behavior:
- every finalized review writes `outputs/engagement_signal.json`
- aggregate-learning promotion only occurs when:
  - review is final
  - collection policy allows it
  - engagement passes the gate
- local review history, local teacher prior, and replay exports still persist regardless

Current retained states:
- `discarded`
- `local_only`
- `aggregate_candidate`

## API Surface

New pipeline endpoints:
- `GET /pipeline/v2/jobs/{job_id}/anchors`
- `POST /pipeline/v2/jobs/{job_id}/anchors`

Existing rubric-confirmation flow remains:
- `GET /pipeline/v2/jobs/{job_id}/rubric`
- `POST /pipeline/v2/jobs/{job_id}/rubric`

## UI Behavior

The teacher UI now:
- surfaces rubric confirmation when needed
- surfaces anchor calibration when needed
- shows the machine’s chosen anchor papers
- lets the teacher enter only:
  - anchor level
  - optional anchor mark
- resumes the run and reloads the calibrated dashboard automatically

The control surface is intentionally narrow:
- no free-form calibration UI
- no manual rerun-step selection
- no duplicate gate decisions exposed to the teacher

## Test Coverage

Focused regression coverage now exists for:
- step graph and anchor resume step set
- rerank stability metrics and anchor-prior suppression
- dashboard surfacing of live runtime artifacts
- queue pause/resume through anchor calibration
- review-store engagement gating
- scope retrieval
- cohort confidence
- anchor calibration patch building
- engagement gate behavior

Recommended command:

```bash
./.venv/bin/pytest --no-cov -q \
  marking_framework/tests/test_step_runner.py \
  marking_framework/tests/test_global_rerank.py \
  marking_framework/tests/test_build_dashboard_data.py \
  marking_framework/tests/test_pipeline_queue.py \
  marking_framework/tests/test_review_store.py \
  marking_framework/tests/test_scope_retrieval.py \
  marking_framework/tests/test_cohort_confidence.py \
  marking_framework/tests/test_apply_anchor_calibration.py \
  marking_framework/tests/test_engagement_gate.py
```
