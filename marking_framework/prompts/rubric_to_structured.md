Rubric Parsing Prompt

Task
Convert the uploaded rubric text into structured JSON using the template in `templates/rubric_structured.json`.

Rules
- Preserve criterion names and point values.
- Copy level descriptors as written.
- Add explicit formatting/requirement statements under `requirements`.
- Output valid JSON only.
