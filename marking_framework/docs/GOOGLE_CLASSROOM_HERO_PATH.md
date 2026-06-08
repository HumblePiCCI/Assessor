# Google Classroom Hero Path

Status: local read-only Classroom pilot surface plus product contract. The
live product surface is implemented as a project-scoped Classroom state model,
Google OAuth connection, Classroom/Drive read adapters, API, and dashboard
controls. A repository owner can configure local OAuth, authenticate as a
teacher, choose a real course and published assignment, sync supported written
submissions, run the existing assessment pipeline, review/finalize, and produce
CSV export evidence. It is intentionally read-only-first: no Google Classroom
write is performed by this repository without a future adapter that proves
OAuth, scopes, tenancy, admin approval, preflight diff, audit records, tests,
docs, and explicit teacher confirmation end to end.

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

The UI exposes the routine path directly: connect Google Classroom, choose a
class, choose a published assignment, sync submissions, review imported/blocked
counts, add rubric and outline, run assessment, review normal and
flagged/boundary students, save draft/finalize review, and confirm CSV export.
Manual IDs, fixture sync, fake audit completion, validation internals, and live
write-looking controls are not part of the routine teacher path.

`read-sync` is the ingestion seam. It accepts roster/submission snapshots from
either the fixture/local adapter or the live Google adapter, materializes
supported extracted text into `inputs/submissions`, writes Classroom import
metadata to `inputs/class_metadata.json`, and records unsupported attachments
as blockers. The latest sync records `roster_count`, `submitted_count`,
`imported_count`, `blocked_count`, `missing_count`, `reclaimed_count`,
`returned_count`, `platform_error_count`, and `external_write_performed: false`.
Zero-import syncs are blocked with a remedy instead of being treated as success.
CI uses mocked adapters only and does not call Google.

OAuth configuration is read only from environment/local config:

- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_URI`
- optional `GOOGLE_OAUTH_CLIENT_SECRETS_FILE`
- optional `GOOGLE_TOKEN_ENCRYPTION_KEY`

Local development token state is stored under ignored
`server/data/google_oauth/`. Public status exposes only configured, connected,
expired/expiring, granted scopes, missing scopes, expiry, remediation, storage
posture, and a teacher email/hash when available. Raw access tokens, refresh
tokens, ID tokens, auth codes, client secrets, and credential JSON are never
returned to the browser or written to outputs/projects. Before each live Google
API call the service refreshes an expired/near-expiry access token; refresh
failure returns `refresh_failed_reconnect_required` and no Classroom/Drive call
is made with the stale token. Strict staging/production must use encrypted
local storage or an approved secret store before launch.

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
zero-text essays and are not materialized for grading. Mixed supported and
unsupported attachments are blocked as `partial_unsupported_attachments` in
this slice; the app does not import the supported portion until the unsupported
attachments are resolved by the teacher/operator.

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

Confirming CSV export records `external_write_performed: false`. The UI states
that no live Classroom write occurred, and backend confirmation rejects
tampered live-write preflights even if a caller bypasses the routine UI.

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
