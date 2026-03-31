# Quick Start Guide - Enhanced Grading System

## Prerequisites

- Python 3.7+
- Student submissions in supported formats (.docx, .txt, .pdf)
- Rubric (structured or to be structured)
- Assignment outline

## Step-by-Step Workflow

Optional: Run the orchestration script

```bash
python3 scripts/hero_path.py --generate-pairs --build-dashboard
```

LLM-assisted assessors (requires OPENAI_API_KEY):

```bash
python3 scripts/hero_path.py --llm-assessors --pricing-report --generate-pairs
```

Cost caps are set in `config/cost_limits.json`. To bypass:

```bash
python3 scripts/hero_path.py --llm-assessors --ignore-cost-limits
```

### 1. Setup Inputs

```bash
# Place files in inputs directory
inputs/
├── rubric.md (or rubric.docx)
├── assignment_outline.md
├── class_metadata.json (optional, e.g., {"grade_level": 7})
└── submissions/
    ├── student001.docx
    ├── student002.docx
    └── ...
```

### 2. Extract & Normalize Text

```bash
python3 scripts/extract_text.py \
  --inputs inputs/submissions \
  --output processing/normalized_text
```

**Output:** `processing/normalized_text/*.txt` (one per student)

### 3. Run Conventions Scan

```bash
python3 scripts/conventions_scan.py \
  --inputs processing/normalized_text \
  --output processing/conventions_report.csv
```

**Output:** `processing/conventions_report.csv` (mistake rates per student)

### 4. Assessor Pass 1 - Independent Scoring

For **each of 3 assessors** (A, B, C):

1. Review role in `docs/ASSESSOR_ROLES.md`
2. Use prompt from `prompts/assessor_pass1.md`
3. Score each student against rubric criteria
4. Save as JSON: `assessments/pass1_individual/assessor_[A|B|C].json`

**Format example:**
```json
{
  "assessor_id": "assessor_A",
  "role": "rubric_strict",
  "rubric_points_possible": 20,
  "scores": [
    {
      "student_id": "student001",
      "rubric_total_points": 16,
      "criteria_points": {
        "thesis": 4,
        "evidence": 5,
        "organization": 4,
        "language": 3
      },
      "notes": "Strong thesis and good evidence."
    }
  ]
}
```

### 5. Assessor Pass 2 - Comparative Ranking

For **each of 3 assessors**:

1. Use prompt from `prompts/assessor_pass2.md`
2. Rank ALL students from best to worst
3. Save as plain text: `assessments/pass2_comparative/assessor_[A|B|C].txt`

**Format example:**
```
student015
student007
student003
student001
...
```

### 6. Aggregate to Consensus

```bash
python3 scripts/aggregate_assessments.py \
  --config config/marking_config.json
```

**Critical checks:**
- ✅ All assessors scored all students?
- ✅ All assessors ranked all students?
- ✅ Conventions data exists for all?

**If validation fails:** Fix missing data, then re-run.

**Outputs:**
- `outputs/consensus_scores.csv` - Full scoring breakdown
- `outputs/ranked_list.md` - Consensus ranking
- `outputs/irr_metrics.json` - Inter-rater reliability
- `assessments/pass3_reconcile/disagreements.md` - Flagged students

**Check IRR metrics:**
```bash
cat outputs/irr_metrics.json
```

Look for:
- `rubric_icc` > 0.7 (good) or > 0.9 (excellent)
- `rank_kendall_w` > 0.7 (good agreement)

### 7. Pass 3 - Reconciliation (if needed)

If students are flagged in `disagreements.md`:

1. Assessors re-read ONLY flagged essays
2. Update scores/rankings as needed
3. Re-run aggregation (step 6)
4. Repeat until flags resolved or accepted

### 8. Final Pairwise Review (Hero Path)

```bash
python3 scripts/generate_pairwise_review.py
```

Update `assessments/final_review_pairs.json` with keep/swap decisions and reasons, then apply:

```bash
python3 scripts/apply_pairwise_adjustments.py --min-confidence med
```

Optional LLM helper:
```bash
python3 scripts/llm_pairwise_review.py
python3 scripts/llm_pairwise_review.py --apply
```

### 9. Interactive Curve Review

```bash
python3 scripts/review_and_grade.py
```

**Interactive prompts:**
1. Review consensus ranking displayed
2. Check flagged students
3. Adjust top grade (default: 92)
4. Adjust bottom grade (default: 58)
5. Preview distribution histogram
6. Confirm or adjust again
7. Press 'yes' to apply

**Output:** `outputs/grade_curve.csv` - Final grades

**Non-interactive mode:**
```bash
python3 scripts/review_and_grade.py --non-interactive
```

### 10. Generate Feedback Templates

```bash
python3 scripts/generate_feedback.py \
  --grades outputs/grade_curve.csv \
  --texts processing/normalized_text \
  --output outputs/feedback_summaries
```

**Output:** `outputs/feedback_summaries/[student_id]_feedback.md` for each student

### 11. Fill In Feedback

For each student's feedback template:

1. Read the student's essay
2. Fill in **Two Stars** (strengths with quotes)
3. Fill in **One Wish** (highest-leverage improvement with quote)
4. Ensure quotes are EXACT text from student's essay

**Template structure:**
```markdown
## Two Stars (Strengths)

### Star 1
**Strength:** Clear thesis statement that previews argument

**Quote:**
> "Social media has fundamentally altered human connection by replacing depth with breadth, intimacy with performance, and genuine dialogue with curated monologues."

**Explanation:** This thesis is specific, arguable, and signals the three-part structure of the essay.
```

### 12. Validate Feedback Quotes

```bash
python3 scripts/generate_feedback.py \
  --validate
```

**Checks:**
- Each feedback file has 3+ quotes
- All quotes appear in student's actual text (exact or fuzzy match)
- Reports invalid quotes for correction

**Fix any validation errors, then re-run.**

### 13. Teacher Review UI

```bash
python3 scripts/build_dashboard_data.py
python3 scripts/serve_ui.py
```

### 13b. Pay-as-you-go job runner (optional)

```bash
python3 scripts/payg_job.py \
  --rubric inputs/rubric.md \
  --outline inputs/assignment_outline.md \
  --submissions inputs/submissions \
  --llm \
  --pricing
```

### 14. Final Outputs

You now have:
- ✅ `outputs/grade_curve.csv` - Final grades
- ✅ `outputs/ranked_list.md` - Consensus ranking
- ✅ `outputs/irr_metrics.json` - Quality metrics
- ✅ `outputs/feedback_summaries/` - Validated feedback for each student

## Configuration Options

### Adjust Weights

Edit `config/marking_config.json`:

```json
{
  "weights": {
    "rubric": 0.70,      // Increase if rubric most important
    "conventions": 0.15,  // Increase if mechanics critical
    "comparative": 0.15   // Increase if relative quality matters
  }
}
```

**Note:** Weights must sum to 1.0

### Adjust Quality Gates

```json
{
  "consensus": {
    "rank_disagreement_threshold": 3,  // Flag if rank SD >= 3
    "rubric_sd_threshold": 0.8         // Flag if rubric SD >= 0.8 points
  }
}
```

### Adjust Conventions Penalty

```json
{
  "conventions": {
    "mistake_rate_threshold": 0.07,  // 7% error rate triggers penalty
    "max_level_drop": 1              // Reduces rubric by ~10%
  }
}
```

## Troubleshooting

### "Data completeness check FAILED"

**Cause:** Missing scores or rankings from assessors

**Fix:**
1. Check error messages for specific student IDs
2. Review `assessments/pass1_individual/*.json` files
3. Review `assessments/pass2_comparative/*.txt` files
4. Ensure all assessors scored ALL students

### "Rubric ICC is poor"

**Cause:** Assessors disagree significantly on rubric scores

**Possible fixes:**
1. Clarify rubric criteria definitions
2. Calibrate assessors with sample essays
3. Check if one assessor is systematically higher/lower
4. Consider rubric redesign if persistent

### "Quote not found in text"

**Cause:** Quote in feedback doesn't match student's actual text

**Fix:**
1. Open student's text file in `processing/normalized_text/`
2. Search for the quoted phrase
3. Copy EXACT text (including punctuation)
4. Paste into feedback template
5. Re-run validation

### Conventions penalty seems too harsh

**Adjust threshold:**
```json
{
  "conventions": {
    "mistake_rate_threshold": 0.10,  // 10% instead of 7%
    "max_level_drop": 0.5            // Smaller penalty
  }
}
```

## Command Reference

```bash
# Full workflow in sequence
python3 scripts/extract_text.py --inputs inputs/submissions --output processing/normalized_text
python3 scripts/conventions_scan.py --inputs processing/normalized_text --output processing/conventions_report.csv

# [Manual: Assessor Pass 1 & 2]

python3 scripts/aggregate_assessments.py --config config/marking_config.json
python3 scripts/review_and_grade.py
python3 scripts/generate_feedback.py
# [Manual: Fill in feedback templates]
python3 scripts/generate_feedback.py --validate

# Non-interactive automation
python3 scripts/review_and_grade.py --non-interactive
```

## Best Practices

1. **Calibrate assessors** before Pass 1 with sample essays
2. **Complete all passes** before aggregation (don't skip Pass 2)
3. **Review IRR metrics** every grading session to track quality
4. **Document deviations** from default settings with rationale
5. **Archive all outputs** for potential grade appeals
6. **Validate quotes** before releasing feedback to students
7. **Never use --allow-missing-data** in production (unfair to students)

## Getting Help

- Review `CHANGELOG.md` for recent changes
- Check `docs/MARKING_MODEL.md` for decision rules
- See `docs/QUALITY_GATES.md` for validation criteria
- Read `docs/ASSESSOR_ROLES.md` for assessor guidance

---

_Last updated: 2026-01-31_
