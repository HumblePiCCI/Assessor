#!/usr/bin/env python3
import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.assessor_utils import load_file_text, resolve_input_path
    from scripts.assessor_context import load_class_metadata, normalize_genre
    from scripts.global_rerank import run_global_rerank
    from scripts.llm_assessors_core import json_from_text
    from scripts.levels import normalize_level
    from scripts.openai_client import extract_text, responses_create
except ImportError:  # pragma: no cover - Support running as script without package context
    from assessor_utils import load_file_text, resolve_input_path  # pragma: no cover
    from assessor_context import load_class_metadata, normalize_genre  # pragma: no cover
    from global_rerank import run_global_rerank  # pragma: no cover
    from llm_assessors_core import json_from_text  # pragma: no cover
    from levels import normalize_level  # pragma: no cover
    from openai_client import extract_text, responses_create  # pragma: no cover


RESPONSE_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["KEEP", "SWAP"]},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "rationale": {"type": "string"},
        },
        "required": ["decision", "confidence", "rationale"],
        "additionalProperties": False,
    },
}

DEFAULT_BAND_SEAM_REPORT = "outputs/band_seam_report.json"
DEFAULT_EXPANSION_REPORT = "outputs/post_seam_pair_expansion.json"


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def clamp01(value, default=0.0) -> float:
    return max(0.0, min(1.0, num(value, default)))


def load_texts(text_dir: Path) -> dict[str, str]:
    texts = {}
    if not text_dir.exists():
        return texts
    for path in sorted(text_dir.glob("*.txt")):
        texts[path.stem.strip()] = path.read_text(encoding="utf-8", errors="ignore")
    return texts


def normalize_confidence(value) -> str:
    token = str(value or "").strip().lower()
    if token == "high":
        return "high"
    if token in {"med", "medium"}:
        return "medium"
    return "low"


def normalize_decision(value) -> str:
    token = str(value or "").strip().upper()
    return "SWAP" if token == "SWAP" else "KEEP"


def load_pairwise_metadata(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        payload = load_class_metadata(path)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_json(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_pairwise_genre(metadata: dict | None) -> str:
    metadata = metadata if isinstance(metadata, dict) else {}
    raw = (
        metadata.get("genre")
        or metadata.get("assignment_genre")
        or metadata.get("genre_form")
        or metadata.get("assessment_unit")
    )
    return str(normalize_genre(raw) or "").strip().lower()


def genre_specific_pairwise_guidance(genre: str, metadata: dict | None = None) -> str:
    metadata = metadata if isinstance(metadata, dict) else {}
    lines = []
    if genre == "literary_analysis":
        lines.extend(
            [
                "Literary-analysis ranking rules:",
                "- Prioritize the strength of the interpretive claim, the depth of explanation, and how well evidence is connected to the theme or idea.",
                "- Do not over-reward rigid five-paragraph structure, formulaic topic sentences, or plot summary when the analysis is thinner.",
                "- A complete essay with stronger interpretation and better explanation should outrank a more mechanical essay with weaker insight, even if the mechanical essay looks more formulaic.",
            ]
        )
    if str(metadata.get("generated_by", "") or "").strip().lower() == "bootstrap" and genre:
        lines.append(
            "This is a cold-start classroom cohort. Be conservative about structure-only wins; prefer essays with clearer meaning-making and prompt-aligned explanation."
        )
    return "\n".join(lines).strip()


def effective_window(requested_window: int, metadata: dict | None = None) -> int:
    metadata = metadata if isinstance(metadata, dict) else {}
    requested = max(1, int(requested_window))
    genre = resolve_pairwise_genre(metadata)
    if str(metadata.get("generated_by", "") or "").strip().lower() == "bootstrap" and genre == "literary_analysis":
        return max(requested, 4)
    return requested


def seed_percentile(seed_rank: int, student_count: int) -> float:
    if student_count <= 1:
        return 1.0
    return max(0.0, min(1.0, 1.0 - ((int(seed_rank) - 1) / max(student_count - 1, 1))))


def comparison_reach(row: dict, requested_window: int, student_count: int, metadata: dict | None = None) -> int:
    base = effective_window(requested_window, metadata)
    metadata = metadata if isinstance(metadata, dict) else {}
    genre = resolve_pairwise_genre(metadata)
    if str(metadata.get("generated_by", "") or "").strip().lower() != "bootstrap" or genre != "literary_analysis":
        return base
    seed_pct = seed_percentile(int(row.get("seed_rank", 1) or 1), student_count)
    borda_pct = clamp01(row.get("borda_percent"), seed_pct)
    composite_pct = clamp01(row.get("composite_score"), seed_pct)
    divergence = max(abs(seed_pct - borda_pct), abs(seed_pct - composite_pct))
    extra = 0
    if divergence >= 0.6:
        extra = 6
    elif divergence >= 0.4:
        extra = 4
    elif divergence >= 0.25:
        extra = 2
    return min(max(1, student_count - 1), base + extra)


def rank_divergence(row: dict, student_count: int) -> float:
    seed_pct = seed_percentile(int(row.get("seed_rank", 1) or 1), student_count)
    borda_pct = clamp01(row.get("borda_percent"), seed_pct)
    composite_pct = clamp01(row.get("composite_score"), seed_pct)
    return max(abs(seed_pct - borda_pct), abs(seed_pct - composite_pct))


def ids_from_band_seam_report(report: dict) -> set[str]:
    ids = set()
    for item in report.get("applied", []) if isinstance(report.get("applied"), list) else []:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("student_id", "") or "").strip()
        if sid:
            ids.add(sid)
    return ids


def ids_from_band_seam_pairwise_requests(report: dict) -> list[tuple[str, str, str]]:
    requested = []
    for item in report.get("pairwise_checks_needed", []) if isinstance(report.get("pairwise_checks_needed"), list) else []:
        if not isinstance(item, dict):
            continue
        higher = str(item.get("higher_candidate", "") or "").strip()
        lower = str(item.get("lower_candidate", "") or "").strip()
        if higher and lower and higher != lower:
            requested.append((higher, lower, str(item.get("reason", "") or "").strip()))
    return requested


def band_seam_mover_ids(rows: list[dict], band_seam_report: dict | None = None) -> set[str]:
    row_ids = {str(row.get("student_id", "") or "").strip() for row in rows}
    movers = ids_from_band_seam_report(band_seam_report or {}) & row_ids
    for row in rows:
        sid = str(row.get("student_id", "") or "").strip()
        if not sid:
            continue
        pre_level = normalize_level(row.get("pre_band_adjudication_level"))
        adjusted_level = normalize_level(row.get("adjusted_level") or row.get("base_level"))
        if pre_level and adjusted_level and pre_level != adjusted_level:
            movers.add(sid)
    return movers


def aggregate_divergence_mover_ids(rows: list[dict], *, divergence_threshold: float = 0.35) -> set[str]:
    count = max(1, len(rows))
    movers = set()
    for row in rows:
        sid = str(row.get("student_id", "") or "").strip()
        if sid and rank_divergence(row, count) >= float(divergence_threshold):
            movers.add(sid)
    return movers


def has_top_pack_claim(row: dict, *, top_pack_size: int, student_count: int) -> bool:
    if top_pack_size <= 0:
        return False
    top_cutoff = seed_percentile(min(top_pack_size, student_count), student_count)
    seed_pct = seed_percentile(int(row.get("seed_rank", 1) or 1), student_count)
    aggregate_peak = max(seed_pct, clamp01(row.get("borda_percent"), seed_pct), clamp01(row.get("composite_score"), seed_pct))
    return aggregate_peak >= max(0.0, top_cutoff - 0.05)


def post_seam_mover_ids(rows: list[dict], band_seam_report: dict | None = None, *, divergence_threshold: float = 0.35) -> set[str]:
    return band_seam_mover_ids(rows, band_seam_report) | aggregate_divergence_mover_ids(rows, divergence_threshold=divergence_threshold)


def add_pair_spec(specs: dict[tuple[str, str], dict], rows_by_id: dict[str, dict], left_id: str, right_id: str, reason: str, *, detail: str = ""):
    left_id = str(left_id or "").strip()
    right_id = str(right_id or "").strip()
    if not left_id or not right_id or left_id == right_id or left_id not in rows_by_id or right_id not in rows_by_id:
        return
    left = rows_by_id[left_id]
    right = rows_by_id[right_id]
    higher, lower = sorted(
        [left, right],
        key=lambda row: (int(row.get("seed_rank", 0) or 0), str(row.get("student_id", "")).lower()),
    )
    key = tuple(sorted((left_id, right_id)))
    item = specs.setdefault(
        key,
        {
            "higher": higher,
            "lower": lower,
            "selection_reasons": [],
            "selection_details": [],
        },
    )
    if reason and reason not in item["selection_reasons"]:
        item["selection_reasons"].append(reason)
    if detail and detail not in item["selection_details"]:
        item["selection_details"].append(detail)


def build_prompt(
    rubric: str,
    outline: str,
    higher: dict,
    lower: dict,
    higher_text: str,
    lower_text: str,
    *,
    genre: str = "",
    metadata: dict | None = None,
    selection_reasons: list[str] | None = None,
    selection_details: list[str] | None = None,
) -> str:
    extra_guidance = genre_specific_pairwise_guidance(genre, metadata)
    guidance_block = f"\nAdditional ranking guidance:\n{extra_guidance}\n" if extra_guidance else ""
    reason_text = ", ".join(selection_reasons or []) or "seed_window"
    details = "\n".join(f"- {detail}" for detail in (selection_details or []) if detail)
    details_block = f"\nSelection details:\n{details}\n" if details else ""
    return f"""You are collecting pairwise ranking evidence for a global reranker.

Rubric:
{rubric}

Assignment Outline:
{outline}
{guidance_block}

Current seed order:
- Higher seed essay: {higher['student_id']} (seed rank {higher['seed_rank']}, level {higher['level'] or 'unknown'}, rubric {higher['rubric_after_penalty_percent']:.2f}%, Borda {clamp01(higher.get('borda_percent'), 0.0):.4f}, composite {num(higher.get('composite_score'), 0.0):.4f})
- Lower seed essay: {lower['student_id']} (seed rank {lower['seed_rank']}, level {lower['level'] or 'unknown'}, rubric {lower['rubric_after_penalty_percent']:.2f}%, Borda {clamp01(lower.get('borda_percent'), 0.0):.4f}, composite {num(lower.get('composite_score'), 0.0):.4f})

Why this pair is being checked:
{reason_text}
{details_block}

Essay A (currently seeded above Essay B): {higher['student_id']}
{higher_text}

Essay B (currently seeded below Essay A): {lower['student_id']}
{lower_text}

Decide whether the seed order should stay as-is or flip for the final ranking.

Return ONLY JSON:
{{
  "decision": "KEEP" | "SWAP",
  "confidence": "low" | "medium" | "high",
  "rationale": "short justification"
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


def build_repair_prompt(raw_text: str) -> str:
    return f"""The prior response was supposed to be JSON but was malformed.

Return ONLY valid JSON in this exact format:
{{
  "decision": "KEEP" | "SWAP",
  "confidence": "low" | "medium" | "high",
  "rationale": "short justification"
}}

Malformed response:
{raw_text}
"""


def rank_key(rows: list[dict]) -> str:
    if not rows:
        return ""
    for key in ("seed_rank", "consensus_rank", "final_rank", "consistency_rank"):
        if key in rows[0]:
            return key
    return ""


def prepare_rows(rows: list[dict]) -> list[dict]:
    seed_key = rank_key(rows)
    ordered = sorted(
        [dict(row) for row in rows if str(row.get("student_id", "")).strip()],
        key=lambda row: (
            int(num(row.get(seed_key), 0.0) or 0.0),
            str(row.get("student_id", "")).lower(),
        ),
    )
    prepared = []
    for idx, row in enumerate(ordered, start=1):
        prepared.append(
            {
                "student_id": str(row.get("student_id", "")).strip(),
                "seed_rank": int(num(row.get("seed_rank") or row.get(seed_key), idx) or idx),
                "adjusted_level": row.get("adjusted_level", ""),
                "base_level": row.get("base_level", ""),
                "level": normalize_level(row.get("adjusted_level") or row.get("base_level")) or "",
                "rubric_after_penalty_percent": num(
                    row.get("rubric_after_penalty_percent"),
                    num(row.get("rubric_mean_percent"), 0.0),
                ),
                "borda_percent": clamp01(row.get("borda_percent"), 0.0),
                "composite_score": num(row.get("composite_score"), 0.0),
                "source": dict(row),
            }
        )
    return prepared


def select_pair_specs(
    rows: list[dict],
    window: int,
    metadata: dict | None = None,
    *,
    top_pack_size: int = 0,
    large_mover_window: int = 0,
    band_seam_report: dict | None = None,
    large_mover_divergence: float = 0.35,
) -> list[dict]:
    ordered = list(rows)
    specs = {}
    rows_by_id = {row["student_id"]: row for row in ordered}
    width = max(1, int(window))
    count = len(ordered)
    reach = {
        row["student_id"]: comparison_reach(row, width, count, metadata)
        for row in ordered
    }
    for idx, higher in enumerate(ordered):
        for lower_idx in range(idx + 1, len(ordered)):
            lower = ordered[lower_idx]
            gap = lower_idx - idx
            if gap > max(reach.get(higher["student_id"], width), reach.get(lower["student_id"], width)):
                continue
            reason = "seed_window" if gap <= width else "aggregate_divergence_reach"
            add_pair_spec(
                specs,
                rows_by_id,
                higher["student_id"],
                lower["student_id"],
                reason,
                detail=f"seed rank gap {gap}; reach {max(reach.get(higher['student_id'], width), reach.get(lower['student_id'], width))}",
            )

    top_count = min(max(0, int(top_pack_size)), count)
    for idx, higher in enumerate(ordered[:top_count]):
        for lower in ordered[idx + 1 : top_count]:
            add_pair_spec(
                specs,
                rows_by_id,
                higher["student_id"],
                lower["student_id"],
                "top_pack",
                detail=f"both essays are in the top {top_count} seed positions after band-seam adjudication",
            )

    seam_movers = band_seam_mover_ids(ordered, band_seam_report or {})
    aggregate_movers = aggregate_divergence_mover_ids(ordered, divergence_threshold=large_mover_divergence)
    movers = seam_movers | aggregate_movers
    top_pack_movers = {
        sid
        for sid in movers
        if sid in seam_movers
        or has_top_pack_claim(rows_by_id.get(sid, {}), top_pack_size=top_count, student_count=count)
    }
    mover_window = max(0, int(large_mover_window))
    index_by_id = {row["student_id"]: idx for idx, row in enumerate(ordered)}
    top_ids = [row["student_id"] for row in ordered[:top_count]]
    for mover_id in sorted(top_pack_movers, key=lambda sid: index_by_id.get(sid, count)):
        mover_idx = index_by_id.get(mover_id)
        if mover_idx is None:
            continue
        for top_id in top_ids:
            if top_id != mover_id:
                add_pair_spec(
                    specs,
                    rows_by_id,
                    mover_id,
                    top_id,
                    "large_mover_top_pack",
                    detail=f"{mover_id} is a post-seam or aggregate-divergence mover checked against the top pack",
                )
    for mover_id in sorted(movers, key=lambda sid: index_by_id.get(sid, count)):
        mover_idx = index_by_id.get(mover_id)
        if mover_idx is None:
            continue
        if mover_window:
            start = max(0, mover_idx - mover_window)
            stop = min(count, mover_idx + mover_window + 1)
            for other in ordered[start:stop]:
                if other["student_id"] != mover_id:
                    add_pair_spec(
                        specs,
                        rows_by_id,
                        mover_id,
                        other["student_id"],
                        "large_mover_neighborhood",
                        detail=f"{mover_id} is checked within +/-{mover_window} seed positions",
                    )

    for higher_id, lower_id, reason in ids_from_band_seam_pairwise_requests(band_seam_report or {}):
        add_pair_spec(
            specs,
            rows_by_id,
            higher_id,
            lower_id,
            "band_seam_requested",
            detail=reason or "band seam adjudicator requested this direct comparison",
        )

    return list(specs.values())


def select_pairs(rows: list[dict], window: int, metadata: dict | None = None) -> list[tuple[dict, dict]]:
    return [(item["higher"], item["lower"]) for item in select_pair_specs(rows, window, metadata)]


def collect_judgments(
    rows: list[dict],
    texts: dict[str, str],
    rubric: str,
    outline: str,
    *,
    model: str,
    routing: str,
    reasoning: str,
    max_output_tokens: int,
    window: int,
    metadata: dict | None = None,
    top_pack_size: int = 0,
    large_mover_window: int = 0,
    band_seam_report: dict | None = None,
    large_mover_divergence: float = 0.35,
) -> list[dict]:
    judgments = []
    genre = resolve_pairwise_genre(metadata)
    pair_specs = select_pair_specs(
        rows,
        window,
        metadata,
        top_pack_size=top_pack_size,
        large_mover_window=large_mover_window,
        band_seam_report=band_seam_report,
        large_mover_divergence=large_mover_divergence,
    )
    for spec in pair_specs:
        higher = spec["higher"]
        lower = spec["lower"]
        prompt = build_prompt(
            rubric,
            outline,
            higher,
            lower,
            texts.get(higher["student_id"], ""),
            texts.get(lower["student_id"], ""),
            genre=genre,
            metadata=metadata,
            selection_reasons=spec.get("selection_reasons", []),
            selection_details=spec.get("selection_details", []),
        )
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
                messages=[{"role": "user", "content": build_repair_prompt(content)}],
                temperature=0.0,
                reasoning="low",
                routing_path=routing,
                text_format=RESPONSE_FORMAT,
                max_output_tokens=max_output_tokens,
            )
            content = extract_text(repair_response)
            parsed = parse_json(content)
            response = repair_response
        decision = normalize_decision(parsed.get("decision"))
        confidence = normalize_confidence(parsed.get("confidence"))
        rationale = str(parsed.get("rationale") or parsed.get("reason") or "").strip()
        judgments.append(
            {
                "pair": [higher["student_id"], lower["student_id"]],
                "seed_order": {
                    "higher": higher["student_id"],
                    "lower": lower["student_id"],
                    "higher_rank": int(higher["seed_rank"]),
                    "lower_rank": int(lower["seed_rank"]),
                },
                "seed_features": {
                    "higher": {
                        "student_id": higher["student_id"],
                        "seed_rank": int(higher["seed_rank"]),
                        "level": higher["level"],
                        "rubric_after_penalty_percent": round(float(higher["rubric_after_penalty_percent"]), 6),
                        "composite_score": round(float(higher["composite_score"]), 6),
                        "borda_percent": round(float(higher["borda_percent"]), 6),
                    },
                    "lower": {
                        "student_id": lower["student_id"],
                        "seed_rank": int(lower["seed_rank"]),
                        "level": lower["level"],
                        "rubric_after_penalty_percent": round(float(lower["rubric_after_penalty_percent"]), 6),
                        "composite_score": round(float(lower["composite_score"]), 6),
                        "borda_percent": round(float(lower["borda_percent"]), 6),
                    },
                },
                "selection_reasons": list(spec.get("selection_reasons", [])),
                "selection_details": list(spec.get("selection_details", [])),
                "decision": decision,
                "confidence": confidence,
                "rationale": rationale,
                "model_metadata": {
                    "requested_model": model,
                    "response_model": response.get("model") or model,
                    "routing_path": routing,
                    "repair_used": repair_used,
                    "reasoning": reasoning,
                    "temperature": 0.0,
                    "cached": bool(response.get("cached", False)),
                    "usage": response.get("usage", {}),
                },
            }
        )
    return judgments


def summarize_pair_reasons(judgments: list[dict]) -> dict:
    counts = Counter()
    for judgment in judgments:
        for reason in judgment.get("selection_reasons", []) if isinstance(judgment.get("selection_reasons"), list) else []:
            counts[str(reason)] += 1
    return dict(sorted(counts.items()))


def write_expansion_report(
    path: Path,
    rows: list[dict],
    judgments: list[dict],
    *,
    top_pack_size: int,
    large_mover_window: int,
    band_seam_report_path: str,
    large_mover_divergence: float,
    band_seam_report: dict,
):
    path.parent.mkdir(parents=True, exist_ok=True)
    seam_movers = band_seam_mover_ids(rows, band_seam_report)
    aggregate_movers = aggregate_divergence_mover_ids(rows, divergence_threshold=large_mover_divergence)
    mover_ids = post_seam_mover_ids(rows, band_seam_report, divergence_threshold=large_mover_divergence)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "top_pack_size": int(top_pack_size),
        "large_mover_window": int(large_mover_window),
        "large_mover_divergence": float(large_mover_divergence),
        "band_seam_report": band_seam_report_path,
        "band_seam_movers": sorted(seam_movers),
        "aggregate_divergence_movers": sorted(aggregate_movers),
        "post_seam_movers": sorted(mover_ids),
        "comparison_count": len(judgments),
        "reason_counts": summarize_pair_reasons(judgments),
        "pairs": [
            {
                "pair": list(judgment.get("pair", [])),
                "seed_order": dict(judgment.get("seed_order", {})),
                "selection_reasons": list(judgment.get("selection_reasons", [])),
                "selection_details": list(judgment.get("selection_details", [])),
            }
            for judgment in judgments
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def write_judgment_payload(
    path: Path,
    rows: list[dict],
    judgments: list[dict],
    *,
    model: str,
    routing: str,
    window: int,
    source_scores: str,
    top_pack_size: int = 0,
    large_mover_window: int = 0,
    band_seam_report: str = "",
):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_scores": source_scores,
        "model": model,
        "routing": routing,
        "comparison_window": int(window),
        "post_seam_expansion": {
            "top_pack_size": int(top_pack_size),
            "large_mover_window": int(large_mover_window),
            "band_seam_report": band_seam_report,
            "reason_counts": summarize_pair_reasons(judgments),
        },
        "seed_student_count": len(rows),
        "checks": judgments,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect pairwise evidence for global ranking consistency.")
    parser.add_argument("--scores", default="outputs/consensus_scores.csv", help="Seed ranking CSV")
    parser.add_argument("--texts", default="processing/normalized_text", help="Essay text dir")
    parser.add_argument("--rubric", default="inputs/rubric.md", help="Rubric file")
    parser.add_argument("--outline", default="inputs/assignment_outline.md", help="Assignment outline file")
    parser.add_argument("--class-metadata", default="inputs/class_metadata.json", help="Class metadata JSON")
    parser.add_argument("--routing", default="config/llm_routing.json", help="Routing config")
    parser.add_argument("--model", default="gpt-5.4-mini", help="Model for pairwise checks")
    parser.add_argument("--reasoning", default="low", help="Reasoning effort for pairwise checks")
    parser.add_argument("--window", type=int, default=2, help="How many lower-seeded neighbors to compare against each essay")
    parser.add_argument("--top-pack-size", type=int, default=6, help="Fully compare the top N seeds after band-seam adjudication")
    parser.add_argument("--large-mover-window", type=int, default=5, help="Neighborhood radius for post-seam and aggregate-divergence movers")
    parser.add_argument("--large-mover-divergence", type=float, default=0.35, help="Seed-vs-aggregate divergence threshold for large-mover expansion")
    parser.add_argument("--band-seam-report", default=DEFAULT_BAND_SEAM_REPORT, help="Band seam report used for post-seam pair expansion")
    parser.add_argument("--expansion-report", default=DEFAULT_EXPANSION_REPORT, help="Pair expansion audit artifact JSON")
    parser.add_argument("--disable-post-seam-expansion", action="store_true", help="Disable top-pack and large-mover pair expansion")
    parser.add_argument("--max-output-tokens", type=int, default=300, help="Max model output tokens")
    parser.add_argument("--output", default="outputs/consistency_checks.json", help="Output JSON")
    parser.add_argument("--apply", action="store_true", help="Compatibility mode: collect evidence, then run the global reranker")
    parser.add_argument("--rerank-output", default="outputs/final_order.csv", help="Final reranked CSV output")
    parser.add_argument("--matrix-output", default="outputs/pairwise_matrix.json", help="Pairwise matrix JSON output")
    parser.add_argument("--scores-output", default="outputs/rerank_scores.csv", help="Rerank score CSV output")
    parser.add_argument("--report-output", default="outputs/consistency_report.json", help="Consistency report JSON output")
    parser.add_argument("--legacy-output", default="outputs/consistency_adjusted.csv", help="Compatibility CSV output")
    parser.add_argument("--config", default="config/marking_config.json", help="Marking config JSON")
    parser.add_argument("--local-prior", default="outputs/local_teacher_prior.json", help="Local teacher prior JSON")
    args = parser.parse_args()

    scores_path = Path(args.scores)
    if not scores_path.exists():
        print(f"Missing scores file: {scores_path}")
        return 1
    seed_rows = prepare_rows(load_rows(scores_path))
    if not seed_rows:
        print("No scores to verify.")
        return 1

    texts = load_texts(Path(args.texts))
    rubric_path = resolve_input_path(Path(args.rubric), "rubric")
    outline_path = resolve_input_path(Path(args.outline), "assignment_outline")
    metadata = load_pairwise_metadata(Path(args.class_metadata))
    rubric = load_file_text(rubric_path)
    outline = load_file_text(outline_path)
    expansion_enabled = not args.disable_post_seam_expansion
    band_seam_report_path = Path(args.band_seam_report)
    if args.band_seam_report == DEFAULT_BAND_SEAM_REPORT and scores_path.parent.name != "outputs":
        band_seam_report_path = scores_path.parent / "band_seam_report.json"
    band_seam_report = load_json(band_seam_report_path) if expansion_enabled else {}
    top_pack_size = max(0, int(args.top_pack_size)) if expansion_enabled else 0
    large_mover_window = max(0, int(args.large_mover_window)) if expansion_enabled else 0

    judgments = collect_judgments(
        seed_rows,
        texts,
        rubric,
        outline,
        model=args.model,
        routing=args.routing,
        reasoning=args.reasoning,
        max_output_tokens=max(64, int(args.max_output_tokens)),
        window=max(1, int(args.window)),
        metadata=metadata,
        top_pack_size=top_pack_size,
        large_mover_window=large_mover_window,
        band_seam_report=band_seam_report,
        large_mover_divergence=max(0.0, float(args.large_mover_divergence)),
    )
    out_path = Path(args.output)
    expansion_report_path = Path(args.expansion_report)
    if args.expansion_report == DEFAULT_EXPANSION_REPORT and out_path.parent.name != "outputs":
        expansion_report_path = out_path.parent / "post_seam_pair_expansion.json"
    write_judgment_payload(
        out_path,
        seed_rows,
        judgments,
        model=args.model,
        routing=args.routing,
        window=effective_window(max(1, int(args.window)), metadata),
        source_scores=str(scores_path),
        top_pack_size=top_pack_size,
        large_mover_window=large_mover_window,
        band_seam_report=str(band_seam_report_path) if expansion_enabled else "",
    )
    if expansion_enabled:
        write_expansion_report(
            expansion_report_path,
            seed_rows,
            judgments,
            top_pack_size=top_pack_size,
            large_mover_window=large_mover_window,
            band_seam_report_path=str(band_seam_report_path),
            large_mover_divergence=max(0.0, float(args.large_mover_divergence)),
            band_seam_report=band_seam_report,
        )
    print(f"Pairwise judgments saved to {out_path}")

    if args.apply:
        run_global_rerank(
            scores_path=scores_path,
            judgments_path=out_path,
            config_path=Path(args.config),
            local_prior_path=Path(args.local_prior),
            final_order_path=Path(args.rerank_output),
            matrix_output_path=Path(args.matrix_output),
            score_output_path=Path(args.scores_output),
            report_output_path=Path(args.report_output),
            legacy_output_path=Path(args.legacy_output),
            iterations=300,
            learning_rate=0.18,
            regularization=0.75,
            low_confidence_max_displacement=1,
            medium_confidence_max_displacement=3,
            high_confidence_max_displacement=999999,
            max_cross_level_gap=1,
            max_cross_rubric_gap=2.0,
            min_crossing_margin=1.5,
            hard_evidence_margin=1.5,
        )
        print(f"Global rerank saved to {args.rerank_output}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
