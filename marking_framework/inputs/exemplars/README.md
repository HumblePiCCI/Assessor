Built-in, Grade-Banded Exemplars

These exemplars are ORIGINAL sample texts written for this project.

Purpose
- Anchor LLM scoring to consistent Ontario achievement level bands (1, 2, 3, 4, 4+).
- Reduce run-to-run drift by giving concrete reference points per grade band and genre.

Structure
inputs/exemplars/
  grade_6_7/
    literary_analysis/
      level_1.md ... level_4_plus.md
    argumentative/
    informational_report/
    news_report/
  grade_8_10/
    ...
  grade_11_12/
    ...

Notes
- These samples avoid copyrighted source texts. Any quoted lines are fictional and part of the sample itself.
- Teachers can replace or add exemplars by dropping their own files alongside these, using the same filenames.
- Governed aggregate-learning promotions stage approved calibration candidates under `inputs/exemplars/promoted/<proposal_id>/calibration_exemplars.jsonl`.
- Promoted calibration candidates remain adjudicated staging assets until they are manually curated into the live exemplar bank.
