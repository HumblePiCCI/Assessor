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
