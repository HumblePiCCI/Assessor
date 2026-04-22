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
PAIRWISE_CONFIDENCE_WEIGHTS = {"low": 0.5, "medium": 1.0, "high": 2.0}

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


def load_pass2_rankings(pass2_dir: Path) -> list[dict]:
    rankings = []
    if not pass2_dir.exists():
        return rankings
    for path in sorted(pass2_dir.glob("*")):
        if not path.is_file():
            continue
        seen = set()
        ranking = []
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            sid = line.strip()
            if not sid or sid.startswith("#") or sid in seen:
                continue
            seen.add(sid)
            ranking.append(sid)
        if ranking:
            rankings.append({"assessor_id": path.stem, "ranking": ranking})
    return rankings


def normalize_decision(value) -> str:
    token = str(value or "").strip().upper()
    return "SWAP" if token == "SWAP" else "KEEP"


def load_pairwise_judgments(path: Path) -> list[dict]:
    payload = load_json(path)
    checks = payload.get("checks", payload.get("judgments", [])) if isinstance(payload, dict) else []
    normalized = []
    for item in checks if isinstance(checks, list) else []:
        if not isinstance(item, dict):
            continue
        pair = item.get("pair")
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        seed_order = item.get("seed_order", {}) if isinstance(item.get("seed_order"), dict) else {}
        higher = str(seed_order.get("higher") or pair[0]).strip()
        lower = str(seed_order.get("lower") or pair[1]).strip()
        decision = normalize_decision(item.get("decision"))
        confidence = normalize_confidence(item.get("confidence"))
        winner = higher if decision == "KEEP" else lower
        loser = lower if decision == "KEEP" else higher
        normalized.append(
            {
                "winner": winner,
                "loser": loser,
                "confidence": confidence,
                "weight": PAIRWISE_CONFIDENCE_WEIGHTS.get(confidence, 0.5),
                "rationale": str(item.get("rationale", "") or "").strip(),
            }
        )
    return normalized


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


def add_evidence_to_boundaries(boundaries: list[dict], rows: list[dict], pass2_rankings: list[dict], pairwise_judgments: list[dict]) -> list[dict]:
    rows_by_id = {str(row.get("student_id", "") or "").strip(): row for row in rows}
    total = max(1, len(rows_by_id))
    enriched = []
    for boundary in boundaries:
        lower_level = boundary["lower_level"]
        upper_level = boundary["upper_level"]
        candidate_ids = [item["student_id"] for item in boundary.get("candidates", [])]
        levels = {sid: row_level(rows_by_id.get(sid, {})) for sid in candidate_ids}
        updated_candidates = []
        for item in boundary.get("candidates", []):
            sid = item["student_id"]
            opposite_ids = [
                other
                for other in candidate_ids
                if other != sid
                and (
                    (levels.get(sid) == lower_level and levels.get(other) == upper_level)
                    or (levels.get(sid) == upper_level and levels.get(other) == lower_level)
                )
            ]
            pass2_wins = 0
            pass2_losses = 0
            for ranking in pass2_rankings:
                positions = {student_id: idx for idx, student_id in enumerate(ranking.get("ranking", []))}
                if sid not in positions:
                    continue
                for other in opposite_ids:
                    if other not in positions:
                        continue
                    if positions[sid] < positions[other]:
                        pass2_wins += 1
                    else:
                        pass2_losses += 1
            direct_support = 0.0
            direct_opposition = 0.0
            direct_examples = []
            for judgment in pairwise_judgments:
                winner = judgment.get("winner")
                loser = judgment.get("loser")
                if winner == sid and loser in opposite_ids:
                    direct_support += float(judgment.get("weight", 0.0) or 0.0)
                    if len(direct_examples) < 3:
                        direct_examples.append(f"beats {loser} ({judgment.get('confidence')})")
                elif loser == sid and winner in opposite_ids:
                    direct_opposition += float(judgment.get("weight", 0.0) or 0.0)
                    if len(direct_examples) < 3:
                        direct_examples.append(f"loses to {winner} ({judgment.get('confidence')})")
            rank = int(item.get("rank", rank_value(rows_by_id.get(sid, {}))) or total)
            seed_percentile = 1.0 if total <= 1 else 1.0 - ((rank - 1) / max(total - 1, 1))
            evidence = {
                "borda_percent": round(num(item.get("borda_percent"), 0.0), 6),
                "composite_score": round(num(item.get("composite_score"), 0.0), 6),
                "distance_from_boundary": round(num(item.get("distance_from_boundary"), 0.0), 6),
                "seed_percentile": round(seed_percentile, 6),
                "pass2_boundary_wins": pass2_wins,
                "pass2_boundary_losses": pass2_losses,
                "pass2_boundary_net": pass2_wins - pass2_losses,
                "direct_pairwise_support": round(direct_support, 6),
                "direct_pairwise_opposition": round(direct_opposition, 6),
                "direct_pairwise_net": round(direct_support - direct_opposition, 6),
                "direct_pairwise_examples": direct_examples,
            }
            updated = dict(item)
            updated["evidence"] = evidence
            updated_candidates.append(updated)
        enriched.append({**boundary, "candidates": updated_candidates})
    return enriched


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
Rubric percent: {num(item.get('rubric_after_penalty_percent'), 0.0):.2f}
Distance from boundary: {num(item.get('distance_from_boundary'), 0.0):+.2f}
Composite: {num(item.get('composite_score'), 0.0):.4f}
Borda percent: {num(item.get('borda_percent'), 0.0):.4f}
Rubric SD: {num(item.get('rubric_sd_points'), 0.0):.2f}
Rank SD: {num(item.get('rank_sd'), 0.0):.2f}
Evidence support:
- Seed percentile: {item.get('evidence', {}).get('seed_percentile', 0.0):.4f}
- Pass2 boundary pairwise: wins={item.get('evidence', {}).get('pass2_boundary_wins', 0)}, losses={item.get('evidence', {}).get('pass2_boundary_losses', 0)}, net={item.get('evidence', {}).get('pass2_boundary_net', 0)}
- Direct pairwise boundary support: support={item.get('evidence', {}).get('direct_pairwise_support', 0.0):.2f}, opposition={item.get('evidence', {}).get('direct_pairwise_opposition', 0.0):.2f}, net={item.get('evidence', {}).get('direct_pairwise_net', 0.0):.2f}
- Direct pairwise examples: {'; '.join(item.get('evidence', {}).get('direct_pairwise_examples', [])) or 'none'}
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
You must return exactly one decision for every candidate listed. Use the aggregate and pairwise evidence as corroboration, but do not let Borda/score alone override the essay quality. If your level recommendation contradicts strong support evidence, explain the contradiction in risks.

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


def build_missing_decisions_prompt(original_prompt: str, missing_ids: list[str], previous_text: str) -> str:
    return f"""{original_prompt}

The previous response omitted required candidate decisions for: {", ".join(missing_ids)}.

Return ONLY valid JSON. Include decisions for the missing candidate ids above. You may include decisions for all candidates again, but every missing id must appear.

Previous response:
{previous_text}
"""


def ambiguous_decision_for_missing(candidate: dict) -> dict:
    return {
        "student_id": candidate["student_id"],
        "decision": "ambiguous",
        "confidence": "low",
        "current_level": candidate.get("current_level", ""),
        "recommended_level": candidate.get("current_level", ""),
        "rationale": "No complete model decision after retry; held for downstream pairwise evidence.",
        "decisive_evidence": [],
        "risks": ["model_omitted_required_decision"],
        "candidate_evidence": dict(candidate.get("evidence", {})),
    }


def complete_chunk_payload(
    attempts: list[dict],
    boundary: dict,
    metadata: dict,
    *,
    missing_after_retries: list[str],
) -> dict:
    candidates_by_id = {item["student_id"]: item for item in boundary.get("candidates", [])}
    decisions_by_id = {}
    pairwise_checks = []
    repair_used = False
    response_models = []
    total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for attempt in attempts:
        normalized = attempt.get("payload", {})
        repair_used = repair_used or bool(normalized.get("model_metadata", {}).get("repair_used", False))
        response_model = normalized.get("model_metadata", {}).get("response_model")
        if response_model:
            response_models.append(response_model)
        usage = normalized.get("model_metadata", {}).get("usage", {})
        if isinstance(usage, dict):
            for key in total_usage:
                total_usage[key] += int(usage.get(key, 0) or 0)
        for decision in normalized.get("decisions", []):
            sid = decision["student_id"]
            if sid in candidates_by_id:
                decisions_by_id[sid] = decision
        pairwise_checks.extend(normalized.get("pairwise_checks_needed", []))
    for sid in missing_after_retries:
        if sid in candidates_by_id:
            decisions_by_id[sid] = ambiguous_decision_for_missing(candidates_by_id[sid])
    ordered_decisions = [decisions_by_id[sid] for sid in candidates_by_id if sid in decisions_by_id]
    return {
        "boundary": boundary["boundary"],
        "lower_level": boundary["lower_level"],
        "upper_level": boundary["upper_level"],
        "candidate_count": boundary["candidate_count"],
        "decisions": ordered_decisions,
        "pairwise_checks_needed": pairwise_checks,
        "model_metadata": {
            **metadata,
            "response_model": response_models[-1] if response_models else metadata.get("response_model", ""),
            "repair_used": repair_used,
            "attempt_count": len(attempts),
            "missing_after_retries": missing_after_retries,
            "usage": total_usage,
        },
    }


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
    chunk_retries: int = 2,
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
            candidate_ids = [item["student_id"] for item in chunk]
            attempts = []
            missing = list(candidate_ids)
            previous_text = ""
            for attempt_idx in range(max(0, int(chunk_retries)) + 1):
                request_prompt = prompt if attempt_idx == 0 else build_missing_decisions_prompt(prompt, missing, previous_text)
                response = responses_create(
                    model=model,
                    messages=[{"role": "user", "content": request_prompt}],
                    temperature=0.0,
                    reasoning=reasoning,
                    routing_path=routing,
                    text_format=RESPONSE_FORMAT,
                    max_output_tokens=max_output_tokens,
                )
                content = extract_text(response)
                previous_text = content
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
                    previous_text = extract_text(repair_response)
                    parsed = parse_json(previous_text)
                normalized = normalize_adjudication_payload(
                    parsed,
                    chunk_boundary,
                    requested_model=model,
                    response_model=str(response.get("model") or model),
                    routing=routing,
                    reasoning=reasoning,
                    repair_used=repair_used,
                    usage=response.get("usage", {}),
                    attempt_index=attempt_idx + 1,
                    **chunk_note,
                )
                attempts.append({"payload": normalized})
                decided = {decision["student_id"] for decision in normalized.get("decisions", [])}
                missing = [sid for sid in candidate_ids if sid not in decided and sid not in {d["student_id"] for a in attempts for d in a["payload"].get("decisions", [])}]
                if not missing:
                    break
            decided_all = {decision["student_id"] for attempt in attempts for decision in attempt["payload"].get("decisions", [])}
            missing_after_retries = [sid for sid in candidate_ids if sid not in decided_all]
            outputs.append(
                complete_chunk_payload(
                    attempts,
                    chunk_boundary,
                    {
                        "requested_model": model,
                        "routing": routing,
                        "reasoning": reasoning,
                        **chunk_note,
                    },
                    missing_after_retries=missing_after_retries,
                )
            )
    return outputs


def normalize_adjudication_payload(payload: dict, boundary: dict, **metadata) -> dict:
    candidates_by_id = {item["student_id"]: item for item in boundary.get("candidates", [])}
    candidate_ids = set(candidates_by_id)
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
                "candidate_evidence": dict(candidates_by_id.get(sid, {}).get("evidence", {})),
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


def evidence_guard_allows(decision: dict, action: str, *, min_confidence: str) -> tuple[bool, str]:
    confidence = normalize_confidence(decision.get("confidence"))
    if not confidence_meets(confidence, min_confidence):
        return False, "below_min_confidence"
    evidence = decision.get("candidate_evidence", {}) if isinstance(decision.get("candidate_evidence"), dict) else {}
    direct_net = num(evidence.get("direct_pairwise_net"), 0.0)
    pass2_net = num(evidence.get("pass2_boundary_net"), 0.0)
    borda = num(evidence.get("borda_percent"), 0.0)
    if action == "promote":
        strong_contrary = direct_net <= -2.0 or (pass2_net <= -4.0 and borda < 0.45)
        weak_contrary = direct_net < 0.0 or (pass2_net <= -3.0 and borda < 0.55)
    elif action == "demote":
        strong_contrary = direct_net >= 2.0 or (pass2_net >= 4.0 and borda > 0.55)
        weak_contrary = direct_net > 0.0 or (pass2_net >= 3.0 and borda > 0.45)
    else:
        return True, ""
    if strong_contrary:
        return False, "strong_cross_evidence_contradiction"
    if confidence != "high" and weak_contrary:
        return False, "weak_judgment_contradicts_cross_evidence"
    return True, ""


def movement_key(sid: str, from_level: str, to_level: str) -> str:
    return f"{sid}:{from_level}->{to_level}"


def apply_adjudications(
    rows: list[dict],
    level_bands: list[dict],
    adjudications: list[dict],
    *,
    min_confidence: str = "medium",
    movement_history: set[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    band_by_level, order_by_level = level_maps(level_bands)
    rows_by_id = {str(row.get("student_id", "") or "").strip(): dict(row) for row in rows}
    movement_history = movement_history if movement_history is not None else set()
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
            guard_allowed, guard_reason = evidence_guard_allows(decision, action, min_confidence=min_confidence)
            reverse_seen = movement_key(sid, target, current) in movement_history
            if reverse_seen and normalize_confidence(decision.get("confidence")) != "high":
                guard_allowed = False
                guard_reason = "weak_reversal_blocked"
            should_apply = action in {"promote", "demote"} and target != current and guard_allowed
            row["pre_band_adjudication_level"] = row.get("pre_band_adjudication_level") or current
            row["band_adjudicated_level"] = target if should_apply else current
            row["band_adjudication_decision"] = action
            row["band_adjudication_confidence"] = normalize_confidence(decision.get("confidence"))
            row["band_adjudication_boundary"] = boundary.get("boundary", "")
            row["band_adjudication_rationale"] = decision.get("rationale", "")
            row["band_adjudication_guard"] = "applied" if should_apply else guard_reason
            if action == "ambiguous":
                row["flags"] = flags_with(row, "band_seam_ambiguous")
            if should_apply:
                movement_history.add(movement_key(sid, current, target))
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
                        "guard": "applied",
                        "evidence": dict(decision.get("candidate_evidence", {})) if isinstance(decision.get("candidate_evidence"), dict) else {},
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
    parser.add_argument("--pass2", default="assessments/pass2_comparative", help="Pass2 comparative rankings directory")
    parser.add_argument("--pairwise-evidence", default="outputs/consistency_checks.json", help="Optional prior pairwise evidence JSON")
    parser.add_argument("--model", default="", help="Model for band-seam adjudication")
    parser.add_argument("--reasoning", default="", help="Reasoning effort for band-seam adjudication")
    parser.add_argument("--max-output-tokens", type=int, default=1800, help="Max adjudicator output tokens")
    parser.add_argument("--per-side", type=int, default=6, help="Top lower-band and bottom upper-band candidates per seam")
    parser.add_argument("--max-candidates-per-call", type=int, default=8, help="Max boundary candidates to include in one model call")
    parser.add_argument("--chunk-retries", type=int, default=2, help="Retry count when a chunk omits required candidate decisions")
    parser.add_argument("--max-passes", type=int, default=3, help="Maximum iterative band-seam passes before stopping")
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
    rubric_text = load_file_text(rubric_path)
    outline_text = load_file_text(outline_path)
    pass2_rankings = load_pass2_rankings(Path(args.pass2))
    pairwise_judgments = load_pairwise_judgments(Path(args.pairwise_evidence))

    current_rows = rows
    movement_history: set[str] = set()
    all_boundaries = []
    all_adjudications = []
    all_applied = []
    pass_reports = []
    max_passes = max(1, int(args.max_passes))
    for pass_index in range(1, max_passes + 1):
        boundaries = select_band_seam_candidates(
            current_rows,
            level_bands,
            per_side=max(1, args.per_side),
            margin=max(0.0, args.margin),
        )
        boundaries = add_evidence_to_boundaries(boundaries, current_rows, pass2_rankings, pairwise_judgments)
        for boundary in boundaries:
            boundary["pass_index"] = pass_index
        all_boundaries.extend(boundaries)
        if not boundaries:
            pass_reports.append({"pass_index": pass_index, "boundary_count": 0, "candidate_count": 0, "decision_count": 0, "applied_count": 0})
            break
        adjudications = adjudicate_boundaries(
            boundaries,
            current_rows,
            texts,
            rubric_text,
            outline_text,
            metadata if isinstance(metadata, dict) else {},
            model=model,
            routing=args.routing,
            reasoning=reasoning,
            max_output_tokens=max(512, int(args.max_output_tokens)),
            max_candidates_per_call=max(1, int(args.max_candidates_per_call)),
            chunk_retries=max(0, int(args.chunk_retries)),
        )
        for adjudication in adjudications:
            adjudication["pass_index"] = pass_index
        adjusted_rows, applied = apply_adjudications(
            current_rows,
            level_bands,
            adjudications,
            min_confidence=args.min_confidence,
            movement_history=movement_history,
        )
        all_adjudications.extend(adjudications)
        all_applied.extend({**item, "pass_index": pass_index} for item in applied)
        pass_reports.append(
            {
                "pass_index": pass_index,
                "boundary_count": len(boundaries),
                "candidate_count": sum(int(boundary.get("candidate_count", 0) or 0) for boundary in boundaries),
                "decision_count": sum(len(boundary.get("decisions", [])) for boundary in adjudications),
                "applied_count": len(applied),
            }
        )
        current_rows = adjusted_rows
        if not applied:
            break

    candidates_payload = {
        "generated_at": now_iso(),
        "source_scores": str(scores_path),
        "per_side": max(1, args.per_side),
        "margin": max(0.0, args.margin),
        "max_passes": max_passes,
        "pass_count": len(pass_reports),
        "passes": pass_reports,
        "boundary_count": len(all_boundaries),
        "boundaries": all_boundaries,
    }
    write_json(Path(args.candidates_output), candidates_payload)

    if not all_boundaries:
        write_csv(Path(args.adjusted_output), rows)
        report = {
            "generated_at": now_iso(),
            "status": "no_band_seams",
            "source_scores": str(scores_path),
            "candidate_count": 0,
            "applied_count": 0,
            "pass_count": len(pass_reports),
            "passes": pass_reports,
        }
        write_json(Path(args.adjudication_output), {"generated_at": now_iso(), "boundaries": []})
        write_json(Path(args.report_output), report)
        print(f"Wrote {args.report_output}")
        return 0

    adjusted_rows = current_rows
    applied = all_applied
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
        "max_passes": max_passes,
        "passes": pass_reports,
        "pass2_evidence": str(args.pass2),
        "pairwise_evidence": str(args.pairwise_evidence),
        "boundaries": all_adjudications,
    }
    report = {
        "generated_at": now_iso(),
        "status": "complete",
        "source_scores": str(scores_path),
        "backup_scores": str(backup_path),
        "adjusted_scores": str(args.adjusted_output),
        "pass_count": len(pass_reports),
        "passes": pass_reports,
        "boundary_count": len(all_boundaries),
        "candidate_count": sum(int(boundary.get("candidate_count", 0) or 0) for boundary in all_boundaries),
        "decision_count": sum(len(boundary.get("decisions", [])) for boundary in all_adjudications),
        "applied_count": len(applied),
        "applied": applied,
        "pairwise_checks_needed": [
            item
            for boundary in all_adjudications
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
