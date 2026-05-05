# Product And Google Classroom Hero Path

Status: product hero-path narrative for the teacher-facing workflow and the
planned Google Classroom integration.

Last reviewed: 2026-05-05

Related docs:

- [LIVE_COHORT_RUNTIME.md](./LIVE_COHORT_RUNTIME.md)
- [TEACHER_PILOT_RUNBOOK.md](./TEACHER_PILOT_RUNBOOK.md)
- [PRODUCTION_READINESS_SPEC.md](./PRODUCTION_READINESS_SPEC.md)
- [PAYG_MODE.md](./PAYG_MODE.md)

## Product Promise

The product is a teacher-in-the-loop writing assessment workspace. It turns a
real class set of student writing, a teacher-owned rubric, and an assignment
outline into a review-ready dashboard fast enough for classroom use, while
preserving the deeper validation and evidence trail needed for defensible
grading decisions.

The product does not replace the teacher. It gives the teacher a structured
first read of the cohort:

- a normalized rubric contract
- extracted and organized student writing
- multi-assessor rubric evidence
- conventions and comparative signals
- a consensus order and level-aware grade curve
- uncertainty, disagreement, and anchor-calibration surfaces
- generated feedback drafts for teacher review
- an audit trail of the evidence and human decisions behind the final result

The Classroom integration extends that product from manual upload to the
teacher's actual assignment workflow. A teacher links a Google Classroom
assignment, the system starts work as submissions arrive, and the teacher gets
a live review dashboard before the final class submission has to be the first
moment the system begins thinking.

## Current Implementation Boundary

Today, the repo has the runtime foundations for the product path:

- `teacher_review` is the browser-submitted low-latency path.
- `full_validation` is the deeper audit path.
- The queue writes isolated job workspaces and status history.
- The UI supports upload-based runs, rubric confirmation, anchor scoring,
  draft review state, finalized review state, and runtime profile selection.
- PAYG runtime profiles and usage cost artifacts exist.

The Google Classroom integration described here is the production target, not
the current shipped behavior. The production-readiness spec tracks the missing
state model, human revision ledger, Classroom linking, event ingestion,
attachment handling, roster sync, passback controls, evidence packets, safety
gates, and institutional launch requirements.

## Hero Path In One View

```text
District policy and app approval
  -> teacher signs in with Google
  -> teacher links a Classroom assignment
  -> rubric and assignment contract are normalized
  -> Classroom submissions arrive over time
  -> per-submission extraction and analysis run incrementally
  -> review-ready dashboard publishes through teacher_review
  -> teacher edits, anchors, flags, and pairwise corrections create human revisions
  -> full_validation runs in the background against the latest human revision
  -> final result promotes only when audit_revision_id == latest_human_revision_id
  -> teacher reviews feedback and evidence
  -> teacher explicitly exports, finalizes, or passbacks results
```

The core product invariant is simple: teacher-visible speed never gets to
silently weaken teacher authority or final-result defensibility.

## Actors

Teacher:

- owns the rubric, assignment interpretation, calibration, feedback edits, and
  final grading decision
- links the Classroom assignment
- confirms rubric interpretation when needed
- reviews uncertainty, anchors, pairwise disagreements, and student flags
- finalizes or exports only after review

Student:

- submits work through Google Classroom
- is represented internally by a stable pseudonym wherever model calls and
  retained artifacts do not require display identity
- never receives model-produced grade changes automatically

District or school admin:

- allows or blocks app access by domain, teacher, course, or product feature
- approves third-party app access for under-18 Google Workspace for Education
  users when required
- controls retention, billing, provider, passback, and support policies

Operator/support:

- monitors queue health, Classroom event health, provider health, billing
  anomalies, and blocked jobs
- can diagnose failures through redacted support packets and audit logs
- does not bypass tenant policy or teacher final authority

## Phase 0: District And Pilot Readiness

The clean hero path begins before the teacher signs in.

A district or school policy record defines:

- allowed Google Workspace domains
- allowed teachers, courses, or pilot cohorts
- under-18 app approval status
- OAuth scope posture
- provider/model allowlist
- data retention rules
- billing owner and cost caps
- whether Classroom passback is disabled, draft-only, or allowed after explicit
  teacher confirmation
- jurisdiction profile for the launch or pilot

For an early pilot, this can be a supervised policy record managed by the
operator. For production, it becomes an administrative control plane. Either
way, the app must fail closed when the policy is missing.

Teacher-facing copy at this stage should be blunt:

- this is a teacher review assistant
- the teacher remains responsible for final assessment decisions
- no grade publication happens automatically
- sensitive data and model-provider routing follow the selected district policy

## Phase 1: Teacher Connects Google

The teacher signs in with Google from the product UI.

The app requests only the scopes required for the chosen workflow. The first
version should prefer a standalone web app with Google OAuth and the Classroom
API, while documenting whether Classroom Add-ons and Marketplace distribution
are out of scope for v1 or scheduled as a later path.

The app records:

- teacher identity
- tenant or district identity
- granted scopes
- refresh token status
- app approval status
- policy gates that were checked
- whether the teacher can access the Classroom API for the selected domain

If access fails, the teacher sees a typed remedy instead of a generic error.
Examples:

- Classroom API disabled
- admin blocked app
- missing OAuth grant
- insufficient scope
- teacher removed from course
- course archived
- resource not found
- quota or retry exhaustion

## Phase 2: Teacher Links An Assignment

The teacher chooses a course and assignment from Google Classroom.

The product stores a Classroom link record:

- tenant id
- teacher id
- course id and display name
- coursework id and title
- selected project id
- selected rubric source
- registration state
- roster sync state
- attachment support state
- passback mode
- latest reconciliation timestamp

The hero path starts as read-only. The first valuable product win is to analyze
and review the assignment, not to write anything back to Classroom.

The teacher can see:

- course and assignment title
- number of students in roster
- submitted, missing, reclaimed, returned, and updated counts
- whether Classroom notifications are registered
- whether reconciliation is healthy
- whether any attachment type is unsupported

## Phase 3: Rubric And Assignment Contract

The product turns the rubric and assignment description into a canonical runtime
contract before scoring.

Rubric sources can be:

- teacher-uploaded rubric
- Classroom assignment text
- manually pasted rubric
- Classroom rubric metadata, when readable and supported
- teacher-edited rubric clarification inside the product

The system normalizes:

- criteria
- performance levels
- genre or assignment family
- teacher-visible interpretation summary
- confidence and validation warnings
- contract hash

If confidence is low, the queue pauses before assessment. The teacher confirms
or edits the interpretation, then the job resumes. This is not a nice-to-have:
the rubric contract is the authority surface that downstream model work must
consume.

Classroom rubric constraints are part of the contract. Rubric scores on student
submissions are readable through the API but not writable through the current
Classroom API. Rubrics are tied to a single `CourseWork`, and create/update
paths have capability and license constraints. The product therefore treats
Classroom rubric data as imported context unless a later explicit integration
slice proves a stronger capability.

## Phase 4: Submissions Arrive Incrementally

The ideal Classroom path starts analysis as soon as a student's work is
available.

Classroom push notifications are change hints delivered through Cloud Pub/Sub.
Registrations expire and must be renewed. Notifications also require the app to
retain the teacher's OAuth grant. Because notifications are not a durable event
log, reconciliation is mandatory.

For each linked assignment, the system maintains:

- push registration id
- registration expiry
- registration renewal job
- Pub/Sub delivery status
- last reconciled Classroom snapshot
- duplicate/out-of-order event handling
- dead-letter and replay state

When an event arrives, the product validates it, fetches the changed
submission, updates the submission unit, and schedules only the missing or stale
work.

Periodic reconciliation calls Classroom directly to catch missed events,
revoked grants, roster changes, and edited or reclaimed submissions.

## Phase 5: Attachments Become Text Or Blockers

Classroom submissions are not all plain documents. The attachment layer is a
first-class hero-path component.

Supported attachment states include:

- Google Docs exportable to text or PDF
- DOCX, TXT, RTF, and PDF uploads
- image submissions that require OCR
- multiple attachments per student
- copied assignments
- reclaimed and resubmitted work
- missing permission cases
- oversized files
- malware-blocked files
- external links
- Forms, Slides, or other unsupported formats

Every attachment gets a recorded state:

- supported
- extractable text available
- requires Drive scope
- needs manual review
- unsupported reason
- file hash
- export MIME type
- extraction status

The product never treats unsupported or empty extraction as a valid zero-text
essay. It surfaces the blocker to the teacher and keeps that student out of any
finalized result until the teacher resolves or explicitly flags the case.

## Phase 6: Per-Submission Analysis Runs Early

Each submission unit can be analyzed independently before the entire class is
complete.

Per-submission work includes:

- external text classification and prompt-injection scan
- text extraction
- conventions scan
- Pass 1 rubric assessment
- draft quality signals
- usage and cost rows
- cache keys tied to text hash, rubric hash, routing hash, provider, and model

This is where the Classroom integration changes the teacher experience. A
class of 30 does not wait for the last student to turn in before the system
starts all model work. By the time the teacher opens the dashboard, much of the
student-local work should already be done.

The scheduler prioritizes:

1. teacher-touched students and pairs
2. new submissions blocking review-ready state
3. boundary neighbors and high-disagreement pairs
4. background full-validation coverage
5. optional feedback generation

## Phase 7: Review-Ready Dashboard Publishes Fast

The first teacher-facing dashboard is produced by `teacher_review`.

That path is designed for latency. It runs:

1. rubric normalization
2. scope grounding
3. text extraction
4. conventions scan
5. bounded multi-assessor scoring
6. cost tracking
7. consensus aggregation
8. pairwise review preparation
9. level-aware grading
10. dashboard build

The UI should present this as review-ready, not final.

The dashboard gives the teacher:

- ranked class order
- suggested levels or marks
- confidence and disagreement indicators
- conventions signals
- rubric evidence
- pairwise comparison prep
- anchor candidates
- draft feedback
- student flags and attachment blockers
- cost and runtime status where relevant

The teacher can start reviewing immediately. The deeper audit can continue
without holding the first useful product moment hostage.

## Phase 8: Teacher Judgment Becomes A Runtime Layer

Teacher actions are not UI annotations. They are authoritative runtime inputs.

Teacher actions create human revisions:

- rubric clarification
- assignment-scope correction
- anchor score
- student flag
- pairwise correction
- curve or grade adjustment
- feedback edit
- finalization

Each applied human revision records:

- monotonic `human_revision_id`
- actor
- timestamp
- source
- payload hash
- affected students
- affected pairs
- earliest invalidated pipeline step

Authority order:

1. teacher rubric edits and assignment-scope clarifications
2. teacher anchors and calibration packets
3. teacher pairwise corrections and protected human edges
4. teacher student flags
5. committee-edge protected decisions
6. full-validation model evidence
7. fast teacher-review evidence
8. deterministic fallback signals

No model rerank may silently demote teacher input. If a graph safety rule blocks
a teacher edge, the block must be explicit and reviewable.

## Phase 9: Background Validation Catches Up

After the review-ready dashboard publishes, `full_validation` runs as a
background child job when policy and billing consent allow it.

That deeper path adds:

- boundary recheck
- band-seam adjudication
- pairwise consistency checks
- routed pairwise escalation
- evidence mapping
- committee-edge resolution
- global rerank
- pairwise adjudicator evaluation
- publish quality gate
- SOTA readiness gate
- cohort confidence
- final dashboard rebuild

The background audit records the `human_revision_id` it consumed. If the
teacher changes the rubric, anchors, flags, pairwise decisions, curve, or
feedback while the audit is running, the affected work becomes stale. The child
job resumes or restarts from the earliest invalidated step.

Final promotion is allowed only when:

- the audit consumed the latest human revision
- no required gate failed
- no stale submission unit remains
- no attachment blocker affects the final result
- no unpriced billable usage exists
- the dashboard was generated from the promoted order

The final promotion condition is:

```text
audit_revision_id == latest_human_revision_id
```

## Phase 10: Feedback Is Drafted, Checked, And Reviewed

Feedback generation is downstream of the review state.

The product drafts teacher-editable feedback, then checks:

- quote grounding
- age-appropriate tone
- no fabricated details
- no hidden prompt leakage
- no sensitive-content mishandling
- accommodation-aware language where policy allows
- no demotivating or punitive phrasing

The teacher can edit feedback before export or passback. In production mode,
feedback export should be blocked when the quality gate fails.

## Phase 11: Evidence Packet Makes The Result Defensible

Every finalized result gets an assessment evidence packet.

The packet should be able to answer:

- What assignment was assessed?
- Which rubric version was used?
- Which student submission hashes were consumed?
- Which model/provider/profile was used?
- What did the fast review path conclude?
- What did the full audit conclude?
- Which teacher revisions changed the result?
- Which protected edges or anchors controlled the order?
- Which blockers were resolved or accepted by the teacher?
- Which feedback or grade export action happened?

This packet is different from security audit logs. Security logs say who
accessed or changed the system. The assessment evidence packet explains why the
final educational artifact exists in its final form.

## Phase 12: Export Or Passback Requires Explicit Teacher Action

The default pilot posture is no automatic grade publication.

The product may support these modes, separately:

- no passback, dashboard only
- CSV export
- write Classroom `draftGrade`
- write Classroom `assignedGrade`
- return submission
- future SIS/OneRoster path

Each write action requires a separate teacher confirmation and preflight diff.
The app never calls `return` as a side effect of setting a grade. Classroom
distinguishes draft grades, assigned grades, and submission state, so the UI
must do the same.

The product also must not call Classroom/CSV export a SIS integration.
OneRoster is a separate SIS partner path with conformance tests and district
signoff. Until that path is explicitly implemented, the hero path stops at
Classroom and export.

## Teacher Experience

The teacher's ideal session feels like this:

1. Sign in.
2. Pick the class and assignment.
3. See whether the district policy and Google access are ready.
4. Confirm the rubric interpretation.
5. Watch submissions move from collected to analyzed.
6. Open a review-ready dashboard while the deeper audit continues.
7. Review the top pack, boundary cases, and flagged students.
8. Score anchors or make pairwise corrections where the system asks for help.
9. Review generated feedback drafts.
10. Wait for final audit readiness or resolve blockers.
11. Finalize the review.
12. Export or pass back only after an explicit confirmation.

The teacher should not need to understand the model stack, queue mechanics, or
Classroom API details. They should understand only what matters for trust:
what is ready, what is provisional, what needs their judgment, and what will be
sent outside the product.

## Product State Language

The UI and API should use stable product states:

- `collecting`: Classroom link is active and submissions are arriving.
- `ingesting`: the system is fetching submission metadata and attachments.
- `analyzing_submissions`: per-student extraction and assessment are running.
- `review_ready`: the fast teacher-review dashboard is available.
- `background_validating`: full validation is running behind the dashboard.
- `teacher_revision_pending`: teacher input has invalidated downstream work.
- `final_ready`: full validation consumed the latest teacher revision.
- `finalized_by_teacher`: the teacher accepted the final review state.
- `blocked`: teacher, attachment, policy, billing, or platform action is needed.
- `failed`: operator or support intervention is needed.

These states should be visible without forcing the teacher to read logs.

## Google Classroom Contract

The Classroom integration is governed by a few hard platform truths:

- Push notifications are delivered through Cloud Pub/Sub and registrations last
  for a limited period, so renewal is required.
- Notifications require the app to retain the teacher's OAuth grant.
- Notifications are hints, not a complete durable ledger; reconciliation is
  required.
- Course-work and student-submission resources can be watched and fetched, but
  attachment content may require Drive scope or may be unsupported.
- Classroom grades separate `draftGrade`, `assignedGrade`, and submission
  return state.
- Rubric scores are readable but not writable through the Classroom API.
- Under-18 app access depends on administrator configuration in Google Admin
  console and cannot be completed programmatically by the app.
- Classroom API errors include structured message prefixes that should map to
  typed remedies.
- Classroom Add-ons are a real product path, but v1 must explicitly decide
  whether to use standalone OAuth/Classroom API first or pursue Add-ons and
  Marketplace distribution earlier.
- OneRoster/SIS integration is a separate partner path and should not be
  overclaimed by Classroom export.

## Non-Goals For V1

Unless a later product decision changes scope, v1 should not claim:

- autonomous grading
- automatic grade publication
- SIS-gradebook sync
- full Classroom Add-on distribution
- unrestricted attachment support
- provider-neutral production readiness without per-provider gates
- production launch without district/admin policy, jurisdiction profile,
  evidence packets, safety checks, accessibility review, and support runbooks

## Success Criteria

The hero path is working when:

- a teacher can link an assignment and understand the active policy boundary
- new submissions trigger incremental per-student analysis
- missed or duplicate Classroom events do not duplicate expensive work or lose
  student changes
- unsupported attachments become visible blockers
- the first class-of-30 review-ready dashboard lands within the target latency
  on the selected production provider path
- teacher edits create durable human revisions
- background validation cannot overwrite newer teacher judgment
- every finalized result has an assessment evidence packet
- feedback export is quality-gated and teacher-reviewed
- grade export or passback happens only through explicit teacher action
- billing covers child jobs, retries, and background validation
- launch validators fail closed when policy, platform, safety, or evidence
  prerequisites are missing

## Source Grounding

This hero path is grounded in the repo's current runtime docs and the
production-readiness roadmap. It also depends on these platform constraints:

- Google Classroom push notifications:
  https://developers.google.com/workspace/classroom/best-practices/push-notifications
- Google Classroom grade updates:
  https://developers.google.com/workspace/classroom/guides/classroom-api/manage-grades
- Google Classroom rubric limitations:
  https://developers.google.com/workspace/classroom/rubrics/limitations
- Google Classroom administrator actions:
  https://developers.google.com/workspace/classroom/guides/key-concepts/admin-actions
- Google Classroom API error structure:
  https://developers.google.com/workspace/classroom/troubleshooting/error-structure
- Google Classroom OneRoster/SIS path:
  https://developers.google.com/workspace/classroom/sis-integrations/validate-your-SIS
- OpenAI assessment and feedback guidance:
  https://help.openai.com/en/articles/8313397-how-can-chatgpt-be-used-for-assessment-and-feedback
- OpenAI usage policies:
  https://openai.com/policies/usage-policies/
