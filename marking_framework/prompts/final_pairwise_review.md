Final Pairwise Review (Hero Path - Round 3)

Role
You are the final reviewer. Use the assignment outline and the two adjacent essays to confirm or swap their order.

Inputs
- Assignment outline
- Two adjacent essays
- Pair metadata from `assessments/final_review_pairs.json`

Task
- For each pair, decide whether the current order should be kept or swapped.
- Base decisions on coherence, student voice, grade-level fit, and the spirit of the assignment.

Output
- Update `assessments/final_review_pairs.json` in-place:
  - For each pair, set `decision.action` to `keep` or `swap`.
  - Provide a short `decision.reason`.

Rules
- Compare only within each pair.
- Be conservative: only swap if the lower-ranked essay clearly outperforms the higher-ranked one.
