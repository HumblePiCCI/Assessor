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
- Stability guards for spelling:
  - title-case proper nouns are excluded
  - class-wide repeated unknown terms are auto-whitelisted (e.g., character names, domain words)
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
  - Rubric central tendency defaults to median across assessors (more robust to outliers)
  - Calibration bias correction supports affine moderation (`corrected = slope * raw + intercept`)
  - Conventions penalty is progressive once threshold is exceeded (fractional level drop up to configured max)
  - Borda aggregation of comparative rankings
  - Disagreement flags if rubric SD or rank SD exceed thresholds
- Data completeness validation: all assessors must score all students (hard requirement)
- Inter-rater reliability metrics calculated (ICC, Kendall's W)
- Any flagged essays require targeted re-reads before final ordering.
- OpenAI main-path contract hardening:
  - Pass 1 and Pass 2 use strict JSON schema outputs.
  - Pass 1 can be anchor-guarded against deterministic drift (`pass1_guard` in routing config).
  - Optional `--require-model-usage` fails the run if zero model outputs are accepted (prevents silent full fallback).

5) Curve-Based Grades
- After consensus order, grades are assigned by a level-aware bell profile.
- Default: highest = 92, lowest = 58, with rubric evidence blended with resolved cohort order.
- Level bands remain locked first; ordering organizes students within each level band.
- Rounding policy is configurable.
- Optional review step allows manual adjustment of top/bottom before applying the curve.

5b) Pairwise Evidence And Global Rerank
- After consensus, near-adjacent essays are re-read in pairs against the assignment outline.
- The consistency stage emits normalized pairwise evidence rather than directly mutating the order.
- A deterministic global reranker consumes:
  - seed composite features
  - pairwise judgments
  - level-band constraints
  - displacement caps
- This produces `final_order.csv` and `consistency_report.json` prior to curve application.

5c) Teacher Review Feedback
- The dashboard persists structured teacher review snapshots:
  - level overrides
  - desired rank changes
  - pairwise adjudications
  - evidence-quality notes
- Each saved review is versioned against the pipeline manifest, calibration manifest, and final artifact set.
- Exploratory edits are saved as draft state; only finalized review becomes learning signal.
- Finalized review feedback feeds replay exports, local learning summaries, and a bounded scoped local teacher prior used during future reranks in the same scope.
- Product-wide aggregate learning from teacher feedback remains a governed follow-on stage.

6) Two Stars and a Wish (Post-Curve)
- Generated only after consensus ranking and curve-based grades are finalized.
- Two Stars: two specific strengths supported by exact quotes.
- One Wish: a single highest-leverage improvement, supported by a quote that shows the gap.
- The Wish must target the biggest improvement to overall quality.

Decision Rules
- Final ranking is seeded by the composite score (weighted: rubric + conventions + comparative) and resolved by the global reranker using pairwise evidence plus level-lock constraints.
- Adjusted level band is resolved before fine-grained ordering.
- Tie-breakers in order: composite bucket, Borda bucket, rubric after penalty, conventions mistake rate, student ID.
- Conventions penalty triggers if mistake rate exceeds threshold (default: 7%).
- Missing data from any assessor for any student causes aggregation to fail (ensures fairness).
- Inter-rater reliability thresholds: ICC >0.7 recommended, Kendall's W >0.7 recommended.

Outputs
- Consensus ranking (composite score-based)
- Score summary table (with composite scores, penalties, flags)
- Inter-rater reliability metrics (ICC, Kendall's W, SDs)
- Pairwise evidence matrix and rerank diagnostics
- Final order artifact for curve application
- Curve-based grades (with interactive review)
- Disagreement list for review
- Persisted teacher review snapshot, replay exports, and local learning profile
- Two stars and a wish feedback per student (post-curve, with quote validation)

Validation Harness
- Run `python3 scripts/benchmark_main_vs_fallback.py --dataset <dataset> --runs 3`.
- Benchmark datasets must include `inputs/`, `submissions/`, and explicit `gold.jsonl` or `gold.csv`.
- The harness emits `benchmark_report.json` and `benchmark_report.md` with exact-level hit rate, within-one-level hit rate, score-band MAE, rank displacement, Kendall correlation, pairwise agreement, stability variance, model usage ratio, cost, and latency.
- The default comparison is current candidate routing versus deterministic fallback, and the report is structured for `publish_gate.py` and `sota_gate.py` to consume directly.
