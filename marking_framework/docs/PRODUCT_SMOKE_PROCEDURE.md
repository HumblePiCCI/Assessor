# Product Smoke Procedure

Status: human product smoke for the teacher-facing assessment workspace.

Last reviewed: 2026-05-12

Related docs:

- [LAUNCH_CHECKLIST.md](./LAUNCH_CHECKLIST.md)
- [WORKFLOW.md](./WORKFLOW.md)
- [LIVE_COHORT_RUNTIME.md](./LIVE_COHORT_RUNTIME.md)

## Purpose

This smoke verifies the product experience, not the full launch contract.

Pass means a teacher can start from an empty workspace, upload a real class set,
run the assessment, review the ordered cohort, make the few required judgment
calls, generate/edit feedback, finalize, and reload without losing the teacher's
work.

Do not treat this as proof that the product is production-launched, district
approved, or fully connected to Google Classroom. Classroom is currently ready
at the Google Cloud OAuth/API setup layer; in-app Classroom linking and sync are
still a separate implementation surface.

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
- a fresh server process, not an old process left on the same port

## Start The Product

From a terminal:

```bash
cd /Users/bldt/Desktop/Essays/marking_framework
python3 -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

If port `8000` is already occupied, stop the stale process or use another port,
then open the matching URL. A stale server can create false failures.

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

### 4. Run Assessment

Click `Run assessment`.

Expected:

- the pipeline state changes from idle to running
- progress is visible in teacher-readable language
- the app does not require terminal/log inspection while the job runs
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

When the run completes, verify the dashboard has:

- an ordered cohort rail
- current essay text
- a decision snapshot
- suggested level or mark
- uncertainty/disagreement signals when relevant
- teacher review controls beside the current essay

Expected:

- the app says the review is ready, not final
- no grade is exported or published automatically
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

- assigned marks update across the cohort
- the current student's displayed mark updates immediately
- no student loses their relative order merely because the curve changed
- the teacher can see that this is a class-level curve action

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

- save the project if it is unsaved
- create or load another project only if you need to verify separation
- return to the smoke project

Expected:

- saved projects are named clearly
- loading a project restores the right cohort and review state
- clearing a session asks for confirmation
- deleting a project asks for confirmation

Fail if destructive actions are too easy or project identity is unclear.

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

This is not a live in-app Classroom sync yet. It verifies that the external
Google side is ready for the next implementation slice.

Expected current setup:

- Google Cloud project exists for the pilot
- Google Classroom API is enabled
- Google Drive API is enabled
- OAuth consent is in Testing
- the teacher account is listed as a test user
- read-only Classroom and Drive scopes are configured
- a Web OAuth client exists
- localhost redirect URIs are configured for the local product ports
- credentials JSON is stored outside git

Do not commit the credentials JSON or paste the client secret into docs, chat,
or source files.

Pass criteria:

- the OAuth client is visible in Google Auth Platform Clients
- the client secret is enabled
- the downloaded JSON remains local and untracked
- the pilot still uses read-only posture until passback is explicitly built and
  reviewed

Expected blocker:

- the current product UI does not yet present "Connect Google Classroom" as a
  working ingestion path. Until that lands, Classroom verification is limited to
  cloud/API readiness plus product upload-mode smoke.

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
- whether rubric review appeared
- whether anchor calibration appeared
- one normal student reviewed with no override
- one boundary/flagged student reviewed with an override or note
- one pairwise decision
- curve top and bottom values tested
- two edited feedback drafts
- draft reload result
- finalized reload result
- any failure screenshots or exact visible error text

The smoke is complete only when the reload checks pass.
