# Source-Calibrated Committee Validation

Date: 2026-04-19

Branch: `codex/fix-live-literary-ranking`

## Purpose

Validate whether the external teacher-scored calibration source pack improves
the live Ghost committee-edge adjudicator on known rougher-vs-cleaner literary
analysis residuals.

## Runs

### Source-Calibrated Prompt Injection

Command shape:

```bash
LLM_TIMEOUT_SECONDS=120 OPENAI_MAX_RETRIES=2 python3 scripts/committee_edge_resolver.py \
  --live --max-reads 12 --max-read-b 12 --max-read-c 12 \
  --candidates-output outputs/committee_edge_candidates.source_calibrated.json \
  --decisions-output outputs/committee_edge_decisions.source_calibrated.json \
  --report-output outputs/committee_edge_report.source_calibrated.json \
  --merged-output outputs/consistency_checks.committee_edge.source_calibrated.json \
  --live-trace-output outputs/committee_edge_live_trace.source_calibrated.json
```

Result:

- Read A: 12/12 completed.
- Read B: 12/12 completed.
- Read C: 11/12 completed.
- Group calibration: 1/1 completed, medium confidence.
- Emitted committee overrides: 2, neither among the five known Ghost residuals.
- Pairwise hard-pair eval: `accuracy=0.666667`, `critical_accuracy=0.857143`.
- Known residuals remained wrong: `s003::s009`, `s003::s013`, `s004::s008`, `s009::s015`, `s019::s022`.

Conclusion: prose source-pack injection alone does not fix the live judge. The
model continues to self-justify the cleaner or more conventional side as having
stronger proof.

### Source-Checklist Guarded Run

After adding `decision_checks.source_calibration_checks` and the deterministic
source-calibration guard, a second live pass was started:

```bash
LLM_TIMEOUT_SECONDS=120 OPENAI_MAX_RETRIES=2 python3 scripts/committee_edge_resolver.py \
  --live --max-reads 12 --max-read-b 12 --max-read-c 12 --max-output-tokens 3000 \
  --candidates-output outputs/committee_edge_candidates.source_guarded.json \
  --decisions-output outputs/committee_edge_decisions.source_guarded.json \
  --report-output outputs/committee_edge_report.source_guarded.json \
  --merged-output outputs/consistency_checks.committee_edge.source_guarded.json \
  --live-trace-output outputs/committee_edge_live_trace.source_guarded.json
```

Result:

- The expanded schema parsed successfully in live Read A/B/C calls.
- The run became non-authoritative after repeated OpenAI 401 errors.
- Intermediate trace showed the model filled `source_calibration_checks`, but
  still assigned `source_calibrated_winner` to the prior/cleaner side on the
  early known residuals.
- The deterministic source guard did not fire on those residuals because the
  model's checklist did not contradict its winner.

Conclusion: the checklist/guard is useful infrastructure and protects against
self-contradictory future reads, but it does not solve this failure when the
model's self-check itself is wrong.

## Product Diagnosis

The remaining Ghost failure is no longer a routing, budget, or artifact problem.
The hard pairs are routed. A/B/C reads execute. Evidence ledgers and source
checklists are produced. The failure is that the live judge still overvalues
explicit multi-event completeness as "proof" and underrates rougher literary
interpretation unless that interpretation is already fully polished and
conventional.

In concrete trace terms:

- The model marks stronger alternate themes as "mature-sounding but underproved"
  even when human adjudication reads them as more meaningful.
- It treats event count and completeness as proof sufficiency.
- It does not reliably distinguish "named events" from "explained literary
  meaning" using prompt text alone.
- It sometimes applies completion/scaffold language to rougher but complete
  essays.

## Next SOTA Step

Do not keep stacking prompt prose. The next durable step is a model-independent
evidence extraction and teacher-anchor contrast seam:

1. Extract per-essay claim/evidence/commentary units deterministically or with a
   cheaper structured extractor.
2. Require every unit to identify: claim, text moment, explanation, literary
   function, and whether the explanation is commentary or plot restatement.
3. Feed committee reads a precomputed evidence map, not just raw essays and
   source rules.
4. Add deterministic guards over the map: do not let a paper win on proof
   merely because it has more events if those events are less explanatory.
5. Use external source rules to score extracted units, not to ask the same
   pairwise judge to self-audit its own bias.

