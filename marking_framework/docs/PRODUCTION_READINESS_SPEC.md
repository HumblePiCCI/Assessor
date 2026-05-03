# Production Readiness Spec

Status: execution spec for the path from controlled teacher pilot to production service.

Last updated: 2026-05-02

Branch context: `codex/runtime-provider-switch`

## Current State

The repository is no longer just an offline marking workspace. It now has a
queue-backed runtime, a browser review UI, runtime/provider profiles, a
teacher-review fast path, and a retained full-validation path.

Implemented foundations:

- `server/step_runner.py`
  - `teacher_review`: 10-step low-latency path through dashboard build.
  - `full_validation`: 22-step audit path through boundary, pairwise
    consistency, routed escalation, committee-edge resolution, rerank, eval,
    gates, confidence, grade, and dashboard.
- `server/pipeline_queue.py`
  - isolated job workspaces under `server/data/workspaces/`
  - job status and event history in `server/data/pipeline_jobs.sqlite3`
  - manifest hashing, runtime profile materialization, cache lookup, recovery,
    rubric confirmation, anchor pause/resume, artifact publishing
- `server/app.py`
  - `/pipeline/v2/run`, `/pipeline/v2/jobs/*`, `/runtime/profiles`,
    `/projects/*`
- `config/runtime_profiles.json`
  - `internal_codex` for internal Codex OAuth testing
  - `teacher_payg_openai` for billable teacher API runs
  - disabled OpenAI-compatible adapter profiles
- `scripts/run_llm_assessors.py`
  - bounded Pass 1 concurrency via `--parallelism` or
    `ASSESSOR_PARALLELISM`
- `ui/app.js`
  - browser submissions default to `pipeline_profile=teacher_review`
  - rubric confirmation, anchor scoring, draft/final review state, runtime
    profile selection
- `docs/TEACHER_PILOT_RUNBOOK.md`
  - controlled pilot boundary and stop rules
- `docs/LIVE_COHORT_RUNTIME.md`
  - current live-cohort runtime contract
- `docs/PAYG_MODE.md`
  - cost-plus billing contract

The current product posture is: suitable for internal testing and controlled
teacher pilot preparation, not production launch.

## Production Definition

Production-ready means a teacher can sign in, link a classroom assignment, let
the service begin work as submissions arrive, receive a review-ready dashboard
within the target latency, edit/anchor/override while deeper validation runs,
and trust that final promoted results consume the latest teacher input before
they are presented as final.

Production-ready also means:

- teacher and student data are isolated by tenant/project
- Google OAuth scopes are minimized and verified
- billing is exact API cost plus configured margin, with no unpriced usage
- queue jobs survive restarts and duplicate events
- background audit cannot overwrite newer teacher input
- provider routing is observable and swappable
- teacher authority is explicit in the ranking contract
- launch gates are automated and reproducible

Target latency:

- first review-ready dashboard for a class of 30: under 5 minutes
- Classroom-linked incremental path: most student-local work starts before the
  final class submission arrives
- full validation may finish later, but it must run in the background and
  promote only against the latest human revision

## Target Architecture

```text
Google Classroom / Drive
  -> Classroom link record
  -> Pub/Sub submission events
  -> idempotent submission ingest
  -> per-submission analysis cache
  -> incremental cohort order
  -> teacher_review dashboard
  -> teacher human_revision stream
  -> revision-aware full_validation audit
  -> final promotion only when audit_revision_id == latest_human_revision_id
```

Authority order:

1. explicit teacher rubric edits and assignment-scope clarifications
2. teacher anchor scores and teacher-confirmed calibration packets
3. teacher pairwise corrections and protected human edges
4. teacher student flags such as incomplete, off-prompt, wrong genre, or
   accommodation notes
5. committee-edge protected decisions
6. full-validation model evidence
7. fast teacher-review consensus evidence
8. deterministic fallback signals

No production path may silently demote teacher input below model evidence.

## External Platform Grounding

Google Classroom supports course-work change feeds delivered to Cloud Pub/Sub
and those feeds cover course work and student-submission creation or
modification. Registrations require the push-notifications scope and the scopes
needed to view the data being watched; registrations expire and must be
renewed. See:

- https://developers.google.com/workspace/classroom/best-practices/push-notifications
- https://developers.google.com/workspace/classroom/reference/rest
- https://developers.google.com/workspace/classroom/guides/classroom-api/manage-grades
- https://developers.google.com/workspace/guides/configure-oauth-consent

Relevant Classroom resources:

- `courses.courseWork.list/get`
- `courses.courseWork.studentSubmissions.list/get`
- `courses.courseWork.studentSubmissions.patch`
- `courses.courseWork.studentSubmissions.return`

Important product constraint: Classroom grading APIs exist, but this product
must not automatically publish grades during pilot or early production. Teacher
approval remains the explicit final action.

## Slice 1: Production State Model And Manifest Contract

Status: not implemented.

Goal: separate review-ready state, background-audit state, human revision
state, and final promotion state in durable data structures.

Why this exists: the current queue has job statuses and manifests, but it does
not yet model a run where a teacher is editing while a background audit is
still running.

Touched files/areas:

- `server/pipeline_queue.py`
- `server/data/pipeline_jobs.sqlite3` schema/migrations
- `server/projects.py`
- `server/review_store.py`
- `scripts/build_dashboard_data.py`
- `docs/LIVE_COHORT_RUNTIME.md`
- tests under `tests/test_pipeline_queue.py`, `tests/test_server_pipeline_v2.py`

Implementation:

- Add durable run phases:
  - `ingesting`
  - `analyzing_submissions`
  - `review_ready`
  - `background_validating`
  - `teacher_revision_pending`
  - `final_ready`
  - `finalized_by_teacher`
  - `failed`
- Add manifest fields:
  - `pipeline_profile`
  - `run_phase`
  - `human_revision_id`
  - `audit_revision_id`
  - `submission_snapshot_id`
  - `promotion_status`
  - `promotion_blockers`
- Add API response fields so UI can distinguish provisional, validating, final
  ready, and teacher-finalized states.
- Add migration-safe schema helper rather than ad hoc table edits.

Done criteria:

- Existing upload path still produces `teacher_review` dashboard.
- Dashboard labels itself as review-ready/provisional until promotion.
- A stale background audit cannot set `final_ready`.
- Tests prove manifest hash changes when `pipeline_profile`,
  `human_revision_id`, or `submission_snapshot_id` changes.

## Slice 2: Human Revision Ledger And Authority Layer

Status: partially implemented through review drafts/finalized reviews and
anchor scores; not production complete.

Goal: make teacher input a first-class, versioned signal consumed by every
downstream audit and rerank step.

Why this exists: teacher edits currently persist as review artifacts, but there
is no single authority ledger with invalidation semantics for background jobs.

Touched files/areas:

- `server/review_store.py`
- `server/projects.py`
- `server/pipeline_queue.py`
- `ui/app.js`
- `scripts/apply_anchor_calibration.py`
- `scripts/global_rerank.py`
- `scripts/committee_edge_resolver.py`
- `scripts/build_dashboard_data.py`

Implementation:

- Add `human_revisions` records with:
  - `revision_id`
  - `project_id`
  - `job_id`
  - `source`: `rubric`, `anchor`, `student_flag`, `pairwise`, `grade_curve`,
    `feedback`, `finalization`
  - `payload_hash`
  - `created_by`
  - `created_at`
  - `affected_students`
  - `affected_pairs`
  - `earliest_invalidated_step`
- Convert teacher pairwise choices into protected human edges:
  - `adjudication_source=teacher`
  - `protection_readiness=protect`
  - `supersedes_model_edges=true`
- Convert student flags into structured constraints:
  - `incomplete`
  - `off_prompt`
  - `wrong_assignment`
  - `needs_manual_review`
  - `accommodation_context`
- Keep draft edits separate from final teacher assertions:
  - draft edits update UI state only
  - applied anchors/pairwise/student flags create human revisions
  - finalization locks a final review version

Invalidation matrix:

- rubric edit: invalidate from `assess`
- assignment outline edit: invalidate from `assess`
- student text changed: invalidate that student's extraction and all downstream
  aggregate/audit steps
- student flag: invalidate that student, adjacent pairs, aggregate, rerank,
  grade, dashboard
- anchor score: invalidate from `aggregate_1`
- teacher pairwise edge: invalidate from `pairwise_escalation` or `rerank`
  depending on whether the pair has existing model evidence
- grade curve edit: invalidate `grade` and `dashboard` only
- feedback edit: invalidate feedback artifacts only

Done criteria:

- Every teacher action produces a monotonic `human_revision_id`.
- Background audit records the `human_revision_id` it consumed.
- Final promotion requires `audit_revision_id == latest_human_revision_id`.
- Tests prove teacher pairwise edges survive model rerank unless explicit graph
  safety blocks them and reports the block.

## Slice 3: Background Full-Validation Promotion

Status: not implemented.

Goal: automatically launch `full_validation` after `teacher_review`, run it in
the background, and promote results only if they consume the latest teacher
revision.

Why this exists: the current fast path solves teacher wait time, but final
accuracy depends on the full audit path continuing behind the scenes.

Touched files/areas:

- `server/pipeline_queue.py`
- `server/step_runner.py`
- `ui/progress_stream.js`
- `ui/app.js`
- `scripts/build_dashboard_data.py`
- tests under `tests/test_pipeline_queue.py`

Implementation:

- Add a child background job type:
  - `parent_job_id`
  - `background_profile=full_validation`
  - `base_manifest_hash`
  - `consumed_human_revision_id`
- Start background audit after `teacher_review` publishes, unless disabled by
  project policy.
- If a teacher revision arrives:
  - mark current background job `stale` when it is past the affected step
  - resume or restart from the earliest invalidated step
  - preserve logs and artifacts for auditability
- Add promotion checks:
  - latest human revision consumed
  - no required gate failed
  - no stale submission units
  - no unpriced billable usage
  - dashboard generated from promoted order

Done criteria:

- UI can show "Review ready; full audit running."
- UI can show "Teacher change queued; audit restarting from rerank."
- A stale audit completion cannot overwrite dashboard state.
- Tests simulate teacher input while background audit runs and prove final
  promotion waits for the revised audit.

## Slice 4: Incremental Submission Analysis Cache

Status: not implemented.

Goal: process each submission as soon as it is available and reuse that work
when the full class set is complete.

Why this exists: a class-of-30 batch run should not start all extraction and
Pass 1 calls after the last student turns in work.

Touched files/areas:

- new `server/submission_units.py`
- `server/pipeline_queue.py`
- `scripts/extract_text.py`
- `scripts/conventions_scan.py`
- `scripts/run_llm_assessors.py`
- `scripts/aggregate_assessments.py`
- `scripts/build_dashboard_data.py`
- `server/data/` schema

Implementation:

- Add `submission_units`:
  - `submission_unit_id`
  - `tenant_id`
  - `project_id`
  - `classroom_course_id`
  - `classroom_coursework_id`
  - `classroom_submission_id`
  - `student_pseudonym`
  - `attachment_fingerprint`
  - `text_hash`
  - `rubric_contract_hash`
  - `analysis_status`
  - `latest_analysis_artifact_dir`
- Add per-submission artifacts:
  - extracted text
  - conventions report row
  - Pass 1 assessor JSON by assessor
  - draft-quality signals
  - usage/cost rows
- Make `aggregate_1` able to consume a partial cohort and recompute when new
  units arrive.
- Make `teacher_review` use cached per-submission artifacts and only run
  missing/stale units.

Done criteria:

- Turning in one new paper triggers only that paper's extraction/conventions/
  Pass 1 work.
- Re-running a 30-paper class after one edited submission reuses the other 29
  students' analysis.
- Tests prove artifact cache keys include text hash, rubric hash, routing hash,
  and provider model.

## Slice 5: Google Sign-In, Classroom Link, And OAuth Scope Boundary

Status: not implemented.

Goal: let teachers sign in with Google, select a course and assignment, and
link it to a project.

Why this exists: production workflow should start from the teacher's real
assignment system, not a manual file upload.

Touched files/areas:

- new `server/google_auth.py`
- new `server/classroom.py`
- new `server/data/classroom_links` or DB tables
- `server/app.py`
- `server/projects.py`
- `ui/app.js`
- `ui/index.html`
- docs: `LEGAL_NOTES.md`, `TEACHER_PILOT_RUNBOOK.md`

Implementation:

- Configure Google OAuth consent and minimal scopes.
- Store encrypted refresh tokens per teacher/tenant.
- Add APIs:
  - `GET /google/auth/start`
  - `GET /google/auth/callback`
  - `GET /classroom/courses`
  - `GET /classroom/courses/{course_id}/coursework`
  - `POST /classroom/link`
  - `DELETE /classroom/link/{link_id}`
- Store:
  - course id/name
  - coursework id/title
  - teacher owner
  - linked project id
  - selected rubric source
  - registration state
- Show link state in UI.

Done criteria:

- Teacher can sign in and link one assignment.
- Service can list submissions for that assignment.
- Revoking Google access disables ingestion and marks the link disconnected.
- No Drive/Classroom scope is requested unless required for this workflow.

## Slice 6: Classroom Event Ingestion And Reconciliation

Status: not implemented.

Goal: receive Classroom submission-change notifications, fetch changed
submissions, and enqueue incremental analysis idempotently.

Why this exists: push notifications are hints, not durable full state. The
service needs both event handling and periodic reconciliation.

Touched files/areas:

- new `server/classroom_events.py`
- new `server/pubsub_handler.py`
- `server/classroom.py`
- `server/pipeline_queue.py`
- deployment config for Pub/Sub/webhook
- tests for duplicate/out-of-order events

Implementation:

- Create one Pub/Sub topic/subscription for Classroom events.
- Register course-work change feeds for linked assignments.
- Renew registrations before expiry.
- On event:
  - validate registration
  - extract `courseId`, `courseWorkId`, `submissionId`
  - fetch `studentSubmissions.get`
  - fetch attachment metadata/content
  - update `submission_units`
  - enqueue stale/missing analysis
- Add reconciliation job:
  - periodically call `studentSubmissions.list`
  - detect missed events
  - update turned-in/reclaimed/returned states

Done criteria:

- Duplicate events do not duplicate model calls.
- Missed events are recovered by reconciliation.
- A reclaimed or edited submission marks prior analysis stale.
- Event ingestion tests cover created, modified, duplicate, out-of-order, and
  revoked-access cases.

## Slice 7: Incremental Scheduler And Priority Queue

Status: not implemented.

Goal: schedule work by educational impact and teacher attention, not FIFO only.

Why this exists: once submissions and teacher edits arrive during the same
window, the system must prioritize the work that changes the teacher-visible
order.

Touched files/areas:

- `server/pipeline_queue.py`
- new `server/work_scheduler.py`
- `server/data/pipeline_jobs.sqlite3`
- `ui/progress_stream.js`

Implementation:

- Add work item types:
  - `submission_extract`
  - `submission_conventions`
  - `submission_pass1`
  - `cohort_aggregate`
  - `teacher_review_publish`
  - `background_validation`
  - `teacher_revision_revalidate`
  - `feedback_generation`
- Add priority tiers:
  1. teacher-touched students/pairs
  2. new submissions blocking review-ready state
  3. boundary neighbors and high-disagreement pairs
  4. background full-validation coverage
  5. optional feedback generation
- Add concurrency controls by provider/profile:
  - Codex OAuth internal: conservative worker count
  - OpenAI PAYG: higher bounded concurrency
  - disabled providers: cannot schedule

Done criteria:

- Teacher edits preempt background audit.
- New Classroom submissions do not starve teacher revision work.
- Provider concurrency limits are visible in job events.
- Load tests prove no duplicate calls for identical work keys.

## Slice 8: Product UI For Incremental Classroom Review

Status: partially implemented for upload-based review; Classroom and
background audit UX not implemented.

Goal: show teachers a live assignment dashboard that evolves from "collecting"
to "review ready" to "audit complete" to "teacher finalized."

Why this exists: teachers need trustable status, not a long spinner.

Touched files/areas:

- `ui/index.html`
- `ui/app.js`
- `ui/progress_stream.js`
- `server/app.py`
- `server/projects.py`
- `scripts/build_dashboard_data.py`

Implementation:

- Add Classroom link panel:
  - Google connection status
  - course selector
  - assignment selector
  - registration status
  - submission count by state
- Add analysis status:
  - submitted
  - analyzed
  - stale
  - needs teacher review
  - audit pending
  - final ready
- Add teacher input surfaces:
  - anchor paper scoring
  - pairwise correction
  - student flag
  - rubric clarification
  - curve/grade adjustment
- Add finalization surface:
  - "Review ready" vs "Final audit complete"
  - final promotion blockers
  - explicit teacher finalization

Done criteria:

- Teacher can see useful progress before full class submission.
- Teacher can start review before background audit finishes.
- Teacher input displays as pending/applied/stale/revalidated.
- Browser reload resumes the active linked assignment state.

## Slice 9: Billing, Cost Controls, And Customer Ledger

Status: partially implemented through runtime profiles and cost reports; not
production complete.

Goal: make teacher billing exact, auditable, and bounded.

Why this exists: `teacher_payg_openai` has cost-plus semantics, but production
needs customer invoices, payment state, refunds/failed jobs, and limits.

Touched files/areas:

- `config/pricing.json`
- `config/runtime_profiles.json`
- `scripts/usage_pricing.py`
- `server/pipeline_queue.py`
- new `server/billing.py`
- UI billing screens

Implementation:

- Add per-job customer cost ledger:
  - raw usage rows
  - priced rows
  - unpriced rows
  - markup
  - customer total
  - payment intent/invoice id
  - refunded/voided amount
- Block billable job completion when `unpriced_models` is non-empty.
- Add preflight estimate and teacher confirmation above a configured cost.
- Separate internal Codex OAuth jobs from billable customer runs.
- Keep usage tied to provider response ids where available.

Done criteria:

- No teacher can be charged for internal Codex OAuth usage.
- No teacher can be charged for unpriced usage.
- Failed jobs are not billed beyond explicitly accepted policy.
- A billing audit can reconstruct cost from `usage_log.jsonl` and pricing
  config version.

## Slice 10: Provider Abstraction Beyond OpenAI-Compatible Adapters

Status: adapter profiles exist but are disabled; native Anthropic/open-source
providers are not implemented.

Goal: make provider routing a real product boundary, not config-only.

Why this exists: the product should support OpenAI, Anthropic, and self-hosted
models while preserving output contracts and cost accounting.

Touched files/areas:

- `scripts/openai_client.py`
- `config/runtime_profiles.json`
- `config/llm_routing.json`
- `config/pricing.json`
- tests for structured output compatibility

Implementation:

- Create provider interface:
  - `responses_create`
  - structured JSON mode support
  - usage extraction
  - timeout/retry policy
  - streaming events
  - provider request id
- Add native Anthropic client or require an OpenAI-compatible adapter with
  explicit feature checks.
- Add local/open-source provider profile with:
  - endpoint health check
  - structured output validation
  - pricing or non-billable policy
- Add provider benchmark pack before enabling for teachers.

Done criteria:

- Provider profile cannot be enabled unless all routed tasks pass contract
  tests.
- Usage/cost reporting is provider-specific and auditable.
- Hard-pair and broad-corpus gates run per provider before teacher release.

## Slice 11: Accuracy Gates And Continuous Validation

Status: many scripts exist; production automation is incomplete.

Goal: make accuracy evidence reproducible for every release and provider
change.

Why this exists: recent work showed hard-pair and source-family regressions can
hide until targeted validation runs.

Touched files/areas:

- `scripts/evaluate_pairwise_adjudicator.py`
- `scripts/publish_gate.py`
- `scripts/sota_gate.py`
- `bench/`
- `docs/reports/`
- CI config

Implementation:

- Define release gate suites:
  - Ghost hard pairs
  - speech
  - persuasive letter
  - summary report
  - instructions
  - NAEP/UK STA/source-family cases
  - broad external corpus
- Add command wrappers that produce timestamped packets.
- Store gate summaries in `docs/reports/` or release artifacts.
- Require provider-specific gate packets before enabling a profile.

Done criteria:

- `teacher_review` and `full_validation` both have explicit accuracy gates.
- Full validation cannot regress protected human/committee edges silently.
- A release candidate has a single reproducible validation command and packet.

## Slice 12: Performance SLO Harness

Status: not implemented.

Goal: prove the service meets the under-5-minute teacher-review target for a
class of 30 under production-like conditions.

Why this exists: unit tests prove behavior, not wall-clock viability.

Touched files/areas:

- new `scripts/benchmark_runtime_slo.py`
- `server/pipeline_queue.py`
- `scripts/run_llm_assessors.py`
- `docs/reports/`
- CI or nightly automation

Implementation:

- Build benchmark scenarios:
  - cold upload, 30 submissions
  - Classroom incremental trickle, 30 submissions
  - one edited submission after analysis
  - teacher anchor added during background audit
  - provider timeout/retry case
- Capture:
  - time to first review-ready dashboard
  - time to full validation
  - model call count
  - cache hit rate
  - cost
  - failure/retry counts
- Add SLO gates:
  - p50/p95 review-ready latency
  - no duplicate model calls for cached submissions
  - retry rate threshold

Done criteria:

- A class-of-30 teacher-review run is measured under 5 minutes on the chosen
  production provider path.
- Incremental Classroom path shows most work completed before final submission
  when submissions arrive over time.
- Performance report is checked into `docs/reports/` for release candidates.

## Slice 13: Privacy, Security, And Compliance Boundary

Status: only high-level `docs/LEGAL_NOTES.md` exists.

Goal: make student-data handling, retention, consent, and access control
production-grade.

Why this exists: this product processes student work and teacher judgments.
Legal/policy review is required before production use.

Touched files/areas:

- `server/runtime_context.py`
- `server/projects.py`
- `server/review_store.py`
- `server/data/` storage
- `docs/LEGAL_NOTES.md`
- deployment secrets/config

Implementation:

- Replace local-dev identity defaults for production.
- Enforce tenant/project access on every API route and artifact load.
- Encrypt:
  - Google refresh tokens
  - provider API keys if teacher-owned keys are stored
  - retained student artifacts at rest in production storage
- Add retention policy:
  - raw submissions
  - extracted text
  - model prompts/responses
  - review state
  - anonymized aggregate learning
- Add export/delete:
  - teacher data export
  - project deletion
  - student artifact deletion
- Add policy docs:
  - human-in-loop educational decision boundary
  - no automatic grade publication
  - school approval/consent requirements
  - data processing and subprocessors

Done criteria:

- Production mode refuses unauthenticated access.
- Tenant A cannot read Tenant B jobs/projects/artifacts.
- Retention prune has dry-run and live modes with audit logs.
- Legal notes are expanded into launch-blocking policy checklist reviewed by
  counsel or school authority.

## Slice 14: Deployment, Operations, And Recovery

Status: local FastAPI service works; production deployment is not implemented.

Goal: run the service reliably outside a local laptop.

Why this exists: long-running jobs, Pub/Sub events, background validation, and
teacher sessions need durable infrastructure.

Touched files/areas:

- deployment manifests
- `server/pipeline_queue.py`
- new worker process entrypoints
- data store config
- logs/metrics config

Implementation:

- Separate web and worker processes.
- Move from local SQLite/filesystem to production-backed storage or explicitly
  supported single-node deployment with backups.
- Add health endpoints:
  - web health
  - worker health
  - provider health
  - Classroom registration health
  - billing health
- Add restart recovery:
  - queued jobs resume
  - running work items reconcile
  - stale locks expire safely
  - background audit state restored
- Add structured logs and metrics:
  - job id
  - tenant id
  - project id
  - provider
  - model
  - work item type
  - latency
  - cost

Done criteria:

- Server restart does not lose linked assignment state.
- Worker restart does not duplicate expensive model calls.
- Operators can identify slow, stale, failed, and blocked jobs from logs.
- Backup/restore has been rehearsed.

## Slice 15: Teacher Pilot To Production Rollout

Status: pilot runbook exists; production rollout plan is incomplete.

Goal: move from controlled pilot to limited production with explicit gates.

Why this exists: teacher trust, accuracy, latency, billing, and privacy must be
validated with real classroom workflows before broad release.

Touched files/areas:

- `docs/TEACHER_PILOT_RUNBOOK.md`
- `docs/PRODUCTION_READINESS_SPEC.md`
- `docs/reports/`
- `scripts/validate_production_launch.py`

Implementation:

- Pilot phase 1:
  - 2-4 teachers
  - manual upload or Classroom read-only link
  - no grade publication
  - operator supervised
- Pilot phase 2:
  - Classroom incremental intake enabled
  - background validation enabled
  - PAYG billing dry-run or capped live billing
- Limited production:
  - Google OAuth verified
  - billing live
  - data retention live
  - support/incident process live
  - launch validator green
- Add `scripts/validate_production_launch.py` checks for:
  - auth strict mode
  - Google OAuth config
  - billing config
  - retention policy
  - latest validation packet
  - latest SLO packet
  - no disabled-but-selected provider profiles

Done criteria:

- Launch validator fails closed when any production requirement is missing.
- Teacher pilot evidence is summarized in a release packet.
- Product copy says "teacher review assistant" and does not imply autonomous
  grading authority.

## Recommended Slice Order

1. Production state model and manifest contract.
2. Human revision ledger and authority layer.
3. Background full-validation promotion.
4. Incremental submission analysis cache.
5. Performance SLO harness for upload-based runs.
6. Google sign-in and Classroom link.
7. Classroom event ingestion and reconciliation.
8. Incremental scheduler and priority queue.
9. Classroom review UI.
10. Billing ledger and cost controls.
11. Privacy/security/compliance hardening.
12. Provider abstraction and provider-specific gates.
13. Continuous validation automation.
14. Production deployment and recovery.
15. Pilot-to-production launch validator and rollout packet.

The immediate next engineering slice should be Slice 1 plus the minimal part of
Slice 2 needed to prevent stale background audit promotion. That gives the fast
teacher-review path a safe finalization story before Classroom integration
adds more event sources.

## Production Blockers

Do not call this production-ready until these are true:

- `teacher_review` result is explicitly provisional until final promotion.
- `full_validation` runs in background and cannot overwrite newer teacher
  revisions.
- Teacher pairwise and anchor input are protected human evidence.
- Classroom-linked submission changes are idempotent and reconciled.
- Class-of-30 review-ready SLO is measured under 5 minutes on the production
  provider path.
- PAYG billing blocks unpriced usage and separates internal Codex OAuth runs.
- Tenant isolation is enforced in production mode.
- Data retention, deletion, and policy docs are launch-ready.
- Release validation packets cover the known hard-pair/source-family failure
  modes.
- Teachers retain explicit final authority before grade publication.
