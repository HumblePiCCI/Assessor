Codex Mode (Local Orchestrator)

Overview
- Codex is used as the local login and orchestration environment.
- Assessment tasks use the configured model routing in `config/llm_routing.json`.
- When `mode` is `codex_local`, LLM calls run through an OAuth-capable Codex CLI runtime, with no API key required.
- The supported OAuth runtime is the Codex app bundled CLI at `/Applications/Codex.app/Contents/Resources/codex`, using `codex exec`.
- The older Homebrew `codex -q` runtime is treated as a legacy API-key path and is not accepted as proof of OAuth readiness.

Recommended Setup
1) Sign in to the Codex desktop app.
2) Confirm OAuth local execution:
   - `env -u OPENAI_API_KEY /Applications/Codex.app/Contents/Resources/codex exec --ignore-user-config --model gpt-5.4-mini --sandbox read-only --skip-git-repo-check 'Return exactly: ok'`
3) Optional: export a provider key only when switching `mode` to the API provider path.

Notes
- Codex sign-in is specific to Codex tools and does not automatically grant API access to third-party apps.
- Local development can run on the current Codex/ChatGPT subscription through `codex_local`.
- Codex local execution uses `CODEX_TIMEOUT_SECONDS` when set. If unset, it uses a 600 second default so larger multi-essay adjudication prompts can finish; `LLM_TIMEOUT_SECONDS` still controls API-provider calls and remains the fallback override for Codex when explicitly set.
- Production pay-as-you-go runs should use the API provider path configured in `config/llm_routing.json`.
