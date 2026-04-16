#!/usr/bin/env python3
import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.aggregate_helpers import get_level_bands, load_config
    from scripts.assessor_context import load_class_metadata, normalize_genre
    from scripts.assessor_utils import load_file_text, resolve_input_path
    from scripts.llm_assessors_core import json_from_text
    from scripts.levels import normalize_level
    from scripts.openai_client import extract_text, responses_create
except ImportError:  # pragma: no cover - Support running as script without package context
    from aggregate_helpers import get_level_bands, load_config  # pragma: no cover
    from assessor_context import load_class_metadata, normalize_genre  # pragma: no cover
    from assessor_utils import load_file_text, resolve_input_path  # pragma: no cover
    from llm_assessors_core import json_from_text  # pragma: no cover
    from levels import normalize_level  # pragma: no cover
    from openai_client import extract_text, responses_create  # pragma: no cover


CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}

RESPONSE_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "boundary": {"type": "string"},
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "student_id": {"type": "string"},
                        "decision": {"type": "string", "enum": ["promote", "hold", "demote", "ambiguous"]},
                        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                        "current_level": {"type": "string"},
                        "recommended_level": {"type": "string"},
                        "rationale": {"type": "string"},
                        "decisive_evidence": {"type": "array", "items": {"type": "string"}},
                        "risks": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": [
                        "student_id",
                        "decision",
                        "confidence",
                        "current_level",
                        "recommended_level",
                        "rationale",
                        "decisive_evidence",
                        "risks",
                    ],
                    "additionalProperties": False,
                },
            },
            "pairwise_checks_needed": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "higher_candidate": {"type": "string"},
                        "lower_candidate": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["higher_candidate", "lower_candidate", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["boundary", "decisions", "pairwise_checks_needed"],
        "additionalProperties": False,
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    seen = set(fieldnames)
    for row in rows[1:]:
        for key in row.keys():
            if key not in seen:
                fieldnames.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_texts(text_dir: Path) -> dict[str, str]:
    if not text_dir.exists():
        return {}
    return {path.stem.strip(): path.read_text(encoding="utf-8", errors="ignore") for path in sorted(text_dir.glob("*.txt"))}


def normalize_confidence(value) -> str:
    token = str(value or "").strip().lower()
    if token == "high":
        return "high"
    if token in {"med", "medium"}:
        return "medium"
    return "low"


def rank_value(row: dict) -> int:
    return int(num(row.get("consensus_rank") or row.get("seed_rank") or row.get("final_rank"), 999999))


def flags_with(row: dict, flag: str) -> str:
    flags = [token.strip() for token in str(row.get("flags", "") or "").split(";") if token.strip()]
    if flag not in flags:
        flags.append(flag)
    return ";".join(flags)


def level_maps(level_bands: list[dict]) -> tuple[dict[str, dict], dict[str, int]]:
    ordered = [band for band in level_bands if normalize_level(band.get("level"))]
    ordered.sort(key=lambda band: num(band.get("min"), 0.0))
    by_level = {normalize_level(band.get("level")): band for band in ordered}
    order = {normalize_level(band.get("level")): idx for idx, band in enumerate(ordered)}
    return by_level, order


def row_level(row: dict) -> str:
    return normalize_level(row.get("band_adjudicated_level") or row.get("adjusted_level") or row.get("base_level")) or ""


def dedupe_candidates(items: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for item in items:
        sid = str(item.get("student_id", "") or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        deduped.append(item)
    return deduped


def select_band_seam_candidates(
    rows: list[dict],
    level_bands: list[dict],
    *,
    per_side: int = 6,
    margin: float = 3.0,
) -> list[dict]:
    by_level, _order = level_maps(level_bands)
    ordered_levels = [normalize_level(band.get("level")) for band in sorted(level_bands, key=lambda band: num(band.get("min"), 0.0))]
    ordered_levels = [level for level in ordered_levels if level]
    boundaries = []
    for idx in range(1, len(ordered_levels)):
        lower_level = ordered_levels[idx - 1]
        upper_level = ordered_levels[idx]
        lower_rows = [dict(row) for row in rows if row_level(row) == lower_level]
        upper_rows = [dict(row) for row in rows if row_level(row) == upper_level]
        if not lower_rows or not upper_rows:
            continue
        upper_min = num(by_level.get(upper_level, {}).get("min"), 0.0)
        top_lower = sorted(lower_rows, key=lambda row: (rank_value(row), str(row.get("student_id", "")).lower()))[: max(1, per_side)]
        bottom_upper = sorted(upper_rows, key=lambda row: (-rank_value(row), str(row.get("student_id", "")).lower()))[: max(1, per_side)]
        near_lower = [
            row
            for row in lower_rows
            if num(row.get("rubric_after_penalty_percent"), num(row.get("rubric_mean_percent"), 0.0)) >= upper_min - float(margin)
        ]
        near_upper = [
            row
            for row in upper_rows
            if num(row.get("rubric_after_penalty_percent"), num(row.get("rubric_mean_percent"), 0.0)) <= upper_min + float(margin)
        ]
        candidates = dedupe_candidates(top_lower + bottom_upper + near_lower + near_upper)
        candidates = sorted(candidates, key=lambda row: (rank_value(row), str(row.get("student_id", "")).lower()))
        boundaries.append(
            {
                "boundary": f"{lower_level}/{upper_level}",
                "lower_level": lower_level,
                "upper_level": upper_level,
                "upper_min_percent": upper_min,
                "candidate_count": len(candidates),
                "candidates": [candidate_record(row, upper_min) for row in candidates],
            }
        )
    return boundaries


def candidate_record(row: dict, boundary_percent: float) -> dict:
    score = num(row.get("rubric_after_penalty_percent"), num(row.get("rubric_mean_percent"), 0.0))
    return {
        "student_id": str(row.get("student_id", "") or "").strip(),
        "current_level": row_level(row),
        "rank": rank_value(row),
        "rubric_after_penalty_percent": round(score, 4),
        "distance_from_boundary": round(score - float(boundary_percent), 4),
        "composite_score": round(num(row.get("composite_score"), 0.0), 6),
        "borda_percent": round(num(row.get("borda_percent"), 0.0), 6),
        "rubric_sd_points": round(num(row.get("rubric_sd_points"), 0.0), 6),
        "rank_sd": round(num(row.get("rank_sd"), 0.0), 6),
        "flags": str(row.get("flags", "") or ""),
    }


def resolve_genre(metadata: dict) -> str:
    raw = metadata.get("genre") or metadata.get("assignment_genre") or metadata.get("genre_form") or metadata.get("assessment_unit")
    return str(normalize_genre(raw) or "").strip()


def build_prompt(boundary: dict, rows_by_id: dict[str, dict], texts: dict[str, str], rubric: str, outline: str, metadata: dict) -> str:
    grade = metadata.get("grade") or metadata.get("grade_level") or metadata.get("class_grade") or ""
    genre = resolve_genre(metadata)
    candidates = []
    for item in boundary.get("candidates", []):
        sid = item["student_id"]
        row = rows_by_id.get(sid, {})
        candidates.append(
            f"""Candidate {sid}
Current level: {item['current_level']}
Current rank: {item['rank']}
Rubric percent: {item['rubric_after_penalty_percent']:.2f}
Composite: {item['composite_score']:.4f}
Borda percent: {item['borda_percent']:.4f}
Flags: {item['flags'] or 'none'}
Essay:
{texts.get(sid, '')}
"""
        )
    genre_guidance = ""
    if genre == "literary_analysis":
        genre_guidance = """
Literary-analysis priority:
1. Stronger interpretation and explanation outrank formulaic structure.
2. Plot summary should not beat a paper that explains how evidence supports a central idea.
3. Mechanics matter after task alignment, interpretation, evidence, and completion status.
"""
    return f"""You are adjudicating a writing level boundary before in-band ranking.

Grade/context: {grade}
Genre: {genre or 'unknown'}
Boundary under review: {boundary['boundary']}

Use the rubric and assignment, not generic essay polish.

Rubric:
{rubric}

Assignment:
{outline}
{genre_guidance}

Decide whether each candidate belongs below the boundary, above the boundary, or remains ambiguous.

Use this priority order:
1. Task alignment and central claim.
2. Literary interpretation or reasoning.
3. Specific evidence and explanation.
4. Organization and coherence.
5. Conventions only after meaning is clear.
6. Completion status.

Candidates:
{chr(10).join(candidates)}

Return ONLY strict JSON:
{{
  "boundary": "{boundary['boundary']}",
  "decisions": [
    {{
      "student_id": "...",
      "decision": "promote" | "hold" | "demote" | "ambiguous",
      "confidence": "low" | "medium" | "high",
      "current_level": "...",
      "recommended_level": "...",
      "rationale": "short task-grounded reason",
      "decisive_evidence": ["short evidence phrase"],
      "risks": ["short uncertainty phrase"]
    }}
  ],
  "pairwise_checks_needed": [
    {{"higher_candidate": "...", "lower_candidate": "...", "reason": "..."}}
  ]
}}
"""


def parse_json(text: str) -> dict:
    try:
        payload = json_from_text(text)
    except ValueError as exc:
        raise ValueError("Invalid JSON response") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid JSON response")
    return payload


def build_repair_prompt(raw_text: str, boundary: str) -> str:
    return f"""The prior response was supposed to be strict JSON for band-seam adjudication but was malformed.

Return ONLY valid JSON in this format:
{{
  "boundary": "{boundary}",
  "decisions": [
    {{
      "student_id": "...",
      "decision": "promote" | "hold" | "demote" | "ambiguous",
      "confidence": "low" | "medium" | "high",
      "current_level": "...",
      "recommended_level": "...",
      "rationale": "short reason",
      "decisive_evidence": ["..."],
      "risks": ["..."]
    }}
  ],
  "pairwise_checks_needed": [
    {{"higher_candidate": "...", "lower_candidate": "...", "reason": "..."}}
  ]
}}

Malformed response:
{raw_text}
"""


def adjudicate_boundaries(
    boundaries: list[dict],
    rows: list[dict],
    texts: dict[str, str],
    rubric: str,
    outline: str,
    metadata: dict,
    *,
    model: str,
    routing: str,
    reasoning: str,
    max_output_tokens: int,
    max_candidates_per_call: int = 8,
) -> list[dict]:
    rows_by_id = {str(row.get("student_id", "") or "").strip(): row for row in rows}
    outputs = []
    for boundary in boundaries:
        candidates = list(boundary.get("candidates", []) or [])
        chunk_size = max(1, int(max_candidates_per_call))
        chunks = [candidates[idx : idx + chunk_size] for idx in range(0, len(candidates), chunk_size)] or [[]]
        for chunk_index, chunk in enumerate(chunks, start=1):
            chunk_boundary = {**boundary, "candidates": chunk, "candidate_count": len(chunk)}
            prompt = build_prompt(chunk_boundary, rows_by_id, texts, rubric, outline, metadata)
            chunk_note = {
                "chunk_index": chunk_index,
                "chunk_count": len(chunks),
                "candidate_count": len(chunk),
            }
            response = responses_create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                reasoning=reasoning,
                routing_path=routing,
                text_format=RESPONSE_FORMAT,
                max_output_tokens=max_output_tokens,
            )
            content = extract_text(response)
            repair_used = False
            try:
                parsed = parse_json(content)
            except ValueError:
                repair_used = True
                repair_response = responses_create(
                    model=model,
                    messages=[{"role": "user", "content": build_repair_prompt(content, boundary["boundary"])}],
                    temperature=0.0,
                    reasoning="low",
                    routing_path=routing,
                    text_format=RESPONSE_FORMAT,
                    max_output_tokens=max_output_tokens,
                )
                response = repair_response
                parsed = parse_json(extract_text(repair_response))
            outputs.append(
                normalize_adjudication_payload(
                    parsed,
                    chunk_boundary,
                    requested_model=model,
                    response_model=str(response.get("model") or model),
                    routing=routing,
                    reasoning=reasoning,
                    repair_used=repair_used,
                    usage=response.get("usage", {}),
                    **chunk_note,
                )
            )
    return outputs


def normalize_adjudication_payload(payload: dict, boundary: dict, **metadata) -> dict:
    candidate_ids = {item["student_id"] for item in boundary.get("candidates", [])}
    decisions = []
    for item in payload.get("decisions", []) if isinstance(payload.get("decisions"), list) else []:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("student_id", "") or "").strip()
        if sid not in candidate_ids:
            continue
        decision = str(item.get("decision", "") or "").strip().lower()
        if decision not in {"promote", "hold", "demote", "ambiguous"}:
            decision = "ambiguous"
        decisions.append(
            {
                "student_id": sid,
                "decision": decision,
                "confidence": normalize_confidence(item.get("confidence")),
                "current_level": normalize_level(item.get("current_level")) or str(item.get("current_level", "") or "").strip(),
                "recommended_level": normalize_level(item.get("recommended_level")) or str(item.get("recommended_level", "") or "").strip(),
                "rationale": str(item.get("rationale", "") or "").strip(),
                "decisive_evidence": [str(value).strip() for value in item.get("decisive_evidence", []) if str(value).strip()]
                if isinstance(item.get("decisive_evidence"), list)
                else [],
                "risks": [str(value).strip() for value in item.get("risks", []) if str(value).strip()] if isinstance(item.get("risks"), list) else [],
            }
        )
    pairwise_checks = []
    for item in payload.get("pairwise_checks_needed", []) if isinstance(payload.get("pairwise_checks_needed"), list) else []:
        if isinstance(item, dict):
            pairwise_checks.append(
                {
                    "higher_candidate": str(item.get("higher_candidate", "") or "").strip(),
                    "lower_candidate": str(item.get("lower_candidate", "") or "").strip(),
                    "reason": str(item.get("reason", "") or "").strip(),
                }
            )
    return {
        "boundary": str(payload.get("boundary") or boundary["boundary"]),
        "lower_level": boundary["lower_level"],
        "upper_level": boundary["upper_level"],
        "candidate_count": boundary["candidate_count"],
        "decisions": decisions,
        "pairwise_checks_needed": pairwise_checks,
        "model_metadata": metadata,
    }


def confidence_meets(value: str, minimum: str) -> bool:
    return CONFIDENCE_ORDER.get(normalize_confidence(value), 0) >= CONFIDENCE_ORDER.get(normalize_confidence(minimum), 1)


def recommended_level_for_decision(decision: dict, boundary: dict, current_level: str) -> str:
    recommended = normalize_level(decision.get("recommended_level"))
    lower = boundary["lower_level"]
    upper = boundary["upper_level"]
    action = str(decision.get("decision", "") or "").strip().lower()
    if action == "promote" and current_level == lower:
        return upper
    if action == "demote" and current_level == upper:
        return lower
    if recommended in {lower, upper}:
        return recommended
    return current_level


def apply_adjudications(
    rows: list[dict],
    level_bands: list[dict],
    adjudications: list[dict],
    *,
    min_confidence: str = "medium",
) -> tuple[list[dict], list[dict]]:
    band_by_level, order_by_level = level_maps(level_bands)
    rows_by_id = {str(row.get("student_id", "") or "").strip(): dict(row) for row in rows}
    applied = []
    for boundary in adjudications:
        for decision in boundary.get("decisions", []):
            sid = str(decision.get("student_id", "") or "").strip()
            row = rows_by_id.get(sid)
            if not row:
                continue
            current = row_level(row)
            action = str(decision.get("decision", "") or "").strip().lower()
            target = recommended_level_for_decision(decision, boundary, current)
            should_apply = action in {"promote", "demote"} and target != current and confidence_meets(decision.get("confidence"), min_confidence)
            row["pre_band_adjudication_level"] = row.get("pre_band_adjudication_level") or current
            row["band_adjudicated_level"] = target if should_apply else current
            row["band_adjudication_decision"] = action
            row["band_adjudication_confidence"] = normalize_confidence(decision.get("confidence"))
            row["band_adjudication_boundary"] = boundary.get("boundary", "")
            row["band_adjudication_rationale"] = decision.get("rationale", "")
            if action == "ambiguous":
                row["flags"] = flags_with(row, "band_seam_ambiguous")
            if should_apply:
                band = band_by_level.get(target, {})
                row["adjusted_level"] = target
                row["adjusted_letter"] = band.get("letter", row.get("adjusted_letter", ""))
                modifier = str(row.get("level_modifier", "") or "")
                row["level_with_modifier"] = target if target.endswith("+") and modifier in {"", "+"} else f"{target}{modifier}"
                row["flags"] = flags_with(row, "band_seam_adjudicated")
                applied.append(
                    {
                        "student_id": sid,
                        "boundary": boundary.get("boundary", ""),
                        "decision": action,
                        "confidence": normalize_confidence(decision.get("confidence")),
                        "from_level": current,
                        "to_level": target,
                        "rationale": decision.get("rationale", ""),
                    }
                )
            rows_by_id[sid] = row
    updated = list(rows_by_id.values())
    updated.sort(
        key=lambda row: (
            -order_by_level.get(row_level(row), -1),
            -round(num(row.get("composite_score"), 0.0), 3),
            -round(num(row.get("borda_points"), 0.0), 3),
            -num(row.get("rubric_after_penalty_percent"), num(row.get("rubric_mean_percent"), 0.0)),
            num(row.get("conventions_mistake_rate_percent"), 0.0),
            str(row.get("student_id", "")).lower(),
        )
    )
    for idx, row in enumerate(updated, start=1):
        row["seed_rank"] = idx
        row["consensus_rank"] = idx
    return updated, applied


def main() -> int:
    parser = argparse.ArgumentParser(description="Adjudicate band seams before pairwise consistency reranking.")
    parser.add_argument("--scores", default="outputs/consensus_scores.csv", help="Consensus scores CSV")
    parser.add_argument("--config", default="config/marking_config.json", help="Marking config JSON")
    parser.add_argument("--texts", default="processing/normalized_text", help="Essay text directory")
    parser.add_argument("--rubric", default="inputs/rubric.md", help="Rubric file")
    parser.add_argument("--outline", default="inputs/assignment_outline.md", help="Assignment outline file")
    parser.add_argument("--class-metadata", default="inputs/class_metadata.json", help="Class metadata JSON")
    parser.add_argument("--routing", default="config/llm_routing.json", help="Routing config JSON")
    parser.add_argument("--model", default="", help="Model for band-seam adjudication")
    parser.add_argument("--reasoning", default="", help="Reasoning effort for band-seam adjudication")
    parser.add_argument("--max-output-tokens", type=int, default=1800, help="Max adjudicator output tokens")
    parser.add_argument("--per-side", type=int, default=6, help="Top lower-band and bottom upper-band candidates per seam")
    parser.add_argument("--max-candidates-per-call", type=int, default=8, help="Max boundary candidates to include in one model call")
    parser.add_argument("--margin", type=float, default=3.0, help="Boundary score margin for extra candidates")
    parser.add_argument("--min-confidence", default="medium", choices=["low", "medium", "high"], help="Minimum confidence needed to change a band")
    parser.add_argument("--candidates-output", default="outputs/band_seam_candidates.json", help="Candidate artifact JSON")
    parser.add_argument("--adjudication-output", default="outputs/band_seam_adjudication.json", help="Adjudication artifact JSON")
    parser.add_argument("--adjusted-output", default="outputs/band_adjusted_scores.csv", help="Adjusted score CSV")
    parser.add_argument("--report-output", default="outputs/band_seam_report.json", help="Report artifact JSON")
    parser.add_argument("--backup-output", default="outputs/consensus_scores.pre_band_seam.csv", help="Pre-seam scores backup CSV")
    args = parser.parse_args()

    scores_path = Path(args.scores)
    rows = load_rows(scores_path)
    if not rows:
        print(f"No score rows found in {scores_path}")
        return 1

    config = load_config(Path(args.config), None)
    level_bands = get_level_bands(config)
    boundaries = select_band_seam_candidates(rows, level_bands, per_side=max(1, args.per_side), margin=max(0.0, args.margin))
    candidates_payload = {
        "generated_at": now_iso(),
        "source_scores": str(scores_path),
        "per_side": max(1, args.per_side),
        "margin": max(0.0, args.margin),
        "boundary_count": len(boundaries),
        "boundaries": boundaries,
    }
    write_json(Path(args.candidates_output), candidates_payload)

    if not boundaries:
        write_csv(Path(args.adjusted_output), rows)
        report = {
            "generated_at": now_iso(),
            "status": "no_band_seams",
            "source_scores": str(scores_path),
            "candidate_count": 0,
            "applied_count": 0,
        }
        write_json(Path(args.adjudication_output), {"generated_at": now_iso(), "boundaries": []})
        write_json(Path(args.report_output), report)
        print(f"Wrote {args.report_output}")
        return 0

    routing_cfg = load_json(Path(args.routing))
    task_cfg = routing_cfg.get("tasks", {}).get("band_seam_adjudicator", {}) if isinstance(routing_cfg.get("tasks"), dict) else {}
    mode = os.environ.get("LLM_MODE") or routing_cfg.get("mode", "openai")
    if mode != "codex_local" and not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. Aborting.")
        return 1
    model = args.model or task_cfg.get("model") or routing_cfg.get("default_model") or "gpt-5.4-mini"
    reasoning = args.reasoning or task_cfg.get("reasoning") or "low"

    metadata = load_class_metadata(Path(args.class_metadata))
    rubric_path = resolve_input_path(Path(args.rubric), "rubric")
    outline_path = resolve_input_path(Path(args.outline), "assignment_outline")
    texts = load_texts(Path(args.texts))
    adjudications = adjudicate_boundaries(
        boundaries,
        rows,
        texts,
        load_file_text(rubric_path),
        load_file_text(outline_path),
        metadata if isinstance(metadata, dict) else {},
        model=model,
        routing=args.routing,
        reasoning=reasoning,
        max_output_tokens=max(512, int(args.max_output_tokens)),
        max_candidates_per_call=max(1, int(args.max_candidates_per_call)),
    )

    adjusted_rows, applied = apply_adjudications(rows, level_bands, adjudications, min_confidence=args.min_confidence)
    backup_path = Path(args.backup_output)
    write_csv(backup_path, rows)
    write_csv(Path(args.adjusted_output), adjusted_rows)
    write_csv(scores_path, adjusted_rows)

    adjudication_payload = {
        "generated_at": now_iso(),
        "source_scores": str(scores_path),
        "model": model,
        "routing": args.routing,
        "reasoning": reasoning,
        "min_confidence": args.min_confidence,
        "boundaries": adjudications,
    }
    report = {
        "generated_at": now_iso(),
        "status": "complete",
        "source_scores": str(scores_path),
        "backup_scores": str(backup_path),
        "adjusted_scores": str(args.adjusted_output),
        "boundary_count": len(boundaries),
        "candidate_count": sum(int(boundary.get("candidate_count", 0) or 0) for boundary in boundaries),
        "decision_count": sum(len(boundary.get("decisions", [])) for boundary in adjudications),
        "applied_count": len(applied),
        "applied": applied,
        "pairwise_checks_needed": [
            item
            for boundary in adjudications
            for item in boundary.get("pairwise_checks_needed", [])
            if item.get("higher_candidate") or item.get("lower_candidate")
        ],
    }
    write_json(Path(args.adjudication_output), adjudication_payload)
    write_json(Path(args.report_output), report)
    print(f"Band seam adjudication applied {len(applied)} change(s).")
    print(f"Wrote {args.report_output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
