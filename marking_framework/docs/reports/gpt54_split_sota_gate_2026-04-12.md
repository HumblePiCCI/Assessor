# SOTA Gate

- **ok**: False
- **target_profile**: dev
- **highest_attained_profile**: none
- **decision_state**: blocked

## Profiles
- **dev**: fail
- dev: publish_gate_not_ok
- dev: publish_gate_profile_below_threshold
- **candidate**: fail
- candidate: publish_gate_not_ok
- candidate: publish_gate_profile_below_threshold
- candidate: benchmark_runs_successful_below_threshold
- **release**: fail
- release: publish_gate_not_ok
- release: publish_gate_profile_below_threshold
- release: benchmark_runs_successful_below_threshold
- release: benchmark_within_one_level_hit_rate_below_threshold
- release: benchmark_latency_above_threshold

## Metrics
- **publish_highest_attained_profile**: 
- **assessor_files**: 3
- **pass1_rows**: 12
- **model_coverage**: 1.0
- **nonzero_score_rate**: 1.0
- **criteria_coverage**: 1.0
- **evidence_coverage**: 1.0
- **mean_assessor_sd**: 2.7473851099909075
- **p95_assessor_sd**: 3.169703806702171
- **consistency_checks**: 0
- **consistency_swap_rate**: 0.0
- **consistency_low_confidence_rate**: 0.0
- **benchmark_candidate_mode**: gpt54_split
- **benchmark_baseline_mode**: gpt52_legacy
- **benchmark_failed_dataset_count**: 0
- **benchmark_dataset_count**: 16
- **benchmark_runs_successful**: 1
- **benchmark_exact_level_hit_rate**: 0.855072
- **benchmark_within_one_level_hit_rate**: 0.956522
- **benchmark_score_band_mae**: 1.856087
- **benchmark_kendall_tau**: 0.889855
- **benchmark_pairwise_order_agreement**: 0.944927
- **benchmark_mean_student_level_sd**: 0.0
- **benchmark_mean_student_rank_sd**: 0.0
- **benchmark_mean_student_score_sd**: 0.0
- **benchmark_cost_usd**: 0.081578
- **benchmark_latency_seconds**: 78.513775
- **benchmark_exact_level_hit_rate_delta**: 0.15942
- **benchmark_within_one_level_hit_rate_delta**: -0.028985
- **benchmark_score_band_mae_delta**: -0.170725
- **benchmark_kendall_tau_delta**: 0.003865
- **benchmark_pairwise_order_agreement_delta**: 0.001932

## Failures
- publish_gate_not_ok
- publish_gate_profile_below_threshold
