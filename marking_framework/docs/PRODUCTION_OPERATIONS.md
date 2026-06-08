# Production Operations

## Runtime Modes

- `development`: shared local workspace, relaxed identity defaults
- `staging` and `production`: strict identity required, tenant-scoped workspaces and project state

## Isolation Model

- Queue jobs:
  - `server/data/pipeline_jobs/<tenant>/<job_id>`
- Job workspaces:
  - `server/data/workspaces/<tenant>/<job_id>`
- Cached artifacts:
  - `server/data/artifacts/<tenant>/<manifest_hash>`
- Teacher workspaces:
  - `server/data/tenant_workspaces/<tenant>/<teacher>/workspace`
- Projects:
  - `projects/<tenant>/projects/<project_id>`
- Current project selection:
  - `projects/<tenant>/current/<teacher>.json`
- Google OAuth state and tokens:
  - `server/data/google_oauth/<tenant>/<teacher>/<project>/token.json`
  - ignored by git and never copied to outputs or project snapshots

## Google OAuth Operations

Google Classroom read sync is configured only through environment/local config:

```bash
export GOOGLE_OAUTH_CLIENT_ID=<client-id>
export GOOGLE_OAUTH_CLIENT_SECRET=<client-secret>
export GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/google/auth/callback
# optional local untracked Google client JSON
export GOOGLE_OAUTH_CLIENT_SECRETS_FILE=/path/to/client_secret.json
# required for strict staging/production local token storage, unless an
# approved external secret store replaces local token files
export GOOGLE_TOKEN_ENCRYPTION_KEY=<local-token-key>
```

Use `.env.example` only as a placeholder template. Real `.env`, `.env.local`,
client secret JSON, tokens, downloaded submissions, raw Google payloads, and
real export CSVs are ignored local artifacts and must not be committed.

Operational endpoints:

- `GET /google/auth/status`
- `POST /google/auth/start`
- `GET /google/auth/callback`
- `POST /google/auth/disconnect`

Status responses are intentionally redacted: configured, connected,
expired/expiring, granted scopes, missing scopes, expiry, teacher display/hash,
storage posture, and remediation only. Raw access tokens, refresh tokens, ID
tokens, auth codes, client secrets, Google credential JSON, and student-private
screenshots must not be committed or returned to the browser.

Before each live Classroom/Drive read, the server refreshes expired or
near-expiry access tokens. Refresh failure returns a reconnect-required blocker
and prevents the stale token from being used against Google APIs.

Strict staging/production launch remains blocked unless token storage is
encrypted with an approved key path or delegated to an approved secret store.
This slice does not enable live Classroom writes. CSV export records
`external_write_performed: false`; live grade, return, comment, rubric-score,
attachment modification, create, update, and delete endpoints remain
unavailable/fail-closed.

## Observability

Use:

```bash
curl -H 'x-tenant-id: <tenant>' -H 'x-teacher-id: <admin>' -H 'x-teacher-role: admin' \
  http://localhost:8000/pipeline/v2/ops/status
```

The response is expected to include:

- queue depth
- queued/running/completed/failed job counts
- mean and p95 job latency
- cache hits, misses, and validation failures
- recent gate failures
- recent incidents
- retention policy
- warning flags when queue depth or latency exceed contract thresholds

## Retention

Current defaults from the production contract:

- jobs: 14 days
- workspaces: 7 days
- artifacts: 30 days

Run maintenance:

```bash
curl -X POST -H 'x-tenant-id: <tenant>' -H 'x-teacher-id: <admin>' -H 'x-teacher-role: admin' \
  'http://localhost:8000/pipeline/v2/ops/maintenance?dry_run=true'
```

Use `dry_run=false` only after reviewing the report.

## Degraded Mode

Treat the service as degraded if any of these are true:

- queue depth warning is active
- p95 job latency warning is active
- cache validation failures are nonzero
- recent gate failures spike above the incident threshold

In degraded mode:

1. pause new releases
2. capture queue ops state
3. validate current launch readiness
4. prepare rollback if the issue is tied to a release change
