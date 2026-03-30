#!/usr/bin/env python3
import argparse
import csv
import hashlib
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


def file_sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


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


def level_boundaries(config_path: Path) -> list[float]:
    config = load_json(config_path)
    bands = (((config or {}).get("levels", {}) or {}).get("bands", []) if isinstance(config, dict) else [])
    mins = []
    for band in bands if isinstance(bands, list) else []:
        try:
            mins.append(float(band.get("min", 0.0) or 0.0))
        except (AttributeError, TypeError, ValueError):
            continue
    ordered = sorted(value for value in mins if value > 0)
    return ordered[1:] if len(ordered) > 1 else [60.0, 70.0, 80.0, 90.0]


def movement_map(consistency_report: dict) -> dict[str, dict]:
    moves = consistency_report.get("movements", []) if isinstance(consistency_report, dict) else []
    return {str(item.get("student_id")): item for item in moves if isinstance(item, dict) and item.get("student_id")}


def student_uncertainty(row: dict, movement: dict, boundaries: list[float], margin: float = 1.0) -> tuple[list[str], list[str]]:
    flags = []
    reasons = []
    score = num(row.get("rubric_after_penalty_percent") or row.get("rubric_mean_percent"), None)
    if score is not None and boundaries:
        nearest = min((abs(score - edge), edge) for edge in boundaries)
        if nearest[0] <= margin:
            flags.append("boundary_case")
            reasons.append(f"Within {margin:.1f} points of the {nearest[1]:.0f}% level boundary.")
    support = num(row.get("rerank_support_weight"), num(movement.get("support_weight"), 0.0))
    opposition = num(row.get("rerank_opposition_weight"), num(movement.get("opposition_weight"), 0.0))
    incident = num(row.get("rerank_incident_weight"), 0.0)
    if support > 0.0 and opposition > 0.0:
        ratio = min(support, opposition) / max(support, opposition)
        if ratio >= 0.6:
            flags.append("high_disagreement")
            reasons.append(
                f"Pairwise evidence is split: support {support:.2f}, opposition {opposition:.2f}, incident weight {incident:.2f}."
            )
    displacement = abs(int(num(row.get("rerank_displacement"), 0)))
    cap_label = str(row.get("rerank_displacement_cap_label") or movement.get("displacement_cap_label") or "").strip().lower()
    notes = str(row.get("rerank_notes", "") or "")
    if displacement > 0 and (cap_label == "low" or "low_confidence" in notes):
        flags.append("low_confidence_rerank_move")
        reasons.append(f"Moved {displacement} ranks on low-confidence evidence.")
    deduped_flags = []
    deduped_reasons = []
    for item in flags:
        if item not in deduped_flags:
            deduped_flags.append(item)
    for item in reasons:
        if item not in deduped_reasons:
            deduped_reasons.append(item)
    return deduped_flags, deduped_reasons


def review_context(root: Path, rows_source: Path | None) -> dict:
    pipeline_path = root / "pipeline_manifest.json"
    if not pipeline_path.exists():
        pipeline_path = root / "outputs" / "pipeline_manifest.json"
    calibration_path = root / "outputs" / "calibration_manifest.json"
    pipeline_manifest = load_json(pipeline_path)
    calibration_manifest = load_json(calibration_path)
    artifact_hashes = {}
    for name, path in {
        "rank_source": rows_source,
        "final_order": root / "outputs" / "final_order.csv",
        "grade_curve": root / "outputs" / "grade_curve.csv",
        "consistency_report": root / "outputs" / "consistency_report.json",
        "pairwise_matrix": root / "outputs" / "pairwise_matrix.json",
    }.items():
        if path and Path(path).exists():
            artifact_hashes[name] = file_sha256(Path(path))
    return {
        "pipeline_manifest": {
            "path": str(pipeline_path),
            "manifest_hash": str(pipeline_manifest.get("manifest_hash", "") or ""),
            "generated_at": str(pipeline_manifest.get("generated_at", "") or ""),
            "run_scope": pipeline_manifest.get("run_scope", {}) if isinstance(pipeline_manifest.get("run_scope", {}), dict) else {},
            "sha256": file_sha256(pipeline_path),
        },
        "calibration_manifest": {
            "path": str(calibration_path),
            "generated_at": str(calibration_manifest.get("generated_at", "") or ""),
            "model_version": str(calibration_manifest.get("model_version", "") or ""),
            "sha256": file_sha256(calibration_path),
        },
        "final_artifact_set": {
            "artifact_hashes": artifact_hashes,
            "artifact_set_hash": canonical_hash(artifact_hashes) if artifact_hashes else "",
        },
    }


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


def build_uncertainty_summary(students: list[dict]) -> dict:
    summary = {
        "boundary_cases": [],
        "high_disagreement_cases": [],
        "low_confidence_rerank_moves": [],
    }
    for student in students:
        sid = student.get("student_id")
        flags = set(student.get("uncertainty_flags", []) or [])
        if "boundary_case" in flags:
            summary["boundary_cases"].append(sid)
        if "high_disagreement" in flags:
            summary["high_disagreement_cases"].append(sid)
        if "low_confidence_rerank_move" in flags:
            summary["low_confidence_rerank_moves"].append(sid)
    summary["counts"] = {key: len(value) for key, value in summary.items() if isinstance(value, list)}
    return summary


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
    pairwise_matrix = load_json(Path("outputs/pairwise_matrix.json"))
    review_draft = load_json(Path("outputs/review_feedback_draft.json"))
    review_feedback = load_json(Path("outputs/review_feedback_latest.json"))
    review_delta = load_json(Path("outputs/review_delta_latest.json"))
    local_learning_profile = load_json(Path("outputs/local_learning_profile.json"))
    local_teacher_prior = load_json(Path("outputs/local_teacher_prior.json"))
    aggregate_learning = load_json(Path("outputs/aggregate_learning_summary.json"))
    uncertainty_by_student = movement_map(consistency_report)
    boundaries = level_boundaries(Path("config/marking_config.json"))

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
        flags, reasons = student_uncertainty(row, uncertainty_by_student.get(sid, {}), boundaries)
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
                "rerank_support_weight": row.get("rerank_support_weight"),
                "rerank_opposition_weight": row.get("rerank_opposition_weight"),
                "rerank_incident_weight": row.get("rerank_incident_weight"),
                "teacher_preference_adjustment": row.get("teacher_preference_adjustment"),
                "teacher_preference_uncertainty_gate": row.get("teacher_preference_uncertainty_gate"),
                "teacher_preference_reasons": row.get("teacher_preference_reasons"),
                "rerank_displacement_cap": row.get("rerank_displacement_cap"),
                "rerank_displacement_cap_label": row.get("rerank_displacement_cap_label"),
                "uncertainty_flags": flags,
                "uncertainty_reasons": reasons,
                "uncertainty_score": len(flags),
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
        "uncertainty_summary": build_uncertainty_summary(data),
        "class_metadata": class_metadata,
        "cost_report": cost_report,
        "consistency_report": consistency_report,
        "pairwise_matrix": pairwise_matrix,
        "review_draft": review_draft,
        "review_feedback": review_feedback,
        "review_delta": review_delta,
        "local_learning_profile": local_learning_profile,
        "local_teacher_prior": local_teacher_prior,
        "aggregate_learning": aggregate_learning,
        "review_context": review_context(Path("."), rows_source),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote dashboard data: {output_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
