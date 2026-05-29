# Google Classroom Live Smoke

Use this checklist when verifying Assessor against your own Google Classroom
account and a real class set. Do not commit credentials, tokens, downloaded
student work, private screenshots, or real student data.

## Cloud And OAuth Setup

- [ ] Create or choose a Google Cloud project.
- [ ] Enable the Google Classroom API.
- [ ] Enable the Google Drive API.
- [ ] Configure the OAuth consent screen in Testing mode.
- [ ] Add the teacher Google account as a test user.
- [ ] Create a `Web application` OAuth client.
- [ ] Add this redirect URI exactly:

```text
http://127.0.0.1:8000/google/auth/callback
```

- [ ] If using `localhost`, add this separate redirect URI too:

```text
http://localhost:8000/google/auth/callback
```

- [ ] Download the client JSON outside this repository.
- [ ] Create a local `.env.google` or `.env.local` from `.env.google.example`.
- [ ] Confirm `.env.google`, `.env.local`, client JSON, and `server/data/` are
      ignored by git.

## Local Preflight

- [ ] Run:

```bash
cd marking_framework
python3 scripts/google_classroom_setup_check.py
```

- [ ] Confirm the report shows configured OAuth values, an exact redirect URI,
      required read-only scopes, and ignored local secret/token paths.
- [ ] Confirm no secret value is printed.

## Start Assessor

- [ ] Start the server:

```bash
cd marking_framework
python3 -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

- [ ] Open:

```text
http://127.0.0.1:8000/
```

- [ ] Create or select a project.

## Connect And Sync Google Classroom

- [ ] Click `Connect Google Classroom`.
- [ ] Authenticate with the teacher Google account.
- [ ] Confirm the callback returns to Assessor with Google connected.
- [ ] Choose a class.
- [ ] Choose a published assignment.
- [ ] Click `Use assignment`.
- [ ] Click `Sync submissions`.
- [ ] Confirm imported count and blocker count.
- [ ] Confirm supported written submissions are present under
      `inputs/submissions/`.
- [ ] Confirm `inputs/class_metadata.json` exists.
- [ ] Confirm unsupported, empty, image-only, permission-denied, or external-link
      submissions are blockers and are not graded as zero-text essays.

## Run Assessment From Imported Inputs

- [ ] Add or upload the rubric.
- [ ] Add or upload the assignment outline.
- [ ] Connect Codex OAuth or configure the API provider runtime.
- [ ] Click `Run assessment`.
- [ ] Confirm no student essay download/re-upload is needed.
- [ ] Confirm the run uses `/pipeline/v2/run-project-inputs`.
- [ ] Confirm `pipeline_manifest.json` includes imported submission files and
      `inputs/class_metadata.json`.
- [ ] Record time to `teacher_review_ready`.
- [ ] Record time to full validation complete.
- [ ] Confirm teacher review is available while background validation is still
      running.

## Review, Save, Finalize

- [ ] Review one normal student.
- [ ] Review one flagged, blocker, or boundary student if present.
- [ ] Adjust the curve.
- [ ] Edit feedback.
- [ ] Save a draft.
- [ ] Reload the page and verify the draft persists.
- [ ] Finalize teacher review.
- [ ] Refresh or complete validation if needed.
- [ ] Confirm the product reaches `final_ready`.
- [ ] Finalize the Classroom result.

## CSV Export And No Live Writes

- [ ] Preflight CSV export.
- [ ] Confirm the preflight is blocked until teacher review, current validation,
      clear blockers, evidence packet, and explicit confirmation are satisfied.
- [ ] Confirm live write modes remain blocked:
      `draft_grade`, `assigned_grade`, and `return_submission`.
- [ ] Confirm blockers include `external_writes_disabled`,
      `classroom_write_adapter_not_configured`, `insufficient_scope` when write
      scopes are absent, and `admin_approval_required` when policy/admin
      approval is absent.
- [ ] Confirm CSV export.
- [ ] Download the CSV.
- [ ] Confirm the evidence packet records the export action and artifact hash.
- [ ] Confirm no live Google Classroom write occurred.

## Launch Validator And Report

- [ ] Run:

```bash
python3 scripts/validate_production_launch.py
```

- [ ] Record the exact launch-validator result and blockers.
- [ ] Do not mark production launch ready unless the validator says `ok`.
- [ ] Fill in
      `docs/reports/product_smoke_2026-__-__google_classroom_live_smoke_ready.md`
      or create a dated copy.
- [ ] Confirm no credentials, tokens, real student documents, or private
      screenshots were committed.
