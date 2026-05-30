# Product Smoke - Google Classroom Live Smoke Ready

Date: 2026-05-29 EDT / 2026-05-30 UTC
Branch: `codex/google-classroom-live-smoke-ready`
Base commit: `origin/main@c30017db`
Head commit at smoke start: `d5ecdb0`
Runtime mode: local FastAPI server, `codex_local` assessment mode, live Google Classroom read-only sync.

## CI Mocked Proof

- Pytest command:
  `python3 -m pytest -q marking_framework/tests/test_assessor_context.py marking_framework/tests/test_rubric_contract.py marking_framework/tests/test_llm_assessors_core.py marking_framework/tests/test_run_llm_assessors_main.py marking_framework/tests/test_product_smoke_ui_contract.py marking_framework/tests/test_extract_text.py marking_framework/tests/test_build_dashboard_data.py marking_framework/tests/test_verify_consistency.py marking_framework/tests/test_escalate_pairwise_adjudications.py marking_framework/tests/test_pipeline_queue.py marking_framework/tests/test_classroom_product.py`
- Pytest result: passed.
- UI syntax command: `node --check marking_framework/ui/app.js`
- UI syntax result: passed.
- Whitespace check: `git diff --check`, passed.
- Full suite command: `cd marking_framework && python3 -m pytest -q --no-cov`
- Full suite result: blocked by 5 `tests/test_source_calibration.py` failures from a pre-existing deleted tracked calibration source:
  `inputs/calibration_sources/writing_assessment_sources.json`.
- Google API calls used in CI: none, mocked transports only.
- Credentials/tokens/student data committed: no.

## Manual Live Local Proof

- Live Google used: yes.
- Teacher account: redacted.
- OAuth config readiness: configured, secrets redacted.
- Redirect URI used: `http://127.0.0.1:8001/google/auth/callback`.
- Course selected: redacted teacher course.
- Assignment selected: redacted Ghost essay assignment.
- Roster count: 29.
- Submission count: 29.
- Imported submission count: 21.
- Blocker count: 8.
- Attachment cases encountered:
  - Google Doc: imported where Drive export returned readable text.
  - DOCX: supported by the import pipeline.
  - PDF: unsupported for this live run without extractable text.
  - text/Markdown/HTML/RTF: supported by the import pipeline.
  - Forms/Slides/Sheets/Drawings: fail-closed unsupported attachments.
  - image-only: blocked as no extractable text.
  - external links: fail-closed unsupported attachments.
  - permission denied: fail-closed if encountered.
  - empty export: blocked as no extractable text.
- Time to `teacher_review_ready`: 20m 48s for the 21 imported essays.
- Time to validation complete after review-ready: 1h 4m 20s.
- Total time from run start to validation complete: 1h 25m 8s.
- Final job status: `completed`.
- Final product phase: `validation_failed_nonblocking`.
- Validation status: `failed_nonblocking`; 3 validation exceptions.
- Proof review was available while validation was still running: yes.
- Proof review remained available after validation failed nonblocking: yes.
- Export/passback readiness after validation: blocked, as expected, because validation attention and 8 attachment blockers remain.
- Draft save/reload result: not mutated during live smoke; local draft/final persistence is covered by tests.
- Final review/reload result: not mutated during live smoke; local draft/final persistence is covered by tests.
- CSV preflight result: not run against the live Classroom cohort because validation attention and 8 attachment blockers remain.
- CSV confirmation/download result: not run against the live Classroom cohort because validation attention and 8 attachment blockers remain.
- CSV artifact SHA-256: not produced.
- Evidence packet export action/hash recorded: not produced.
- Confirmation no live Google write occurred: yes; Classroom passback remains CSV/read-only and `external_write_performed` stayed false.

## Background Validation Outcome

- Consistency checking completed and wrote `outputs/consistency_checks.json`.
- Pairwise escalation completed with 203 candidate checks, 44 selected hard pairs, 44 escalations, and 159 skipped pairs.
- Final rerank completed with pairwise agreement of 0.89589 against the final order.
- Nonblocking validation exception: pairwise eval failed because `evals/pairwise/ghost_literary_hard_pairs.json` had an empty expected pairs list.
- Publish gate failed in the local dev profile for expected launch-only artifacts/calibration requirements:
  `benchmark_report_missing`, `calibration_scope_mismatch`,
  `calibration_scope_observations_below_threshold`,
  `calibration_scope_samples_below_threshold`, `calibration_synthetic_not_allowed`,
  `pairwise_eval_escalated_path_missing`, `pairwise_eval_report_missing`,
  and `reproducibility_report_missing`.
- SOTA gate failed because publish was not green and the run used the dev profile:
  `benchmark_report_missing`, `publish_gate_not_ok`,
  and `publish_gate_profile_below_threshold`.
- Teacher-facing interpretation: review is usable; export/passback stays fail-closed until validation attention is resolved.

## Teacher-Facing Findings From Live Smoke

- The assignment did sync essays; the UI made it look ambiguous because saved project inputs still displayed generic upload drop labels after reload.
- The Classroom panel counted grouped blocker codes instead of affected submissions, which hid that 8 submissions required attachment follow-up.
- The review-ready dashboard initially stayed behind the run overlay even after `teacher_can_review` was true.
- The dashboard artifact used Classroom user IDs as display names; the pipeline now preserves anonymous internal IDs while showing roster display names.
- The Ghost rubric was initially over-generalized: explicit `(8)` style criteria were missed, and pass-1 prompt examples still nudged model output toward generic `K1`/`K2` IDs.
- The long background consistency pass had no in-step output; future runs now emit low-noise pairwise progress lines so the UI does not look frozen.
- Validation completed after review-ready, but the UI needed to keep the teacher in review mode while clearly showing validation attention and blocked export/passback status.
- Project-level validation blockers initially inherited the attachment blocker submission count, which made validation attention look like another 8-student import problem.

## Fixes Applied

- Saved Classroom/rubric/outline inputs now render as `Classroom essays synced`, `Rubric saved`, and `Outline saved`.
- Review-ready reload restores the pipeline chip and removes the blocking overlay immediately.
- Classroom blockers display the actual affected submission count in the exceptions surface.
- Rubric parsing recognizes parenthetical weights such as `(8)` and prefers explicit weighted criteria rows.
- Literary analysis genre inference runs before generic argumentative matching.
- Pass-1 assessor prompts use verified normalized rubric IDs and criterion labels instead of generic `K1`/`K2` examples.
- Classroom roster display names flow into extraction metadata and dashboard rebuilds without changing anonymous student IDs.
- Raw subprocess failure text is mapped to teacher-readable run errors.
- Pairwise consistency now prints selected-pair and progress checkpoints for long background validation steps.
- Pairwise escalation now prints selected escalation count, estimated model calls, and progress checkpoints.
- Classroom exception labels now append submission counts only to attachment-level blockers, not project-level validation blockers.

## Launch Validator

- Command: `python3 scripts/validate_production_launch.py`
- Result: not rerun in this smoke; prior launch-gate blockers remain expected for this non-launch slice.
- Blockers: publish/SOTA/calibration launch gates remain outside this smoke.

## Privacy And Commit Hygiene

- Credentials committed: no.
- Access/refresh tokens committed: no.
- Downloaded client JSON committed: no.
- Real student documents committed: no.
- Private screenshots committed: no.
- Raw Google payloads committed: no.

## Notes

The live run materialized 21 text submissions locally and left 8 attachment
blockers for teacher follow-up. The teacher can review the ordered cohort, but
CSV/export/passback stays blocked because validation completed with nonblocking
launch-gate attention. The smoke report intentionally redacts teacher account,
course, student names, and essay text.
