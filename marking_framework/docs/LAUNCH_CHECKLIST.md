# Launch Checklist

This checklist is the release handoff for the merged `main` branch after the live release-candidate smoke test on a novel Grade 7 cohort.

## Baseline

- Repo: `/Users/bldt/Desktop/Essays`
- Product: `/Users/bldt/Desktop/Essays/marking_framework`
- Branch: `main`
- Release benchmark contract evidence is already tracked in:
  - [/Users/bldt/Desktop/Essays/marking_framework/docs/reports/gpt54_split_full_corpus_with_ontario_release_runs3_2026-04-13.md](/Users/bldt/Desktop/Essays/marking_framework/docs/reports/gpt54_split_full_corpus_with_ontario_release_runs3_2026-04-13.md)
  - [/Users/bldt/Desktop/Essays/marking_framework/docs/reports/gpt54_split_publish_gate_with_ontario_release_2026-04-13.md](/Users/bldt/Desktop/Essays/marking_framework/docs/reports/gpt54_split_publish_gate_with_ontario_release_2026-04-13.md)
  - [/Users/bldt/Desktop/Essays/marking_framework/docs/reports/gpt54_split_sota_gate_with_ontario_release_2026-04-13.md](/Users/bldt/Desktop/Essays/marking_framework/docs/reports/gpt54_split_sota_gate_with_ontario_release_2026-04-13.md)

## Release-Candidate Smoke

Environment:
- Clean FastAPI process started from `/Users/bldt/Desktop/Essays/marking_framework` on `http://127.0.0.1:8002`
- Browser driver: Playwright CLI
- Dataset: [/Users/bldt/Desktop/Essays/7A Ghost Novel, Theme Essays](/Users/bldt/Desktop/Essays/7A%20Ghost%20Novel,%20Theme%20Essays)
- Project: `RC Smoke 7A Ghost 2026-04-15 release`
- Scope ID: `rc-smoke-7a-ghost-2026-04-15-release-22349f`
- Job ID: `d5f00e42f0f8485a9f4e03ef3294baa6`
- Mode: `codex_local`
- Uncached end-to-end runtime: `282.75s` (`4m 42.75s`)

### Functional Checklist

- [x] Start from an empty project on `main`.
- [x] Upload `23` `.docx` essays plus rubric and outline from the novel Grade 7 set.
- [x] Run the full pipeline to completion on a clean server process.
- [x] Render a full ordered cohort and current-essay review surface after scoring.
- [x] Toggle split/compare mode.
- [x] Record a pairwise teacher preference on a live comparison.
- [x] Generate feedback from the live cohort result.
- [x] Change `Top mark` and `Bottom mark` and verify the whole cohort rescales automatically.
- [x] Save draft review state.
- [x] Finalize the teacher review.
- [x] Reload the project and verify persistence of:
  - final level override
  - teacher note
  - pairwise adjudication
  - generated feedback
  - adjusted curve bounds
  - assigned marks derived from the adjusted curve

### Concrete Smoke Evidence

- Full run completed with artifact path:
  - [/Users/bldt/Desktop/Essays/marking_framework/server/data/artifacts/52a258ada1e2f8a4/1cd6bb6e184b1d01f10fe52ebf2b02127e0a3e9587818fad91b3158d7c6ddc3b/outputs/dashboard_data.json](/Users/bldt/Desktop/Essays/marking_framework/server/data/artifacts/52a258ada1e2f8a4/1cd6bb6e184b1d01f10fe52ebf2b02127e0a3e9587818fad91b3158d7c6ddc3b/outputs/dashboard_data.json)
- Finalized teacher review persisted at:
  - [/Users/bldt/Desktop/Essays/marking_framework/server/data/reviews/rc-smoke-7a-ghost-2026-04-15-release-22349f/latest_review.json](/Users/bldt/Desktop/Essays/marking_framework/server/data/reviews/rc-smoke-7a-ghost-2026-04-15-release-22349f/latest_review.json)
- Verified persisted edited essay state on reload for `Alyssa - ghost essay`:
  - level override: `4`
  - teacher note: `RC launch smoke: persisted curve, feedback, and finalized review verified on reload.`
  - assigned mark after persisted curve: `88`
  - persisted curve: `top=96`, `bottom=64`

## Fixed During Smoke

The smoke surfaced one real release issue and it is fixed in code:

- Teacher review persistence originally saved level/pairwise decisions only.
- The saved review bundle now also persists:
  - `curve_top`
  - `curve_bottom`
  - per-student assigned marks
  - generated feedback drafts

Implementation surface:
- [/Users/bldt/Desktop/Essays/marking_framework/server/projects.py](/Users/bldt/Desktop/Essays/marking_framework/server/projects.py)
- [/Users/bldt/Desktop/Essays/marking_framework/server/review_store.py](/Users/bldt/Desktop/Essays/marking_framework/server/review_store.py)
- [/Users/bldt/Desktop/Essays/marking_framework/ui/app.js](/Users/bldt/Desktop/Essays/marking_framework/ui/app.js)
- [/Users/bldt/Desktop/Essays/marking_framework/tests/test_review_store.py](/Users/bldt/Desktop/Essays/marking_framework/tests/test_review_store.py)
- [/Users/bldt/Desktop/Essays/marking_framework/tests/test_server_app.py](/Users/bldt/Desktop/Essays/marking_framework/tests/test_server_app.py)

## Operational Notes

- A stale local server process on port `8000` produced a false negative during an earlier smoke attempt (`consistency` failed with a missing `OPENAI_API_KEY` error even though Codex local mode was available). The clean server process on `8002` completed successfully. Release smoke should be run from a fresh process.
- The live novel cohort does not satisfy the benchmark publish/SOTA gates in local dev mode. That is expected here and does not mean the product path failed. This run is a functional smoke on a new classroom cohort, not a replacement for the tracked benchmark release evidence.
- The completed project reloads with persisted review state and curve state. The top-bar pipeline badge reflects current active job state rather than historical completion state after reload.

## Formal Launch-Contract Check

Command run:

```bash
cd /Users/bldt/Desktop/Essays/marking_framework
python3 scripts/validate_production_launch.py
```

Current local result:
- state: `blocked`
- report path:
  - [/Users/bldt/Desktop/Essays/marking_framework/outputs/production_launch_report.md](/Users/bldt/Desktop/Essays/marking_framework/outputs/production_launch_report.md)

Current blockers are environment/contract blockers for the local dev smoke context:
- `publish_gate_not_ok`
- `publish_profile_below_required`
- `sota_gate_not_ok`
- `sota_profile_below_required`
- `synthetic_calibration_not_allowed`

This validator result should not be interpreted as a regression in the merged benchmark release candidate. It reflects that the live smoke run used:
- local dev identity mode
- synthetic cold-start calibration for a novel scope
- no release benchmark artifact regeneration in the current `outputs/` directory

## Go / No-Go

Functional smoke on `main`:
- Status: `PASS`

Strict launch contract in the local smoke environment:
- Status: `BLOCKED`

## Final Pre-Distribution Checklist

- [x] Merged release candidate branch into `main`
- [x] Benchmarked release corpus and release gate artifacts already tracked in repo
- [x] Novel-cohort empty-project smoke passes end to end on `main`
- [x] Teacher review persistence verified after finalize + reload
- [ ] Regenerate launch validator artifacts in a strict-identity staging or production-like environment
- [ ] Re-run `/Users/bldt/Desktop/Essays/marking_framework/scripts/validate_production_launch.py` in that strict environment
- [ ] Confirm production deployment starts from a fresh server process, not a stale local dev runtime
