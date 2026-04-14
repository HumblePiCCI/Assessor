#!/usr/bin/env python3
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.assessor_utils import load_file_text, resolve_input_path
    from scripts.global_rerank import run_global_rerank
    from scripts.levels import normalize_level
    from scripts.openai_client import extract_text, responses_create
except ImportError:  # pragma: no cover - Support running as script without package context
    from assessor_utils import load_file_text, resolve_input_path  # pragma: no cover
    from global_rerank import run_global_rerank  # pragma: no cover
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


def build_prompt(rubric: str, outline: str, higher: dict, lower: dict, higher_text: str, lower_text: str) -> str:
    return f"""You are collecting pairwise ranking evidence for a global reranker.

Rubric:
{rubric}

Assignment Outline:
{outline}

Current seed order:
- Higher seed essay: {higher['student_id']} (seed rank {higher['seed_rank']}, level {higher['level'] or 'unknown'}, rubric {higher['rubric_after_penalty_percent']:.2f}%)
- Lower seed essay: {lower['student_id']} (seed rank {lower['seed_rank']}, level {lower['level'] or 'unknown'}, rubric {lower['rubric_after_penalty_percent']:.2f}%)

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
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
    raise ValueError("Invalid JSON response")


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
                "composite_score": num(row.get("composite_score"), 0.0),
                "source": dict(row),
            }
        )
    return prepared


def select_pairs(rows: list[dict], window: int) -> list[tuple[dict, dict]]:
    ordered = list(rows)
    pairs = []
    seen = set()
    width = max(1, int(window))
    for idx, higher in enumerate(ordered):
        for offset in range(1, width + 1):
            lower_idx = idx + offset
            if lower_idx >= len(ordered):
                break
            lower = ordered[lower_idx]
            token = (higher["student_id"], lower["student_id"])
            if token in seen:
                continue
            seen.add(token)
            pairs.append((higher, lower))
    return pairs


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
) -> list[dict]:
    judgments = []
    for higher, lower in select_pairs(rows, window):
        prompt = build_prompt(
            rubric,
            outline,
            higher,
            lower,
            texts.get(higher["student_id"], ""),
            texts.get(lower["student_id"], ""),
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
        parsed = parse_json(content)
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
                    },
                    "lower": {
                        "student_id": lower["student_id"],
                        "seed_rank": int(lower["seed_rank"]),
                        "level": lower["level"],
                        "rubric_after_penalty_percent": round(float(lower["rubric_after_penalty_percent"]), 6),
                        "composite_score": round(float(lower["composite_score"]), 6),
                    },
                },
                "decision": decision,
                "confidence": confidence,
                "rationale": rationale,
                "model_metadata": {
                    "requested_model": model,
                    "response_model": response.get("model") or model,
                    "routing_path": routing,
                    "reasoning": reasoning,
                    "temperature": 0.0,
                    "cached": bool(response.get("cached", False)),
                    "usage": response.get("usage", {}),
                },
            }
        )
    return judgments


def write_judgment_payload(path: Path, rows: list[dict], judgments: list[dict], *, model: str, routing: str, window: int, source_scores: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_scores": source_scores,
        "model": model,
        "routing": routing,
        "comparison_window": int(window),
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
    parser.add_argument("--routing", default="config/llm_routing.json", help="Routing config")
    parser.add_argument("--model", default="gpt-5.4-mini", help="Model for pairwise checks")
    parser.add_argument("--reasoning", default="low", help="Reasoning effort for pairwise checks")
    parser.add_argument("--window", type=int, default=2, help="How many lower-seeded neighbors to compare against each essay")
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
    rubric = load_file_text(rubric_path)
    outline = load_file_text(outline_path)

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
    )
    out_path = Path(args.output)
    write_judgment_payload(
        out_path,
        seed_rows,
        judgments,
        model=args.model,
        routing=args.routing,
        window=max(1, int(args.window)),
        source_scores=str(scores_path),
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
