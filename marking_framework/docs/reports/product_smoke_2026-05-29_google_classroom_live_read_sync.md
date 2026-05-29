# Product Smoke: Google Classroom Live Read Sync

Date: 2026-05-29

Branch: `codex/google-classroom-live-connect-assignments`

Base commit: `origin/main@c30017dbb625710374827c7abefa67eed84e7af9`

Runtime mode: local CI fixture/mocked Google transport. No live Google API calls,
paid model calls, credentials, refresh tokens, access tokens, real student data,
or private screenshots were used or committed.

## Scope

This smoke covers the Google Classroom live read integration slice:

- Google OAuth web-server flow with state binding and PKCE.
- Course and coursework selection through the teacher UI/API.
- Classroom roster, submissions, and Drive attachment read sync through mocked
  Google transports.
- Server-side Classroom imports materialized into the existing assessment input
  path.
- Fast teacher-review readiness before background validation completes.
- Teacher review persistence, curve/feedback edits, and CSV export as the
  shipped passback path.
- Live Google grade, return, and comment writes remain disabled.

Official Google API references used for the implementation:

- Classroom courses list:
  `https://developers.google.com/workspace/classroom/reference/rest/v1/courses/list`
- Classroom coursework list:
  `https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWork/list`
- Classroom student submissions list:
  `https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWork.studentSubmissions/list`
- Classroom students list:
  `https://developers.google.com/workspace/classroom/reference/rest/v1/courses.students/list`
- Drive files export:
  `https://developers.google.com/drive/api/reference/rest/v3/files/export`
- Drive files get/download:
  `https://developers.google.com/drive/api/reference/rest/v3/files/get`
- OAuth 2.0 web server flow:
  `https://developers.google.com/identity/protocols/oauth2/web-server`

## OAuth Proof

Google OAuth status was tested with mocked transport and safe public status only:

- `connected: true` after callback.
- Granted scopes are listed by name.
- Expiry is exposed.
- Teacher email is display-only when available; a teacher identity hash is
  available for correlation.
- Raw access tokens and refresh tokens are never returned by status.
- Disconnect revokes via the mocked revocation endpoint and clears local token
  state.

Token storage remains private server data under `server/data/google_oauth/...`
for local development. That directory is ignored. Staging/production strict mode
requires encryption or delegation to an approved secret store before launch.

Codex OAuth local mode was not re-smoked manually in this report, but the
existing Codex/runtime focused tests were rerun and passed. API provider runtime
compatibility was preserved through the OpenAI client/provider focused suites.

## Course And Assignment Selection

The teacher path is now:

1. Connect Google Classroom.
2. Load courses through `GET /projects/classroom/google/courses`.
3. Select a course.
4. Load assignments through
   `GET /projects/classroom/google/courses/{course_id}/coursework`.
5. Select coursework through `POST /projects/classroom/google/select`.
6. Sync submissions through `POST /projects/classroom/google/read-sync`.

The routine UI shows connection status, course selector, assignment selector,
sync action, and roster/submission/import/blocker counts. Manual IDs and API
diagnostics are behind Session/Admin details.

## Sync Counts

Mocked live Google read-sync endpoint test:

- Roster count: 2.
- Submission count: 2.
- Imported count: 1.
- Blocker count: 1.
- Supported imported submission was written to `inputs/submissions`.
- Unsupported submission was not materialized for grading.
- `class_metadata.json` records `google_classroom` source, `live_google`
  adapter, selected course/coursework identity, and sync counts.
- `external_write_performed: false`.

Attachment support cases covered by fixture tests:

- Google Doc export to text.
- Plain text attachment.
- DOCX extraction through the existing document extraction seam.
- Google Forms, Slides, Sheets, and Drawings blocked as unsupported.
- Image attachment blocked as `ocr_not_configured`.
- External link blocked as `external_link_unsupported`.
- Empty export blocked as `no_extractable_text`.
- Missing Drive scope blocked as `insufficient_scope` / `requires_drive_scope`.
- Quota/rate-limit and permission failures map to explicit blockers.

## Fast Review Proof

Pipeline bridge test:

- Classroom-imported server-side `inputs/submissions` ran through
  `PipelineQueue` without requiring local essay re-upload.
- Rubric and outline were read from project inputs.
- `teacher_can_review` became true before the mocked background
  `band_seam_adjudication.py` step started.
- Background validation then completed and wrote
  `background_validation_summary.json`.

Observed in test assertions:

- `teacher_review_ready`: immediate in the mocked local queue run.
- `ready_before_background_validation`: true.
- Background validation final status: `complete`.
- Teacher review state survives background validation refresh because human
  review save/finalize still stales validation and validation refresh updates
  the validation record without erasing teacher edits.

## Teacher Review And Export

Teacher review behavior covered by product tests:

- Draft review save.
- Finalize review.
- Curve adjustment.
- Feedback edit persistence.
- Draft reload.
- Final reload.
- Attachment blockers displayed through the exceptions/blockers surface.

CSV passback/export:

- CSV preflight is blocked before finalized teacher review.
- CSV preflight is blocked before current validation.
- CSV preflight is blocked when Classroom attachment blockers remain.
- CSV confirmation writes a deterministic downloadable artifact under review
  export storage.
- Evidence packet includes the export action and export artifact hash.
- Download endpoint returns the CSV artifact.

Live write modes remain fail-closed by default:

- `draft_grade`: blocked.
- `assigned_grade`: blocked.
- `return_submission`: blocked.
- Reasons include `external_writes_disabled`,
  `classroom_write_adapter_not_configured`, `insufficient_scope`, and
  `admin_approval_required` when policy/scopes/admin approval are absent.

No live Google write occurred. No `draftGrade`, `assignedGrade`,
`returnSubmission`, Classroom comment, or feedback write is implemented in this
PR.

## Verification

Baseline focused suite before edits:

```bash
cd /Users/bldt/Desktop/Essays/.worktrees/google-classroom-live-connect-assignments/marking_framework
python3 -m pytest -q --no-cov \
  tests/test_step_runner.py \
  tests/test_pipeline_queue.py \
  tests/test_classroom_product.py \
  tests/test_server_app.py \
  tests/test_openai_client.py \
  tests/test_openai_client_structured.py
```

Result: passed.

Full suite after implementation:

```bash
python3 -m pytest -q --no-cov
```

Result: passed.

Focused Google/Classroom suite after implementation:

```bash
python3 -m pytest -q --no-cov \
  tests/test_step_runner.py \
  tests/test_pipeline_queue.py \
  tests/test_classroom_product.py \
  tests/test_server_app.py \
  tests/test_openai_client.py \
  tests/test_openai_client_structured.py \
  tests/test_google_oauth.py \
  tests/test_google_classroom_adapter.py \
  tests/test_google_drive_adapter.py \
  tests/test_classroom_live_read_sync.py
```

Result: passed.

UI syntax:

```bash
node --check ui/app.js
```

Result: passed.

Static browser UI smoke:

- Served `marking_framework/ui` with `python3 -m http.server 8030 --bind
  127.0.0.1`.
- Loaded `http://127.0.0.1:8030/index.html` in Playwright.
- Verified the Google Classroom controls render: Connect Google Classroom,
  course selector, assignment selector, sync submissions, and Session/Admin
  details.
- Console errors were expected API fetch failures from the static-only smoke
  because the FastAPI server was not available through `uvicorn` in this local
  Python environment.

Launch validator:

```bash
python3 scripts/validate_production_launch.py
```

Result: blocked, as expected.

Blockers:

- `publish_gate_missing`
- `sota_gate_missing`
- `calibration_manifest_missing`

The launch gates, publish/SOTA requirements, teacher review authority, runtime
isolation, background validation model, and passback confirmation gates were not
weakened.
