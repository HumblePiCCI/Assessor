#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from scripts.document_extract import extract_document_text
except ImportError:  # pragma: no cover
    from document_extract import extract_document_text  # pragma: no cover


DEFAULT_SOURCE_URL = (
    "https://microsite-sws-prod.s3.amazonaws.com/media/courseware/relatedresource/file/"
    "Ontario_writing_exemplars_GM8YI9R.pdf"
    '?ResponseContentDisposition=attachment%3Bfilename%3D%22Ontario_writing_exemplars_GM8YI9R.pdf%22'
)
GRADE_TASKS = {
    1: {"task_name": "A Short Piece of Descriptive Writing", "prompt_label": "My Favourite Toy", "assignment_genre": "descriptive_writing"},
    2: {"task_name": "A Short Narrative", "prompt_label": "My Adventure", "assignment_genre": "narrative"},
    3: {"task_name": "A Letter", "prompt_label": "to a Favourite Author", "assignment_genre": "letter"},
    4: {"task_name": "A Humorous Fictional Story", "prompt_label": "The Day Gravity Failed", "assignment_genre": "narrative"},
    5: {"task_name": "A Non-fiction Report", "prompt_label": "A Person I Admire", "assignment_genre": "informational_report"},
    6: {"task_name": "A Summary Report", "prompt_label": "Canada's Newest Territory", "assignment_genre": "summary_report"},
    7: {"task_name": "An Advertisement", "prompt_label": "for a New Food Product", "assignment_genre": "advertisement"},
    8: {"task_name": "An Opinion Piece", "prompt_label": "a Letter to the Editor", "assignment_genre": "opinion_letter"},
}
SAMPLE_HEADER_RE = re.compile(r"^\s*Grade\s+(?P<grade>\d+)\s+Level\s+(?P<level>\d):\s+Example\s+(?P<example>\d+)\s*$", re.M)
NOTES_SPLIT_RE = re.compile(r"Teachers[’']\s*Notes\s*Reasoning\b", re.I)
PAGE_NOISE_RE = re.compile(
    r"^(?:"
    r"\d+\s+The Ontario Curriculum .*Writing, 1999"
    r"|Grade\s+\d+:\s+.+\s+\d+"
    r"|The Ontario Curriculum Exemplars: Student Writing Samples, Grades 1–8, 1999 \d+"
    r"|\d+"
    r")$"
)
NEXT_SECTION_RE = re.compile(r"^Grade\s+\d+\b(?!\s+Level)(?::|\s*$)")
DOCUMENT_SECTION_STOP_RE = re.compile(
    r"^(?:Glossary|Introduction|Background|Using the Writing Samples|How the Samples Were Selected)\b"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_to_temp(url: str) -> Path:
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = response.read()
    tmp_dir = Path(tempfile.mkdtemp(prefix="ontario_exemplars_"))
    path = tmp_dir / "ontario_writing_exemplars.pdf"
    path.write_bytes(payload)
    return path


def _strip_sample_noise(lines: list[str]) -> list[str]:
    cleaned = []
    for raw in lines:
        line = raw.strip()
        if not line or PAGE_NOISE_RE.match(line):
            continue
        cleaned.append(line)
    return cleaned


def _collapse_note_lines(lines: list[str]) -> list[str]:
    items: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("–", "-")):
            items.append(line.lstrip("–- ").strip())
            continue
        if items:
            items[-1] = f"{items[-1]} {line}".strip()
        else:
            items.append(line)
    return items


def parse_teacher_notes(notes_text: str) -> dict:
    categories = {
        "reasoning": [],
        "communication": [],
        "organization": [],
        "conventions": [],
        "comments": "",
    }
    current: str | None = "reasoning"
    buffers = {
        "reasoning": [],
        "communication": [],
        "organization": [],
        "conventions": [],
        "comments": [],
    }
    labels = {
        "reasoning": "reasoning",
        "communication": "communication",
        "organization": "organization",
        "conventions": "conventions",
        "comments": "comments",
    }
    for raw in notes_text.splitlines():
        line = raw.strip()
        if not line or PAGE_NOISE_RE.match(line):
            continue
        if "teachers" in line.lower() and "notes" in line.lower():
            continue
        lowered = line.rstrip(":").lower()
        if lowered in labels:
            current = labels[lowered]
            continue
        if current == "comments" and (NEXT_SECTION_RE.match(line) or DOCUMENT_SECTION_STOP_RE.match(line)):
            break
        if current is None:
            continue
        buffers[current].append(line)
    for key in ("reasoning", "communication", "organization", "conventions"):
        categories[key] = _collapse_note_lines(buffers[key])
    categories["comments"] = " ".join(_collapse_note_lines(buffers["comments"])).strip()
    return categories


def parse_ontario_writing_exemplars(text: str) -> list[dict]:
    matches = list(SAMPLE_HEADER_RE.finditer(text))
    rows = []
    for index, match in enumerate(matches):
        grade = int(match.group("grade"))
        level = match.group("level")
        example = int(match.group("example"))
        chunk_start = match.end()
        chunk_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunk = text[chunk_start:chunk_end]
        note_match = NOTES_SPLIT_RE.search(chunk)
        if not note_match:
            raise ValueError(f"Missing Teachers' Notes block for Grade {grade} Level {level} Example {example}")
        student_lines = _strip_sample_noise(chunk[:note_match.start()].splitlines())
        if not student_lines:
            raise ValueError(f"Missing student text for Grade {grade} Level {level} Example {example}")
        sample_title = student_lines[0].strip("“”\" ")
        student_text = "\n".join(student_lines[1:]).strip()
        notes_text = chunk[note_match.start():]
        teacher_notes = parse_teacher_notes(notes_text)
        task = GRADE_TASKS.get(grade, {})
        rows.append(
            {
                "sample_id": f"ontario_g{grade}_l{level}_e{example}",
                "source_collection": "ontario_writing_exemplars_1999",
                "grade_level": grade,
                "assigned_level": level,
                "example_number": example,
                "task_name": task.get("task_name", ""),
                "prompt_label": task.get("prompt_label", ""),
                "assignment_genre": task.get("assignment_genre", ""),
                "sample_title": sample_title,
                "student_text": student_text,
                "teacher_notes": teacher_notes,
                "teacher_notes_text": "\n".join(
                    [
                        "Reasoning",
                        *[f"- {item}" for item in teacher_notes["reasoning"]],
                        "Communication",
                        *[f"- {item}" for item in teacher_notes["communication"]],
                        "Organization",
                        *[f"- {item}" for item in teacher_notes["organization"]],
                        "Conventions",
                        *[f"- {item}" for item in teacher_notes["conventions"]],
                        "Comments",
                        teacher_notes["comments"],
                    ]
                ).strip(),
            }
        )
    return rows


def build_manifest(rows: list[dict], *, source_path: Path, source_url: str, extraction_meta: dict) -> dict:
    by_grade = {}
    by_level = {}
    missing_notes = []
    for row in rows:
        grade = str(row.get("grade_level"))
        level = str(row.get("assigned_level"))
        by_grade[grade] = by_grade.get(grade, 0) + 1
        by_level[level] = by_level.get(level, 0) + 1
        notes = row.get("teacher_notes", {})
        if not all(notes.get(key) for key in ("reasoning", "communication", "organization", "conventions")) or not notes.get("comments"):
            missing_notes.append(row.get("sample_id"))
    return {
        "source_collection": "ontario_writing_exemplars_1999",
        "source_url": source_url,
        "source_path": str(source_path),
        "source_sha256": file_sha256(source_path),
        "sample_count": len(rows),
        "grade_counts": by_grade,
        "level_counts": by_level,
        "missing_teacher_note_sections": missing_notes,
        "extraction_meta": extraction_meta,
        "task_map": GRADE_TASKS,
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse the Ontario Grades 1-8 writing exemplars PDF into structured sample records.")
    parser.add_argument("--pdf", default="", help="Local PDF path. If omitted, --url is downloaded first.")
    parser.add_argument("--url", default=DEFAULT_SOURCE_URL, help="Source PDF URL")
    parser.add_argument("--output-dir", default="outputs/ontario_writing_exemplars_1999", help="Directory for samples.jsonl and manifest.json")
    args = parser.parse_args()

    source_url = str(args.url or DEFAULT_SOURCE_URL).strip()
    pdf_path = Path(args.pdf).expanduser() if args.pdf else fetch_to_temp(source_url)
    text, extraction_meta = extract_document_text(pdf_path)
    if not text:
        raise SystemExit("Failed to extract readable text from the Ontario exemplars PDF.")
    rows = parse_ontario_writing_exemplars(text)
    manifest = build_manifest(rows, source_path=pdf_path, source_url=source_url, extraction_meta=extraction_meta)

    output_dir = Path(args.output_dir)
    write_jsonl(output_dir / "samples.jsonl", rows)
    write_json(output_dir / "manifest.json", manifest)
    print(f"Wrote {len(rows)} samples to {output_dir / 'samples.jsonl'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
