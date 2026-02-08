# Real Student Full-Tri 3-Pass Benchmark

Dataset root: `bench/runs/real_student_3pass_fulltri_20260208_085721`

## Overall
- **students_total**: 9
- **students_real**: 6
- **students_anchor**: 3
- **anchor_hit_rate_mean**: 0.6667
- **anchor_level_mae_mean**: 0.3889
- **real_level_consistency_rate**: 1.0
- **real_rank_std_mean**: 0.2357
- **real_score_std_mean**: 0.5108
- **real_pairwise_order_agreement_mean**: 1.0
- **irr_rank_kendalls_w_mean**: 0.9183
- **irr_rubric_sd_mean**: 1.3333

## Per Run
- Run 1: anchors hit 66.67%, anchor MAE 0.5, KendallW 0.881, rubricSD 1.48
- Run 2: anchors hit 66.67%, anchor MAE 0.3333, KendallW 1.0, rubricSD 1.03
- Run 3: anchors hit 66.67%, anchor MAE 0.3333, KendallW 0.874, rubricSD 1.49

## Real Student Stability
- real_01_cheating-america: ranks [4, 3, 4] (std 0.4714), scores [84.94, 86.13, 85.53] (std 0.4858), levels ['4', '4', '4']
- real_02_hang-and-drive: ranks [3, 1, 3] (std 0.9428), scores [83.47, 83.26, 82.88] (std 0.2442), levels ['4', '4', '4']
- real_04_internet-plagiarism: ranks [5, 5, 5] (std 0.0), scores [82.35, 80.38, 80.45] (std 0.9126), levels ['4', '4', '4']
- real_05_adopting-pet-pound: ranks [6, 6, 6] (std 0.0), scores [83.75, 82.39, 81.73] (std 0.841), levels ['4', '4', '4']
- real_06_letter-editor: ranks [9, 9, 9] (std 0.0), scores [5.33, 5.33, 5.34] (std 0.0047), levels ['1', '1', '1']
- real_07_my-favorite-place-go: ranks [7, 7, 7] (std 0.0), scores [81.79, 80.42, 81.4] (std 0.5763), levels ['4', '4', '4']
