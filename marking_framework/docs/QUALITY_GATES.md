Quality Gates

This repo has three different gate layers. They answer different questions and
should not be collapsed into one "pass/fail" idea.

1) Aggregation Data-Completeness Gates

Hard requirements (`scripts/aggregate_assessments.py` will fail unless
`--allow-missing-data` is explicitly used):
- at least 3 assessors for both Pass 1 and Pass 2
- every assessor scores every student
- every assessor ranks every student
- conventions scan data exists for all students

Use `--allow-missing-data` only for development or fixture work. It can produce
unfair grades because missing evidence changes the consensus denominator.

2) Re-Read And Boundary Quality Signals

Re-read or boundary review is required when any of these are true:
- rubric score SD meets or exceeds `consensus.rubric_sd_threshold` in `config/marking_config.json`
- rank SD meets or exceeds `consensus.rank_disagreement_threshold`
- conventions mistake rate exceeds the configured conventions threshold
- conventions penalty flags are applied
- band-seam artifacts identify a boundary-near paper with contradictory aggregate/pairwise support

Current reliability targets remain:
- Rubric ICC: `>0.7` good, `>0.9` excellent
- Rank Kendall's W: `>0.7` good agreement
- Mean rubric SD: `<1.0` points preferred
- Mean rank SD: `<3` positions preferred

3) Publish/SOTA Release Gates

Release gates live in:
- `config/accuracy_gate.json`
- `config/sota_gate.json`
- `scripts/publish_gate.py`
- `scripts/sota_gate.py`

The configured profiles are `dev`, `candidate`, and `release`.

Important current checks:
- calibration manifest/freshness/scope/routing/rubric checks
- benchmark report coverage, accuracy, stability, cost, and latency thresholds
- reproducibility report requirements for candidate/release profiles
- routed hard-pair evaluation via `outputs/pairwise_adjudicator_eval.json`
- pairwise eval must use the escalated/committee-edge path when required
- evidence-neighborhood and evidence-group-packet readiness for candidate/release profiles when committee candidates exist

Development profiles report missing evidence packets as diagnostics. Candidate
and release profiles can fail when required evidence-neighborhood or
evidence-group-packet artifacts are missing, disabled, empty, or exceed packet
caps.

Minimum Workflow Coverage
- Pass 1: independent scoring from all assessors
- Pass 2: comparative ranking from all assessors
- optional boundary recheck and band-seam adjudication before pairwise consistency
- pairwise consistency collection
- pairwise escalation for unstable/high-leverage edges
- evidence map and committee-edge resolver before rerank
- global rerank using `outputs/consistency_checks.committee_edge.json`
- routed hard-pair eval before publish/SOTA gates
- curve review before finalizing grades
- quote validation for all feedback
