# Incident Response

## Trigger Conditions

Open an incident when any of the following happen:

- publish or SOTA gate regressions after a release
- queue depth or latency exceeds the production contract and remains elevated
- cache validation failures appear
- calibration freshness or scope validity is broken in release traffic
- teacher/project isolation is violated or suspected

## Immediate Actions

1. Freeze new releases.
2. If the issue is release-induced, stop routing new work to the bad candidate.
3. Capture:
   - `outputs/publish_gate.json`
   - `outputs/sota_gate.json`
   - `outputs/benchmark_report.json`
   - `server/data/pipeline_ops.json`
   - the active `pipeline_manifest.json`
4. Run the launch validator:

```bash
cd /Users/bldt/Desktop/Essays/marking_framework
python3 scripts/validate_production_launch.py
```

5. Generate a rollback plan:

```bash
cd /Users/bldt/Desktop/Essays/marking_framework
python3 scripts/release_rollback.py --reason <incident-reason> --target-git-sha <known-good-sha>
```

## Rollback Decision

Rollback when:

- launch validation is blocked by a new release regression
- release gates are no longer satisfied
- latency or failure posture cannot be recovered without reverting model, prompt, or config changes

## Reopen Conditions

Do not reopen traffic until all of the following are true:

- rollback or fix is deployed
- benchmark, publish, and SOTA gates pass on the candidate in place
- launch validation returns `ok: true`
- queue ops warnings are cleared or explicitly accepted for the current window
