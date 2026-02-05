#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


RECOMMENDED_FIELDS = [
    "grade_level",
    "class_name",
    "course_code",
    "term",
    "assignment_name",
    "total_students",
    "teacher_name",
]


def count_submissions(submissions_dir: Path) -> int:
    if not submissions_dir.exists():
        return 0
    return len([p for p in submissions_dir.iterdir() if p.is_file()])


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate class_metadata.json")
    parser.add_argument("--path", default="inputs/class_metadata.json", help="Path to class_metadata.json")
    parser.add_argument("--submissions", default="inputs/submissions", help="Submissions directory")
    parser.add_argument("--strict", action="store_true", help="Fail on missing recommended fields")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print("class_metadata.json not found (optional).")
        return 0

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        return 1

    if not isinstance(data, dict):
        print("Metadata must be a JSON object.")
        return 1

    errors = []
    warnings = []

    for field in RECOMMENDED_FIELDS:
        if field not in data:
            msg = f"Missing recommended field: {field}"
            if args.strict:
                errors.append(msg)
            else:
                warnings.append(msg)

    if "grade_level" in data:
        try:
            grade_level = int(data["grade_level"])
            if grade_level < 1 or grade_level > 12:
                errors.append("grade_level must be between 1 and 12")
        except (TypeError, ValueError):
            errors.append("grade_level must be an integer")

    if "total_students" in data:
        try:
            total_students = int(data["total_students"])
            if total_students < 0:
                errors.append("total_students must be >= 0")
            else:
                submissions_count = count_submissions(Path(args.submissions))
                if submissions_count and submissions_count != total_students:
                    warnings.append(
                        f"total_students ({total_students}) does not match submissions count ({submissions_count})"
                    )
        except (TypeError, ValueError):
            errors.append("total_students must be an integer")

    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f"- {w}")

    if errors:
        print("Errors:")
        for e in errors:
            print(f"- {e}")
        return 1

    print("class_metadata.json validation passed.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
