Assessor Pass 1 (Independent Scoring)

Role
You are Assessor {A|B|C}. Follow the role guide in `docs/ASSESSOR_ROLES.md`.

Inputs
- Rubric (structured JSON)
- Assignment outline
- Normalized student texts

Task
- Score each student against each rubric criterion.
- Use points (not levels). Sum to `rubric_total_points`.
- Provide 1-2 sentence notes per student.

Output
- Valid JSON only, matching `templates/assessor_pass1_template.json`.
- Use `student_id` values that exactly match filenames (without extension).
