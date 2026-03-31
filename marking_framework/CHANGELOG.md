# Changelog: Grading Infrastructure Improvements

## Version 2.0 - Fairness & Reliability Enhancements

### High-Priority Fixes Implemented

#### 1. ✅ Composite Score Ranking (CRITICAL FIX)
**Problem:** Weighting system (70% rubric, 15% conventions, 15% comparative) was configured but ignored. Final ranking used only Borda count.

**Solution:**
- Final ranking now uses **composite score** as primary sort key
- Composite = (0.70 × rubric) + (0.15 × conventions) + (0.15 × comparative)
- Tie-breakers: Borda → rubric mean → conventions → student ID
- Configurable weights in `marking_config.json`

**Impact:** Rankings now reflect the documented weighting model, ensuring consistency between documented policy and actual behavior.

**File:** `scripts/aggregate_assessments.py` (lines 172-186)

---

#### 2. ✅ Conventions Penalty Logic (ALIGNMENT FIX)
**Problem:** Config defined `mistake_rate_threshold` and `max_level_drop`, but code never applied the penalty.

**Solution:**
- Implemented penalty: if conventions mistake rate > threshold (default 7%), reduce rubric score by ~10% (one "level")
- Penalty applied BEFORE composite score calculation
- Students flagged with "conventions_penalty" tag
- Logged for transparency

**Impact:** High error rates now have consequences as documented, improving fairness and incentivizing careful writing.

**File:** `scripts/aggregate_assessments.py` (lines 179-192)

---

#### 3. ✅ Missing Data Hard-Fail (FAIRNESS FIX)
**Problem:** Missing data was silently handled by assigning worst rank, penalizing students for assessor errors.

**Solution:**
- **Hard validation:** Aggregation fails if ANY assessor missing data for ANY student
- Checks: minimum 3 assessors, all students scored by all assessors, all rankings complete
- Detailed error reporting with student-by-student breakdown
- `--allow-missing-data` flag available (not recommended)

**Impact:** Ensures no student is penalized due to incomplete assessments. Forces proper data collection.

**File:** `scripts/aggregate_assessments.py` (lines 78-117)

---

#### 4. ✅ Inter-Rater Reliability Metrics (QUALITY CONTROL)
**Problem:** No overall consistency metrics; couldn't tell if assessors agreed across the whole cohort.

**Solution:**
- **ICC (Intraclass Correlation):** Measures rubric score consistency (>0.7 = good, >0.9 = excellent)
- **Kendall's W:** Measures ranking agreement (>0.7 = good)
- **Mean SDs:** Average rubric SD and rank SD across all students
- Metrics saved to `outputs/irr_metrics.json`
- Interpretation guide included in output

**Impact:** Provides quality assurance signal. Low IRR indicates assessor training needed or rubric clarification required.

**File:** `scripts/aggregate_assessments.py` (lines 69-135, 229-253)

---

#### 5. ✅ Two Stars and a Wish Auto-Generator (AUTOMATION)
**Problem:** Feedback generation was manual and ad-hoc; no quote validation.

**Solution:**
- New script: `scripts/generate_feedback.py`
- **Template generation:** Creates structured markdown templates for each student
- **Quote validation:** Checks that quoted text actually appears in student essays
- **Fuzzy matching:** Allows minor punctuation/whitespace differences
- **Validation mode:** `--validate` flag checks all existing feedback

**Impact:** Standardizes feedback format, ensures quotes are authentic, saves time.

**File:** `scripts/generate_feedback.py` (full file)

---

#### 6. ✅ Interactive Curve Review (ALREADY IMPLEMENTED BY USER)
**Problem:** Curve was applied automatically without human verification of ordering or grade distribution.

**Solution:**
- New script: `scripts/review_and_grade.py`
- Shows consensus ranking with flags
- Allows adjustment of top/bottom grades
- Previews distribution histogram before applying
- Confirms before writing final grades

**Impact:** Decouples ordering from distribution, gives control over grade ranges while preserving rank order.

**File:** `scripts/review_and_grade.py` (full file)

---

#### 7. ✅ Comprehensive Logging (AUDITABILITY)
**Problem:** No logging; hard to debug or audit the grading process.

**Solution:**
- Added Python `logging` module to all scripts
- Timestamped logs show:
  - Files processed
  - Students counted
  - Penalties applied
  - Validation results
  - IRR metrics
- Summary report at end of each script

**Impact:** Full audit trail of grading decisions. Easier debugging and transparency.

**Files:** All scripts in `scripts/`

---

#### 8. ✅ Input Validation & Error Handling (ROBUSTNESS)
**Problem:** Malformed JSON or missing fields caused cryptic errors.

**Solution:**
- JSON schema validation for Pass 1 files
- Required field checking (`assessor_id`, `scores`, etc.)
- Helpful error messages with file names
- Graceful degradation with warnings

**Impact:** Clearer error messages help identify and fix data issues quickly.

**File:** `scripts/aggregate_assessments.py` (lines 24-41)

---

### Updated Documentation

#### Files Modified:
1. **`MARKING_MODEL.md`**: Updated to reflect composite scoring, penalties, IRR metrics
2. **`WORKFLOW.md`**: Added feedback generation and validation steps
3. **`QUALITY_GATES.md`**: Added hard requirements, IRR targets
4. **`README.md`**: Updated outputs list, added IRR metrics and validation
5. **`CHANGELOG.md`**: This file - comprehensive summary of changes

---

### Configuration Changes

#### `marking_config.json` - Now Fully Functional
All parameters are now used by the code:

```json
{
  "weights": {
    "rubric": 0.70,        // ✅ NOW USED in composite score
    "conventions": 0.15,   // ✅ NOW USED in composite score
    "comparative": 0.15    // ✅ NOW USED in composite score
  },
  "consensus": {
    "rank_disagreement_threshold": 3,    // Flags if rank SD >= 3
    "rubric_sd_threshold": 0.8           // Flags if rubric SD >= 0.8 points
  },
  "curve": {
    "top": 92,              // Default top grade (adjustable in review)
    "bottom": 58,           // Default bottom grade (adjustable in review)
    "rounding": "nearest"   // Options: nearest, floor, ceil
  },
  "rubric": {
    "points_possible": null  // Auto-detected from assessor files
  },
  "conventions": {
    "mistake_rate_threshold": 0.07,  // ✅ NOW USED: triggers penalty if exceeded
    "max_level_drop": 1              // ✅ NOW USED: ~10% penalty per level
  }
}
```

---

### New Outputs

#### `outputs/irr_metrics.json`
```json
{
  "inter_rater_reliability": {
    "rubric_icc": 0.823,
    "rank_kendall_w": 0.756,
    "mean_rubric_sd": 0.64,
    "mean_rank_sd": 2.1
  },
  "assessment_info": {
    "num_students": 25,
    "num_assessors_pass1": 3,
    "num_assessors_pass2": 3,
    "rubric_points_possible": 20
  },
  "quality_summary": {
    "students_flagged": 3,
    "conventions_penalties": 2
  },
  "interpretation": {
    "rubric_icc": "good",
    "rank_agreement": "good"
  }
}
```

#### `outputs/consensus_scores.csv` - New Columns
- `rubric_after_penalty_percent`: Rubric score after conventions penalty (if applied)
- `composite_score`: Weighted combination used for ranking
- Flags now include: `conventions_penalty`

#### `outputs/feedback_summaries/[student_id]_feedback.md`
- Structured template with placeholders
- Quote validation support
- Consistent format across all students

---

### Workflow Changes

#### Before (v1.0):
1. Aggregate → 2. Apply curve → 3. Manual feedback

#### After (v2.0):
1. **Aggregate** (with validation, IRR, penalties) →
2. **Review ranking & flags** →
3. **Interactive curve adjustment** →
4. **Generate feedback templates** →
5. **Fill in templates** →
6. **Validate quotes**

---

### Remaining Known Issues

#### 1. Conventions Spell Checker (DOCUMENTED)
The current spell checker has limitations:
- Ignores all capitalized words (proper nouns)
- Splits contractions incorrectly
- Depends on system wordlist availability

**Recommendation:** Use as a heuristic baseline, or replace with `language-tool-python` for production use.

#### 2. Linear Curve Assumption (DOCUMENTED)
The curve is strictly linear from top to bottom. This may not reflect actual quality distribution.

**Future Enhancement:** Add non-linear curve options (normal distribution, piecewise linear).

#### 3. Borda Count Ordinal Assumption (DOCUMENTED)
Borda assumes equal intervals between ranks. Rank 1→2 difference treated same as rank 15→16.

**Mitigation:** Borda is now a tie-breaker, not the primary ranking mechanism.

---

### Testing Recommendations

Before using in production:

1. **Unit Tests:** Create tests for `mean()`, `stdev()`, `calculate_irr_metrics()`, `validate_quote()`
2. **Integration Test:** Run full workflow with sample data
3. **IRR Baseline:** Establish acceptable IRR thresholds for your context
4. **Penalty Calibration:** Test conventions penalty with various mistake rates
5. **Quote Validation:** Test with various quote formats and edge cases

---

### Migration Guide

If upgrading from v1.0:

1. **Re-run aggregation** with new script to get composite scores
2. **Review IRR metrics** to establish baseline
3. **Adjust weights** in config if needed (defaults: 70/15/15)
4. **Set conventions threshold** appropriately for your context (default: 7% mistake rate)
5. **Use interactive review** for curve application
6. **Generate feedback templates** instead of creating from scratch
7. **Validate quotes** before releasing feedback to students

---

### Summary

**Fairness:** Missing data validation ensures no student is unfairly penalized.
**Consistency:** Composite score ranking aligns behavior with documented model.
**Quality:** IRR metrics provide ongoing quality assurance.
**Transparency:** Comprehensive logging creates full audit trail.
**Efficiency:** Automated feedback generation with validation saves time.

**Result:** A grading infrastructure that is now **fair, consistent, transparent, and auditable**.

---

_Updated: 2026-01-31_
_Version: 2.0_
