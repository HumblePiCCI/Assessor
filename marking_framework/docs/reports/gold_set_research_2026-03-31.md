# Gold-set research report — 2026-03-31

## What was added

Added **5** explicit-gold-ready datasets to the real repo corpus, for **25** new benchmark submissions total.

### Accepted explicit_gold_ready datasets added

#### naep_1998_g4_narrative_castle
- source family: NAEP / NCES
- source URL: https://nces.ed.gov/pubs2000/2000495.PDF
- grades: Grade 4
- genre/form: narrative
- explicit labels: True
- prompt/rubric recoverable: True
- copying exact text appears permitted: True
- duplicates current corpus: False
- classification: explicit_gold_ready
- rationale: Official NCES release with prompt, six-level rubric, six labeled student responses, and public-domain reuse note.
- samples added: 6

#### naep_1998_g8_informative_tv_show
- source family: NAEP / NCES
- source URL: https://nces.ed.gov/pubs2000/2000506.pdf
- grades: Grade 8
- genre/form: informative letter
- explicit labels: True
- prompt/rubric recoverable: True
- copying exact text appears permitted: True
- duplicates current corpus: False
- classification: explicit_gold_ready
- rationale: Official NCES release with prompt, six-level rubric, and six labeled released responses.
- samples added: 6

#### naep_1998_g12_persuasive_one_vote
- source family: NAEP / NCES
- source URL: https://nces.ed.gov/pubs2000/2000488.pdf
- grades: Grade 12
- genre/form: persuasive response
- explicit labels: True
- prompt/rubric recoverable: True
- copying exact text appears permitted: True
- duplicates current corpus: False
- classification: explicit_gold_ready
- rationale: Official NCES release with prompt, six-level rubric, and six labeled persuasive responses.
- samples added: 6

#### uk_sta_2018_ks1_writing_portfolios
- source family: Standards and Testing Agency / GOV.UK
- source URL: https://www.gov.uk/government/publications/teacher-assessment-exemplification-ks1-english-writing
- grades: Key Stage 1 / Year 2
- genre/form: portfolio / mixed forms
- explicit labels: True
- prompt/rubric recoverable: True
- copying exact text appears permitted: True
- duplicates current corpus: False
- classification: explicit_gold_ready
- rationale: Official GOV.UK exemplification with explicit WTS/EXS/GDS judgements, recoverable framework, and OGL v3.0 reuse.
- samples added: 3

#### uk_sta_2018_ks2_writing_portfolios
- source family: Standards and Testing Agency / GOV.UK
- source URL: https://www.gov.uk/government/publications/teacher-assessment-exemplification-ks2-english-writing
- grades: Key Stage 2 / Year 6
- genre/form: portfolio / mixed forms
- explicit labels: True
- prompt/rubric recoverable: True
- copying exact text appears permitted: True
- duplicates current corpus: False
- classification: explicit_gold_ready
- rationale: Official GOV.UK exemplification with explicit WTS/EXS/GDS judgements, recoverable framework, and OGL v3.0 reuse.
- samples added: 4

## Adjudication candidates

### ACARA / NAPLAN marking guides
- source URL: https://nap.edu.au/_resources/Amended_2013_Persuasive_Writing_Marking_Guide_-With_cover.pdf
- grades: Years 3, 5, 7, 9
- genre/form: persuasive writing
- explicit labels: True
- prompt/rubric recoverable: True
- copying exact text appears permitted: non-commercial only
- duplicates current corpus: False
- classification: adjudication_candidate
- rationale: Excellent explicit scoring and rich sample scripts, but reuse text is limited to non-commercial purposes; repo-use context needs legal confirmation before ingesting as benchmark gold.

### Louisiana Department of Education sample student responses
- source URL: https://louisianabelieves.com/docs/default-source/assessment-guidance/english-iii-sample-test-items.pdf?sfvrsn=31f4bcec_26
- grades: High school (English III example found)
- genre/form: essay / constructed response
- explicit labels: True
- prompt/rubric recoverable: True
- copying exact text appears permitted: unclear
- duplicates current corpus: False
- classification: adjudication_candidate
- rationale: Official source with scored student work and rubric commentary, but explicit reuse permission for exact-text benchmark redistribution was not established in the reviewed material.

### NYSED Regents rating guides / anchor papers
- source URL: https://www.nysedregents.org/hsela/625/reela-62025-rga.pdf
- grades: High school
- genre/form: argument / textual analysis
- explicit labels: True
- prompt/rubric recoverable: True
- copying exact text appears permitted: unclear
- duplicates current corpus: False
- classification: adjudication_candidate
- rationale: Anchor papers and scoring materials are explicit and useful, but the review did not establish a clear permission basis for exact-text redistribution into this benchmark corpus.

## Rejected sources

### ACARA curriculum work-sample portfolios
- source URL: https://www.acara.edu.au/curriculum/worksamples/Year_6_English_Portfolio_Above.pdf
- grades: Year 6 (example reviewed)
- genre/form: portfolio / mixed
- explicit labels: True
- prompt/rubric recoverable: True
- copying exact text appears permitted: False
- duplicates current corpus: False
- classification: reject
- rationale: The reviewed PDF explicitly states that student work samples are not licensed under ACARA’s Creative Commons terms and instead carry a more restrictive licence.

### Texas Education Agency STAAR scoring guides
- source URL: https://tea.texas.gov/student-assessment/staar/2025-staar-english-i-scoring-guide.pdf
- grades: Grade 4 through high school (examples reviewed: Grade 4, English I, English II)
- genre/form: informational / argumentative / short constructed response
- explicit labels: True
- prompt/rubric recoverable: True
- copying exact text appears permitted: False
- duplicates current corpus: False
- classification: reject
- rationale: TEA scoring guides are strong exemplars, but the guides are explicitly copyrighted and reproduction requires permission beyond narrow local-use carve-outs.

## Dedupe log

- Audited the current corpus against bench/*/inputs/sources.md and found no source-URL overlap with the five imported datasets.
- Research candidates were also deduped against one another by URL and source family.

## Counts of new samples by grade

- Year 2 / KS1: 3
- Grade 4: 6
- Year 6 / KS2: 4
- Grade 8: 6
- Grade 12: 6

## Counts of new samples by genre/form

- mixed portfolio: 7
- narrative: 6
- informative letter: 6
- persuasive response: 6

## Benchmark run status

- New-dataset candidate exact-level hit: 0.4400
- New-dataset baseline exact-level hit: 0.3600
- New-dataset candidate score-band MAE: 4.0588
- New-dataset baseline score-band MAE: 6.9644
- Combined corpus candidate exact-level hit: 0.4783
- Combined corpus baseline exact-level hit: 0.4928
- Combined corpus candidate score-band MAE: 2.9768
- Combined corpus baseline score-band MAE: 3.7022
- Updated corpus total: 69 students across 16 datasets
- Tracked benchmark report: docs/reports/external_benchmark_corpus_2026-03-31.md

## Verification status

- Source-manifest dedupe completed against the real repo.
- The five imported datasets were benchmarked through scripts/benchmark_corpus.py.
- Benchmark data was merged into docs/reports/external_benchmark_corpus_2026-03-31.{json,md}.

## Git status

- Working branch: codex/stable-bell-curve
- Commit / push: pending local commit at report generation time.
