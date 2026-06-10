# Google Classroom Local OAuth Setup

Status: local owner-run Google Classroom pilot setup, not production launch.

This repository supports a local, teacher-owned, read-only Google Classroom pilot. The app can connect through Google OAuth, list the teacher's active courses, list published coursework, read roster and submissions, export/download supported Drive attachments, materialize supported written work into local project inputs, run the existing assessment pipeline, and produce CSV export evidence. It does not write grades, return submissions, modify attachments, write comments, or write rubric scores to Google Classroom.

Official references:

- [Google OAuth 2.0 for Web Server Applications](https://developers.google.com/identity/protocols/oauth2/web-server)
- [Google Classroom API authorization scopes](https://developers.google.com/workspace/classroom/guides/auth)
- [Google Drive files.export](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/export)
- [Google restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)
- [Google Classroom grade update semantics](https://developers.google.com/workspace/classroom/guides/classroom-api/manage-grades)

## 1. Create Or Choose A Google Cloud Project

Use a project owned by the teacher/operator or the Workspace organization. Do not reuse a production OAuth client for this local pilot unless the Workspace admin explicitly approves that posture.

Enable these APIs:

- Google Classroom API
- Google Drive API

## 2. Configure OAuth Consent

Use Google Auth Platform / OAuth consent:

- Prefer `Internal` when the teacher account belongs to a Google Workspace domain and the app is only for that domain.
- Otherwise use `External` in `Testing` mode and add the owner teacher account as a test user.
- Add app name, support email, and developer contact email.
- Declare the exact scopes below.

Scopes requested by this app:

- `https://www.googleapis.com/auth/classroom.courses.readonly`
  - lists the connected teacher's active courses
- `https://www.googleapis.com/auth/classroom.coursework.students.readonly`
  - lists coursework and reads student submissions for teacher courses
- `https://www.googleapis.com/auth/classroom.rosters.readonly`
  - reads the roster so submissions can be reconciled to students
- `https://www.googleapis.com/auth/drive.readonly`
  - exports Google Docs and downloads supported text/DOCX/PDF/DOC/RTF/HTML attachments

Google's Classroom authorization guide also lists
`https://www.googleapis.com/auth/classroom.student-submissions.students.readonly`
with the same teacher/admin student-work read meaning. The app still requests
`classroom.coursework.students.readonly`, matching the CourseWork and
StudentSubmissions method references, but local status accepts Google's
documented student-submissions grant as satisfying the same read-only pilot
capability. If a later Classroom API call returns `insufficient_scope`, add the
explicit `classroom.coursework.students.readonly` scope to the OAuth consent
screen and reconnect.

Distribution warning: Drive read-only scopes are sensitive/restricted for broader distribution. Public or third-party production use may require Google verification and, for restricted data access from or through a third-party server, a security assessment. This local pilot does not satisfy that production verification requirement.

## 3. Create A Web OAuth Client

Create an OAuth client with application type `Web application`.

Add authorized redirect URIs exactly. Google requires the redirect URI in the request to exactly match one of the client URIs, including scheme, host, path, case, and trailing slash. Localhost HTTP redirect URIs are allowed for local testing.

Recommended redirect URI:

```text
http://127.0.0.1:8000/google/auth/callback
```

Optional alternate if you will start the server and open the UI on localhost:

```text
http://localhost:8000/google/auth/callback
```

Download the client secret JSON only to a local path outside the repository, or to an ignored path. Do not commit it.

## 4. Configure The Local App

Use the committed placeholder file as a template:

```bash
cd /Users/bldt/Desktop/Essays/marking_framework
cp .env.example .env.local
```

Fill local values in `.env.local`, or export them in your shell:

```bash
export GOOGLE_OAUTH_CLIENT_ID=<web-client-id>.apps.googleusercontent.com
export GOOGLE_OAUTH_CLIENT_SECRET=<web-client-secret>
export GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/google/auth/callback
```

The server auto-loads `marking_framework/.env.local` and then
`marking_framework/.env` at startup. Already-exported shell environment
variables win over file values. The loader supports simple `KEY=value`,
quoted values, comments, and blank lines; it never logs values or returns them
to the browser.

Optional local client JSON outside the repo:

```bash
export GOOGLE_OAUTH_CLIENT_SECRETS_FILE=/absolute/path/outside/repo/client_secret.json
```

Optional strict/staging local token encryption:

```bash
export GOOGLE_TOKEN_ENCRYPTION_KEY=<local-token-storage-key>
```

Local token files live under ignored `server/data/google_oauth/`. Without `GOOGLE_TOKEN_ENCRYPTION_KEY`, development mode stores local token data as plaintext under that ignored folder. Strict staging/production must use encrypted local token storage or an approved external secret store.

## 5. Start The Server

```bash
cd /Users/bldt/Desktop/Essays/marking_framework
python3 -m uvicorn server.app:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open:

```text
http://127.0.0.1:8000
```

Use `--no-access-log` for local Google OAuth smoke runs. Uvicorn's default
access log includes the full request target, and OAuth callback request targets
can include short-lived authorization codes.

## 6. Connect, Disconnect, Reconnect

In the UI:

1. Create or save a project.
2. Click `Connect Google Classroom`.
3. Authenticate with the owner teacher Google account.
4. Return to the app.
5. Confirm the status shows `Connected as <teacher email>` or the redacted teacher identity.
6. Choose a real low-risk class.
7. Choose a real low-risk published written assignment.
8. Sync submissions.

Disconnect:

- Click `Disconnect`.
- The server clears local token state and attempts best-effort Google revocation.

Reconnect:

- Click `Reconnect Google` when the app reports missing scopes, rejected refresh, revoked grant, or a changed OAuth client. Ordinary access-token expiry is refreshed automatically before the next live read.

The browser never receives access tokens, refresh tokens, ID tokens, auth codes, client secrets, or raw credential JSON.

## 7. Supported And Blocked Attachments

Supported:

- Google Docs exported as `text/plain`
- `text/plain`
- `text/markdown`
- `text/html` with text extraction
- `application/rtf` through the existing extraction seam
- DOCX/PDF/DOC only when the existing extraction seam returns readable text

Blocked:

- Google Forms
- Google Slides
- Google Sheets
- Google Drawings
- images/scans requiring OCR
- external links
- YouTube attachments
- empty exports/downloads
- no extractable text
- missing Drive scope
- permission denied
- deleted/not-found file
- quota/rate limits
- file/export too large
- unsupported MIME types

Mixed supported and unsupported attachments are blocked as `partial_unsupported_attachments` in this slice. The app does not grade the supported portion until the unsupported attachments are resolved.

Synced Classroom-owned submissions are materialized only under
`inputs/submissions/classroom_import/` and tracked by
`inputs/classroom_import_manifest.json`. Each live or fixture sync is
authoritative for that selected assignment: a different-assignment sync,
zero-import sync, OAuth failure, or Google platform failure clears prior
Classroom-owned imports and writes a non-runnable manifest. Teacher-uploaded
local essays outside that Classroom import area are not deleted by Classroom
sync.

## Common Failure Remedies

`redirect_uri_mismatch`
: Add the exact URI shown in `GOOGLE_OAUTH_REDIRECT_URI` to the Web OAuth client's authorized redirect URIs. `127.0.0.1` and `localhost` are different hosts.

`access blocked` / `app not verified`
: Use Workspace `Internal` mode when possible. For External Testing, add the owner teacher account as a test user and keep the app in Testing until verification is complete.

`missing scope` / `insufficient_scope`
: Reconnect Google and approve all Classroom and Drive read scopes. If the
status page shows Google granted `classroom.student-submissions.students.readonly`
instead of `classroom.coursework.students.readonly`, the local status gate treats
that as satisfying the read-only pilot. A downstream Classroom API
`insufficient_scope` still means the OAuth consent screen/client must include
the explicit coursework read scope before reconnecting.

`API disabled`
: Enable Google Classroom API and Google Drive API in the Google Cloud project used by the OAuth client.

`admin approval required` / `admin blocked app`
: Ask the Workspace admin to approve this OAuth app and scopes for the pilot teacher.

`no courses`
: Confirm the connected account is a teacher in active Google Classroom courses.

`no assignments`
: Confirm the selected course has published coursework. Draft coursework is not shown in the routine teacher flow.

`Drive permission denied`
: Confirm the teacher has access to the submitted attachment in Drive/Classroom.

`no extractable text`
: Open the attachment and verify it contains readable text. Images and scans are not OCRed in this slice.

`No current Classroom imports are ready to assess`
: Resolve sync blockers and resync. The app will not run stale files from an
older assignment, zero-import sync, or failed Google read.

`preflight_stale_rebuild_required`
: Review, validation, sync, blockers, or evidence changed after the CSV
preflight. Rebuild CSV preflight before confirming export.

## Production Boundary

This setup is a local read-only pilot. It does not satisfy `docs/LAUNCH_CONTRACT.md`. Live modes such as `draftGrade`, `assignedGrade`, returning submissions, Classroom comments, rubric score writes, attachment modification, create/update/delete, and live feedback writes remain unavailable and fail-closed.
