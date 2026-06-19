# Product Smoke Procedure

Status: human product smoke for the teacher-facing assessment workspace.

Last reviewed: 2026-06-08

Related docs:

- [LAUNCH_CHECKLIST.md](./LAUNCH_CHECKLIST.md)
- [WORKFLOW.md](./WORKFLOW.md)
- [LIVE_COHORT_RUNTIME.md](./LIVE_COHORT_RUNTIME.md)
- [GOOGLE_CLASSROOM_LOCAL_OAUTH_SETUP.md](./GOOGLE_CLASSROOM_LOCAL_OAUTH_SETUP.md)

## Purpose

This smoke verifies the product experience, not the full launch contract.

Pass means a teacher can start from an empty workspace, upload a real class set,
run the assessment, review the ordered cohort, make the few required judgment
calls, generate/edit feedback, finalize, and reload without losing the teacher's
work.

Do not treat this as proof that the product is production-launched or district
approved. Classroom is read-only pilot ready through Google OAuth plus
Classroom/Drive read sync, or through the fixture/local sync path for CI and
local demos. Live Classroom writes remain intentionally blocked.

## Smoke Inputs

Use a low-risk, non-live test cohort.

Recommended local cohort:

- Essays: `/Users/bldt/Desktop/Essays/7A Ghost Novel, Theme Essays`
- Product root: `/Users/bldt/Desktop/Essays/marking_framework`
- Browser URL: `http://127.0.0.1:8000`

The smoke needs:

- multiple student essays, ideally at least 8 and preferably a full class set
- one teacher-owned rubric
- one assignment outline
- either a connected Codex OAuth runtime or a configured API provider key
- Google OAuth configuration for saved-project access and live Classroom read sync
- a fresh server process, not an old process left on the same port

## Start The Product

From a terminal:

```bash
cd /Users/bldt/Desktop/Essays/marking_framework
python3 -m uvicorn server.app:app --host 127.0.0.1 --port 8000 --no-access-log
```

If port `8000` is already occupied, stop the stale process or use another port,
then open the matching URL. A stale server can create false failures.
For Google OAuth smoke runs, keep `--no-access-log` so callback authorization
codes are not written into local server access logs.

## Pass/Fail Rule

Pass only if the teacher can complete the whole path without needing to inspect
raw logs, artifact folders, scripts, or model internals.

Fail the smoke if:

- the first screen does not make the next action obvious
- the teacher has to hunt through more than one secondary panel for a routine
  action
- upload, run, review, feedback, save, finalize, or reload loses state
- a blocked state does not tell the teacher what to fix
- model output can become final without an explicit teacher review/finalize step
- generated feedback cannot be edited before export/copy
- the interface feels crowded enough that the teacher cannot tell what matters

## Procedure

### 1. Load A Clean Workspace

Open `http://127.0.0.1:8000`.

Expected:

- the top bar shows project, connection, and pipeline state
- saved project controls require Google sign-in and do not show another teacher's projects
- the setup area is visible without navigation
- the three required inputs are visible together: essays, rubric, outline
- teacher review controls are hidden or inactive until there is a real result
- no raw technical logs are required to understand the state

Product judgment:

- A teacher should immediately understand: add files, then run assessment.
- Secondary project/connection controls may exist, but they should not dominate
  the screen.

### 2. Verify Runtime Connection

Open the connection controls only if the top bar says the runtime is offline.

Expected:

- `Sign in with Codex` or API-provider key connection reaches a ready state
- the primary run button becomes usable only when required inputs and runtime
  are ready
- connection failures are phrased as remedies, not stack traces

Fail if the teacher has to guess whether the app can run.

### 3. Upload Inputs

Upload:

- all essay files from the test cohort
- the rubric file
- the assignment outline

Expected:

- file counts update immediately
- the ordered cohort rail previews the loaded essays or clearly says no essays
  are loaded yet
- the run button becomes available once all required inputs are present
- unsupported files are visible as blockers, not silently ignored

Product judgment:

- A teacher should not need to navigate away from the first screen to prepare a
  run.

### 3a. Google Classroom Local Read Sync

Use a low-risk teacher-owned Classroom course only. Do not use real
student-private data for committed screenshots, fixtures, raw payloads, or
generated CSVs.

Before the UI smoke, complete
`docs/GOOGLE_CLASSROOM_LOCAL_OAUTH_SETUP.md`:

- create or choose a Google Cloud project
- enable Google Classroom API and Google Drive API
- configure OAuth consent as Workspace Internal or External Testing with the
  owner teacher as a test user
- create a Web OAuth client
- add `http://127.0.0.1:8000/google/auth/callback` as an authorized redirect
  URI, and optionally `http://localhost:8000/google/auth/callback`
- for the hosted smoke route, also add
  `https://assessor.carboncaste.io/google/auth/callback`
- set `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, and
  `GOOGLE_OAUTH_REDIRECT_URI` in an ignored local env file or shell
- keep client secret JSON outside git or in an ignored local path
- restart the server after editing `.env.local`; the app auto-loads
  `.env.local` and `.env` without printing their values

Expected:

- `Connect Google Classroom` opens the Google OAuth flow when the server has
  `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, and
  `GOOGLE_OAUTH_REDIRECT_URI`
- after connection, the app shows not configured, not connected, connected as
  teacher identity, reconnect required, missing scope, admin approval required,
  or API-disabled states in plain language
- the Projects control unlocks only after Google sign-in and shows only
  projects saved by that verified Google account
- the teacher can choose a class and published assignment from dropdowns
- `Sync submissions` imports supported attachments into the ignored local
  workspace under `inputs/submissions/classroom_import/` and records the
  current manifest in `inputs/classroom_import_manifest.json`
- Classroom-owned imports are materialized with local system IDs such as
  `s001.txt`; the routine review UI should show first-name labels plus those
  local IDs, not raw Google numeric user IDs or student last names
- counts show roster, submitted, imported, blocked, missing, reclaimed,
  returned, and platform-error counts
- blockers appear in Exceptions with remedies
- zero imported submissions is a blocked/warn state, not green success
- a zero-import sync, failed Google/OAuth sync, or sync for a different
  assignment clears prior Classroom-owned imports so stale work cannot run
- unsupported, empty, permission-denied, no-OCR, external-link, missing-scope,
  quota, and API-disabled cases are blockers and are not graded as zero-text
  essays
- the run button becomes available when runtime, rubric, outline, and either
  local uploads or synced Classroom submissions are ready
- the Classroom card states that no live Classroom write occurred

Fail if raw OAuth tokens, raw Google file IDs, stack traces, or queue internals
are exposed in the routine path.

### 4. Run Assessment

Click `Run assessment`.

Expected:

- the pipeline state changes from idle to running
- progress is visible in teacher-readable language
- the review-ready dashboard loads as soon as the fast review phase succeeds
- for a large first pass, the UI keeps polling the live job and shows the
  current backend stage instead of declaring a client-side timeout
- the app does not require terminal/log inspection while the job runs
- background validation continues after the review dashboard appears
- Classroom-imported submissions can run without downloading and re-uploading
  essays
- if the rubric interpretation needs confirmation, the rubric review panel
  appears in the main workflow
- if anchor calibration is required, the anchor panel appears with clear
  candidates and controls

If rubric review appears:

- read the interpretation summary
- confirm it if it matches the assignment
- correct it if it materially misreads criteria, levels, genre, or task
- reject only if the app cannot recover the contract

If anchor calibration appears:

- assign the requested anchor levels or marks
- apply anchors
- verify the pipeline resumes

Pass only if every pause is actionable from the UI.

### 5. Confirm Review-Ready Dashboard

When the app reports review ready, verify the dashboard has:

- an ordered cohort rail
- current essay text
- a decision snapshot
- suggested level or mark
- uncertainty/disagreement signals when relevant
- teacher review controls beside the current essay

Expected:

- the app says the review is ready, not final
- if validation is still running, the app says: "Review ready. SOTA validation
  is checking edge cases in the background."
- if validation completes, the state changes to "Validation complete."
- if validation finds exceptions, the Exceptions panel lists the cases to inspect
- no grade is exported or published automatically
- no live Google Classroom write occurs
- the teacher can move through students with the rail and next/previous controls
- the teacher can understand why the current essay is placed where it is

Product judgment:

- The product should now feel like a focused review desk, not a data dump.

### 6. Review A Normal Student

Pick one student that looks uncontroversial.

Do:

- read the decision snapshot
- skim the essay
- leave the suggested level alone if it is reasonable
- add no teacher note unless something important was missed

Expected:

- "do nothing" is a valid fast path for normal cases
- the teacher is not forced to fill unnecessary fields

Fail if every student feels like a form to complete.

### 7. Review A Flagged Or Boundary Student

Pick one student with an uncertainty flag, boundary placement, or surprising
mark.

Do at least one of:

- change final level
- add a teacher note
- set evidence signal
- set teacher rank only if placement is materially wrong

Expected:

- the changed student visibly reflects the teacher decision
- the note field is easy to find but does not dominate the screen
- the teacher can distinguish model suggestion from teacher override

### 8. Run A Pairwise Check

Click `Compare`.

Expected:

- the current essay and comparison essay are visible side by side
- pairwise controls appear in the teacher review panel
- the teacher can select either:
  - `Keep current above compare`
  - `Move compare above current`

Do:

- make one pairwise decision
- verify the pairwise status changes
- turn compare mode off and back on

Pass only if the decision is still visible after toggling compare mode.

### 9. Adjust The Curve

Change the class curve:

- set `Top mark` to a different value
- set `Bottom mark` to a different value

Expected:

- assigned marks update across the cohort from the original assessment order
- the top-ranked essay receives the top mark, the bottom-ranked essay receives
  the bottom mark, and essays between them are re-spaced by the original
  assessment rank
- the current student's displayed mark updates immediately
- no student loses their relative order merely because the curve changed
- the teacher can see that this is a class-level curve action
- invalid bounds, such as a top mark below the bottom mark, show a teacher-facing
  warning instead of silently changing marks

Fail if the curve looks like a hidden global side effect.

### 10. Generate And Edit Feedback

For at least two students:

- click `Generate feedback`
- edit Star 1, Star 2, and Wish
- use `Copy feedback` for one student

Expected:

- feedback is draft text, not final text
- the teacher can edit before copying/exporting
- feedback stays attached to the correct student while navigating
- no feedback is sent outside the product automatically

Fail if feedback feels like an unreviewed publication action.

### 11. Save Draft Review

Click `Save draft`.

Expected:

- the draft status updates with a saved timestamp or equivalent saved state
- teacher level overrides, notes, pairwise decisions, curve bounds, assigned
  marks, and feedback drafts are included in the draft

Then reload the browser.

Expected after reload:

- the same project/result loads or can be reloaded from Projects
- the draft teacher decisions are still present
- the curve bounds and generated feedback are still present

Fail if reload loses any teacher-authored work.

### 12. Finalize Review

Click `Finalize review`.

Expected:

- the app records a finalized review state
- the finalized state is visibly different from draft state
- local learning summary updates only from finalized review data
- the teacher remains the actor who finalized the result

Reload again.

Expected after reload:

- finalized review state persists
- final level override persists
- teacher note persists
- pairwise decision persists
- feedback draft persists
- curve bounds and assigned marks persist

Fail if finalization is reversible by accident, invisible, or not durable.

### 13. Project Persistence Check

Use the project controls:

- sign in with Google first; anonymous browsers and header-only requests must
  not list, load, save, or run saved projects
- save the project if it is unsaved
- create another project only after the current pass has been saved or
  auto-saved by the app
- return to the smoke project

Expected:

- saved projects are named clearly
- switching Google accounts changes the project list to that account's scoped
  projects only
- starting a new project preserves the currently loaded pass before the
  workspace is cleared for another class set
- loading a project restores the right cohort and review state
- clearing a session asks for confirmation
- deleting a project asks for confirmation

Fail if a teacher can accidentally lose a loaded pass while starting another
class set.

### 14. Minimalist UX Check

Before calling the smoke good, scan the whole workflow as a teacher.

Pass criteria:

- routine path is one step away: upload, run, compare, review, feedback,
  save/finalize
- advanced controls are available but visually secondary
- teacher-facing states are short and concrete
- the current essay, teacher decision, and next action stay balanced on screen
- the interface avoids making the teacher understand queue internals, model
  routing, file paths, or launch gates

Fail if the product feels powerful but cognitively expensive.

## Google Classroom Readiness Smoke

This is not a live Classroom write/passback smoke. It verifies the read-only
pilot path and the external Google setup posture.

Expected current setup:

- Google Cloud project exists for the pilot
- Google Classroom API is enabled
- Google Drive API is enabled
- OAuth consent is Internal for a Workspace domain where possible, otherwise
  External Testing
- the teacher account is listed as a test user when External Testing is used
- read-only Classroom and Drive scopes are configured
- a Web OAuth client exists
- exact redirect URI is configured:
  - `http://127.0.0.1:8000/google/auth/callback`
  - optionally `http://localhost:8000/google/auth/callback`
- credentials JSON is stored outside git
- the in-app `Connect Google Classroom` flow succeeds for the owner teacher
- live courses and published assignments are listed from the connected account
- `Sync submissions` imports supported written submissions into
  `inputs/submissions`
- the review rail, essay title, exceptions, anchor calibration, feedback copy,
  and CSV/export preview identify Classroom work with first-name-plus-local-ID
  labels such as `First - s001`, not raw Google numeric IDs
- unsupported links, Forms/Slides/Sheets/drawings, image/OCR gaps, missing Drive
  scope, permission denial, API-disabled, quota, file-too-large, and empty
  extraction become blockers
- `POST /pipeline/v2/run-project-inputs` can score Classroom-imported
  submissions without local essay re-upload
- CSV preflight/export is available only after finalized teacher review,
  current validation, clear blockers, generated evidence, and explicit request
- CSV export confirmation rejects a preflight generated before a later teacher
  edit, validation change, Classroom resync, blocker change, or evidence change;
  rebuild CSV preflight before confirming export

Do not commit the credentials JSON or paste the client secret into docs, chat,
source files. Do not commit downloaded submissions, private screenshots, raw
Google payloads, real generated CSVs, or real student names in smoke reports.
Do not record student last names; local smoke notes should use only redacted
labels or first-name-plus-local-ID labels.

Pass criteria:

- the OAuth client is visible in Google Auth Platform Clients
- the client secret is enabled
- the downloaded JSON remains local and untracked
- the pilot still uses read-only posture until passback is explicitly built and
  reviewed
- no live Classroom write occurs
- evidence/export actions record `external_write_performed: false`

## Operator Checks After The Product Smoke

These checks are useful after the human product walk-through, but they are not
substitutes for it.

Run unit tests or targeted tests relevant to the changed surface:

```bash
cd /Users/bldt/Desktop/Essays/marking_framework
python3 -m pytest
```

Run the launch validator only when you want the strict launch-contract answer:

```bash
cd /Users/bldt/Desktop/Essays/marking_framework
python3 scripts/validate_production_launch.py
```

A local dev smoke may pass while the launch validator remains blocked by
release, identity, privacy, benchmark, or calibration requirements. That is not
a contradiction. The product smoke answers whether the teacher workflow works;
the launch validator answers whether the environment satisfies the production
contract.

## Evidence To Capture

Record:

- date and branch
- server URL and port
- dataset used
- runtime mode
- API provider status/proof
- time to teacher-review-ready
- time to background validation complete
- whether teacher review was available while validation was still running
- whether rubric review appeared
- whether anchor calibration appeared
- Classroom read/sync pilot result
- first-name-plus-local-ID label check; no raw Google numeric IDs in the
  routine review UI
- export/passback preflight result
- CSV preflight timestamp/hash and whether confirmation used that current
  preflight
- confirmation that no live Classroom write occurred
- launch validator result and blockers
- one normal student reviewed with no override
- one boundary/flagged student reviewed with an override or note
- one pairwise decision
- curve top and bottom values tested
- two edited feedback drafts
- draft reload result
- finalized reload result
- any failure screenshots or exact visible error text

The smoke is complete only when the reload checks pass.
