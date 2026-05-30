# Google Classroom Local Setup

This is the local-only setup path for a teacher-owned Google Classroom smoke.
It enables read sync from Google Classroom and Drive into Assessor. It does not
enable live grade writes, comments, returns, or rubric-score writes.

## 1. Create Google Cloud OAuth Credentials

1. Create or choose a Google Cloud project.
2. Enable the Google Classroom API.
3. Enable the Google Drive API.
4. Configure the OAuth consent screen. For a local pilot, keep the app in
   Testing mode and add the teacher account as a test user.
5. Create an OAuth client with application type `Web application`.
6. Add this authorized redirect URI exactly:

```text
http://127.0.0.1:8000/google/auth/callback
```

If you will open the server as `localhost`, add this as a separate redirect
URI:

```text
http://localhost:8000/google/auth/callback
```

Google treats redirect URIs as exact values. Scheme, host, port, path, and
trailing slash behavior must match the server setting.

7. Download the client JSON outside the repository. Do not commit it.

Relevant Google docs:

- OAuth web-server flow: https://developers.google.com/identity/protocols/oauth2/web-server
- OAuth sensitive-scope verification: https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification
- Classroom courses: https://developers.google.com/workspace/classroom/reference/rest/v1/courses/list
- Classroom coursework: https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWork/list
- Classroom submissions: https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWork.studentSubmissions/list
- Classroom rosters: https://developers.google.com/workspace/classroom/reference/rest/v1/courses.students/list
- Drive export: https://developers.google.com/workspace/drive/api/reference/rest/v3/files/export
- Drive file get/download: https://developers.google.com/workspace/drive/api/reference/rest/v3/files/get

## 2. Configure Local Environment

Copy `.env.google.example` to an untracked local file such as `.env.google` or
`.env.local`, then fill in values:

```bash
GOOGLE_OAUTH_CLIENT_ID=<client-id>
GOOGLE_OAUTH_CLIENT_SECRET=<client-secret>
GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/google/auth/callback
GOOGLE_OAUTH_CLIENT_SECRETS_FILE=/absolute/path/outside/repo/client_secret.json
GOOGLE_TOKEN_ENCRYPTION_KEY=<local-key-required-for-strict-runtime>
```

Notes:

- `.env`, `.env.local`, `.env.google`, `.env.google.local`,
  `client_secret*.json`, and `google_oauth_client*.json` are ignored by git.
- `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` can be supplied
  directly, or loaded from `GOOGLE_OAUTH_CLIENT_SECRETS_FILE`.
- `GOOGLE_TOKEN_ENCRYPTION_KEY` is optional for local development, but strict
  staging/production must use encrypted local storage or an approved secret
  store.
- Token files live under ignored `server/data/google_oauth/`.

## 3. Run The Setup Checker

From `marking_framework`:

```bash
python3 scripts/google_classroom_setup_check.py
```

For JSON output:

```bash
python3 scripts/google_classroom_setup_check.py --json
```

The report is intentionally redacted. It prints:

- configured or missing OAuth variables
- redirect URI and callback URL
- required read-only scopes
- token-store path and strict-mode encryption status
- whether local env files and token state are ignored by git

It does not print client secrets, access tokens, refresh tokens, or downloaded
Google credential JSON.

The server exposes the same redacted report at:

```text
GET /google/auth/preflight
```

## 4. Start The Local Product

Load your local env file in your shell, then run:

```bash
cd marking_framework
python3 -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/
```

Use `docs/GOOGLE_CLASSROOM_LIVE_SMOKE.md` for the end-to-end smoke checklist.

## Scope And Verification Notes

This integration requests read-only Classroom scopes for courses, coursework,
student submissions, and rosters, plus Drive read-only access for attachment
export/download. Public or distributed use with sensitive or restricted scopes
may require Google verification, security assessment, or Workspace admin trust.
Google may report the granted Classroom submissions capability as
`classroom.student-submissions.students.readonly`; Assessor treats that returned
grant as satisfying the coursework/submissions read requirement.

Live Classroom writes remain fail-closed in this repository. CSV export is the
passback path for this pilot slice.
