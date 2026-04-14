#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.document_extract import extract_document_text
from scripts.parse_ontario_writing_exemplars import (
    DEFAULT_SOURCE_URL,
    GRADE_TASKS,
    build_manifest,
    fetch_to_temp,
    parse_ontario_writing_exemplars,
    extract_grade_packet_sections,
    write_json,
)


LEVEL_TO_BAND = {
    "1": (50, 59),
    "2": (60, 69),
    "3": (70, 79),
    "4": (80, 89),
}
SOURCE_FAMILY = "Ontario Ministry of Education / Queen's Printer for Ontario"
RUBRIC_FAMILY = "Ontario Curriculum Exemplars 1999 grade-specific writing rubric"
LICENSE_NOTE = "The ministry grants permission to reproduce material in this publication for non-commercial purposes."


def slugify(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_").replace("__", "_")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def submission_text(row: dict) -> str:
    title = str(row.get("sample_title", "") or "").strip()
    body = str(row.get("student_text", "") or "").strip()
    if title and body:
        return f"{title}\n\n{body}\n"
    return f"{body}\n"


def dataset_name(grade: int, example_number: int) -> str:
    task = GRADE_TASKS[grade]
    return f"ontario_1999_grade{grade}_{task['dataset_slug']}_example{example_number}"


def class_metadata(grade: int, task: dict) -> dict:
    return {
        "grade_level": grade,
        "grade_numeric_equivalent": grade,
        "assignment_genre": task["assignment_genre"],
        "assignment_name": f"Ontario Exemplars 1999 {task['task_name']} Benchmark",
        "assignment_prompt_label": task["prompt_label"],
        "source_family": SOURCE_FAMILY,
        "rubric_family": RUBRIC_FAMILY,
        "source_collection": "ontario_writing_exemplars_1999",
        "prompt_shared": True,
        "cohort_shape": "same_prompt",
        "sample_count": 4,
        "scoring_scale": {
            "type": "ordinal",
            "labels": ["Level 1", "Level 2", "Level 3", "Level 4"],
            "numeric_mapping": {"Level 1": 1, "Level 2": 2, "Level 3": 3, "Level 4": 4},
        },
        "license_note": LICENSE_NOTE,
    }


def assignment_outline_text(grade: int, task: dict, packet: dict, dataset: str, example_number: int) -> str:
    return "\n".join(
        [
            f"Assignment Family: Ontario Curriculum Exemplars 1999 ({dataset})",
            "",
            f"Source URL: {DEFAULT_SOURCE_URL}",
            f"Grade level context: Grade {grade}",
            f"Task: {task['task_name']}",
            f'Prompt / focus: "{task["prompt_label"]}"',
            f"Form / genre: {task['assignment_genre']}",
            "Cohort shape: same_prompt",
            f"Example track: Example {example_number} across Levels 4, 3, 2, 1",
            "",
            "Task excerpt recovered from the Ontario exemplar packet:",
            "",
            packet["assignment_outline"].strip(),
            "",
        ]
    )


def rubric_text(grade: int, packet: dict) -> str:
    return "\n".join(
        [
            f"Ontario Curriculum Exemplars 1999 Grade {grade} Rubric",
            "",
            f"Primary rubric source: {DEFAULT_SOURCE_URL}",
            f"Reuse note: {LICENSE_NOTE}",
            "",
            packet["rubric"].strip(),
            "",
        ]
    )


def sources_text(grade: int, task: dict, example_number: int, packet_manifest: dict) -> str:
    return "\n".join(
        [
            "# Sources",
            "",
            f"- Primary source URL: {DEFAULT_SOURCE_URL}",
            f"- Source family: {SOURCE_FAMILY}",
            "- Publication: The Ontario Curriculum – Exemplars, Grades 1–8: Writing, 1999",
            "- Copyright note: © Queen’s Printer for Ontario, 1999.",
            f"- Reuse note: {LICENSE_NOTE}",
            f"- Task: Grade {grade} {task['task_name']} ({task['prompt_label']})",
            f"- Dataset build note: this benchmark pack uses Example {example_number} across Levels 4, 3, 2, and 1 to preserve same-prompt ordering without inventing within-level rank ties.",
            "- Level mapping: official Ontario exemplar levels are used directly as canonical levels 1-4.",
            f"- Source PDF SHA256: {packet_manifest['source_sha256']}",
            "",
        ]
    )


def gold_rows_for_pack(rows: list[dict]) -> list[dict]:
    sorted_rows = sorted(rows, key=lambda row: int(row["assigned_level"]), reverse=True)
    gold_rows = []
    for idx, row in enumerate(sorted_rows, start=1):
        level = str(row["assigned_level"])
        band_min, band_max = LEVEL_TO_BAND[level]
        notes = row.get("teacher_notes", {})
        summary = str(notes.get("comments", "") or "").strip()
        gold_rows.append(
            {
                "student_id": f"s{idx:03d}",
                "display_name": f"Grade {row['grade_level']} Level {level} Example {row['example_number']}",
                "gold_level": level,
                "gold_band_min": band_min,
                "gold_band_max": band_max,
                "gold_rank": idx,
                "gold_neighbors": [f"s{idx - 1:03d}"] if idx == len(sorted_rows) else ([f"s{idx + 1:03d}"] if idx == 1 else [f"s{idx - 1:03d}", f"s{idx + 1:03d}"]),
                "boundary_flag": level in {"2", "3"},
                "adjudication_notes": f"Official Ontario exemplar labeled Level {level}. Teacher summary: {summary}",
                "source_file": f"sample_{idx:02d}_grade{row['grade_level']}_level{level}_example{row['example_number']}.txt",
                "sample_id": row["sample_id"],
                "teacher_notes": row["teacher_notes"],
                "teacher_notes_text": row["teacher_notes_text"],
                "sample_title": row["sample_title"],
            }
        )
    return gold_rows


def write_dataset(bench_root: Path, grade: int, example_number: int, rows: list[dict], packet: dict, packet_manifest: dict) -> Path:
    task = GRADE_TASKS[grade]
    dataset = dataset_name(grade, example_number)
    dataset_dir = bench_root / dataset
    if dataset_dir.exists():
        shutil.rmtree(dataset_dir)
    (dataset_dir / "inputs").mkdir(parents=True, exist_ok=True)
    (dataset_dir / "submissions").mkdir(parents=True, exist_ok=True)
    gold_rows = gold_rows_for_pack(rows)
    for row in gold_rows:
        content_row = next(item for item in rows if item["sample_id"] == row["sample_id"])
        (dataset_dir / "submissions" / row["source_file"]).write_text(submission_text(content_row), encoding="utf-8")
    write_jsonl(dataset_dir / "gold.jsonl", gold_rows)
    (dataset_dir / "inputs" / "assignment_outline.md").write_text(
        assignment_outline_text(grade, task, packet, dataset, example_number),
        encoding="utf-8",
    )
    (dataset_dir / "inputs" / "rubric.md").write_text(rubric_text(grade, packet), encoding="utf-8")
    write_json(dataset_dir / "inputs" / "class_metadata.json", class_metadata(grade, task))
    (dataset_dir / "inputs" / "sources.md").write_text(
        sources_text(grade, task, example_number, packet_manifest),
        encoding="utf-8",
    )
    return dataset_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Import the Ontario Grades 1-8 exemplar PDF into benchmark-ready datasets.")
    parser.add_argument("--pdf", default="", help="Local PDF path. If omitted, --url is downloaded first.")
    parser.add_argument("--url", default=DEFAULT_SOURCE_URL, help="Source PDF URL")
    parser.add_argument("--bench-root", default="bench", help="Benchmark root directory")
    parser.add_argument("--manifest-output", default="", help="Optional path for the structured parse manifest")
    args = parser.parse_args()

    source_url = str(args.url or DEFAULT_SOURCE_URL).strip()
    pdf_path = Path(args.pdf).expanduser() if args.pdf else fetch_to_temp(source_url)
    text, extraction_meta = extract_document_text(pdf_path)
    if not text:
        raise SystemExit("Failed to extract readable text from the Ontario exemplars PDF.")
    rows = parse_ontario_writing_exemplars(text)
    packet_manifest = build_manifest(rows, source_path=pdf_path, source_url=source_url, extraction_meta=extraction_meta)
    bench_root = Path(args.bench_root)
    written = []
    for grade in sorted(GRADE_TASKS):
        packet = extract_grade_packet_sections(text, grade)
        for example_number in (1, 2):
            pack_rows = [
                row for row in rows
                if int(row["grade_level"]) == grade and int(row["example_number"]) == example_number
            ]
            written.append(write_dataset(bench_root, grade, example_number, pack_rows, packet, packet_manifest))
    if args.manifest_output:
        write_json(Path(args.manifest_output), {"datasets": [str(path) for path in written], "parse_manifest": packet_manifest})
    print(f"Wrote {len(written)} datasets under {bench_root}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
