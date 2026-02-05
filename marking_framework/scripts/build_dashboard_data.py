#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path


def load_csv(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_texts(text_dir: Path):
    texts = {}
    if not text_dir.exists():
        return texts
    for path in text_dir.glob("*.txt"):
        texts[path.stem.strip()] = path.read_text(encoding="utf-8", errors="ignore")
    return texts


def load_feedback_text(feedback_dir: Path, student_id: str) -> str:
    if not feedback_dir.exists():
        return ""
    path = feedback_dir / f"{student_id}_feedback.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build dashboard JSON for the teacher UI")
    parser.add_argument("--input", default="outputs/final_order.csv", help="Primary ranking CSV")
    parser.add_argument("--fallback", default="outputs/consensus_scores.csv", help="Fallback ranking CSV")
    parser.add_argument("--grades", default="outputs/grade_curve.csv", help="Final grades CSV (optional)")
    parser.add_argument("--texts", default="processing/normalized_text", help="Normalized text directory")
    parser.add_argument("--feedback", default="outputs/feedback_summaries", help="Feedback summaries directory")
    parser.add_argument("--output", default="outputs/dashboard_data.json", help="Dashboard JSON output")
    args = parser.parse_args()

    input_path = Path(args.input)
    fallback_path = Path(args.fallback)
    grades_path = Path(args.grades)
    texts_dir = Path(args.texts)
    feedback_dir = Path(args.feedback)
    output_path = Path(args.output)

    rows = load_csv(input_path)
    if not rows:
        rows = load_csv(fallback_path)

    if not rows:
        print("Error: No ranking data found. Run aggregate_assessments.py first.")
        return 1

    grades_rows = load_csv(grades_path) if grades_path.exists() else []
    grades = {row["student_id"]: row for row in grades_rows}
    texts = load_texts(texts_dir)

    # Determine rank key
    rank_key = "final_rank" if "final_rank" in rows[0] else "consensus_rank"

    data = []
    for row in rows:
        sid = row.get("student_id")
        grade_row = grades.get(sid, {})
        data.append(
            {
                "student_id": sid,
                "rank": int(row.get(rank_key, row.get("consensus_rank", 0)) or 0),
                "rubric_mean_percent": row.get("rubric_mean_percent"),
                "rubric_after_penalty_percent": row.get("rubric_after_penalty_percent"),
                "conventions_mistake_rate_percent": row.get("conventions_mistake_rate_percent"),
                "borda_points": row.get("borda_points"),
                "composite_score": row.get("composite_score"),
                "base_level": row.get("base_level"),
                "base_letter": row.get("base_letter"),
                "adjusted_level": row.get("adjusted_level"),
                "adjusted_letter": row.get("adjusted_letter"),
                "level_modifier": row.get("level_modifier"),
                "level_with_modifier": row.get("level_with_modifier"),
                "flags": row.get("flags"),
                "final_grade": grade_row.get("final_grade"),
                "text": texts.get(sid, ""),
                "feedback_text": load_feedback_text(feedback_dir, sid),
            }
        )

    # Sort by rank for UI
    data.sort(key=lambda r: r["rank"])

    metadata_path = Path("inputs/class_metadata.json")
    class_metadata = {}
    if metadata_path.exists():
        class_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    curve_top = grades_rows[0].get("curve_top") if grades_rows else None
    curve_bottom = grades_rows[0].get("curve_bottom") if grades_rows else None

    payload = {
        "students": data,
        "rank_key": rank_key,
        "has_final_grades": bool(grades),
        "curve_top": curve_top,
        "curve_bottom": curve_bottom,
        "class_metadata": class_metadata,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote dashboard data: {output_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
