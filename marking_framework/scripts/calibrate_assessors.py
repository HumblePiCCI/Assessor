#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.assessor_context import (
    build_grade_context,
    format_exemplars,
    load_exemplars,
    load_grade_profiles,
    normalize_genre,
)
from scripts.assessor_utils import load_file_text, resolve_input_path
from scripts.openai_client import extract_text, responses_create
from scripts.rubric_criteria import criteria_ids, criteria_prompt, evidence_requirements, load_rubric_criteria, total_points
from scripts.run_llm_assessors import build_pass1_prompt, parse_pass1_item, pass1_text_format


BAND_GRADE_LEVEL = {"grade_6_7": 7, "grade_8_10": 9, "grade_11_12": 11}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def score_to_percent(score: float, points_possible: int | None) -> float:
    if points_possible and score <= points_possible:
        return (score / points_possible) * 100.0
    return float(score)


def iter_gold_samples(calibration: dict):
    for band, genres in calibration.get("gold_samples", {}).items():
        for genre, samples in genres.items():
            for sample in samples:
                yield band, genre, sample


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate assessors using a gold exemplar set")
    parser.add_argument("--calibration", default="config/calibration_set.json", help="Calibration set JSON")
    parser.add_argument("--exemplars", default="inputs/exemplars", help="Exemplars root")
    parser.add_argument("--rubric", default="inputs/rubric.md", help="Rubric file")
    parser.add_argument("--outline", default="inputs/assignment_outline.md", help="Assignment outline file")
    parser.add_argument("--routing", default="config/llm_routing.json", help="Routing config")
    parser.add_argument("--assessors", default="A,B,C", help="Assessor IDs")
    parser.add_argument("--grade-profiles", default="config/grade_level_profiles.json", help="Grade profiles")
    parser.add_argument("--rubric-criteria", default="config/rubric_criteria.json", help="Rubric criteria JSON")
    parser.add_argument("--output", default="outputs/calibration_bias.json", help="Bias output")
    args = parser.parse_args()

    calibration = load_json(Path(args.calibration))
    rubric_path = resolve_input_path(Path(args.rubric), "rubric")
    outline_path = resolve_input_path(Path(args.outline), "assignment_outline")
    rubric = load_file_text(rubric_path)
    outline = load_file_text(outline_path)
    if not rubric.strip():
        print(f"Rubric text is empty. Check file at {rubric_path}.")
        return 1

    profiles = load_grade_profiles(Path(args.grade_profiles))
    criteria_cfg = load_rubric_criteria(Path(args.rubric_criteria))
    points_possible = total_points(criteria_cfg) if criteria_cfg else None
    assessors = [a.strip() for a in args.assessors.split(",") if a.strip()]
    routing = load_json(Path(args.routing))
    pass1_model = routing["tasks"]["pass1_assessor"]["model"]
    pass1_reasoning = routing["tasks"]["pass1_assessor"].get("reasoning", "medium")

    errors_by_assessor = {f"assessor_{a}": [] for a in assessors}
    details = []
    for band, genre, sample in iter_gold_samples(calibration):
        genre_norm = normalize_genre(genre)
        grade_level = BAND_GRADE_LEVEL.get(band)
        grade_context = build_grade_context(grade_level, profiles)
        exemplars_dir = Path(args.exemplars) / band / genre_norm
        essay_path = exemplars_dir / sample["file"]
        if not essay_path.exists():
            continue
        essay = load_file_text(essay_path)
        exemplar_block = format_exemplars(load_exemplars(exemplars_dir, exclude_files={essay_path.name}))
        criteria_block = criteria_prompt(criteria_cfg, genre_norm) if criteria_cfg else ""
        reqs = evidence_requirements(criteria_cfg) if criteria_cfg else {}
        required_ids = criteria_ids(criteria_cfg, genre_norm) if criteria_cfg else []

        for assessor in assessors:
            prompt = build_pass1_prompt(
                assessor,
                rubric,
                outline,
                essay_path.stem,
                essay,
                grade_context,
                exemplar_block,
                criteria_block,
                reqs,
            )
            response = responses_create(
                model=pass1_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                reasoning=pass1_reasoning,
                routing_path=args.routing,
                text_format=pass1_text_format(),
            )
            content = extract_text(response)
            item = parse_pass1_item(content, essay_path.stem, required_ids, reqs, essay)
            score_pct = score_to_percent(float(item["rubric_total_points"]), points_possible)
            error = score_pct - float(sample["target_pct"])
            errors_by_assessor[f"assessor_{assessor}"].append(error)
            details.append({
                "assessor_id": f"assessor_{assessor}",
                "band": band,
                "genre": genre_norm,
                "file": sample["file"],
                "target_pct": sample["target_pct"],
                "score_pct": round(score_pct, 2),
                "error": round(error, 2),
            })

    bias = {}
    for assessor_id, errors in errors_by_assessor.items():
        if not errors:
            continue
        mean_error = sum(errors) / len(errors)
        bias[assessor_id] = {"mean_error": round(mean_error, 2), "bias": round(mean_error, 2), "samples": len(errors)}

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "method": calibration.get("bias_correction", {}).get("method", "linear_offset"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assessors": bias,
        "details": details,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Calibration saved to {out_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
