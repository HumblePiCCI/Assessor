Codex Mode (Local Orchestrator)

Overview
- Codex is used as the local login and orchestration environment.
- Assessment tasks use the configured model routing in `config/llm_routing.json`.
- When runtime profile `internal_codex` resolves to `mode=codex_local`, LLM calls run through the OAuth-backed Codex app CLI at `/Applications/Codex.app/Contents/Resources/codex` using `codex exec` (no API key required).
- `internal_codex` is for internal testing and is not customer billable.

Recommended Setup
1) Sign in to the Codex app/CLI so `~/.codex/auth.json` contains the OAuth token set.
2) Select `internal_codex` in the UI runtime profile switch.
3) Optional: export `OPENAI_API_KEY` if you switch to `teacher_payg_openai`.

Notes
- Codex sign-in is specific to Codex tools and does not automatically grant API access to third-party apps.
- The Homebrew/standalone `codex` binary on PATH may require `OPENAI_API_KEY`. Internal runs therefore pin the Codex app bundle CLI and its `exec` interface in `config/runtime_profiles.json`.
- Internal queue jobs strip `OPENAI_API_KEY` and write `outputs/runtime_auth_audit.json`; a healthy internal run reports `auth_funding_source=codex_oauth`, `openai_api_key_visible_to_job=false`, and the pinned `codex_cli_path`.
- Provider/billing profiles are defined in `config/runtime_profiles.json`; see `docs/RUNTIME_PROVIDER_SWITCH.md`.
