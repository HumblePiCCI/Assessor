#!/usr/bin/env python3
import argparse
import csv
import json
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.assessor_context import (  # noqa: E402
    build_grade_context,
    format_exemplars,
    infer_genre_from_text,
    load_class_metadata,
    load_exemplars,
    load_grade_profiles,
    normalize_genre,
    resolve_exemplars_dir,
    select_grade_level,
)
from scripts.assessor_utils import load_file_text, resolve_input_path  # noqa: E402
from scripts.llm_assessors_core import (  # noqa: E402
    build_pass1_prompt,
    load_routing,
    parse_pass1_item,
    pass1_text_format,
)
from scripts.openai_client import extract_text, responses_create  # noqa: E402
from scripts.rubric_criteria import criteria_ids, criteria_prompt, evidence_requirements, load_rubric_criteria  # noqa: E402


def load_consensus(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_texts(text_dir: Path) -> dict[str, str]:
    texts = {}
    for path in sorted(text_dir.glob("*.txt")):
        texts[path.stem.strip()] = path.read_text(encoding="utf-8", errors="ignore")
    return texts


def load_level_boundaries(config_path: Path) -> list[float]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    bands = config.get("levels", {}).get("bands", [])
    mins = sorted(float(b.get("min", 0.0) or 0.0) for b in bands)
    return mins[1:] if len(mins) > 1 else [60.0, 70.0, 80.0, 90.0]


def _safe_score(row: dict) -> float:
    try:
        return float(row.get("rubric_after_penalty_percent", 0.0) or 0.0)
    except ValueError:
        return 0.0


def select_boundary_students(rows: list[dict], boundaries: list[float], margin: float, limit: int) -> list[dict]:
    selected = []
    for row in rows:
        score = _safe_score(row)
        distance = min(abs(score - edge) for edge in boundaries) if boundaries else 999.0
        if distance <= margin:
            selected.append(
                {
                    "student_id": row.get("student_id", ""),
                    "score": score,
                    "distance": round(distance, 4),
                }
            )
    selected.sort(key=lambda item: (item["distance"], item["student_id"].lower()))
    return selected[: max(0, limit)]


def load_pass1(path: Path) -> dict[str, dict]:
    payload = {}
    for file in sorted(path.glob("assessor_*.json")):
        payload[file.name] = json.loads(file.read_text(encoding="utf-8"))
    return payload


def find_score_item(scores: list[dict], student_id: str) -> dict | None:
    for item in scores:
        if str(item.get("student_id", "")).strip() == student_id:
            return item
    return None


def assessor_role(assessor_id: str) -> str:
    token = str(assessor_id).strip()
    if token.startswith("assessor_"):
        token = token[len("assessor_") :]
    if "_" in token:
        token = token.rsplit("_", 1)[-1]
    return token.upper() or "A"


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(value)))


def apply_score_update(item: dict, new_score: float):
    original = float(item.get("rubric_total_points", 0.0) or 0.0)
    updated = round(_clamp(new_score), 2)
    delta = updated - original
    item["rubric_total_points"] = updated
    criteria = item.get("criteria_points")
    if isinstance(criteria, dict) and abs(delta) > 0.001:
        shifted = {}
        for key, value in criteria.items():
            if isinstance(value, (int, float)):
                shifted[key] = round(_clamp(float(value) + delta), 2)
            else:
                shifted[key] = value
        item["criteria_points"] = shifted
    notes = str(item.get("notes", "")).strip()
    tag = f"Boundary recheck adjusted to {updated:.2f}"
    item["notes"] = f"{notes} | {tag}" if notes else tag


def capped_score(old_score: float, proposed: float, max_adjustment: float) -> tuple[float, bool]:
    cap = max(0.0, float(max_adjustment))
    if abs(proposed - old_score) <= cap:
        return proposed, False
    adjusted = old_score + cap if proposed > old_score else old_score - cap
    return adjusted, True


def write_json(path: Path, payload: dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def build_context(args, rubric: str, outline: str) -> tuple[str, str, list[str], dict]:
    metadata = load_class_metadata(Path(args.class_metadata))
    profiles = load_grade_profiles(Path(args.grade_profiles))
    grade_level = select_grade_level(None, metadata)
    grade_context = build_grade_context(grade_level, profiles)
    genre = args.genre or metadata.get("genre") or metadata.get("assignment_genre")
    if not genre:
        genre = infer_genre_from_text(rubric, outline)
    genre = normalize_genre(genre)
    exemplars_dir = Path(args.exemplars)
    if str(args.exemplars) == "inputs/exemplars":
        exemplars_dir = resolve_exemplars_dir(exemplars_dir, grade_level, genre)
    exemplars = load_exemplars(exemplars_dir)
    exemplar_block = format_exemplars(exemplars)
    criteria_cfg = load_rubric_criteria(Path(args.rubric_criteria))
    criteria_block = criteria_prompt(criteria_cfg, None) if criteria_cfg else ""
    required_ids = criteria_ids(criteria_cfg, None) if criteria_cfg else []
    reqs = evidence_requirements(criteria_cfg) if criteria_cfg else {}
    return grade_context, exemplar_block + ("\n\n" + criteria_block if criteria_block else ""), required_ids, reqs


def main() -> int:
    parser = argparse.ArgumentParser(description="Recheck near-boundary essays and adjust pass1 scores.")
    parser.add_argument("--consensus", default="outputs/consensus_scores.csv", help="Consensus CSV")
    parser.add_argument("--config", default="config/marking_config.json", help="Marking config")
    parser.add_argument("--margin", type=float, default=1.0, help="Boundary margin in percentage points")
    parser.add_argument("--max-students", type=int, default=8, help="Max boundary students to recheck")
    parser.add_argument("--replicates", type=int, default=3, help="Recheck attempts per assessor per student")
    parser.add_argument("--min-samples", type=int, default=2, help="Minimum successful samples to apply update")
    parser.add_argument("--max-adjustment", type=float, default=4.0, help="Max absolute score change from prior value")
    parser.add_argument("--pass1", default="assessments/pass1_individual", help="Pass1 directory")
    parser.add_argument("--texts", default="processing/normalized_text", help="Texts directory")
    parser.add_argument("--rubric", default="inputs/rubric.md", help="Rubric file")
    parser.add_argument("--outline", default="inputs/assignment_outline.md", help="Assignment outline file")
    parser.add_argument("--routing", default="config/llm_routing.json", help="Routing config")
    parser.add_argument("--grade-profiles", default="config/grade_level_profiles.json", help="Grade profiles")
    parser.add_argument("--class-metadata", default="inputs/class_metadata.json", help="Class metadata")
    parser.add_argument("--exemplars", default="inputs/exemplars", help="Exemplars root")
    parser.add_argument("--genre", default=None, help="Optional genre override")
    parser.add_argument("--rubric-criteria", default="config/rubric_criteria.json", help="Rubric criteria")
    parser.add_argument("--output", default="outputs/boundary_recheck.json", help="Report JSON")
    args = parser.parse_args()

    routing = load_routing(Path(args.routing))
    mode = os.environ.get("LLM_MODE") or routing.get("mode", "openai")
    if mode != "codex_local" and not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. Aborting.")
        return 1

    rows = load_consensus(Path(args.consensus))
    boundaries = load_level_boundaries(Path(args.config))
    selected = select_boundary_students(rows, boundaries, args.margin, args.max_students)
    if not selected:
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "updated": 0,
            "selected": [],
            "status": "no_boundary_students",
        }
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote {out}")
        return 0

    texts = load_texts(Path(args.texts))
    rubric_path = resolve_input_path(Path(args.rubric), "rubric")
    outline_path = resolve_input_path(Path(args.outline), "assignment_outline")
    rubric = load_file_text(rubric_path)
    outline = load_file_text(outline_path)
    grade_context, context_block, required_ids, reqs = build_context(args, rubric, outline)

    pass1_dir = Path(args.pass1)
    pass1 = load_pass1(pass1_dir)
    pass1_model = routing["tasks"]["pass1_assessor"]["model"]
    pass1_reasoning = routing["tasks"]["pass1_assessor"].get("reasoning", "medium")
    pass1_temp = routing["tasks"]["pass1_assessor"].get("temperature", 0.0)
    pass1_tokens = routing["tasks"]["pass1_assessor"].get("max_output_tokens")
    require_evidence = bool(routing.get("tasks", {}).get("pass1_assessor", {}).get("require_evidence", False))

    updates = []
    for file_name, payload in pass1.items():
        assessor_id = str(payload.get("assessor_id", file_name.replace(".json", "")))
        role = assessor_role(assessor_id)
        scores = payload.get("scores", [])
        changed = False
        for student in selected:
            sid = student["student_id"]
            text = texts.get(sid, "")
            if not text:
                continue
            item = find_score_item(scores, sid)
            if item is None:
                continue
            prompt = build_pass1_prompt(role, rubric, outline, sid, text, grade_context, context_block, "", reqs if require_evidence else {})
            collected = []
            for _ in range(max(1, int(args.replicates))):
                try:
                    response = responses_create(
                        model=pass1_model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=pass1_temp,
                        reasoning=pass1_reasoning,
                        routing_path=args.routing,
                        text_format=pass1_text_format(require_evidence),
                        max_output_tokens=pass1_tokens,
                    )
                    parsed = parse_pass1_item(
                        extract_text(response),
                        sid,
                        required_ids,
                        reqs if require_evidence else {},
                        text,
                        strict=False,
                    )
                    score = float(parsed.get("rubric_total_points", 0.0) or 0.0)
                    collected.append(score)
                except Exception:
                    continue
            if len(collected) < max(1, int(args.min_samples)):
                continue
            raw_new_score = statistics.median(collected)
            old_score = float(item.get("rubric_total_points", 0.0) or 0.0)
            new_score, capped = capped_score(old_score, raw_new_score, args.max_adjustment)
            if abs(new_score - old_score) < 0.01:
                continue
            apply_score_update(item, new_score)
            changed = True
            updates.append(
                {
                    "assessor_id": assessor_id,
                    "student_id": sid,
                    "old_score": round(old_score, 2),
                    "new_score": round(float(item["rubric_total_points"]), 2),
                    "raw_new_score": round(raw_new_score, 2),
                    "capped": capped,
                    "distance_to_boundary": student["distance"],
                    "samples": len(collected),
                }
            )
        if changed:
            write_json(pass1_dir / file_name, payload)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "selected": selected,
        "updated": len(updates),
        "updates": updates,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
