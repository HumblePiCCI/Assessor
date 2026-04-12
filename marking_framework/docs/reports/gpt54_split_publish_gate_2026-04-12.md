# Publish Gate

- **ok**: False
- **target_profile**: dev
- **highest_attained_profile**: none
- **decision_state**: blocked

## Profiles
- **dev**: fail
- dev: rubric_sd_above_threshold
- dev: calibration_abs_bias_above_threshold
- **candidate**: fail
- candidate: rubric_sd_above_threshold
- candidate: calibration_scope_samples_below_threshold
- candidate: calibration_stale
- candidate: calibration_abs_bias_above_threshold
- candidate: reproducibility_report_missing
- candidate: benchmark_runs_successful_below_threshold
- **release**: fail
- release: rubric_sd_above_threshold
- release: calibration_scope_samples_below_threshold
- release: calibration_stale
- release: calibration_abs_bias_above_threshold
- release: reproducibility_report_missing
- release: benchmark_runs_successful_below_threshold
- release: benchmark_within_one_level_hit_rate_below_threshold
- release: benchmark_latency_above_threshold

## Metrics
- **irr_rank_kendalls_w**: 0.6
- **irr_mean_rubric_sd**: 3.24
- **model_coverage**: 1.0
- **boundary_count**: 2
- **anchor_hit_rate**: 0.0
- **anchor_level_mae**: 0.0
- **calibration_scope_samples**: 5
- **calibration_scope_observations**: 15
- **calibration_scope_match**: True
- **calibration_synthetic**: False
- **calibration_generated_age_hours**: 298.9474572252778
- **benchmark_mode**: gpt54_split
- **benchmark_failed_dataset_count**: 0
- **benchmark_dataset_count**: 16
- **benchmark_runs_successful**: 1
- **benchmark_exact_level_hit_rate**: 0.855072
- **benchmark_within_one_level_hit_rate**: 0.956522
- **benchmark_score_band_mae**: 1.856087
- **benchmark_mean_rank_displacement**: 0.173913
- **benchmark_kendall_tau**: 0.889855
- **benchmark_pairwise_order_agreement**: 0.944927
- **benchmark_model_usage_ratio**: 1.0
- **benchmark_cost_usd**: 0.081578
- **benchmark_latency_seconds**: 78.513775
- **benchmark_mean_student_level_variance**: 0.0
- **benchmark_mean_student_rank_variance**: 0.0
- **benchmark_mean_student_score_variance**: 0.0
- **benchmark_mean_student_level_sd**: 0.0
- **benchmark_mean_student_rank_sd**: 0.0
- **benchmark_mean_student_score_sd**: 0.0
- **reproducibility_report_present**: False
- **reproducibility_runs_compared**: 0
- **reproducibility_manifest_identical**: False
- **reproducibility_final_outputs_exact_match**: False
- **reproducibility_within_tolerance**: False
- **reproducibility_max_intermediate_metric_delta**: 0.0

## Failures
- rubric_sd_above_threshold
- calibration_abs_bias_above_threshold
