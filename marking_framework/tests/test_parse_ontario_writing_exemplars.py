from pathlib import Path

from scripts.parse_ontario_writing_exemplars import build_manifest, parse_ontario_writing_exemplars, parse_teacher_notes


def test_parse_teacher_notes_handles_newline_after_teachers_notes():
    notes = """Teachers’ Notes
Reasoning
– develops one clear idea
Communication
– uses simple sentences
Organization
– follows a beginning and an ending
Conventions
– uses capitals correctly
Comments
This is a clear sample.
Grade 2: A Short Narrative 31
Grade 3
"""
    parsed = parse_teacher_notes(notes)
    assert parsed["reasoning"] == ["develops one clear idea"]
    assert parsed["communication"] == ["uses simple sentences"]
    assert parsed["organization"] == ["follows a beginning and an ending"]
    assert parsed["conventions"] == ["uses capitals correctly"]
    assert parsed["comments"] == "This is a clear sample."


def test_parse_teacher_notes_stops_at_glossary_section():
    notes = """Teachers’ Notes Reasoning
– captures all key ideas
Communication
– communicates clearly
Organization
– ideas flow natu-
rally
Conventions
– almost no errors
Comments
This is a level 4 sam-
ple.
Glossary
achievement. Example glossary text.
"""
    parsed = parse_teacher_notes(notes)
    assert parsed["organization"] == ["ideas flow naturally"]
    assert parsed["comments"] == "This is a level 4 sample."


def test_parse_ontario_writing_exemplars_strips_page_noise_and_associates_notes():
    text = """Grade 6 Level 4: Example 2
“CANADA’S NEWEST TERRITORY”
“Nunavut”
Move over Northwest Territories.
Grade 6: A Summary Report 109
More supporting detail appears here.
146 The Ontario Curriculum – Exemplars, Grades 1–8: Writing, 1999
Teachers’ Notes Reasoning
– captures all key ideas
Communication
– uses complex vocabulary
Organization
– each paragraph is focused
Conventions
– there are practically no errors
Comments
This summary is level 4.
Grade 6: A Summary Report 110
Grade 7
An Advertisement
The Task
Grade 6 Level 3: Example 1
“CANADA’S NEWEST TERRITORY”
“Nunavut”
This is a second sample.
Teachers’ Notes
Reasoning
– shows general understanding
Communication
– uses some descriptive detail
Organization
– mostly logical order
Conventions
– some minor errors
Comments
This summary is level 3.
"""
    rows = parse_ontario_writing_exemplars(text)
    assert len(rows) == 2
    first = rows[0]
    assert first["grade_level"] == 6
    assert first["assigned_level"] == "4"
    assert first["example_number"] == 2
    assert first["sample_title"] == "CANADA’S NEWEST TERRITORY"
    assert "Grade 6: A Summary Report 109" not in first["student_text"]
    assert "The Ontario Curriculum" not in first["student_text"]
    assert first["teacher_notes"]["reasoning"] == ["captures all key ideas"]
    assert first["teacher_notes"]["comments"] == "This summary is level 4."
    second = rows[1]
    assert second["teacher_notes"]["communication"] == ["uses some descriptive detail"]


def test_build_manifest_summarizes_parsed_rows(tmp_path):
    pdf = tmp_path / "ontario.pdf"
    pdf.write_bytes(b"fake")
    rows = [
        {
            "sample_id": "ontario_g1_l1_e1",
            "grade_level": 1,
            "assigned_level": "1",
            "teacher_notes": {
                "reasoning": ["a"],
                "communication": ["b"],
                "organization": ["c"],
                "conventions": ["d"],
                "comments": "ok",
            },
        },
        {
            "sample_id": "ontario_g1_l2_e1",
            "grade_level": 1,
            "assigned_level": "2",
            "teacher_notes": {
                "reasoning": ["a"],
                "communication": ["b"],
                "organization": ["c"],
                "conventions": ["d"],
                "comments": "ok",
            },
        },
    ]
    manifest = build_manifest(rows, source_path=pdf, source_url="https://example.com/ontario.pdf", extraction_meta={"methods": ["ghostscript_txtwrite"]})
    assert manifest["sample_count"] == 2
    assert manifest["grade_counts"] == {"1": 2}
    assert manifest["level_counts"] == {"1": 1, "2": 1}
    assert manifest["missing_teacher_note_sections"] == []
    assert manifest["extraction_meta"]["methods"] == ["ghostscript_txtwrite"]
