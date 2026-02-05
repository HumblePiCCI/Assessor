Codex Mode (Local Orchestrator)

Overview
- Codex is used as the local login and orchestration environment.
- Assessment tasks use the configured model routing in `config/llm_routing.json`.
- When `mode` is `codex_local`, LLM calls run via the Codex CLI (no API key required).

Recommended Setup
1) Sign in to Codex (CLI/IDE). Use `codex --login` if you want a browser-based login.
2) Set your preferred model for Codex interaction (e.g., GPT-5.2).
3) Optional: export `OPENAI_API_KEY` if you switch `mode` to `openai`.

Notes
- Codex sign-in is specific to Codex tools and does not automatically grant API access to third-party apps.
- This repo uses the OpenAI API for assessment tasks via `scripts/run_llm_assessors.py`.
