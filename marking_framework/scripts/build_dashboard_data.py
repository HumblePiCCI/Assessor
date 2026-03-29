#!/usr/bin/env python3
import argparse
import csv
import json
import re
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
    for path in sorted(text_dir.glob("*.txt")):
        texts[path.stem.strip()] = path.read_text(encoding="utf-8", errors="ignore")
    return texts


def load_feedback_text(feedback_dir: Path, student_id: str) -> str:
    if not feedback_dir.exists():
        return ""
    path = feedback_dir / f"{student_id}_feedback.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_submission_metadata(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if isinstance(data, list):
        return {str(item.get("student_id")): item for item in data if isinstance(item, dict) and item.get("student_id")}
    return {}


def num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def sentences(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text or "") if p.strip()]
    return parts if parts else [text.strip()] if text.strip() else []


def snippet(text: str, limit: int = 140) -> str:
    clean = " ".join((text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def pick_sentence(candidates: list[str], keywords: tuple[str, ...]) -> str:
    for sent in candidates:
        low = sent.lower()
        if any(k in low for k in keywords):
            return sent
    return max(candidates, key=len) if candidates else ""


def fallback_feedback(row: dict, text: str, rank: int, cohort_size: int) -> str:
    sents = sentences(text)
    first = sents[0] if sents else "Your opening establishes the topic clearly."
    evidence = pick_sentence(sents, ("because", "for example", "according", "quote", "evidence", "%", "\""))
    if not evidence:
        evidence = first
    rubric = num(row.get("rubric_after_penalty_percent") or row.get("rubric_mean_percent"), 0.0)
    conv = num(row.get("conventions_mistake_rate_percent"), 0.0)
    words = len((text or "").split())
    if conv >= 8.0:
        wish = (
            f'Highest‑leverage next step: run one focused conventions pass (sentence boundaries, punctuation, and spelling) '
            f'before submission. Start with this sentence: "{snippet(first)}" and correct mechanics throughout.'
        )
    elif rubric < 70.0:
        wish = (
            f'Highest‑leverage next step: deepen analysis after each piece of evidence by adding a "this shows..." sentence. '
            f'Anchor from your draft: "{snippet(evidence)}".'
        )
    elif words < 180:
        wish = (
            f'Highest‑leverage next step: expand your strongest idea with one concrete example and one explanation sentence. '
            f'Build from: "{snippet(evidence)}".'
        )
    else:
        wish = (
            f'Highest‑leverage next step: increase precision by tightening your thesis and linking each paragraph back to it. '
            f'Use this line as your anchor: "{snippet(first)}".'
        )
    star1 = (
        f'Placement context: ranked {rank} of {cohort_size}. A clear strength is idea clarity. '
        f'Example: "{snippet(first)}".'
    )
    star2 = (
        f'Another strength is support and development of thinking. '
        f'Example: "{snippet(evidence)}".'
    )
    return f"### Star 1\n{star1}\n\n### Star 2\n{star2}\n\n## One Wish\n{wish}\n"


def select_rank_key(rows: list[dict]) -> str:
    if not rows:
        return ""
    for key in ("final_rank", "consistency_rank", "consensus_rank"):
        if key in rows[0]:
            return key
    return ""


def load_rank_rows(primary_path: Path, fallback_path: Path) -> tuple[list[dict], Path | None]:
    rows = load_csv(primary_path)
    if rows:
        return rows, primary_path
    consistency_path = primary_path.parent / "consistency_adjusted.csv"
    rows = load_csv(consistency_path)
    if rows:
        return rows, consistency_path
    rows = load_csv(fallback_path)
    if rows:
        return rows, fallback_path
    return [], None


def build_distribution(students: list[dict]) -> dict:
    grade_histogram = {}
    level_counts = {}
    for student in students:
        final_grade = student.get("final_grade")
        if final_grade not in (None, ""):
            grade_histogram[str(final_grade)] = grade_histogram.get(str(final_grade), 0) + 1
        level = student.get("level_with_modifier") or student.get("adjusted_level") or student.get("base_level")
        if not level:
            percent = num(student.get("rubric_after_penalty_percent") or student.get("rubric_mean_percent"), None)
            if percent is not None:
                if percent >= 90:
                    level = "4+"
                elif percent >= 80:
                    level = "4"
                elif percent >= 70:
                    level = "3"
                elif percent >= 60:
                    level = "2"
                elif percent >= 50:
                    level = "1"
        if level:
            level_counts[str(level)] = level_counts.get(str(level), 0) + 1
    return {
        "cohort_size": len(students),
        "grade_histogram": dict(sorted(grade_histogram.items(), key=lambda item: int(item[0]), reverse=True)),
        "level_counts": dict(sorted(level_counts.items(), key=lambda item: item[0])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build dashboard JSON for the teacher UI")
    parser.add_argument("--input", default="outputs/final_order.csv", help="Primary ranking CSV")
    parser.add_argument("--fallback", default="outputs/consensus_scores.csv", help="Fallback ranking CSV")
    parser.add_argument("--grades", default="outputs/grade_curve.csv", help="Final grades CSV (optional)")
    parser.add_argument("--texts", default="processing/normalized_text", help="Normalized text directory")
    parser.add_argument("--feedback", default="outputs/feedback_summaries", help="Feedback summaries directory")
    parser.add_argument("--cost-report", default="outputs/usage_costs.json", help="API cost report JSON (optional)")
    parser.add_argument("--output", default="outputs/dashboard_data.json", help="Dashboard JSON output")
    args = parser.parse_args()

    input_path = Path(args.input)
    fallback_path = Path(args.fallback)
    grades_path = Path(args.grades)
    texts_dir = Path(args.texts)
    feedback_dir = Path(args.feedback)
    cost_path = Path(args.cost_report)
    output_path = Path(args.output)

    rows, rows_source = load_rank_rows(input_path, fallback_path)

    if not rows:
        print("Error: No ranking data found. Run aggregate_assessments.py first.")
        return 1

    grades_rows = load_csv(grades_path) if grades_path.exists() else []
    grades = {row["student_id"]: row for row in grades_rows}
    texts = load_texts(texts_dir)
    meta = load_submission_metadata(Path("processing/submission_metadata.json"))
    cost_report = load_json(cost_path)
    consistency_report = load_json(Path("outputs/consistency_report.json"))

    # Determine rank key
    rank_key = select_rank_key(rows) or "consensus_rank"

    data = []
    cohort_size = len(rows)
    for row in rows:
        sid = row.get("student_id")
        meta_row = meta.get(sid, {})
        grade_row = grades.get(sid, {})
        rank = int(row.get(rank_key, row.get("consensus_rank", 0)) or 0)
        student_text = texts.get(sid, "")
        feedback_text = load_feedback_text(feedback_dir, sid)
        data.append(
            {
                "student_id": sid,
                "display_name": meta_row.get("display_name") or sid,
                "source_file": meta_row.get("source_file", ""),
                "word_count": meta_row.get("word_count"),
                "paragraph_count": meta_row.get("paragraph_count"),
                "rank": rank,
                "seed_rank": row.get("seed_rank") or row.get("consensus_rank"),
                "final_rank": row.get("final_rank") or row.get("consistency_rank") or row.get("consensus_rank"),
                "rerank_score": row.get("rerank_score"),
                "rerank_displacement": row.get("rerank_displacement"),
                "rerank_notes": row.get("rerank_notes"),
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
                "text": student_text,
                "feedback_text": feedback_text,
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
        "rank_source": str(rows_source) if rows_source else "",
        "has_final_grades": bool(grades),
        "curve_top": curve_top,
        "curve_bottom": curve_bottom,
        "curve_profile": grades_rows[0].get("curve_profile") if grades_rows else None,
        "distribution": build_distribution(data),
        "class_metadata": class_metadata,
        "cost_report": cost_report,
        "consistency_report": consistency_report,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote dashboard data: {output_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
