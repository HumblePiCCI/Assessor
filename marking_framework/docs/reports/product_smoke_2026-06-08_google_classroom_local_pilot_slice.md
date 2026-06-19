# Product Smoke: Google Classroom Local Pilot Slice

Status: implementation verified with mocks/fixtures; manual live owner smoke pending.

This report intentionally contains no real student names, document titles, raw Google IDs, screenshots, downloaded student work, OAuth tokens, client secrets, auth codes, raw Google payloads, or generated CSVs from real students.
For Classroom review labels, record only the fact that first-name-plus-local-ID
labels were visible, for example `First - s001`; do not record student last
names.

## Implementation Verification

- Date: 2026-06-08
- Branch: `codex/google-classroom-local-pilot-smoke`
- Hardening branch: `codex/google-classroom-local-pilot-smoke-hardening`
- Hardening starting commit verified: `94acf0efdd8fb2686034e583aeade67e758d0a32`
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

Timeout/source-isolation patch verification on 2026-06-17:

```bash
cd marking_framework
python3 -m pytest -q --no-cov tests/test_server_app.py tests/test_server_pipeline.py tests/test_server_pipeline_v2.py tests/test_classroom_live_read_sync.py tests/test_classroom_product.py tests/test_pipeline_queue.py
python3 -m pytest -q --no-cov
python3 -m pytest -q --no-cov tests/test_google_oauth.py tests/test_google_classroom_adapter.py tests/test_google_drive_adapter.py tests/test_classroom_live_read_sync.py tests/test_classroom_product.py tests/test_pipeline_queue.py tests/test_server_app.py
node --check ui/app.js
python3 scripts/validate_production_launch.py
```

Timeout/source-isolation patch result:

- server/Classroom/queue focused pytest: passed
- full pytest: passed
- required focused pytest: passed
- UI syntax: passed
- production launch validator: blocked as expected by real launch gates
  - `publish_gate_missing`
  - `sota_gate_missing`
  - `calibration_manifest_missing`

First-name label/privacy patch verification on 2026-06-17:

```bash
cd marking_framework
python3 -m pytest -q --no-cov tests/test_server_app.py tests/test_classroom_product.py tests/test_classroom_live_read_sync.py
python3 -m pytest -q --no-cov tests/test_google_oauth.py tests/test_google_classroom_adapter.py tests/test_google_drive_adapter.py tests/test_classroom_live_read_sync.py tests/test_classroom_product.py tests/test_pipeline_queue.py tests/test_server_app.py
python3 -m pytest -q --no-cov
node --check ui/app.js
python3 scripts/validate_production_launch.py
```

First-name label/privacy patch result:

- Classroom/product focused pytest: passed
- required focused pytest: passed
- full pytest: passed
- UI syntax: passed
- production launch validator: blocked as expected by real launch gates
  - `publish_gate_missing`
  - `sota_gate_missing`
  - `calibration_manifest_missing`
- Classroom-owned imports now materialize as local `s001.txt` style files and
  dashboards prefer first-name-plus-local-ID labels.
- `/data.json` hydrates older numeric dashboard labels from sanitized
  Classroom state so an already-run local review becomes readable after refresh.
- Public Classroom state and metadata used by the routine UI avoid student last
  names; raw Google numeric IDs are not used as teacher-facing labels.

Hardening coverage added for the final local pilot smoke patch:

- `.env.local` and `.env` are auto-loaded at server startup and by
  `GoogleOAuthService` without overriding exported env vars or exposing values
  in `/google/auth/status`.
- Classroom-owned imports are written only under
  `inputs/submissions/classroom_import/` and tracked by
  `inputs/classroom_import_manifest.json`.
- Different-assignment, zero-import, OAuth failure, and Google platform failure
  syncs clear prior Classroom-owned imports and make
  `/pipeline/v2/run-project-inputs` reject stale work.
- CSV export confirmation recomputes the preflight freshness hash before
  writing a CSV and rejects stale preflights with
  `preflight_stale_rebuild_required`.
- Local teacher-owned Classroom imports, generated dashboards, manifests, and
  run outputs are published to ignored
  `server/data/tenant_workspaces/<tenant>/<teacher>/workspace/`; the checked-out
  source tree remains a read-only runtime dependency and is not used as the
  live project workspace.
- Saved local project snapshots default to ignored `server/data/projects/`;
  legacy ignored `projects/` snapshots are migrated forward when the new store
  is empty.
- Saved projects, active workspaces, run state, Classroom state, and export
  state require the HttpOnly Google session cookie and are scoped by the
  verified Google identity hash; anonymous/header-only project access returns
  `google_sign_in_required`.
- Large first-pass assessment runs keep polling the backend job after the old
  client-side timeout threshold and show the current stage instead of falsely
  marking a healthy running job as failed.

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
  - `https://assessor.carboncaste.io/google/auth/callback`
  - other:
- Scopes requested:
  - `openid`
  - `email`
  - `https://www.googleapis.com/auth/classroom.courses.readonly`
  - `https://www.googleapis.com/auth/classroom.coursework.students.readonly`
  - `https://www.googleapis.com/auth/classroom.rosters.readonly`
  - `https://www.googleapis.com/auth/drive.readonly`
- Runtime mode:
  - Codex local OAuth:
  - provider-generic API key:
- Project access evidence:
  - anonymous `/projects` blocked:
  - signed-in teacher can list own projects:
  - different Google account cannot see this teacher's saved projects:

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
- current Classroom import manifest hash:
- stale prior Classroom imports absent after latest sync:
- Classroom-owned source files used local IDs such as `s001.txt`:
- routine review UI showed first-name-plus-local-ID labels, not raw Google
  numeric IDs:
- student last names absent from smoke notes/artifacts:
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
- Curve bounds tested:
  - top mark:
  - bottom mark:
  - rank order preserved:
  - invalid-bound warning checked:

### Export And Evidence

- CSV preflight result:
- CSV preflight timestamp:
- CSV preflight freshness hash:
- CSV preflight row hash:
- CSV preflight was rebuilt after any teacher edit/validation change/sync/blocker/evidence change:
- CSV export artifact hash:
- final CSV confirmation action hash/id:
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
   - for hosted smoke, `https://assessor.carboncaste.io/google/auth/callback`
6. Store client secret JSON outside the repo or in an ignored local path.
7. Set env vars:
   - `GOOGLE_OAUTH_CLIENT_ID`
   - `GOOGLE_OAUTH_CLIENT_SECRET`
   - `GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/google/auth/callback`
   - optional `GOOGLE_OAUTH_CLIENT_SECRETS_FILE`
8. Start the app:

   ```bash
   cd marking_framework
   python3 -m uvicorn server.app:app --host 127.0.0.1 --port 8000 --no-access-log
   ```

9. Open `http://127.0.0.1:8000`.
10. Click `Connect Google Classroom`.
11. Authenticate with the owner teacher Google account.
12. Return to the app.
13. Confirm connected status shows the teacher identity.
14. Confirm the Projects control unlocks and shows only this Google account's projects.
15. Create or save a project.
16. Choose a real low-risk course.
17. Choose a real low-risk published written assignment.
18. Sync submissions.
19. Confirm all sync counts.
20. Confirm Classroom-owned imports use local IDs such as `s001.txt`, and the
    review rail/title/exceptions/anchor panel show first-name-plus-local-ID
    labels rather than raw Google numeric IDs or student last names.
21. Confirm blockers have remedies and unsupported/empty/permission-denied files are not graded as zero-text.
22. Add rubric and assignment outline.
23. Connect runtime through Codex local OAuth or provider-generic API mode.
24. Run assessment.
25. Confirm `teacher_review_ready` appears before background validation completes when fast review succeeds.
26. Review one normal student.
27. Review one flagged/boundary student.
28. Save draft.
29. Reload and verify draft persistence.
30. Finalize review.
31. Reload and verify finalized persistence.
32. Run CSV export preflight.
33. Confirm CSV export only after required gates. If any teacher edit,
    validation refresh, Classroom resync, blocker change, or evidence change
    happens after preflight, rebuild preflight before confirming export.
34. Download CSV or record artifact hash without committing the CSV.
35. Generate/inspect evidence packet.
36. Confirm no live Google Classroom write occurred.
36. Run launch validator and record that production launch remains blocked unless all launch gates are truly satisfied.
