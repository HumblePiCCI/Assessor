LLM Routing

Config file: `config/llm_routing.json`

Purpose
- Define which model to use for each LLM task.
- Centralize defaults so the pipeline is consistent.

Tasks
- pass1_assessor: rubric scoring
- pass2_ranker: comparative ranking
- pairwise_reviewer: adjacent pair review
- feedback_drafter: optional feedback drafts

Notes
- `OPENAI_API_KEY` is required for API calls.
- Update the routing config to adjust models or reasoning levels.
