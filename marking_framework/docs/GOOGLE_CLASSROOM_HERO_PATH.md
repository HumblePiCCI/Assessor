# Google Classroom Hero Path

Status: product contract and implementation notes for the Classroom-facing hero
path. The live product surface is implemented as a project-scoped Classroom
state model, Google OAuth connection, Classroom/Drive read adapters, API, and
dashboard controls. It is intentionally read-only-first: no Google Classroom
write is performed by this repository without a future adapter that proves
OAuth, scopes, tenancy, admin approval, and teacher confirmation end to end.

## Product Invariant

The teacher gets a fast `teacher_review` dashboard while `full_validation` can
catch up in the background. Teacher judgment remains an authoritative runtime
input. Final export or passback is blocked until:

- the teacher has finalized the review
- background validation has consumed the latest human revision
- attachment blockers are clear
- an assessment evidence packet can be generated
- the teacher explicitly requests and confirms an export/passback preflight

## Implemented Surface

The backend stores Classroom state under `server/data/classroom/<scope_id>/` and
materializes the current state into `outputs/classroom_state.json`.

API endpoints:

- `GET /google/auth/status`
- `GET /google/auth/preflight`
- `POST /google/auth/start`
- `GET /google/auth/callback`
- `POST /google/auth/disconnect`
- `GET /projects/classroom`
- `POST /projects/classroom/link`
- `POST /projects/classroom/read-sync`
- `GET /projects/classroom/google/courses`
- `GET /projects/classroom/google/courses/{course_id}/coursework`
- `POST /projects/classroom/google/select`
- `POST /projects/classroom/google/read-sync`
- `POST /projects/classroom/reconcile`
- `POST /projects/classroom/events`
- `POST /projects/classroom/audit/complete`
- `POST /projects/classroom/finalize`
- `GET /projects/classroom/evidence-packet`
- `POST /projects/classroom/passback/preflight`
- `POST /projects/classroom/passback/confirm`
- `GET /projects/classroom/passback/exports/{action_id}`
- `POST /pipeline/v2/run-project-inputs`
- `GET /pipeline/v2/project-inputs/status`

The UI exposes the routine path directly: connect Google Classroom, choose a
class, choose an assignment, sync submissions, add rubric and outline, run
assessment, review, finalize, and confirm CSV export. Manual IDs and fixture
sync remain under Session/Admin details for local proof and CI fixtures.
Teacher course listing defaults to active courses and published assignments;
draft coursework visibility is reserved for admin diagnostics.

Local setup is documented in `docs/GOOGLE_CLASSROOM_LOCAL_SETUP.md`. The setup
checker and `/google/auth/preflight` return only redacted readiness data. The
OAuth callback redirects back to the Assessor app with a safe `google` status
query parameter and never leaks authorization codes or tokens.

`read-sync` is the ingestion seam. It accepts roster/submission snapshots from
either the fixture/local adapter or the live Google adapter, materializes
supported extracted text into `inputs/submissions`, writes Classroom import
metadata to `inputs/class_metadata.json`, and records unsupported attachments
as blockers. CI uses mocked adapters only and does not call Google.

`/pipeline/v2/run-project-inputs` reuses saved/imported project inputs. The
teacher can upload rubric and assignment outline at run time or reuse saved
`inputs/rubric.*` and `inputs/assignment_outline.*`; imported submissions and
`inputs/class_metadata.json` must exist before the run starts.

OAuth configuration is read only from environment/local config:

- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_URI`
- optional `GOOGLE_OAUTH_CLIENT_SECRETS_FILE`
- optional `GOOGLE_TOKEN_ENCRYPTION_KEY`

Local development token state is stored under ignored
`server/data/google_oauth/`. Public status exposes only connected state,
granted scopes, expiry, refresh availability as a boolean, and a teacher
email/hash when available. Raw access and refresh tokens are never returned to
the browser or written to outputs/projects. Expired tokens are refreshed before
live Classroom adapter calls when a refresh token is available; failed refresh
or missing refresh token maps to a reconnect-required blocker.
Strict staging/production must use encrypted local storage or an approved secret
store before launch.

Default Google scopes are read-only:

- Classroom courses read-only
- Classroom coursework/submissions read-only
- Classroom rosters read-only
- Drive read-only for attachment export/download

## Product States

The contract uses the same stable state language as the hero path:

- `collecting`
- `ingesting`
- `analyzing_submissions`
- `review_ready`
- `background_validating`
- `final_ready`
- `finalized_by_teacher`
- `blocked`
- `failed`

`final_ready` requires `audit_revision_id >= latest_human_revision_id` and a
passing audit gate. Saving or finalizing teacher review state on a linked
Classroom project creates a monotonic human revision and marks prior audit
evidence stale. `finalized_by_teacher` is revision-bound: a later teacher
revision reopens the background-validation gate until a fresh audit consumes
that revision.

## Attachment And Event Rules

Reconciliation treats Classroom events as hints, not a durable ledger. Duplicate
event IDs are counted and ignored, and reconciliation remains mandatory.

Attachment states are normalized per submission. Supported Google Docs are
exported as text, text/Markdown/HTML/RTF are extracted as text, and DOCX/PDF
attachments are downloaded into the existing extraction path where possible.
Multiple supported attachments are combined with internal separators.

Unsupported links, Forms, Slides, Sheets, Drawings, image/OCR gaps, missing
Drive scope, permission failures, quota failures, or empty extraction become
explicit blockers. Empty or unsupported attachments are never treated as
zero-text essays and are not materialized for grading.

## Export And Passback Rules

`passback/preflight` returns a teacher-visible diff and blocker list. It
preserves Classroom grade semantics:

- `draftGrade` is not `assignedGrade`
- returning a submission is separate from grade updates
- Classroom rubric scores are not treated as writable

`passback/confirm` records the explicit teacher action, writes a downloadable
CSV artifact under review export storage, records the export artifact hash, and
updates the evidence packet. It does not perform a live Classroom write in this
implementation. Live Classroom write modes stay fail-closed with
`external_writes_disabled`, `classroom_write_adapter_not_configured`,
`insufficient_scope` when applicable, and `admin_approval_required` when policy
is absent. CSV export is the shipped passback path for this slice.

## Evidence Packet

`GET /projects/classroom/evidence-packet` writes
`outputs/assessment_evidence_packet.json`. The packet includes:

- assignment and project identity
- submission text and attachment hashes
- fast review and full-validation state
- teacher human revisions
- latest review delta
- feedback/export/passback actions
- artifact hashes for the dashboard, review, curve, final order, and Classroom
  state

This packet explains why the final educational artifact exists in its final
form. It is separate from security audit logs.
