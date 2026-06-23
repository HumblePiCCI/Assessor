# Changelog: Grading Infrastructure Improvements

## 2026-06-22 - Criterion Evidence Cockpit + Local Teacher-Aid Hardening

**Problem:** The product was still too rank/curve-forward. Numeric marks could
look more precise than the evidence justified, teacher review depended on
explicit saves in too many paths, and tracked benchmark run artifacts included
private-looking `real_student_*` data that should not live in git.

**Solution:**
- Dashboard data now packages rubric-centered `rubric_claims`: criterion,
  evidence excerpts, counter-evidence, uncertainty, and instructional tags.
- Missing generated feedback no longer leaves blank feedback cards; dashboard
  build emits baseline two-stars-and-a-wish drafts from available evidence.
- Teacher review now includes an evidence cockpit, nearest-neighbor context,
  override history, autosaved draft edits, local browser recovery clearing, and
  data posture/PII-pattern counts.
- `criterion_referenced` is the default curve profile; rank no longer forces a
  bell distribution or monotonic cap in that mode.
- Review finalization writes `outputs/review_analytics.json` with override and
  drift summaries.
- Candidate/release publish profiles can require the perturbation stability
  harness report; missing or unstable stability evidence becomes a release
  blocker.
- Tracked `bench/runs/real_student_*` artifacts were removed. Local
  `bench/runs/` remains ignored; committed benchmark packs must be licensed,
  public or governed teacher-adjudicated cohorts with manifest review.

**Impact:** The teacher sees marks as defensible rubric claims first, ranking as
a reliability aid second, and local pilot data now has visible lifecycle and
privacy posture.

---

## 2026-06-11 - Close-Pair Committee Reads (E5)

**Problem:** Hard-pair eval showed single reads deciding close pairs on
structure/completion grounds ("more essay-shaped") against interpretive
depth, and one repair-tainted read surviving as a decider.

**Solution:** `verify_consistency.py` routes risky decisive CLOSE pairs
(structure-bias signature + top-pack/band-crossing + rubric gap <= 6 or
depth-not-backing-winner) to a 3-vote committee: primary read plus two
depth-lens reads (one per A/B orientation). Majority decides; clean votes
outrank tainted ones; verdicts are adjudicated evidence with full per-vote
traces; bounded by `--close-pair-committee-budget` (default 12; ~1.3x
pairwise cost). `--close-pair-committee-model/-reasoning` enable a stronger
diverse judge.

**Measured (live Ghost, fresh judgments):** tau 0.629 -> 0.638, top-5 4/5,
mean displacement improved; same-model committees uphold the model's sincere
convictions (1 flip), a stronger judge flips more (3, incl. the human's #1/#2
ordering) but net hard-pair accuracy is unchanged-to-slightly-lower. The
remaining Ghost disagreements (Jack pairs) persist across model sizes,
orientations, and lenses — a genuine judge-vs-this-teacher disagreement
(plausibly the teacher-familiarity effect blind-marked holdouts exist to
avoid), addressable per-cohort via the now-active anchor calibration, not by
more orchestration. Defaults keep same-model committees for benchmark
comparability.

---

## 2026-06-11 - Anchor Calibration: Rank-Evidence Redesign + Activation (R2)

**Problem:** Simulating the teacher anchor loop against blind-marked gold on
the holdout cohorts showed the score-interpolation patch HARMS the cohorts
anchors exist for (non-anchor tau 0.60 -> 0.20 on grade 6): interpolation
assumes machine scores are mis-scaled, but on novel scopes they are
mis-ordered, so rewriting seeds amplifies the noise.

**Solution (validated against gold on two holdout cohorts):**
- `apply_anchor_calibration.py` now emits the teacher's relative anchor order
  as `anchor_pairwise_judgments` (committee-grade adjudications) and disables
  seed patching (`seed_patch_enabled: false`).
- `global_rerank.py` injects those judgments when `ANCHOR_CALIBRATION_ACTIVE=1`
  (highest precedence, protected edges); `aggregate_assessments.py` respects
  rank-evidence mode and leaves seeds untouched. Anchor marks are reserved
  for grade-curve pinning (the teacher-review pin & re-flow).
- Measured effect (5 machine-selected anchors scored with gold): grade-6 tau
  0.644 -> 0.689, grade-10 tau 0.527 -> 0.600, non-anchor agreement never
  harmed. The old patch's hold-harmless reverts remain as backstop.
- `scripts/simulate_anchor_calibration.py`: replayable gold-anchored
  validation harness for any completed workspace.
- **Activated:** `live_cohort.shadow_mode=false` in config — novel cohorts now
  pause background auto-publish for teacher anchors (fast review unaffected).

---

## 2026-06-10 - Holdout Benchmark Cohorts (ASAP 2.0, grades 6-10)

Added four blind-marked holdout datasets for release validation —
`bench/holdout_asap2_g6_cowboy_waves`, `_g8_face_on_mars`,
`_g9_electoral_college`, `_g10_driverless_cars` (44 essays total, holistic 1-6
scores from trained state-assessment raters, full score-range coverage,
CC BY 4.0). Sampled deterministically by `scripts/import_asap2_cohorts.py`
from the ASAP 2.0 train split; never used for tuning. PERSUADE 2.0 and ELLIPSE
were evaluated and excluded (CC BY-NC-SA licensing); Texas STAAR and NY
Regents scoring guides identified as future grade-11/12 anchor sources.

---

## 2026-06-10 - Engine Consistency: Evidence-Adaptive Rerank + P0 Fixes

**Problem:** On live novel scopes the deterministic rerank layer underperformed
a plain fit of its own pairwise evidence (Ghost cohort: full pipeline tau 0.55
vs human adjudication, pure pairwise fit 0.64). Single unopposed LLM reads
became absolute constraint edges; seed-anchored protections (level locks,
collapse rescue, displacement caps) re-imposed noisy pass-1 seeds; repaired
judgments silently survived; large movers lacked top-pack comparisons.

**Solution (measured on the live Ghost cohort, offline-reproducible):**
- Seed trust is now earned: cohort-confidence signals (synthetic calibration,
  novel scope, assessor SD) plus the judgments' own swap rate scale prior
  regularization, displacement caps, and crossing margins
  (`compute_seed_reliability`, report `seed_trust` block; `--seed-trust-mode
  fixed` restores legacy behavior).
- Hard precedence edges require corroboration (2+ clean reads, adjudicated
  source, or redundant-agreement margins) and insert strongest-first;
  uncorroborated single reads only inform the score fit.
- On unvalidated scopes, seed-anchored edges that contradict the evidence-
  fitted order are waived (auditable `*_waived_low_seed_trust` drop reasons).
- P0-1: level-lock override hardened (named audit fields; completion/
  off-prompt/scaffold guard, also applied to band-crossing hard edges).
- P0-2: post-surge movers get direct top-pack comparisons and a second solve
  (`coverage_gap_repairs` / `coverage_gaps` in the consistency report).
- P0-3: repair-tainted judgments are detected, downweighted 0.25x, barred from
  all hard constraints; one strict-contract rerun before accepting taint;
  `pairwise_repair_tainted_rate` metric; publish gate blocks candidate/release
  when tainted pairs touch the top ten.
- P0-4: literary-analysis pass-1 scoring contract separates plot recall,
  evidence, explanation, and sustained interpretation; penalizes event-lists;
  protects rough-but-deep writing.
- New: `scripts/evaluate_live_cohort.py` (human-gold eval by display name),
  `scripts/stability_harness.py` (seeded Monte Carlo judge-noise harness).

**Impact:** Ghost cohort tau vs human 0.5524 → 0.6476, top-5 overlap 2/5 →
3/5, critical-pair accuracy 0.714 → 0.857, mean displacement 3.71 → 2.95.
Top-5 stability under 8% simulated judge noise: 4.75/5. Benchmark-suite
regression must be re-validated with a live API key before release (local
LLM caches do not cover benchmark workspaces).

---

## 2026-06-10 - Server-Authoritative Pin & Re-flow Curve

**Problem:** Teacher grade adjustments were client-side only — the server stored
`assigned_marks` verbatim and never re-shaped the curve, the UI replaced the
pipeline's band-aware bell with a plain linear spread, and moving one student's
mark did not cascade to the rest of the cohort.

**Solution:**
- New deterministic core: `scripts/curve_reflow.py`. The machine curve
  (unrounded `curve_grade_raw` when available) is the shape function; teacher
  pins and curve bounds are anchors; every unpinned mark re-interpolates along
  the machine shape between its nearest anchors. Precedence: monotonicity >
  pins > bounds > shape. Rounding plateaus respace positionally so they stretch
  rather than move as a block. Identity (no pins, no bounds) returns machine
  marks verbatim.
- Server authority: `POST /projects/curve/reflow` previews the cascade;
  review saves with `pinned_marks` recompute `assigned_marks` server-side
  (client marks are never trusted). Pin-implied rank changes require explicit
  teacher confirmation (`accept_reorder`); finalize returns 409 otherwise.
  Passback/CSV export consume the recomputed `assigned_marks` unchanged.
- UI: the rail and workspace now display the pipeline's real curve. Setting a
  mark pins that student (badge in rail + snapshot, unpin control); all other
  marks re-flow live from the server; a curve strip shows machine vs adjusted
  shape with pins; rank-change confirmations appear inline. Exceptions panel
  is collapsed until findings exist; arrow keys move between essays.
- Tests: `tests/test_curve_reflow.py` (algorithm), `tests/test_curve_reflow_server.py`
  (endpoint, persistence, finalize gate), plus UI source contract assertions.

**Impact:** Teacher keeps final authority with one-slider adjustments that
cascade deterministically and repeatably; the whole bell stays in place and
every mark is explainable via its anchors.

---

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
