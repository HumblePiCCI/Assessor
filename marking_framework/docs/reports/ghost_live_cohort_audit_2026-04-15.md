# Ghost Live Cohort Audit - 2026-04-15

## Scope

- Cohort: `7A Ghost Novel, Theme Essays`
- Workspace:
  `/Users/bldt/Desktop/Essays/marking_framework/server/data/tenant_workspaces/1ab418ede009c1af/81a14df23c0ed483/workspace`
- Active branch: `codex/fix-live-literary-ranking`
- Purpose: paper-by-paper live-cohort audit to make the ranking defensible end to end, then drive code fixes and reruns until the placements are accurate, fair, and consistent.

## Baseline Snapshot

Current top 10:

1. `s010` Jacob
2. `s011` Jasmine
3. `s015` Logan
4. `s012` Johanna
5. `s009` Jack
6. `s013` Kyle
7. `s006` Graydon
8. `s022` Sienna
9. `s007` Hudson B
10. `s003` Easton

Current bottom 5:

19. `s021` Olivia
20. `s004` Farris
21. `s008` Hudson L
22. `s023` William
23. `s020` Nora

Known baseline issues before this audit pass:

- Incomplete scaffold draft `s020` previously outranked a completed weak essay; that is now corrected by the draft-completion floor.
- Sienna (`s022`) moved from old smoke-run last place to current rank 8. That move is directionally plausible, but the current placement still needs direct audit against the surrounding band.
- Several essays with middling raw rubric means are being lifted by `boundary_calibration` + `severe_collapse_rescue` on a synthetic cold-start scope. This is the main suspected source of remaining overcorrection.

## Working Judgments

### Confirmed

- `s020` belongs last or near-last because it is visibly unfinished and still contains organizer residue.
- `s023` is weak but complete; it should outrank `s020`.
- `s022` does not belong near the bottom. Current evidence places it in the upper-middle, not the top and not the tail.

### Open Questions

- Is `s010` actually the strongest essay, or is it being over-promoted by collapse rescue?
- Are `s011`, `s012`, `s013`, `s015`, and `s006` the true top cluster, with `s022` and `s009` just below them?
- Are there remaining lower-middle essays that are structurally cleaner and more analytical than their current placements suggest?

## Audit Loop

### Pass 1

Findings in progress:

- `s022` audit against ranks 5-10:
  - not bottom
  - not true top-tier
  - best fit appears to be around ranks 9-10
- likely overcorrection source:
  - `boundary_calibration`
  - `severe_collapse_rescue`
  - synthetic cold-start scope

Pending comparisons:

- top cluster pairwise audit: `s010`, `s011`, `s012`, `s013`, `s015`, `s006`
- upper-middle boundary audit: `s022`, `s009`, `s007`, `s003`, `s002`
- lower-middle audit: `s019`, `s017`, `s018`, `s005`, `s014`, `s016`, `s021`

### Pass 2

Change:

- tightened bootstrap-scope severe-collapse rescue so bootstrap-generated, rubric-unknown live cohorts do not get automatic `70` floors from middling raw rubric scores
- added upward movement caps for severe-collapse rescue rows in the reranker

Observed effect:

- `s010` dropped out of the top rank cluster
- `s022` was no longer rescue-lifted into the top third by calibration alone
- top-band ordering became much closer to direct reading

Remaining problem after Pass 2:

- pairwise consistency still over-rewarded formulaic structure in literary analysis and under-represented direct neighborhood evidence in the middle band

### Pass 3

Change:

- added literary-analysis-specific pairwise guidance in `verify_consistency.py`
- widened the bootstrap literary-analysis comparison window
- allowed direct high-confidence pairwise wins to override a one-level lock when the rubric gap is small

Observed effect:

- `s020` remained correctly last
- `s010` stabilized in the lower end of the upper-middle rather than the top band
- `s022` settled into the middle band rather than the tail or top third
- final order became substantially more consistent with direct essay reading and less dependent on bootstrap calibration

## Current Working Order

Top band:

1. `s015`
2. `s009`
3. `s013`
4. `s006`
5. `s012`

Upper-middle:

6. `s011`
7. `s007`
8. `s002`
9. `s003`
10. `s019`
11. `s010`
12. `s022`

Lower-middle:

13. `s014`
14. `s016`
15. `s018`
16. `s017`
17. `s001`
18. `s021`
19. `s005`

Bottom:

20. `s004`
21. `s023`
22. `s008`
23. `s020`

## Final Judgment

The current ranking is now defensible as a live cold-start result for this cohort.

Most important calls:

- `s020` is correctly last because it is visibly unfinished and still contains live organizer residue.
- `s023` now correctly outranks `s020`.
- `s010` is no longer artificially promoted into the class lead by synthetic-scope collapse rescue.
- `s022` is no longer mis-scored as either a bottom essay or a top-third essay. The final landing around the middle of the level-2+ cluster is defensible.

The pipe changes that made the difference were not cosmetic:

- rescue logic is now scope-aware for bootstrap-generated live cohorts
- literary-analysis pairwise checks now prioritize interpretation over formulaic structure
- direct high-confidence pairwise evidence can now break a one-level lock when the essays are close enough for that override to be credible

## Code Paths Under Review

- `scripts/boundary_calibrator.py`
- `scripts/run_llm_assessors.py`
- `scripts/global_rerank.py`
- `config/marking_config.json`

## Success Condition

The audit is complete only when:

- every placement is defensible on direct reading
- the rank transitions between adjacent essays are coherent
- rescue/calibration logic is not masking weak raw scoring on live cold-start scopes
- the rerun outputs hold up under another full paper-by-paper read
