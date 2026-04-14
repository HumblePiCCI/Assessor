# Publish Gate

- **ok**: True
- **target_profile**: candidate
- **highest_attained_profile**: candidate
- **decision_state**: candidate_ready

## Profiles
- **dev**: pass
- **candidate**: pass
- **release**: fail
- release: reproducibility_final_outputs_mismatch
- release: reproducibility_intermediate_delta_above_threshold
- release: benchmark_runs_successful_below_threshold
- release: benchmark_latency_above_threshold

## Metrics
- **irr_rank_kendalls_w**: 0.911
- **irr_mean_rubric_sd**: 0.35
- **model_coverage**: 1.0
- **boundary_count**: 3
- **anchor_hit_rate**: 0.0
- **anchor_level_mae**: 0.0
- **calibration_scope_samples**: 45
- **calibration_scope_observations**: 45
- **calibration_scope_match**: True
- **calibration_synthetic**: False
- **calibration_generated_age_hours**: 0.5596389663888889
- **benchmark_mode**: gpt54_split
- **benchmark_failed_dataset_count**: 0
- **benchmark_dataset_count**: 16
- **benchmark_runs_successful**: 2
- **benchmark_exact_level_hit_rate**: 0.891304
- **benchmark_within_one_level_hit_rate**: 0.971015
- **benchmark_score_band_mae**: 1.81442
- **benchmark_mean_rank_displacement**: 0.173913
- **benchmark_kendall_tau**: 0.902416
- **benchmark_pairwise_order_agreement**: 0.951208
- **benchmark_model_usage_ratio**: 1.0
- **benchmark_cost_usd**: 0.082137
- **benchmark_latency_seconds**: 83.363188
- **benchmark_mean_student_level_variance**: 0.0
- **benchmark_mean_student_rank_variance**: 0.0
- **benchmark_mean_student_score_variance**: 0.0
- **benchmark_mean_student_level_sd**: 0.0
- **benchmark_mean_student_rank_sd**: 0.0
- **benchmark_mean_student_score_sd**: 0.0
- **reproducibility_report_present**: True
- **reproducibility_runs_compared**: 2
- **reproducibility_manifest_identical**: True
- **reproducibility_final_outputs_exact_match**: False
- **reproducibility_within_tolerance**: True
- **reproducibility_max_intermediate_metric_delta**: 0.0079
