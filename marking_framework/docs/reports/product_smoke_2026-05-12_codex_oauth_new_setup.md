# Product Smoke Report: Codex OAuth New Setup

Date: 2026-05-12 America/Toronto

Branch: `codex/codex-oauth-band-seam-timeout`

Server: `http://127.0.0.1:8010`

Dataset: `/Users/bldt/Desktop/Essays/7A Ghost Novel, Theme Essays`

Project: `Smoke Codex OAuth 2026-05-12`

## Result

Status: passed for the teacher-facing product smoke.

The smoke completed the local Codex OAuth path with API keys removed from the
server process. The product accepted 23 Ghost essay submissions, the rubric,
and the outline; produced a review-ready ordered cohort; allowed teacher review,
pairwise adjudication, curve adjustment, editable feedback, project save, draft
save, finalization, and reload persistence.

This does not mark the product production-launched. The strict publish and SOTA
gates remain blocked for this dev smoke, and Classroom remains read-only/blocked
until live in-app linking and sync are implemented.

## Runtime Proof

Command:

```bash
env -u OPENAI_API_KEY -u LLM_API_KEY python3 - <<'PY'
from scripts.codex_runtime import codex_status_payload
import json
print(json.dumps(codex_status_payload(), indent=2, sort_keys=True))
PY
```

Observed result:

```json
{
  "auth_source": "codex_oauth",
  "available": true,
  "connected": true,
  "oauth_supported": true,
  "oauth_tokens_present": true,
  "reason": "Codex OAuth runtime ready",
  "runtime_kind": "exec",
  "runtime_path": "/Applications/Codex.app/Contents/Resources/codex",
  "version": "codex-cli 0.130.0-alpha.5"
}
```

The server was started without `OPENAI_API_KEY` or `LLM_API_KEY`, and pipeline
model calls executed through:

```text
/Applications/Codex.app/Contents/Resources/codex exec --ignore-user-config --model gpt-5.4-mini ...
```

## Pipeline Evidence

Job id: `05a1a36927da46a4959acec7a7f3eef5`

Workspace:
`/Users/bldt/Desktop/Essays-smoke-codex-oauth/marking_framework/server/data/workspaces/52a258ada1e2f8a4/05a1a36927da46a4959acec7a7f3eef5`

Completed outputs included:

- `outputs/band_seam_report.json`
- `outputs/consistency_checks.json`
- `outputs/pairwise_escalation_candidates.json`
- `outputs/pairwise_escalations.json`
- `outputs/evidence_map.json`
- `outputs/committee_edge_report.json`
- `outputs/final_order.csv`
- `outputs/pairwise_matrix.json`
- `outputs/rerank_scores.csv`
- `outputs/consistency_report.json`
- `outputs/cohort_confidence.json`
- `assessments/final_review_pairs.json`
- `outputs/grade_curve.csv`
- `outputs/dashboard_data.json`

Run summary:

- `band_seam`: completed after timeout fix, with 12 adjudication changes.
- `consistency`: completed 237 judgments.
- `pairwise_escalation`: 237 candidates, 44 selected, 44 escalations.
- `rerank`: completed; final-order pairwise agreement was `0.942661`.
- `grade`: completed 23 student marks.
- `dashboard`: completed and rendered in the teacher UI.

Strict launch gates remained blocked, as expected for a dev smoke:

- `outputs/publish_gate.json`: `ok=false`
- `outputs/sota_gate.json`: `ok=false`
- `pairwise_eval`: blocked because the local eval fixture had an empty pairs
  list.

## Product Walk-Through Evidence

Inputs loaded:

- 23 student `.docx` essays
- `Essay Rubric.docx`
- `Essay Outline.docx`

UI states verified:

- Clean workspace showed project, connection, and pipeline state in the top bar.
- Connection state showed `Codex OAuth connected`.
- Upload status showed `23 essay files ready`, `rubric ready`, and `outline ready`.
- Completed dashboard showed a 23-student ordered cohort rail, current essay
  text, decision snapshot, assigned mark, uncertainty/status signals, and
  teacher review controls.
- Anchor calibration was not required.

Teacher workflow actions:

- Reviewed `Easton - Ghost final essay` at rank 2.
- Left the suggested Level 3 placement in place.
- Set evidence quality to `strong`.
- Added a teacher evidence note.
- Compared against `Alyssa - ghost essay` and kept the current essay above the
  compare essay.
- Changed the teacher curve to top `94` and bottom `56`.
- Generated feedback for the cohort and edited feedback for two students.
- Saved a draft review.
- Saved the project as `Smoke Codex OAuth 2026-05-12`.
- Finalized the review.
- Reloaded and verified persistence.

Reload persistence API summary:

```json
{
  "review_state": "final",
  "student_reviews": 1,
  "pairwise_decisions": 1,
  "curve_top": 94,
  "curve_bottom": 56,
  "assigned_marks": 23,
  "feedback_drafts": 23,
  "local_learning_review_count": 1
}
```

Local screenshots captured:

- `/Users/bldt/Desktop/Essays/smoke-2026-05-12-01-clean-codex-oauth.png`
- `/Users/bldt/Desktop/Essays/smoke-2026-05-12-02-uploaded.png`
- `/Users/bldt/Desktop/Essays/smoke-2026-05-12-03-completed-dashboard.png`
- `/Users/bldt/Desktop/Essays/smoke-2026-05-12-04-review-finalized-project.png`
- `/Users/bldt/Desktop/Essays/smoke-2026-05-12-05-reload-finalized.png`

## Classroom Readiness

The smoke confirmed the current expected Classroom posture:

```json
{
  "product_state": "blocked",
  "teacher_review_finalized": true,
  "blockers": ["classroom_link_required"],
  "external_write_performed": false,
  "latest_review": {
    "review_state": "final",
    "student_review_count": 1,
    "assigned_mark_count": 23,
    "feedback_draft_count": 23
  }
}
```

This is correct for the current implementation. The product does not perform a
live Classroom write, and the read/sync pilot remains blocked until in-app
Classroom linking/sync is implemented.

## Fix Applied During Smoke

The first full run failed at `band_seam` with:

```text
RuntimeError: Codex CLI timed out after 180s
```

That was a real product failure for the Codex OAuth smoke path. The fix splits
Codex subprocess timeout behavior from normal API-provider timeout behavior:

- API-provider calls keep the conservative `LLM_TIMEOUT_SECONDS` default of
  180 seconds.
- Codex local execution now defaults to 600 seconds.
- `CODEX_TIMEOUT_SECONDS` can override Codex specifically.
- `LLM_TIMEOUT_SECONDS` still acts as a fallback override for Codex when set.

The smoke was then resumed with `CODEX_TIMEOUT_SECONDS=600` and completed
through dashboard, project save, review finalization, and reload persistence.

## Verification

```bash
../.venv/bin/python -m pytest tests/test_openai_client.py tests/test_openai_client_structured.py tests/test_codex_runtime.py tests/test_classroom_product.py tests/test_server_app.py --disable-warnings
```

Result:

```text
85 passed in 0.38s
```
