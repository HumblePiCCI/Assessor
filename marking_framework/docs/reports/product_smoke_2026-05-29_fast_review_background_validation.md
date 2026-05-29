# Product Smoke: Fast Review + Background Validation

Date: 2026-05-29 UTC / 2026-05-28 EDT

Branch: `codex/teacher-fast-review-background-validation-api-classroom-pilot`

Base commit: `origin/main@1fbb04c9ab5160adb1210a159080ac7477bda35f`

Server URL/port: `http://127.0.0.1:8017`

## Scope

This report records the PR smoke evidence for the fast teacher-review lane,
background validation phase, provider-generic API mode, and read-only Classroom
pilot sync. It is product-smoke evidence, not production-launch evidence.

Dataset/cohort shape:

- Fast-review contract smoke: 2 fixture submissions.
- Classroom read-sync smoke: 1 supported text submission plus 1 unsupported
  external-link blocker in tests.
- UI front-page smoke: local FastAPI app loaded in the in-app browser.

Runtime mode:

- Queue contract smoke used mocked subprocess steps, not live paid model calls.
- Codex OAuth status was checked with `OPENAI_API_KEY` and `LLM_API_KEY`
  removed.
- API provider status was checked from `config/llm_routing.json`.

## Runtime Proof

Codex OAuth without API keys:

- Command: `env -u OPENAI_API_KEY -u LLM_API_KEY python3 - <<'PY' ... codex_status_payload()`
- Result: `connected: true`, `auth_source: codex_oauth`, `runtime_kind: exec`,
  runtime path `/Applications/Codex.app/Contents/Resources/codex`.

API provider status:

- Command: `python3 - <<'PY' ... api_provider_status('config/llm_routing.json')`
- Result in this environment: `connected: true`, provider `openai`, kind
  `openai_responses`, auth source `OPENAI_API_KEY`.
- Mocked tests prove OpenAI Responses, Anthropic Messages, and Kimi/OpenAI-
  compatible chat payloads without live paid calls.

## Fast Dashboard Proof

Contract smoke command:

```bash
cd /Users/bldt/Desktop/Essays/marking_framework
python3 - <<'PY'
# fixture PipelineQueue run with an artificial slow background band_seam step
PY
```

Observed result:

```json
{
  "status": "completed",
  "product_phase": "validation_complete",
  "teacher_can_review": true,
  "validation_status": "complete",
  "teacher_review_ready_seconds": 0.0361,
  "validation_complete_seconds": 0.3497,
  "ready_before_background_band_seam": true
}
```

The queue also has a regression test with failing background validation proving
that `dashboard_data.json` is available and `teacher_can_review` is true before
`band_seam` completes.

## Teacher Workflow Proof

Covered by tests and UI smoke:

- Normal student review: `tests/test_projects_review_endpoints` saves draft and
  final review state with assigned marks and feedback.
- Flagged/exception review: same test persists level override, evidence note,
  and rank movement; dashboard exceptions are covered by
  `teacher_exceptions` and validation summary tests.
- Pairwise decision: `tests/test_projects_review_endpoints` persists a
  pairwise preference and reloads it from the review bundle.
- Curve top/bottom: draft and final review tests persist `curve_top=96` and
  `curve_bottom=64`.
- Two edited feedback drafts: Classroom/passback tests persist two feedback
  draft rows for export preflight.
- Draft reload result: `GET /projects/review` returns the saved draft.
- Final reload result: finalized review persists as `latest_review`.

UI front-page smoke:

- Loaded `http://127.0.0.1:8017/` in the in-app browser.
- Visible title: `Assessor`.
- Primary action: `Run assessment`.
- Classroom controls present: `Link`, `Read sync`, `Reconcile`,
  `Refresh validation`, `Finalize`.
- Exceptions surface present.
- Browser console errors: none.

## Classroom Read/Sync Pilot

Read-sync result:

- `POST /projects/classroom/read-sync` is covered by endpoint tests.
- Supported text is written to `inputs/submissions/<student>.txt`.
- Unsupported external links remain blockers.
- No credentials are required in tests.
- `external_write_performed: false`.

Export/passback preflight:

- Blocked until teacher review is finalized, validation is current for the
  latest human revision, attachment blockers are clear, evidence exists, and the
  teacher confirms.
- CSV preflight can prepare rows after gates clear.
- Live write modes remain fail-closed with `external_writes_disabled` unless a
  future verified adapter/scopes/policy path exists.

No live Classroom write occurred.

## Verification

Targeted suites:

```bash
python3 -m pytest -q --no-cov \
  tests/test_step_runner.py \
  tests/test_pipeline_queue.py \
  tests/test_server_app.py \
  tests/test_classroom_product.py \
  tests/test_openai_client.py \
  tests/test_openai_client_structured.py
```

Result: passed.

Full suite:

```bash
python3 -m pytest -q --no-cov
```

Result: passed.

UI syntax:

```bash
node --check marking_framework/ui/app.js
```

Result: passed.

Launch validator:

```bash
python3 scripts/validate_production_launch.py
```

Result: blocked, as expected.

Blockers:

- `publish_gate_missing`
- `sota_gate_missing`
- `calibration_manifest_missing`

The launch gates were not weakened.
