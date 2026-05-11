# Google Classroom Hero Path

Status: product contract and implementation notes for the Classroom-facing hero
path. The live product surface is implemented as a project-scoped Classroom
state model, API, and dashboard controls. It is intentionally read-only-first:
no Google Classroom write is performed by this repository without a future
adapter that proves OAuth, scopes, tenancy, and teacher confirmation end to end.

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

- `GET /projects/classroom`
- `POST /projects/classroom/link`
- `POST /projects/classroom/reconcile`
- `POST /projects/classroom/events`
- `POST /projects/classroom/audit/complete`
- `POST /projects/classroom/finalize`
- `GET /projects/classroom/evidence-packet`
- `POST /projects/classroom/passback/preflight`
- `POST /projects/classroom/passback/confirm`

The UI exposes these controls inside Session details. A teacher or operator can
link a Classroom assignment, reconcile the current cohort snapshot, see product
state and blockers, mark the background audit current, generate the evidence
packet, and preflight a CSV/Classroom passback action.

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
evidence stale.

## Attachment And Event Rules

Reconciliation treats Classroom events as hints, not a durable ledger. Duplicate
event IDs are counted and ignored, and reconciliation remains mandatory.

Attachment states are normalized per submission. Unsupported links, unsupported
Google file types, image/OCR gaps, missing Drive scope, or empty extraction
become explicit blockers. Empty or unsupported attachments are never treated as
zero-text essays.

## Export And Passback Rules

`passback/preflight` returns a teacher-visible diff and blocker list. It
preserves Classroom grade semantics:

- `draftGrade` is not `assignedGrade`
- returning a submission is separate from grade updates
- Classroom rubric scores are not treated as writable

`passback/confirm` records the explicit teacher action and updates the evidence
packet. It does not perform a live Classroom write in this implementation.

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
