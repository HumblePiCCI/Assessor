from pathlib import Path

from scripts.import_ontario_writing_exemplars import class_metadata, dataset_name, gold_rows_for_pack
from scripts.parse_ontario_writing_exemplars import extract_grade_packet_sections


def test_extract_grade_packet_sections_recovers_outline_and_rubric():
    text = """
Grade 2
A Short Narrative
The Task
Students were asked to write a story called My Adventure.
Teachers then evaluated students’ work using the rubric reproduced on the next page.
Grade 2: Rubric for a Short Narrative
Categories Level 1 Level 2 Level 3 Level 4
Reasoning The student:
- sample descriptor
Grade 2 Level 1: Example 1
"""
    packet = extract_grade_packet_sections(text, 2)
    assert "Students were asked to write a story called My Adventure." in packet["assignment_outline"]
    assert "Grade 2: Rubric for a Short Narrative" in packet["rubric"]
    assert "Grade 2 Level 1: Example 1" not in packet["rubric"]


def test_gold_rows_for_pack_orders_strongest_to_weakest():
    rows = [
        {
            "sample_id": "ontario_g2_l2_e1",
            "grade_level": 2,
            "assigned_level": "2",
            "example_number": 1,
            "sample_title": "My Adventure",
            "teacher_notes": {"comments": "Level 2 sample."},
            "teacher_notes_text": "Comments\nLevel 2 sample.",
        },
        {
            "sample_id": "ontario_g2_l4_e1",
            "grade_level": 2,
            "assigned_level": "4",
            "example_number": 1,
            "sample_title": "My Adventure",
            "teacher_notes": {"comments": "Level 4 sample."},
            "teacher_notes_text": "Comments\nLevel 4 sample.",
        },
        {
            "sample_id": "ontario_g2_l1_e1",
            "grade_level": 2,
            "assigned_level": "1",
            "example_number": 1,
            "sample_title": "My Adventure",
            "teacher_notes": {"comments": "Level 1 sample."},
            "teacher_notes_text": "Comments\nLevel 1 sample.",
        },
        {
            "sample_id": "ontario_g2_l3_e1",
            "grade_level": 2,
            "assigned_level": "3",
            "example_number": 1,
            "sample_title": "My Adventure",
            "teacher_notes": {"comments": "Level 3 sample."},
            "teacher_notes_text": "Comments\nLevel 3 sample.",
        },
    ]
    gold = gold_rows_for_pack(rows)
    assert [row["gold_level"] for row in gold] == ["4", "3", "2", "1"]
    assert [row["gold_rank"] for row in gold] == [1, 2, 3, 4]
    assert gold[1]["gold_neighbors"] == ["s001", "s003"]


def test_dataset_name_and_class_metadata_are_stable():
    assert dataset_name(6, 2) == "ontario_1999_grade6_summary_canadas_newest_territory_example2"
    meta = class_metadata(7, {"assignment_genre": "advertisement", "task_name": "An Advertisement", "prompt_label": "for a New Food Product"})
    assert meta["grade_level"] == 7
    assert meta["prompt_shared"] is True
    assert meta["assignment_genre"] == "advertisement"
