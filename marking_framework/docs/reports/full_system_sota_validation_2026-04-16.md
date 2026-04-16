# Full System SOTA Validation

- Generated: 2026-04-16
- Branch: `codex/fix-live-literary-ranking`
- Scope: full external corpus plus the live Grade 7 Ghost cohort

## External Corpus

I reran the full external benchmark corpus at `--runs 3` with the current `gpt54_split` routing against the `gpt52_legacy` baseline.

- Datasets: 32
- Students: 133
- Failed datasets: 0
- Exact-level hit rate: 0.954887
- Within-one-level hit rate: 0.992481
- Score-band MAE: 1.13594
- Mean rank displacement: 0.075188
- Kendall tau: 0.961905
- Pairwise order agreement: 0.980952
- Cost: 0.081254 USD
- Latency: 25.6633 seconds

Against the `gpt52_legacy` baseline, the split routing is ahead on every quality metric that matters for release:

- Exact-level hit delta: +0.383458
- Within-one-level hit delta: +0.045113
- Score-band MAE delta: -1.958571
- Mean rank displacement delta: -0.255639
- Kendall tau delta: +0.185464
- Pairwise order agreement delta: +0.092732

Against the previous Ontario release run from 2026-04-13, the new run also improves exact hit, MAE, rank displacement, Kendall, pairwise agreement, and cost. Latency is higher because this was a live model-backed run rather than the earlier cached/near-instant benchmark path, but it remains below the 60 second release threshold.

Tracked artifacts:

- `docs/reports/gpt54_split_full_corpus_with_ghost_fixes_release_runs3_2026-04-16.json`
- `docs/reports/gpt54_split_full_corpus_with_ghost_fixes_release_runs3_2026-04-16.md`

## Release Gate

The SOTA gate is green at release profile using the current full corpus summary and the previously accepted release publish profile.

- SOTA gate ok: true
- Highest attained profile: release
- Decision state: release_ready
- Benchmark failed datasets: 0
- Benchmark runs successful: 3

Tracked artifacts:

- `docs/reports/gpt54_split_sota_gate_with_ghost_fixes_release_2026-04-16.json`
- `docs/reports/gpt54_split_sota_gate_with_ghost_fixes_release_2026-04-16.md`

## Live Ghost Cohort

I checked the current live Grade 7 Ghost project against the adjudicated human order from `ghost_live_cohort_audit_2026-04-15.md`.

The current final pipe order matches the adjudicated order exactly:

`s015, s011, s009, s002, s003, s013, s019, s010, s022, s006, s012, s014, s016, s018, s001, s017, s007, s021, s005, s004, s008, s023, s020`

Live cohort consistency metrics:

- Students: 23
- Pairwise agreement with final order: 0.941057
- Swap rate: 0.316176
- Low-confidence rate: 0.014706
- Mean absolute displacement: 2.782609
- Pairwise conflict density: 0.0
- Boundary disagreement concentration: 0.0

The unfinished scaffold draft remains last (`s020`), and the previously problematic complete-vs-incomplete lower-band edge is now enforced by the completion-floor constraint plus direct pairwise evidence.

Production note: this live project still has bootstrap/synthetic calibration and no teacher-scored anchors. That means the production confidence gate should keep it provisional or anchor-required until teacher anchors exist. That is the intended live-cohort safety posture, not an ordering failure.

## Remaining Weak Spots

The system is release-green, but not literally perfect. The largest remaining corpus misses are all level/banding misses rather than broad ordering failures:

- `thoughtful_assessment_grade2_book_review / s003`: gold 2, predicted 1, score-band error 26.36, rank displacement 0
- `thoughtful_assessment_grade6_8_persuasive_letter / s003`: gold 2, predicted 1, score-band error 22.27, rank displacement 0
- `ontario_1999_grade1_descriptive_my_favourite_toy_example2 / s002`: gold 3, predicted 1, score-band error 14.26, rank displacement 1
- `naep_1998_g8_informative_tv_show / s002`: gold Skillful/canon 4, predicted 3, score-band error 10.00, rank displacement 0
- `thoughtful_assessment_grade11_12_speech / s004`: gold 1, predicted 2, score-band error 7.92, rank displacement 1
- `thoughtful_assessment_grade9_10_argument / s002`: gold 3, predicted 4, score-band error 1.00, rank displacement 0

Decision: no additional code change is promoted from this validation pass. The full corpus improves over the previous release run and clears the release gate; the live Ghost cohort matches the defended adjudication exactly. The remaining benchmark errors are documented as future calibration targets, not release blockers.
