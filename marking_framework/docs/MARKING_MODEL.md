Marking Model

Overview
This model standardizes marking across three inputs: a rubric, an assignment outline, and student submissions. It enforces a multi-pass workflow with multiple assessors and consensus ranking before curve-based grading.

Model Components
1) Conventions Mistake Rate
- Purpose: measure mechanics consistency and writing control.
- Baseline scan includes:
  - sentence-start capitalization
  - missing end punctuation
  - repeated spaces
  - spelling outliers (wordlist-based; heuristic)
- Metric: `mistake_rate = total_errors / total_words` (reported as %)
- Conventions modifiers (e.g., 3+, 4-) are derived from mistake-rate bands in config.

2) Rubric Adherence
- Assessors score each rubric criterion on the rubric's scale.
- Scores are converted to points and totaled per essay.
- Rubric scores are normalized to 0-100 for aggregation.
- Board level bands are applied to rubric percent:
  - Level 1 = 50-59% (D)
  - Level 2 = 60-69% (C)
  - Level 3 = 70-79% (B)
  - Level 4 = 80-89% (A)
  - Level 4+ = 90%+ (A+)

3) Comparative Ranking
- Each assessor produces a best-to-worst ordering of the class.
- Aggregation uses Borda count (higher points = stronger rank).
- Ranking is used to stabilize ordering beyond raw point totals.

4) Multi-Assessor Consensus
- Minimum of three assessors with distinct roles:
  - Rubric-strict
  - Conventions-strict
  - Holistic
- Consensus algorithm:
  - Composite score = weighted combination (default: 70% rubric + 15% conventions + 15% comparative)
  - Rubric scores averaged across assessors
  - Conventions penalty applied if mistake rate exceeds threshold (reduces rubric score by one level, based on band width)
  - Borda aggregation of comparative rankings
  - Disagreement flags if rubric SD or rank SD exceed thresholds
- Data completeness validation: all assessors must score all students (hard requirement)
- Inter-rater reliability metrics calculated (ICC, Kendall's W)
- Any flagged essays require targeted re-reads before final ordering.

5) Curve-Based Grades
- After consensus order, grades are assigned along a fixed curve.
- Default: highest = 92, lowest = 58 (linear interpolation).
- Rounding policy is configurable.
- Optional review step allows manual adjustment of top/bottom before applying the curve.

5b) Final Pairwise Review (Hero Path)
- After consensus, adjacent essays are re-read in pairs against the assignment outline.
- Order changes are conservative (swap only when clearly justified).
- This produces a final order prior to curve application.
- Optional confidence threshold can auto-apply swaps and flag low-confidence cases.

6) Two Stars and a Wish (Post-Curve)
- Generated only after consensus ranking and curve-based grades are finalized.
- Two Stars: two specific strengths supported by exact quotes.
- One Wish: a single highest-leverage improvement, supported by a quote that shows the gap.
- The Wish must target the biggest improvement to overall quality.

Decision Rules
- Final ranking determined by composite score (weighted: rubric + conventions + comparative).
- Tie-breakers in order: Borda points, rubric after penalty, conventions mistake rate, student ID.
- Conventions penalty triggers if mistake rate exceeds threshold (default: 7%).
- Missing data from any assessor for any student causes aggregation to fail (ensures fairness).
- Inter-rater reliability thresholds: ICC >0.7 recommended, Kendall's W >0.7 recommended.

Outputs
- Consensus ranking (composite score-based)
- Score summary table (with composite scores, penalties, flags)
- Inter-rater reliability metrics (ICC, Kendall's W, SDs)
- Curve-based grades (with interactive review)
- Disagreement list for review
- Two stars and a wish feedback per student (post-curve, with quote validation)
