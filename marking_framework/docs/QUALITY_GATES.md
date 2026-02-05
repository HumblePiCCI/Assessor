Quality Gates

Hard Requirements (Aggregation Will Fail)
- At least 3 assessors for both Pass 1 and Pass 2
- Every assessor must score every student (no missing data)
- Every assessor must rank every student (no missing rankings)
- Conventions scan data must exist for all students
- Use --allow-missing-data flag to bypass (NOT RECOMMENDED - may produce unfair grades)

Re-read Required If Any Condition Is Met
- Rubric score SD >= 0.8 points (on the rubric scale converted to points)
- Rank SD >= 3 positions across assessors
- Conventions mistake rate exceeds configured threshold (default: 7%)
- Conventions penalty flag applied

Inter-Rater Reliability Targets
- Rubric ICC: >0.7 good, >0.9 excellent
- Rank Kendall's W: >0.7 good agreement
- Mean rubric SD: <1.0 points preferred
- Mean rank SD: <3 positions preferred

Minimum Workflow Coverage
- Pass 1: Independent scoring (all assessors)
- Pass 2: Comparative ranking (all assessors)
- Pass 3: Reconciliation on flagged essays
- Final pairwise review (adjacent essays, assignment outline check)
- Interactive curve review before finalizing grades
- Quote validation for all feedback
