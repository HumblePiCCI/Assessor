# Product Smoke: Google Classroom Local Pilot Slice

Status: implementation verified with mocks/fixtures; manual live owner smoke pending.

This report intentionally contains no real student names, document titles, raw Google IDs, screenshots, downloaded student work, OAuth tokens, client secrets, auth codes, raw Google payloads, or generated CSVs from real students.

## Implementation Verification

- Date: 2026-06-08
- Branch: `codex/google-classroom-local-pilot-smoke`
- Starting PR #19 head verified before edits: `358480b533c5b79d40a0961c4bfedffbf03d2ebe`
- Base reference verified before edits: `main@c30017dbb625710374827c7abefa67eed84e7af9`
- Verification data: mocks/fixtures only
- Live Google account used by Codex: no
- Live Classroom write performed: no
- Production launch status: not launched

Commands run before edits:

```bash
cd marking_framework
python3 -m pytest -q --no-cov tests/test_google_oauth.py tests/test_google_classroom_adapter.py tests/test_google_drive_adapter.py tests/test_classroom_live_read_sync.py tests/test_classroom_product.py tests/test_pipeline_queue.py tests/test_server_app.py
python3 -m pytest -q --no-cov
node --check ui/app.js
python3 scripts/validate_production_launch.py
```

Baseline result:

- focused pytest: passed
- full pytest: passed
- UI syntax: passed
- production launch validator: blocked as expected by real launch gates
  - `publish_gate_missing`
  - `sota_gate_missing`
  - `calibration_manifest_missing`

Commands run after implementation:

```bash
cd marking_framework
python3 -m pytest -q --no-cov tests/test_google_oauth.py tests/test_google_classroom_adapter.py tests/test_google_drive_adapter.py tests/test_classroom_live_read_sync.py tests/test_classroom_product.py
python3 -m pytest -q --no-cov tests/test_google_oauth.py tests/test_google_classroom_adapter.py tests/test_google_drive_adapter.py tests/test_classroom_live_read_sync.py tests/test_classroom_product.py tests/test_pipeline_queue.py tests/test_server_app.py
python3 -m pytest -q --no-cov
node --check ui/app.js
python3 scripts/validate_production_launch.py
```

Current implementation result:

- focused Google/Classroom/Drive/product pytest: passed
- required focused pytest including queue/server: passed
- full pytest: passed
- UI syntax: passed
- production launch validator: blocked as expected by real launch gates
  - `publish_gate_missing`
  - `sota_gate_missing`
  - `calibration_manifest_missing`

## Manual Live Owner Smoke

Status: pending owner-run live smoke.

Codex cannot authenticate with the repository owner's Google Classroom account. The owner should complete this section after running the live local pilot with a low-risk course and assignment.

### Setup Evidence

- Date:
- Branch:
- Commit SHA:
- Server URL/port:
- OAuth app mode:
  - Internal Workspace:
  - External Testing:
- Teacher test user configured, if External Testing:
- APIs enabled:
  - Google Classroom API:
  - Google Drive API:
- Redirect URI used:
  - `http://127.0.0.1:8000/google/auth/callback`
  - other:
- Scopes requested:
  - `https://www.googleapis.com/auth/classroom.courses.readonly`
  - `https://www.googleapis.com/auth/classroom.coursework.students.readonly`
  - `https://www.googleapis.com/auth/classroom.rosters.readonly`
  - `https://www.googleapis.com/auth/drive.readonly`
- Runtime mode:
  - Codex local OAuth:
  - provider-generic API key:

### Classroom Shape

Do not record course names, assignment names, student names, document titles, raw Google IDs, screenshots, or document contents here.

- Course shape:
  - active teacher course:
  - approximate roster size:
  - no private course name recorded:
- Assignment shape:
  - published coursework:
  - written-submission assignment:
  - no private assignment title recorded:

### Sync Counts

- `roster_count`:
- `submitted_count`:
- `imported_count`:
- `blocked_count`:
- `missing_count`:
- `reclaimed_count`:
- `returned_count`:
- `platform_error_count`:
- blocker types:
- unsupported/empty/permission-denied files were not graded as zero-text:

### Pipeline And Review

- Rubric added:
- Assignment outline added:
- Assessment run started:
- Time to `teacher_review_ready`:
- Background validation still running when review became available:
- Normal student reviewed:
  - no private name recorded:
  - action taken:
- Flagged/boundary student reviewed:
  - no private name recorded:
  - flag type:
  - action taken:
- Draft save reload result:
- Final review reload result:

### Export And Evidence

- CSV preflight result:
- CSV export artifact hash:
- Evidence packet hash/id:
- Explicit confirmation no live Classroom write occurred:
  - no `draftGrade` changed:
  - no `assignedGrade` changed:
  - no submission returned:
  - no Classroom comment written:
  - evidence/export action says `external_write_performed: false`:
- Launch validator result:
- Launch validator blockers:

## Owner Procedure

1. Create or choose a Google Cloud project.
2. Enable Google Classroom API and Google Drive API.
3. Configure OAuth consent:
   - Internal for a Workspace domain when possible, otherwise External Testing.
   - Add the owner teacher account as a test user for External Testing.
   - Add app name and support email.
   - Add the exact read scopes used by this app.
   - Note Drive read-only distribution implications.
4. Create a Web OAuth client.
5. Add authorized redirect URI:
   - `http://127.0.0.1:8000/google/auth/callback`
   - optionally `http://localhost:8000/google/auth/callback`
6. Store client secret JSON outside the repo or in an ignored local path.
7. Set env vars:
   - `GOOGLE_OAUTH_CLIENT_ID`
   - `GOOGLE_OAUTH_CLIENT_SECRET`
   - `GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/google/auth/callback`
   - optional `GOOGLE_OAUTH_CLIENT_SECRETS_FILE`
8. Start the app:

   ```bash
   cd marking_framework
   python3 -m uvicorn server.app:app --host 127.0.0.1 --port 8000
   ```

9. Open `http://127.0.0.1:8000`.
10. Create or save a project.
11. Click `Connect Google Classroom`.
12. Authenticate with the owner teacher Google account.
13. Return to the app.
14. Confirm connected status shows the teacher identity.
15. Choose a real low-risk course.
16. Choose a real low-risk published written assignment.
17. Sync submissions.
18. Confirm all sync counts.
19. Confirm blockers have remedies and unsupported/empty/permission-denied files are not graded as zero-text.
20. Add rubric and assignment outline.
21. Connect runtime through Codex local OAuth or provider-generic API mode.
22. Run assessment.
23. Confirm `teacher_review_ready` appears before background validation completes when fast review succeeds.
24. Review one normal student.
25. Review one flagged/boundary student.
26. Save draft.
27. Reload and verify draft persistence.
28. Finalize review.
29. Reload and verify finalized persistence.
30. Run CSV export preflight.
31. Confirm CSV export only after required gates.
32. Download CSV or record artifact hash without committing the CSV.
33. Generate/inspect evidence packet.
34. Confirm no live Google Classroom write occurred.
35. Run launch validator and record that production launch remains blocked unless all launch gates are truly satisfied.
