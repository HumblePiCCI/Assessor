# Real Student 3-Pass Benchmark

Dataset: `bench/runs/real_student_3pass_20260208_083924`

## Overall
- **dataset_root**: bench/runs/real_student_3pass_20260208_083924
- **students_total**: 9
- **students_real**: 6
- **students_anchor**: 3
- **anchor_hit_rate_mean**: 0.6667
- **anchor_level_mae_mean**: 0.3889
- **real_level_consistency_rate**: 0.8333
- **real_rank_std_mean**: 0.5221
- **real_score_std_mean**: 1.0537
- **real_pairwise_order_agreement_mean**: 0.9333

## Anchor Accuracy by Run
- Run 1: anchors=3, hit_rate=66.67%, level_mae=0.5
- Run 2: anchors=3, hit_rate=66.67%, level_mae=0.3333
- Run 3: anchors=3, hit_rate=66.67%, level_mae=0.3333

## Real Student Stability
- real_01_cheating-america: rank=[5, 4, 4] (std 0.4714), score_std=0.0, levels=['4', '4', '4']
- real_02_hang-and-drive: rank=[1, 1, 3] (std 0.9428), score_std=0.0943, levels=['4', '4', '4']
- real_04_internet-plagiarism: rank=[3, 5, 6] (std 1.2472), score_std=4.2829, levels=['4', '3', '3']
- real_05_adopting-pet-pound: rank=[6, 6, 5] (std 0.4714), score_std=1.2869, levels=['4', '4', '4']
- real_06_letter-editor: rank=[9, 9, 9] (std 0.0), score_std=0.0, levels=['1', '1', '1']
- real_07_my-favorite-place-go: rank=[7, 7, 7] (std 0.0), score_std=0.6582, levels=['4', '4', '4']
