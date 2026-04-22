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
- `OPENAI_API_KEY` is required for API calls.
- Update `config/llm_routing.json`, not individual scripts, to change models or reasoning levels.
- Keep task additions explicit in this doc whenever a new route is introduced; otherwise queue, hero-path, and local runs become hard to compare.
