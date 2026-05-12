LLM Routing

Config file: `config/llm_routing.json`

Purpose
- Define which model to use for each LLM task.
- Centralize defaults so the pipeline is consistent across CLI, queue, and hero-path runs.
- Keep cheap broad screening separate from routed teacher-grade adjudication.

Current Tasks
- `pass1_assessor`: independent rubric scoring. Current default: `gpt-5.4-mini`, low reasoning.
- `pass2_ranker`: comparative ranking. Current default: `gpt-5.4-mini`, low reasoning.
- `pairwise_reviewer`: broad cheap pairwise review. Current default: `gpt-5.4-mini`, low reasoning.
- `pairwise_escalator`: stronger routed adjudication for high-leverage/unstable pairs. Current default: `gpt-5.4`, medium reasoning.
- `literary_committee`: live committee-edge reads for literary-analysis residuals. Current default: `gpt-5.4-mini`, high reasoning.
- `feedback_drafter`: optional feedback drafts. Current default: `gpt-5.4-nano`, medium reasoning.

Committee-Edge Routing Notes
- The default `scripts/committee_edge_resolver.py` path is model-free and writes passthrough artifacts unless live or fixture inputs are supplied.
- Live committee reads are opt-in:
  - CLI: `python3 scripts/committee_edge_resolver.py --live`
  - Hero path: `python3 scripts/hero_path.py --committee-edge-live ...`
  - Step runner env: `COMMITTEE_EDGE_LIVE=1`
- The live literary committee path intentionally uses `gpt-5.4-mini`; do not override it ad hoc unless the routing config is deliberately changed.
- `pairwise_escalator` remains the stronger routed pairwise adjudicator; it is not the broad screener.

Operational Notes
- Local proof/dev mode is `codex_local`. It uses the OAuth-capable Codex app CLI (`codex exec`) and does not require an API key.
- Pay-as-you-go mode is `openai`, which now means "API provider path." The active provider is selected by `api_provider` in `config/llm_routing.json` or by `LLM_API_PROVIDER`.
- Provider keys are read from `LLM_API_KEY` first, then the provider-specific `api_key_env` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `KIMI_API_KEY`, etc.).
- Supported API adapter kinds:
  - `openai_responses`: OpenAI Responses-compatible providers.
  - `openai_chat`: OpenAI-compatible chat completions providers, including Kimi-style routes.
  - `anthropic_messages`: Anthropic Messages-compatible providers.
- Update `config/llm_routing.json`, not individual scripts, to change models or reasoning levels.
- Keep task additions explicit in this doc whenever a new route is introduced; otherwise queue, hero-path, and local runs become hard to compare.
