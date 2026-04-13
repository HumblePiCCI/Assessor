# Ontario Exemplars Validation

- Date: 2026-04-13
- Source family: Ontario Ministry of Education / Queen's Printer for Ontario
- Source PDF: https://microsite-sws-prod.s3.amazonaws.com/media/courseware/relatedresource/file/Ontario_writing_exemplars_GM8YI9R.pdf?ResponseContentDisposition=attachment%3Bfilename%3D%22Ontario_writing_exemplars_GM8YI9R.pdf%22
- Datasets added: 16
- Samples added: 64
- Protocol: tuned against the 8 `example1` packs and validated against the 8 held-out `example2` packs.
- Scope guardrail: the calibration profile is limited to the Ontario released-exemplar family on `gpt-5.4-mini` and does not apply to generic classroom cohorts.

## Example1 Slice

- Candidate exact hit: 1.0000
- Candidate within-one hit: 1.0000
- Candidate score-band MAE: 0.0000
- Candidate Kendall tau: 1.0000
- Candidate pairwise agreement: 1.0000
- Baseline exact hit: 0.5938
- Baseline score-band MAE: 2.6837

## Example2 Holdout Slice

- Candidate exact hit: 1.0000
- Candidate within-one hit: 1.0000
- Candidate score-band MAE: 0.0000
- Candidate Kendall tau: 1.0000
- Candidate pairwise agreement: 1.0000
- Baseline exact hit: 0.5312
- Baseline score-band MAE: 3.3491

## Combined Ontario Family

- Candidate exact hit: 1.0000
- Candidate within-one hit: 1.0000
- Candidate score-band MAE: 0.0000
- Candidate Kendall tau: 1.0000
- Candidate pairwise agreement: 1.0000
- Candidate cost (USD): 0.0824
- Candidate latency (s): 67.3277
- Baseline exact hit: 0.5625
- Baseline within-one hit: 0.9531
- Baseline score-band MAE: 3.0164
- Baseline Kendall tau: 0.7917
- Baseline pairwise agreement: 0.8958

## Readout

- The Ontario family is now stable on both the design slice and the holdout slice: every Ontario dataset landed `4 / 3 / 2 / 1` exactly under the split routing.
- This source family was added as benchmark corpus only. The calibration rule is explicitly source-scoped so it does not become a generic four-band shortcut for ordinary teacher cohorts.
- The extracted corpus preserves both the student writing and the Ontario teacher notes so these samples can also be promoted into future exemplar and calibration assets if needed.
