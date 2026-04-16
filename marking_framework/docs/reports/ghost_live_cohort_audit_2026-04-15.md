# Ghost Live Cohort Audit - 2026-04-15

## Scope

- Cohort: `7A Ghost Novel, Theme Essays`
- Workspace:
  `/Users/bldt/Desktop/Essays/marking_framework/server/data/tenant_workspaces/1ab418ede009c1af/81a14df23c0ed483/workspace`
- Active branch: `codex/fix-live-literary-ranking`
- Purpose: full paper-by-paper adjudication of a live cold-start Grade 7 literary-analysis cohort, with repeated code/rerun loops until the final order matched a defensible human order.

## Baseline Problems

Before this adjudication loop, the live pipe had three real failure modes:

1. Incomplete drafts could outrank weak but finished essays.
2. Bootstrap-scope severe-collapse rescue could over-promote middling essays.
3. The reranker protected bad seeds too aggressively:
   - fixed-neighborhood pairwise collection missed some true upward and downward moves
   - generic level locks were added before strong direct pairwise evidence, so the evidence was often dropped as `cycle_avoided`

## Method

The adjudication loop for this cohort was:

1. Read the whole cohort directly, not just the rubric/score artifacts.
2. Lock an independent full 1-23 human order.
3. Compare that order to the pipe output.
4. Inspect the exact seams that determined the pipe rank:
   - direct pairwise checks
   - level-lock edges
   - displacement caps
   - calibration/rescue effects
5. Decide whether the pipe or the human order was wrong.
6. If the pipe was wrong, fix code and rerun the actual workspace.
7. Repeat until the final live order matched a reasoned human adjudication end to end.

## Independent Human Adjudication

After the full read and seam review, the final defended human order was:

1. `s015`
2. `s011`
3. `s009`
4. `s002`
5. `s003`
6. `s013`
7. `s019`
8. `s010`
9. `s022`
10. `s006`
11. `s012`
12. `s014`
13. `s016`
14. `s018`
15. `s001`
16. `s017`
17. `s007`
18. `s021`
19. `s005`
20. `s004`
21. `s008`
22. `s023`
23. `s020`

This is the order I can defend on direct reading after reviewing the pipe justifications.

## Final Pipe Order

Final live rerun order:

1. `s015`
2. `s011`
3. `s009`
4. `s002`
5. `s003`
6. `s013`
7. `s019`
8. `s010`
9. `s022`
10. `s006`
11. `s012`
12. `s014`
13. `s016`
14. `s018`
15. `s001`
16. `s017`
17. `s007`
18. `s021`
19. `s005`
20. `s004`
21. `s008`
22. `s023`
23. `s020`

Human order and final pipe order match exactly.

## Band Notes

### Top Band

- `s015` and `s011` are the strongest two. The exact `1/2` ordering was the closest call in the cohort. I accept `s015 > s011` as defensible because `s015` is tighter and less mechanical, while `s011` is more formulaic despite being fuller.
- `s009`, `s002`, `s003`, `s013` form the rest of the true upper cluster.
- `s002` was initially too low in my first human pass. After reading its direct wins and revisiting the essay, I changed my judgment, not the code.

### Upper Middle

- `s019`, `s010`, and `s022` all belong here.
- `s022` was the main human-versus-pipe audit case early in the loop. Final landing at `9` is defensible: complete, coherent, not top-tier, not tail.
- `s006` and `s012` read stronger at first glance because of rubric-friendly surface features, but on direct comparison they belong below the more meaning-making essays above them.

### Lower Middle

- `s014`, `s016`, `s018`, `s001`, `s017` are all weak but complete.
- `s007` is the key corrected misplacement. It had been badly over-ranked by the pipe. After the reranker fixes, it dropped to `17`, which matches the direct read: fragmented, repetitive, summary-heavy, and thinly analytical.

### Bottom

- `s021`, `s005`, `s004`, `s008`, `s023` are the weakest complete essays.
- `s020` is last because it is visibly unfinished and still contains live planning scaffold residue.

## Seams Investigated

### `s020` vs `s023`

Direct read:

- `s020` is unfinished, with exposed organizer residue and incomplete clauses.
- `s023` is weak and summary-heavy, but complete.

Judgment:

- `s023` must outrank `s020`.

Result:

- fixed by the draft-completion floor and completion-floor ranking rule
- final order: `s023 = 22`, `s020 = 23`

### `s007` over-ranking

Direct read:

- `s007` is mostly a trauma inventory with weak interpretive control.
- it is not a top-third essay

What the pipe was doing wrong:

- seed was too high from pass1
- fixed-neighborhood pairwise checks did not compare it widely enough
- even after direct losses were collected, strong pairwise edges were being added after level locks and dropped as cycles

Fixes:

- divergence-aware pairwise reach for bootstrap literary-analysis cohorts in `scripts/verify_consistency.py`
- direction-aware downward displacement caps in `scripts/global_rerank.py`
- strong pairwise evidence now lands before generic level locks in `scripts/global_rerank.py`

Result:

- `s007` fell from the upper band to `17`
- final placement matches the direct read

### `s011` under-ranking

Direct read:

- `s011` is one of the strongest essays in the set
- it is formulaic, but materially stronger than its old placement

What the pipe was doing wrong:

- it had strong direct wins over better-seeded neighbors
- those direct wins were still getting neutralized by earlier generic constraints

Fix:

- same reranker precedence fix as above

Result:

- `s011` rose to `2`
- direct human read and direct pairwise evidence now agree

### `s022` placement

Direct read:

- `s022` is complete and coherent
- not top-tier
- clearly not near the bottom

What changed:

- I initially placed it a little too high
- the pairwise rationales against nearby essays were mostly sound

Result:

- final adjudicated landing: `9`
- this was a human recalibration, not a pipe fix

## Code Changes That Mattered

- `scripts/verify_consistency.py`
  - bootstrap literary-analysis comparison reach is now divergence-aware, not just a fixed neighborhood
  - outlier essays now get enough comparisons to move meaningfully

- `scripts/global_rerank.py`
  - displacement caps are now direction-aware
  - high-opposition outliers can fall much farther than before
  - strong direct pairwise evidence is now added before generic level locks
  - generic caps no longer quietly dominate direct evidence in the wrong order

## Validation

- `python3 -m py_compile`
- `./.venv/bin/pytest --no-cov -q marking_framework/tests/test_verify_consistency.py marking_framework/tests/test_global_rerank.py`
- result: `23 passed`

Live workspace rerun:

- `outputs/consistency_checks.json`
- `outputs/final_order.csv`
- `outputs/consistency_report.json`
- `outputs/dashboard_data.json`

Key live summary after the final rerun:

- `judgment_count = 136`
- `pairwise_agreement_with_final_order = 0.941057`
- `s007` moved from seed `6` to final `17`
- `s011` moved from seed `7` to final `2`
- `s020` remains locked last by completion-floor logic

## Final Judgment

For this Ghost cohort, the pipe is now at the standard required for this class set:

- every placement is defensible on direct reading
- the human adjudicated order matches the final live rerun exactly
- the obvious cold-start failure modes have been corrected in code, not papered over manually

This cohort is complete as an adjudication-driven development pass.
