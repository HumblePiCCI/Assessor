# External Writing Calibration Sources

This project uses public exemplar sources as calibration guidance for routed
committee adjudication. The repository stores links, score-scale metadata, and
distilled decision rules only. It does not ingest full external student
responses.

## Runtime Use

The source pack lives at:

- `inputs/calibration_sources/writing_assessment_sources.json`

`scripts/committee_edge_resolver.py` loads that pack through
`--source-calibration` and injects compact source-derived rules into Read A,
Read B, Read C, and group-neighborhood committee prompts. The broad cheap
pairwise screener does not consume this pack; calibration stays on the routed
teacher-grade path.

## Current Source Families

- [New Meridian / PARCC Grade 7 Literary Analysis Task](https://resources.newmeridiancorp.org/wp-content/uploads/2019/07/Gr7_LAT_4127_Released_Set_12016.pdf): core middle-grade literary-analysis anchor set with annotated score points for reading and written expression.
- [New Meridian / PARCC Grade 3, 8, and 10 Literary Analysis Tasks](https://resources.newmeridiancorp.org/): linked lower/upper grade score-scale references for literary-analysis transfer.
- [Massachusetts Writing Standards in Action Grade 7 text-based response](https://www.doe.mass.edu/frameworks/ela/wsa/grade7/c712.pdf): standards-commentary anchor for theme, evidence, and concise grade-level/exceeds performance.
- [Massachusetts Writing Standards in Action Grade 8 literary interpretation](https://www.doe.mass.edu/frameworks/ela/wsa/grade8/b85.pdf): stretch middle-grade literary-interpretation anchor.
- [Understanding Proficiency ELA](https://understandingproficiency.wested.org/ela/): cross-grade Smarter Balanced student work scored and annotated by teachers.
- [Smarter Annotated Response Tool](https://smart.smarterbalanced.org/examples): cross-grade annotated response examples by writing trait and score point.
- [B.C. Performance Standards](https://www2.gov.bc.ca/gov/content/education-training/k-12/teach/resources-for-teachers/curriculum/bc-performance-standards): four-level writing performance standards with teacher observations and additional samples.
- [Massachusetts MCAS student work](https://www.doe.mass.edu/mcas/student/): cross-grade released student work with idea-development and conventions score commentary.
- [AP English Literature samples and scoring commentary](https://apcentral.collegeboard.org/courses/ap-english-literature-and-composition/exam/past-exam-questions): upper-bound literary-analysis calibration for thesis, evidence/commentary, and sophistication.
- [Cambridge IGCSE Literature example candidate response resources](https://learning.cambridgeinternational.org/classroom/pluginfile.php/151555/mod_resource/content/4/ECR_Literature_0475_Paper1_Prose_v2.pdf): upper-secondary literature calibration for textual reference, deeper meaning, craft/effect, and informed response.

## Decision Rules

The source pack is intentionally rule-based. Important transferred rules:

- Separate content traits from surface traits. Strong organization is not strong
  evidence or commentary.
- Literary analysis must explain how textual moments support meaning; feature
  naming and event listing have a ceiling.
- Mature or sophisticated theme vocabulary does not win unless the paper proves
  it with recoverable evidence and explanation.
- Concise writing can be strong when it answers the task directly and explains
  selected evidence.
- Conventions matter when they block meaning; otherwise they are secondary to
  task response, development, and evidence.
- Transfer grade-adjacent sources by decision axis, not absolute sophistication.

## Copyright Guard

Do not paste external exemplar essays into prompts, fixtures, or docs unless a
separate license review approves ingestion. The committee prompt explicitly
instructs the model to use the distilled rules only and not quote, reproduce, or
infer full source essay text.

