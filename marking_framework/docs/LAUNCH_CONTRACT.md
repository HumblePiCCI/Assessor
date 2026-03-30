# Launch Contract

This repo is launchable only when the production contract is satisfied in code, artifacts, and runtime configuration.

## Authoritative Sources

- `config/accuracy_gate.json`
- `config/sota_gate.json`
- `scripts/validate_production_launch.py`
- `scripts/release_rollback.py`

## Required Runtime Posture

- Runtime mode: `production` or `staging`
- Strict identity headers:
  - `x-tenant-id`
  - `x-teacher-id`
  - `x-teacher-role`
- Project ownership enforced per teacher, with tenant-scoped admin visibility
- Queued job workspaces isolated under `server/data/workspaces/<tenant>/<job_id>`
- Manifest-keyed artifacts isolated under `server/data/artifacts/<tenant>/<manifest_hash>`
- Teacher workspace state isolated under `server/data/tenant_workspaces/<tenant>/<teacher>/workspace`

## Required Release Bars

- Publish gate: `release`
- SOTA gate: `release`
- Benchmark dataset coverage: at least 3 explicit-gold datasets
- Calibration freshness: no older than 168 hours
- Privacy posture: `governed_finalized_anonymized`

## Required Ops Controls

- Queue depth and latency visible from `/pipeline/v2/ops/status`
- Cache validation failures tracked and treated as launch blockers
- Gate failure summaries persisted in queue ops state
- Retention maintenance available from `/pipeline/v2/ops/maintenance`
- Incident runbook present in [INCIDENT_RESPONSE.md](/Users/bldt/Desktop/Essays/marking_framework/docs/INCIDENT_RESPONSE.md)

## Required Validation

Run:

```bash
cd /Users/bldt/Desktop/Essays/marking_framework
python3 scripts/validate_production_launch.py
```

Expected outputs:

- `outputs/production_launch_report.json`
- `outputs/production_launch_report.md`

Launch is blocked if the report is not `ok: true`.

## Required Rollback Readiness

Every release candidate must be able to generate a rollback plan:

```bash
cd /Users/bldt/Desktop/Essays/marking_framework
python3 scripts/release_rollback.py --reason prompt_regression --target-git-sha <known-good-sha>
```

Expected outputs:

- `outputs/release_rollback_plan.json`
- `outputs/release_rollback_plan.md`

## Go / No-Go Rule

This product is not launch-ready because someone says it is. It is launch-ready only when:

- the gate artifacts pass
- the launch validator passes
- the rollback plan is producible
- the deployment environment enforces the strict identity contract
