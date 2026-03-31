# Consistency Calibration Design (Ontario-Aligned)

## Why this pass exists

For assessment to be defensible in schools, the system must be stable across runs and aligned to provincial expectations:

- Ontario treats **Level 3** as the provincial standard ([Growing Success](http://www.edu.gov.on.ca/eng/policyfunding/growSuccess.pdf)).
- EQAO scoring uses trained raters, item-specific rubrics, second scoring checks, and adjudication to control drift ([EQAO Item Development and Scoring Framework](https://www.eqao.com/wp-content/uploads/EQAO-Item-Development-and-Scoring-Framework.pdf)).

LLMs do not naturally behave this way. Recent work shows judge models can be inconsistent and biased by position/framing, so explicit calibration and bias control are required ([ACL 2025](https://aclanthology.org/2025.findings-acl.306/)).

## Research-backed principles used

1. **Anchor-based calibration beats raw free scoring**
   - Calibrate assessors against fixed exemplars per grade band and genre.
   - Use monotonic mapping from observed scores to target scores.
2. **Bias correction must include reliability weighting**
   - Penalize assessors with high error and low repeat consistency.
3. **Sparse scope estimates should shrink to global estimates**
   - Avoid overfitting genre/grade profiles with low sample counts.
4. **Order reliability is as important as exact score reliability**
   - Track pairwise order agreement and position hit, not just MAE.

## Implemented model

### A) Calibration records

For each assessor × exemplar:

- score against gold target percentage and level
- repeat scoring `N` times (default from config: `3`)
- store observed vs target for profile fitting

### B) Profile fitting

Per assessor (global and per scope `grade_band|genre`):

- collapse repeated observations by sample (mean observed)
- fit monotonic `map_points` (piecewise interpolation)
- compute:
  - `mae_raw`, `mae`
  - `level_hit_rate`
  - `order_position_hit_rate`
  - `pairwise_order_agreement`
  - `stability_sd`
  - `repeat_level_consistency`
- derive a single reliability `weight` (used downstream)

### C) Scoped/global shrinkage at inference

When a scoped profile exists, blend scoped and global bias entries using:

- scope sample count
- configurable prior (`scope_prior`)
- relative assessor reliability

This reduces unstable jumps when scope data are sparse.

### D) Aggregation impact

- pass1 scores are bias-corrected using calibration profile
- assessor reliability weights influence rubric central tendency and rank contribution
- final ranking remains deterministic tie-broken

## Reliability gates to enforce in production

- ICC interpretation guideline from Koo & Li (2016):
  - `< 0.50` poor
  - `0.50–0.75` moderate
  - `0.75–0.90` good
  - `> 0.90` excellent
  - source: [PMCID: PMC4913118](https://pmc.ncbi.nlm.nih.gov/articles/PMC4913118/)
- Minimum calibration quality before release:
  - `level_hit_rate >= 0.70`
  - `pairwise_order_agreement >= 0.80`
  - `stability_sd <= 4.0`

## Practical deployment defaults

- `temperature = 0.0` for pass1/pass2
- strict structured output format for pass1 parsing
- deterministic fallback enabled for malformed responses
- calibration rerun when:
  - rubric family changes materially
  - grade band/genre changes
  - model version changes

## Additional references

- Comparative judgement reliability literature supports pairwise order methods for writing quality when calibrated (see synthesis and reliability values in [Frontiers in Education](https://www.frontiersin.org/articles/10.3389/feduc.2024.1305987/full)).
- Evidence that calibration + anchoring improves LLM score alignment and reduces systematic error in educational estimation ([PubMed 40697062](https://pubmed.ncbi.nlm.nih.gov/40697062/)).
