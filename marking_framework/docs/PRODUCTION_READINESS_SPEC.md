# Production Readiness Spec

Status: execution spec for the path from controlled teacher pilot to production service.

Last updated: 2026-05-03

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
- https://developers.google.com/workspace/classroom/rubrics/limitations
- https://developers.google.com/workspace/classroom/guides/key-concepts/user-eligibility
- https://developers.google.com/workspace/classroom/guides/key-concepts/admin-actions
- https://developers.google.com/workspace/classroom/sis-integrations/validate-your-SIS
- https://developers.google.com/workspace/classroom/troubleshooting/error-structure
- https://help.openai.com/en/articles/8313397-how-can-chatgpt-be-used-for-assessment-and-feedback
- https://openai.com/policies/usage-policies/

Relevant Classroom resources:

- `courses.courseWork.list/get`
- `courses.courseWork.studentSubmissions.list/get`
- `courses.courseWork.studentSubmissions.patch`
- `courses.courseWork.studentSubmissions.return`

Important product constraint: Classroom grading APIs exist, but this product
must not automatically publish grades during pilot or early production. Teacher
approval remains the explicit final action.

Additional Google constraints that must be treated as launch inputs:

- Classroom push registrations expire and must be renewed before expiry.
- Classroom notifications are change hints delivered through Pub/Sub, not a
  durable complete event log; reconciliation is mandatory.
- Notifications require the app to retain the teacher's OAuth grant.
- OAuth scope selection can trigger sensitive/restricted app verification or
  security review, so the scope matrix is a launch artifact.
- Classroom distinguishes `draftGrade`, `assignedGrade`, and submission state;
  `return` changes state and does not itself set grades.
- Classroom Add-ons are generally available and should be treated as an
  explicit product-path decision, even if they are out of scope for v1.
- Rubric API support is not equivalent to gradebook control: rubric grades are
  read-only through the API, rubrics are tied to one `CourseWork`, and rubric
  create/update/delete paths require capability and license checks.
- Third-party app access for under-18 Google Workspace for Education users is
  an administrator action in the Admin console and cannot be configured
  programmatically by this developer app.
- OneRoster/SIS integration is a separate partner path with conformance tests;
  Classroom/CSV export should not be described as SIS-gradebook integration.
- Classroom errors carry structured failure details and must be translated into
  typed retry/remedy behavior instead of generic failed jobs.
- Assessment and feedback workflows must keep humans in the loop for
  educational decisions; product UX must force teacher review before final
  grade/export/passback actions.

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

## Slice 16: District/Admin Production Path

Status: not implemented.

Goal: support district-level adoption instead of only individual teacher OAuth.

Why this exists: school production usually requires tenant setup, vendor
approval, domain policy, data processing review, co-teacher access, billing
controls, and retention controls before individual teachers can use the app.

Touched files/areas:

- new `server/districts.py`
- `server/runtime_context.py`
- `server/projects.py`
- `server/review_store.py`
- `server/billing.py`
- admin UI routes
- docs: `LEGAL_NOTES.md`, `TEACHER_PILOT_RUNBOOK.md`,
  `PRODUCTION_READINESS_SPEC.md`

Implementation:

- Add district tenant model:
  - district id/name/domain
  - allowed Google Workspace domains
  - admin contacts
  - DPA/vendor approval status
  - COPPA/FERPA/school-official posture fields
  - retention policy
  - billing owner and cost caps
  - allowed providers/models
  - allowed product features such as grade passback
- Add district admin roles:
  - district admin
  - school admin
  - teacher
  - co-teacher
  - support/operator
- Add admin allowlisting:
  - permitted domains
  - permitted courses
  - permitted teachers
  - disabled external providers by default
- Add district-level retention/billing controls that override teacher-level
  defaults.
- Add audit records for admin actions.

Done criteria:

- Teacher sign-in can be blocked or allowed by district policy.
- Co-teachers inherit access only when district/course policy permits it.
- Billing caps can be enforced at district, school, teacher, and project level.
- Retention policy can be applied and audited at district level.
- Production launch validator fails when district policy is absent for a
  district-managed deployment.

## Slice 17: Classroom Attachment Reality Matrix

Status: not implemented.

Goal: make Classroom/Drive attachment handling explicit, testable, and scoped.

Why this exists: "fetch attachment metadata/content" hides most real-world
Classroom complexity. Production must know which attachment types are supported
and exactly when Drive scopes are unavoidable.

Touched files/areas:

- new `server/attachments.py`
- `server/classroom.py`
- `scripts/extract_text.py`
- OCR/image extraction dependencies
- `server/data/` attachment artifacts
- docs and tests for attachment support

Implementation:

- Add an attachment support matrix:
  - Google Docs export to text/PDF
  - uploaded Drive docs
  - PDFs
  - images/OCR
  - RTF/TXT/DOCX
  - Slides
  - Forms/non-text submissions
  - external links
  - multiple attachments per submission
  - copied assignments
  - reclaimed/resubmitted work
  - missing permission cases
  - malware/file-size blocked files
  - empty placeholder submissions
- Add attachment state fields:
  - `supported`
  - `requires_drive_scope`
  - `extractable_text`
  - `needs_manual_review`
  - `unsupported_reason`
  - `file_hash`
  - `export_mime_type`
- Define Drive scope escalation policy:
  - Classroom-only metadata first
  - Drive read scope only when the teacher links an assignment whose
    attachments cannot be accessed through Classroom metadata alone
  - explicit consent copy before requesting broader scopes
- Add extraction quarantine for file-size/malware/OCR failures.

Done criteria:

- Unsupported attachment types surface as teacher-visible blockers, not silent
  zero-text submissions.
- Drive scope use is justified by a recorded attachment need.
- Tests cover at least Docs, DOCX, PDF, image, link-only, missing permission,
  reclaimed submission, oversized file, and unsupported Forms/Slides cases.

## Slice 18: Roster And Co-Teacher Sync

Status: not implemented.

Goal: keep roster identity, co-teacher access, and pseudonym maps correct as
Classroom courses change.

Why this exists: coursework events alone do not handle roster drift, access
removal, renamed students, course ownership changes, or co-teacher lifecycle.

Touched files/areas:

- `server/classroom.py`
- new `server/roster_sync.py`
- `server/runtime_context.py`
- `server/projects.py`
- `server/review_store.py`
- `server/data/` roster tables
- UI access/roster status panel

Implementation:

- Sync:
  - students added/dropped
  - student name changes
  - co-teachers added/removed
  - course owner changes
  - teacher removed from course
  - archived courses
- Maintain pseudonym map lifecycle:
  - stable per district/course/project where needed
  - reversible only by authorized teacher/admin where policy permits
  - retained/deleted according to district policy
- Enforce co-teacher access:
  - course co-teacher may view linked project only when district policy allows
  - review/finalization actions record actor identity
- Reconcile roster periodically, not only through push events.

Done criteria:

- Removing teacher access disables new ingestion and review access.
- Added students can be ingested without recreating the project.
- Dropped students are retained or hidden according to policy and audit state.
- Co-teacher actions are authorized and separately logged.

## Slice 19: Google Integration Path Decision

Status: not decided.

Goal: explicitly choose the v1 Google product path and park alternative Google
integration modes with rationale.

Why this exists: Classroom API + OAuth linking is one path; Classroom Add-ons
and Google Workspace Marketplace review are now material options. Ignoring
them should be intentional, not accidental.

Touched files/areas:

- docs: new `docs/GOOGLE_INTEGRATION_DECISION.md`
- `docs/PRODUCTION_READINESS_SPEC.md`
- product UI copy
- deployment/OAuth config

Implementation:

- Compare:
  - standalone web app with Google OAuth and Classroom API
  - Classroom Add-on
  - Google Workspace Marketplace app
  - Drive-folder-only workflow
- Decide v1:
  - recommended: standalone OAuth/Classroom API app for speed of iteration
  - Classroom Add-on/Marketplace as later production-distribution slice unless
    district procurement requires it earlier
- Record implications:
  - OAuth review burden
  - install/admin approval flow
  - UI entry points
  - attachment access
  - passback capabilities
  - support burden

Done criteria:

- The chosen v1 path is documented with explicit non-goals.
- Add-ons/Marketplace are either scoped into a dated later slice or declared
  out of scope for v1.
- OAuth consent, scopes, and procurement docs match the chosen path.

## Slice 20: Grade Export And Passback Guardrails

Status: not implemented.

Goal: define and enforce exactly how grades can leave the product.

Why this exists: the product must not automatically publish grades. Classroom
distinguishes draft grades, assigned grades, and returned submissions; each
action needs separate teacher consent and auditability.

Touched files/areas:

- `server/classroom.py`
- new `server/grade_passback.py`
- `server/projects.py`
- `ui/app.js`
- `scripts/review_and_grade.py`
- `scripts/build_dashboard_data.py`
- audit log tables

Implementation:

- Keep passback disabled by default in pilot.
- Add explicit modes:
  - export CSV only
  - write Classroom `draftGrade`
  - write Classroom `assignedGrade`
  - return submission
- Require separate teacher confirmation for each write/return action.
- Never call `return` as a side effect of setting a grade.
- Add preflight diff:
  - current Classroom grade/state
  - proposed draft/assigned grade
  - affected students
  - changed/unchanged rows
- Add rollback story:
  - previous grade snapshot
  - compensating update where Classroom permits it
  - audit note when state cannot be fully rolled back

Done criteria:

- No grade API write occurs without explicit teacher action.
- Pilot mode cannot publish/return submissions.
- Every passback action has an actor, timestamp, before/after, and Classroom
  response id.
- Tests prove draft grade, assigned grade, and return are separate actions.

## Slice 21: Prompt-Injection And Sensitive-Content Safety

Status: not implemented.

Goal: treat student submissions as untrusted input and route sensitive content
to teacher/operator policy rather than unfiltered model execution.

Why this exists: essays can contain instructions to the model, private student
data, abuse disclosures, self-harm content, hate/harassment, or other
sensitive material.

Touched files/areas:

- `scripts/extract_text.py`
- new `scripts/content_safety_scan.py`
- `scripts/run_llm_assessors.py`
- `scripts/build_dashboard_data.py`
- `server/pipeline_queue.py`
- `ui/app.js`
- safety policy docs

Implementation:

- Add pre-model content scan:
  - prompt-injection language
  - attempts to override rubric/system instructions
  - PII beyond expected schoolwork identifiers
  - self-harm or abuse disclosures
  - hate/harassment/violent threats
  - sexual content involving minors
  - doxxing or credential leakage
- Add model prompt hardening:
  - isolate submission text as quoted data
  - instruct models to ignore student-authored meta-instructions
  - never expose hidden prompts or system details in feedback
- Add escalation outputs:
  - `outputs/content_safety_report.json`
  - per-student teacher-visible flags
  - district/operator escalation hook when policy requires
- Add policy:
  - the product does not replace mandatory reporting obligations
  - teacher/school policy controls response to sensitive disclosures

Done criteria:

- Prompt-injection text inside a submission cannot alter evaluator routing.
- Sensitive-content flags are visible to the teacher before feedback export.
- Tests cover malicious instructions, PII, self-harm/abuse disclosure,
  hate/harassment, and benign false positives.

## Slice 22: Fairness And Accommodation Evaluation

Status: not implemented as a launch-blocking packet.

Goal: evaluate differential performance across student contexts before
production release.

Why this exists: existing accuracy gates cover hard-pair/source-family
regressions, but production must also test whether the system behaves fairly
across ELL, IEP/accommodation, dialect/language variation, grade band, genre,
topic familiarity, and polish-vs-insight failure modes.

Touched files/areas:

- `bench/`
- `config/accuracy_gate.json`
- `scripts/publish_gate.py`
- new `scripts/fairness_eval.py`
- `docs/reports/`
- `inputs/class_metadata.json` schema docs

Implementation:

- Define metadata fields that can be used only with policy approval:
  - ELL context
  - accommodation context
  - grade band
  - genre
  - dialect/language variation marker where appropriate and consented
  - source/topic familiarity
- Add benchmark packets:
  - rough but insightful vs polished shallow
  - ELL grammar surface vs meaning quality
  - accommodation-aware incomplete/scaffold cases
  - dialect/language variation cases
  - genre-specific expectations for speech, letter, report, instructions,
    literary analysis
- Add differential metrics:
  - override concentration
  - rank displacement by group
  - boundary false movement by group
  - feedback tone/edit rate by group

Done criteria:

- Release candidate includes a fairness/accommodation packet.
- Any launch-blocking differential regression has an owner and remediation.
- Teacher-facing explanations do not expose sensitive metadata unnecessarily.

## Slice 23: Audit Log And Security Threat Model

Status: not implemented as a concrete control set.

Goal: define and enforce security controls for OAuth, sessions, webhooks,
artifacts, admin actions, and model/provider secrets.

Why this exists: broad privacy/security language is insufficient for a school
SaaS product that handles student work and OAuth grants.

Touched files/areas:

- `server/runtime_context.py`
- `server/app.py`
- `server/google_auth.py`
- `server/pubsub_handler.py`
- `server/projects.py`
- artifact serving paths
- deployment config
- CI/dependency scanning config

Implementation:

- OAuth/session controls:
  - state parameter
  - PKCE
  - secure cookies
  - session expiry and refresh
  - CSRF protection for state-changing routes
- Pub/Sub/webhook controls:
  - IAM verification
  - signed push token or equivalent verification
  - registration id validation
  - replay protection
  - dead-letter topic
- App controls:
  - rate limiting
  - dependency scanning
  - secret rotation procedure
  - admin action audit log
  - artifact access audit log
  - support impersonation rules, if any
- Threat model:
  - unauthorized classroom access
  - cross-tenant artifact access
  - prompt injection
  - stale audit promotion
  - billing tampering
  - provider key leakage
  - webhook spoofing

Done criteria:

- Threat model is checked into docs and reviewed before launch.
- Security tests cover CSRF, tenant isolation, webhook verification, and
  artifact authorization.
- Admin/support access is logged and visible in audit export.

## Slice 24: Provider Data-Processing Contract

Status: not implemented.

Goal: make provider privacy posture part of runtime profile enablement.

Why this exists: provider abstraction is not only model compatibility. Schools
need to know retention, training, subprocessors, region, and logging behavior
for each provider that receives student work.

Touched files/areas:

- `config/runtime_profiles.json`
- `config/provider_data_processing.json`
- `scripts/openai_client.py`
- `scripts/run_llm_assessors.py`
- `server/pipeline_queue.py`
- docs and launch validator

Implementation:

- Add provider data-processing fields:
  - training/no-training terms
  - retention duration
  - zero-retention availability
  - subprocessors
  - region/data residency
  - request/response logging policy
  - whether student names are stripped before model calls
  - whether prompts/responses are retained locally
- Add pseudonymization controls:
  - substitute student display names with stable ids before model calls
  - keep mapping local to authorized tenant/project
  - avoid sending unnecessary class metadata
- Block provider enablement unless data-processing fields are complete.

Done criteria:

- Runtime profile status reports provider privacy posture.
- Launch validator blocks incomplete provider data-processing records.
- Model calls can be audited for pseudonymization and minimized metadata.

## Slice 25: Operational Support Surface

Status: not implemented.

Goal: give operators and teachers a supportable production service, not a black
box queue.

Why this exists: health checks are not enough. Production needs stuck-job
inspection, alerting, retry budgets, dead-letter queues, outage modes, support
exports, and RPO/RTO targets.

Touched files/areas:

- new admin/support UI
- `server/pipeline_queue.py`
- `server/classroom_events.py`
- `server/billing.py`
- logs/metrics config
- support export tooling

Implementation:

- Teacher-facing status page:
  - provider outage
  - Classroom ingestion degraded
  - billing unavailable
  - delayed validation
- Admin console:
  - stuck jobs
  - stale background audits
  - DLQ events
  - provider errors
  - cost anomalies
  - retry budget exhaustion
- Add support export packet:
  - job manifest
  - event log
  - redacted inputs/outputs
  - provider request ids
  - billing rows
  - current human revision state
- Define:
  - retry budgets by work item
  - alert thresholds
  - provider outage mode
  - RPO/RTO targets

Done criteria:

- Operator can diagnose a stuck job without shell access.
- DLQ events can be replayed or dismissed with audit logs.
- Provider outage degrades gracefully and explains status to teachers.
- Support export redacts student-identifying data unless explicitly authorized.

## Slice 26: Schema And Artifact Versioning

Status: not implemented.

Goal: version every durable schema and artifact consumed by long-running jobs,
dashboards, review ledgers, and rollback/backfill tools.

Why this exists: long-running background audits and retained dashboards will
span code deploys. Without versioning, old artifacts can be misread or
silently corrupted by newer code.

Touched files/areas:

- `server/pipeline_queue.py`
- `server/review_store.py`
- `scripts/build_dashboard_data.py`
- `scripts/aggregate_assessments.py`
- `outputs/dashboard_data.json`
- review ledger artifacts
- migration scripts

Implementation:

- Add schema versions to:
  - pipeline manifest
  - dashboard JSON
  - review ledger
  - human revisions
  - submission units
  - attachment records
  - cost ledger
  - provider data-processing records
- Add compatibility checks:
  - refuse to promote unknown future schema
  - migrate known old schemas
  - flag stale dashboard artifacts
- Add rollback/backfill policy:
  - what can be downgraded
  - what must be regenerated
  - what is immutable audit evidence

Done criteria:

- Dashboard loader validates `schema_version`.
- Review ledger migrations are tested.
- Long-running job promotion checks code/artifact compatibility before
  publishing.
- Backfill tool can report which retained projects require regeneration.

## Slice 27: Accessibility And Procurement Readiness

Status: not implemented.

Goal: make the product acceptable for school procurement and accessible teacher
use.

Why this exists: schools commonly require accessibility conformance,
procurement documentation, privacy terms, and support contacts before approval.

Touched files/areas:

- `ui/index.html`
- `ui/app.js`
- `ui/styles.css`
- docs:
  - privacy policy
  - terms
  - accessibility statement
  - VPAT or VPAT-lite packet
  - procurement/security questionnaire answers
- browser/Playwright accessibility tests

Implementation:

- Meet WCAG 2.2 AA target:
  - keyboard navigation
  - focus order
  - screen-reader labels
  - color contrast
  - error announcement
  - non-hover-only controls
  - reduced motion where appropriate
- Add procurement documents:
  - privacy policy
  - terms of service
  - DPA template
  - subprocessors list
  - accessibility statement
  - support/security contact
- Add UI links where appropriate.

Done criteria:

- Automated accessibility smoke tests pass.
- Manual keyboard/screen-reader review is documented for core flows.
- Procurement docs are complete enough for pilot districts.

## Slice 28: Classroom Rubric And Gradebook Semantics

Status: not implemented.

Goal: define how the product treats Classroom rubrics and gradebook state
without overclaiming API control.

Why this exists: Classroom rubric support has hard platform boundaries. Rubric
grades are readable but not writable through the API, rubrics belong to one
`CourseWork`, rubric management can depend on the Google Cloud project that
created the coursework, and create/update/delete operations require user and
course-owner eligibility checks.

Touched files/areas:

- new `server/rubrics.py`
- `server/classroom.py`
- `server/projects.py`
- `server/review_store.py`
- `scripts/extract_text.py`
- `scripts/review_and_grade.py`
- `scripts/build_dashboard_data.py`
- `ui/app.js`
- `outputs/evidence_packet.json`
- docs: rubric source matrix and teacher workflow copy

Implementation:

- Add rubric source matrix:
  - imported Classroom rubric
  - uploaded rubric file
  - teacher-edited rubric
  - app-generated draft rubric
  - assignment instructions without formal rubric
- Snapshot rubric state:
  - source
  - criterion ids/titles/descriptions
  - level ids/titles/descriptions/points
  - scored vs unscored
  - total points
  - source `CourseWork` id where applicable
  - rubric version hash
  - teacher edits and effective rubric hash
- Add Classroom rubric constraints:
  - rubric grades can be read but not written
  - app cannot promise to enforce rubric usage in Classroom
  - app cannot assume it can manage rubrics for teacher-created coursework
  - rubric creation/update/delete requires `checkUserCapability`
  - Education Plus/license failures are first-class capability failures
- Add gradebook mapping:
  - app rubric evidence
  - Classroom `draftGrade`
  - Classroom `assignedGrade`
  - Classroom rubric-grade readback, if present
  - CSV/export grade columns

Done criteria:

- Every finalized run records the effective rubric source and version hash.
- Teacher-facing copy clearly distinguishes app rubric evidence from Classroom
  gradebook writes.
- Capability/license failures produce actionable UI, not generic pipeline
  errors.
- Tests cover imported Classroom rubric, uploaded rubric, teacher-edited
  rubric, app-generated rubric, no-rubric assignment, read-only rubric grades,
  and unavailable rubric capability.

## Slice 29: Admin And Under-18 App Approval Preflight

Status: not implemented.

Goal: determine whether a teacher/domain/student population can actually use
the app before a pilot or Classroom sync begins.

Why this exists: district approval is not only a contract artifact. Google
Workspace for Education administrators must configure third-party app access
for under-18 users in the Admin console, and the developer app cannot do that
programmatically.

Touched files/areas:

- `server/google_auth.py`
- `server/districts.py`
- `server/classroom.py`
- `server/projects.py`
- `ui/app.js`
- `docs/TEACHER_PILOT_RUNBOOK.md`
- docs: admin preflight checklist

Implementation:

- Add admin/domain preflight:
  - teacher domain
  - known district tenant
  - OAuth consent status
  - requested scopes
  - under-18 app access status, teacher-confirmed or admin-confirmed
  - required admin actions
  - student-facing feature availability
- Add capability preflight:
  - Classroom API enabled
  - app authorized for teacher
  - retained teacher grant present
  - add-on/rubric capability checks where relevant
  - course owner/course status compatible with intended action
- Add UX:
  - block Classroom-linked run when under-18 approval is unknown and student
    access is required
  - allow upload-only pilot path when district policy permits
  - produce admin checklist packet for approval

Done criteria:

- A teacher can see whether the blocker is OAuth, admin app approval, license,
  Classroom API disabled, or district policy.
- The product never implies it can programmatically approve itself for
  under-18 Workspace users.
- Launch validator fails Classroom pilot setup when admin preflight is
  incomplete.

## Slice 30: SIS And OneRoster Boundary

Status: not decided.

Goal: explicitly decide whether v1 stops at Classroom/CSV or includes SIS and
OneRoster partnership work.

Why this exists: Classroom is often not the district gradebook of record.
Google treats OneRoster as a separate SIS partner path with conformance tests,
so a Classroom export is not automatically a SIS integration.

Touched files/areas:

- docs: new `docs/SIS_ONEROSTER_DECISION.md`
- `docs/PRODUCTION_READINESS_SPEC.md`
- `server/grade_passback.py`
- export tooling
- procurement docs

Implementation:

- Compare v1 options:
  - Classroom and CSV only
  - district-specific CSV export templates
  - SIS file export without official OneRoster partnership
  - formal OneRoster/SIS partner path
- Record recommendation:
  - v1 should stop at Classroom/CSV unless a pilot district requires a
    specific SIS export
  - OneRoster partnership planning is a later production-distribution slice
    with conformance tests, partner approval, and support burden
- Add copy guardrails:
  - do not call Classroom passback "SIS sync"
  - do not imply gradebook-of-record integration without district validation

Done criteria:

- Product docs state whether v1 includes SIS integration.
- Any SIS export has district-specific owner, mapping, and signoff.
- OneRoster work has separate acceptance criteria and is not bundled into
  generic Classroom readiness.

## Slice 31: Classroom API Error Taxonomy

Status: not implemented.

Goal: translate Classroom and Drive failures into typed retry/remedy behavior
for teachers and operators.

Why this exists: generic "pipeline failed" errors are not supportable in school
production. Teachers need to know whether the remedy is admin action, scope
reauthorization, license upgrade, file permission change, retry later, or
manual upload.

Touched files/areas:

- new `server/classroom_errors.py`
- `server/classroom.py`
- `server/classroom_events.py`
- `server/pubsub_handler.py`
- `server/pipeline_queue.py`
- `server/support_export.py`
- `ui/app.js`
- tests for Classroom/Drive error mapping

Implementation:

- Add typed error kinds:
  - `ClassroomApiDisabled`
  - `MissingOrExpiredGrant`
  - `AdminAppBlocked`
  - `Under18AppAccessBlocked`
  - `AttachmentNotVisible`
  - `ProjectPermissionDenied`
  - `ResourceExhausted`
  - `RateLimited`
  - `LicenseOrCapabilityUnavailable`
  - `ArchivedCourse`
  - `NonmodifiableCourseWork`
  - `RubricUnavailable`
  - `DriveScopeRequired`
  - `FileTooLarge`
  - `MalwareOrSafetyBlocked`
- Map each error to:
  - teacher-facing message
  - operator details
  - retry policy
  - admin remedy
  - fallback workflow
  - support export fields
- Preserve raw provider error details in support logs without exposing secrets
  or unnecessary student data.

Done criteria:

- Known Classroom errors are not surfaced as undifferentiated run failures.
- Teacher UI shows a specific next action for each recoverable class.
- Retryable quota/network failures do not consume teacher attention until the
  retry budget is exhausted.
- Tests cover the named taxonomy and unknown-error fallback behavior.

## Slice 32: Assessment Evidence Packet

Status: not implemented.

Goal: generate a defensibility artifact for every finalized result.

Why this exists: security audit logs answer who accessed or changed data. They
do not by themselves prove why the final assessment order, grade, feedback, or
export was defensible at the time the teacher finalized it.

Touched files/areas:

- new `scripts/build_evidence_packet.py`
- `scripts/build_dashboard_data.py`
- `scripts/publish_gate.py`
- `server/review_store.py`
- `server/projects.py`
- `server/pipeline_queue.py`
- `server/grade_passback.py`
- `outputs/evidence_packet.json`
- `outputs/evidence_packet.zip`
- dashboard export UI

Implementation:

- Capture:
  - assignment snapshot
  - source/rubric version hash
  - submission ids and text hashes
  - attachment extraction status
  - runtime profile
  - provider/model/effective model id
  - pricing and billing profile
  - model prompt/schema version
  - human revisions and `human_revision_id`
  - teacher anchors/pairwise corrections/flags
  - protected committee and human edges
  - withheld/suppressed edges
  - promotion blockers and resolution
  - final teacher action
  - export/passback action
  - generated feedback quality gate result
- Produce redacted and full variants:
  - teacher/local full packet
  - support-safe redacted packet
  - district audit packet according to policy

Done criteria:

- Every finalized project has an evidence packet linked from the dashboard.
- Evidence packet can be regenerated or verified from retained artifacts.
- Packet schema is versioned and migration-tested.
- Tests prove missing evidence blocks finalization in production mode.

## Slice 33: Feedback Quality Gate

Status: not implemented.

Goal: gate generated feedback separately from ranking and grade accuracy.

Why this exists: a correct order can still produce unsafe, ungrounded, harsh,
or unhelpful feedback. Teacher pilots need feedback that is grounded in the
student work and does not leak hidden model rationale.

Touched files/areas:

- `scripts/review_and_grade.py`
- `scripts/build_dashboard_data.py`
- new `scripts/feedback_quality_gate.py`
- `config/accuracy_gate.json`
- `bench/feedback_quality/`
- `ui/app.js`
- `docs/TEACHER_PILOT_RUNBOOK.md`

Implementation:

- Add feedback checks:
  - quote/evidence grounding
  - no fabricated details
  - age-appropriate tone
  - no harsh or demotivating phrasing
  - accommodation-aware wording
  - no hidden chain-of-thought or system-prompt leakage
  - no sensitive content disclosure beyond policy
  - actionable next step tied to the rubric
- Add teacher UI status:
  - passed
  - needs teacher review
  - blocked from export
- Add benchmark packets:
  - short/rough but insightful response
  - polished but shallow response
  - sensitive disclosure
  - ELL/accommodation context
  - prompt-injection attempt
  - missing/unsupported attachment

Done criteria:

- Feedback export is blocked when the quality gate fails in production mode.
- Tests catch fabricated feedback and hidden-rationale leakage.
- Teacher can edit/approve feedback without losing evidence packet traceability.

## Slice 34: Teacher Onboarding And Automation-Bias Controls

Status: not implemented.

Goal: make teacher authority a product behavior, not only a policy sentence.

Why this exists: education assessment decisions require human review. The UI
must prevent automation bias by requiring calibration, review attestations, and
explicit teacher action before finalization or passback.

Touched files/areas:

- `ui/app.js`
- `ui/index.html`
- `server/projects.py`
- `server/review_store.py`
- `server/grade_passback.py`
- `docs/TEACHER_PILOT_RUNBOOK.md`
- onboarding/training docs

Implementation:

- Add onboarding:
  - model-as-aide explanation
  - assessment authority checklist
  - sample calibration exercise
  - limitations and known failure modes
- Add workflow gates:
  - rubric confirmation before run
  - cohort calibration checkpoint
  - low-confidence cohort warning
  - "I reviewed this" attestation before finalization
  - separate attestation before export/passback
- Add anti-bias nudges:
  - require review of boundary cases
  - show uncertainty and withheld items
  - avoid defaulting teacher into one-click mass acceptance

Done criteria:

- Production finalization requires teacher attestation.
- Passback/export requires a second explicit teacher action.
- Training docs state that the model is an aide and the teacher remains the
  assessor of record.
- Tests cover blocked finalization when calibration or attestation is missing.

## Slice 35: Model Lifecycle And Alias Drift

Status: not implemented.

Goal: prevent provider alias, pricing, or structured-output changes from
silently changing teacher-facing behavior.

Why this exists: provider profiles can name a model alias today, but aliases
can move, deprecate, change price, or change structured-output behavior. Any
such drift should force recertification before teacher release.

Touched files/areas:

- `config/runtime_profiles.json`
- new `config/model_lifecycle.json`
- `config/provider_data_processing.json`
- `scripts/openai_client.py`
- `scripts/run_llm_assessors.py`
- `scripts/publish_gate.py`
- `server/runtime_context.py`
- `server/billing.py`
- CI/nightly validation

Implementation:

- Record model lifecycle fields:
  - configured model id
  - effective provider model id
  - provider-side revision where available
  - certified date
  - certified benchmark packet
  - price schedule hash
  - structured-output/schema behavior hash
  - deprecation status
  - allowed runtime profiles
- Add drift checks:
  - alias resolves differently
  - model deprecated
  - price changed
  - max context/output limits changed
  - structured output no longer validates
  - provider safety/data-processing posture changed
- Gate teacher release:
  - internal testing may use uncertified models
  - teacher-facing profiles require current certification

Done criteria:

- Runtime profile status reports model certification state.
- Launch validator blocks teacher-facing use of uncertified alias drift.
- Evidence packet records the effective model id used for the run.
- Tests simulate alias and price drift.

## Slice 36: Untrusted External Text Boundary

Status: not implemented.

Goal: treat all text imported from outside the trusted codebase as untrusted
before it enters prompts, logs, feedback, or dashboards.

Why this exists: prompt injection and sensitive data are not limited to student
essays. Rubrics, assignment descriptions, Classroom comments, Drive metadata,
teacher-uploaded files, copied assignment text, and attachment filenames can
also contain malicious instructions or sensitive content.

Touched files/areas:

- `scripts/extract_text.py`
- `scripts/content_safety_scan.py`
- `scripts/run_llm_assessors.py`
- `scripts/build_dashboard_data.py`
- `server/classroom.py`
- `server/attachments.py`
- `server/projects.py`
- `ui/app.js`

Implementation:

- Define external text classes:
  - student submission body
  - rubric text
  - assignment title/description
  - teacher comments
  - Classroom attachment metadata
  - Drive filenames and descriptions
  - OCR output
  - uploaded rubric or assignment files
  - imported exemplar/anchor text
- Apply:
  - content safety scan
  - prompt-injection scan
  - PII/minimization pass
  - prompt quoting/escaping
  - display sanitization
  - evidence packet hash recording
- Keep trusted internal prompts, schemas, and code-generated instructions
  separate from external text in every model call.

Done criteria:

- No external text enters a model prompt without source classification and
  scan status.
- Tests cover malicious rubric text, assignment description injection,
  malicious filename/metadata, and benign external text.
- Feedback never exposes hidden prompts because of external text injection.

## Slice 37: Co-Teacher Conflict Semantics

Status: not implemented.

Goal: define how simultaneous teacher and co-teacher edits merge, lock, or
conflict.

Why this exists: authorization alone does not make collaborative review safe.
Two teachers can edit anchors, flags, curve changes, feedback, or finalization
state at the same time.

Touched files/areas:

- `server/review_store.py`
- `server/projects.py`
- `server/runtime_context.py`
- `ui/app.js`
- review ledger schema
- websocket/event stream if added

Implementation:

- Add edit semantics:
  - optimistic concurrency token per review object
  - short locks for destructive/final actions
  - mergeable comments/notes
  - conflict resolution for anchors, flags, curve changes, feedback edits, and
    finalization
  - actor identity on every revision
- Add UI:
  - show active editor where available
  - stale edit warning
  - conflict diff
  - finalization lock
- Protect finalization:
  - no passback/export while unresolved review conflicts exist
  - final teacher action records actor and latest revision id

Done criteria:

- Concurrent edits cannot silently overwrite teacher evidence.
- Conflicts block finalization until resolved.
- Tests cover two-teacher edit, stale update rejection, and finalization lock.

## Slice 38: Background-Audit Billing Consent

Status: not implemented.

Goal: make child-job, restart, and revision-triggered background audit spend
explicit under PAYG.

Why this exists: `full_validation` may continue after the review-ready result,
rerun after teacher edits, or retry after provider errors. That spend can be
real money even when it happens in the background.

Touched files/areas:

- `server/billing.py`
- `server/pipeline_queue.py`
- `server/runtime_context.py`
- `server/projects.py`
- `ui/app.js`
- `docs/PAYG_MODE.md`
- cost ledger schema

Implementation:

- Add billing consent fields:
  - initial review-ready run cap
  - background full-validation cap
  - child-job cap
  - retry budget cap
  - revision-triggered rerun cap
  - district override cap
  - hard stop vs ask-to-continue mode
- Add UI:
  - estimated initial cost
  - estimated background validation cost
  - spend so far
  - remaining authorized budget
  - paused-for-consent state
- Add ledger rows for:
  - parent job
  - child job
  - retry
  - resumed run
  - teacher-triggered rerun
  - background audit promotion attempt

Done criteria:

- Background work cannot exceed teacher/district budget consent.
- Teacher sees when a job is paused for additional billing approval.
- Tests prove child jobs and retries are charged, capped, and auditable.

## Slice 39: Jurisdiction Matrix

Status: not implemented.

Goal: define launch jurisdictions and the policy controls required for each.

Why this exists: "school approval" is too generic for production. FERPA/COPPA
posture in the United States, Ontario/Canada privacy expectations, and EU/UK
data protection obligations produce different consent, retention, residency,
and contracting requirements.

Touched files/areas:

- docs: new `docs/JURISDICTION_MATRIX.md`
- `docs/LEGAL_NOTES.md`
- `docs/TEACHER_PILOT_RUNBOOK.md`
- `server/districts.py`
- `server/runtime_context.py`
- retention/deletion tooling
- provider data-processing config

Implementation:

- Define v1 launch jurisdiction:
  - United States baseline: FERPA, COPPA, PPRA, state student privacy laws
  - Canada/Ontario path if relevant to pilot districts
  - EU/UK explicitly out of scope until GDPR/UK GDPR/DPA packet is complete,
    unless a pilot requires it earlier
- Map each jurisdiction to:
  - required agreement documents
  - consent posture
  - subprocessors
  - data residency/transfer posture
  - retention/deletion policy
  - student/parent access or deletion workflow
  - provider eligibility
- Add launch validator jurisdiction mode.

Done criteria:

- Pilot packet states which jurisdiction it is valid for.
- Launch validator blocks production mode without a jurisdiction profile.
- Provider and retention settings are compatible with the selected
  jurisdiction.

## Recommended Slice Order

1. Production state model and manifest contract.
2. Human revision ledger and authority layer.
3. Background full-validation promotion.
4. Incremental submission analysis cache.
5. Schema and artifact versioning.
6. Model lifecycle and alias drift.
7. Untrusted external text boundary.
8. Prompt-injection and sensitive-content safety.
9. Feedback quality gate.
10. Assessment evidence packet.
11. Teacher onboarding and automation-bias controls.
12. Performance SLO harness for upload-based runs.
13. District/admin production path.
14. Admin and under-18 app approval preflight.
15. Google integration path decision.
16. Google sign-in and Classroom link.
17. Classroom attachment reality matrix.
18. Classroom rubric and gradebook semantics.
19. Roster and co-teacher sync.
20. Classroom event ingestion and reconciliation.
21. Incremental scheduler and priority queue.
22. Classroom review UI.
23. Co-teacher conflict semantics.
24. Grade export and passback guardrails.
25. SIS and OneRoster boundary.
26. Billing ledger and cost controls.
27. Background-audit billing consent.
28. Provider data-processing contract.
29. Provider abstraction and provider-specific gates.
30. Fairness and accommodation evaluation.
31. Privacy/security/compliance hardening.
32. Jurisdiction matrix.
33. Audit log and security threat model.
34. Classroom API error taxonomy.
35. Operational support surface.
36. Accessibility and procurement readiness.
37. Continuous validation automation.
38. Production deployment and recovery.
39. Pilot-to-production launch validator and rollout packet.

The immediate next engineering slice should be Slice 1 plus the minimal part of
Slice 2 needed to prevent stale background audit promotion. That gives the fast
teacher-review path a safe finalization story before Classroom integration
adds more event sources.

Before a teacher-facing pilot expands beyond trusted internal operators, the
highest-risk second-order gates are the Classroom rubric/gradebook semantics,
admin/under-18 approval preflight, assessment evidence packet, feedback quality
gate, and model lifecycle/alias drift certification.

## Production Blockers

Do not call this production-ready until these are true:

- `teacher_review` result is explicitly provisional until final promotion.
- `full_validation` runs in background and cannot overwrite newer teacher
  revisions.
- Teacher pairwise and anchor input are protected human evidence.
- Classroom-linked submission changes are idempotent and reconciled.
- Attachment support matrix is explicit and unsupported work is teacher-visible.
- Roster/co-teacher drift is reconciled and authorized.
- Classroom rubric and gradebook semantics are explicit and capability-checked.
- Admin/under-18 app approval preflight is complete for the pilot domain.
- Google Add-on/Marketplace path is intentionally decided for v1.
- SIS/OneRoster boundary is explicitly decided and not overclaimed.
- Grade passback is disabled by default and guarded by explicit teacher action.
- Classroom API errors have typed teacher remedies and retry behavior.
- Assessment evidence packet exists for every finalized result.
- Feedback quality gate passes before export or passback.
- Teacher onboarding and review attestations are enforced in product flow.
- Model alias, pricing, structured-output, and provider-policy drift force
  recertification before teacher release.
- Prompt-injection and sensitive-content scans run before model assessment on
  all external text, not only student submissions.
- Fairness/accommodation packet is launch-green.
- Co-teacher conflict semantics protect simultaneous edits and finalization.
- Class-of-30 review-ready SLO is measured under 5 minutes on the production
  provider path.
- PAYG billing blocks unpriced usage and separates internal Codex OAuth runs.
- Background audit, retry, child-job, and revision-triggered rerun spend is
  separately capped and consented.
- Tenant isolation is enforced in production mode.
- District/admin policy can gate teacher access, retention, and billing.
- Jurisdiction profile is selected and policy-compatible for each launch.
- Provider data-processing posture is complete for every enabled model profile.
- Audit logs cover admin actions, artifact access, passback, and support access.
- Schema/artifact version compatibility is enforced for long-running jobs and
  retained dashboards.
- Accessibility/procurement docs meet school approval expectations.
- Data retention, deletion, and policy docs are launch-ready.
- Release validation packets cover the known hard-pair/source-family failure
  modes.
- Teachers retain explicit final authority before grade publication.
