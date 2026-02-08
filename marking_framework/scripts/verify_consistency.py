#!/usr/bin/env python3
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.assessor_utils import load_file_text, resolve_input_path
    from scripts.openai_client import extract_text, responses_create
except ImportError:  # pragma: no cover - Support running as script without package context
    from assessor_utils import load_file_text, resolve_input_path  # pragma: no cover
    from openai_client import extract_text, responses_create  # pragma: no cover


def load_rows(path: Path) -> list:
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_texts(text_dir: Path) -> dict:
    texts = {}
    for path in sorted(text_dir.glob("*.txt")):
        texts[path.stem.strip()] = path.read_text(encoding="utf-8", errors="ignore")
    return texts


def build_prompt(rubric: str, outline: str, a_id: str, a_text: str, b_id: str, b_text: str) -> str:
    return f"""You are checking ranking consistency.

Rubric:
{rubric}

Assignment Outline:
{outline}

Essay A (currently ranked higher): {a_id}
{a_text}

Essay B (currently ranked lower): {b_id}
{b_text}

Decide if the ordering is correct.
Return ONLY JSON:
{{
  \"decision\": \"KEEP\" | \"SWAP\",
  \"confidence\": \"low\" | \"medium\" | \"high\",
  \"reason\": \"short explanation\"
}}
"""


def parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
    raise ValueError("Invalid JSON response")


def apply_swaps(order: list, decisions: list, min_confidence: str) -> list:
    ranking = list(order)
    conf_rank = {"low": 0, "medium": 1, "high": 2}
    threshold = conf_rank.get(min_confidence, 1)
    index = {sid: i for i, sid in enumerate(ranking)}
    for item in decisions:
        if item.get("decision") != "SWAP":
            continue
        if conf_rank.get(item.get("confidence", "low"), 0) < threshold:
            continue
        a_id, b_id = item.get("pair", [])
        if a_id not in index or b_id not in index:
            continue
        i, j = index[a_id], index[b_id]
        if abs(i - j) != 1:
            continue
        ranking[i], ranking[j] = ranking[j], ranking[i]
        index = {sid: k for k, sid in enumerate(ranking)}
    return ranking


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify adjacent ranking consistency")
    parser.add_argument("--scores", default="outputs/consensus_scores.csv", help="Consensus scores CSV")
    parser.add_argument("--texts", default="processing/normalized_text", help="Essay text dir")
    parser.add_argument("--rubric", default="inputs/rubric.md", help="Rubric file")
    parser.add_argument("--outline", default="inputs/assignment_outline.md", help="Assignment outline file")
    parser.add_argument("--routing", default="config/llm_routing.json", help="Routing config")
    parser.add_argument("--model", default="gpt-5.2", help="Model for consistency check")
    parser.add_argument("--output", default="outputs/consistency_checks.json", help="Output JSON")
    parser.add_argument("--apply", action="store_true", help="Apply swaps to produce adjusted ranking")
    parser.add_argument("--min-confidence", default="medium", help="Min confidence to apply swap")
    args = parser.parse_args()

    scores_path = Path(args.scores)
    if not scores_path.exists():
        print(f"Missing scores file: {scores_path}")
        return 1
    rows = load_rows(scores_path)
    if not rows:
        print("No scores to verify.")
        return 1
    rows.sort(key=lambda r: int(r.get("consensus_rank", 0) or 0))
    texts = load_texts(Path(args.texts))
    rubric_path = resolve_input_path(Path(args.rubric), "rubric")
    outline_path = resolve_input_path(Path(args.outline), "assignment_outline")
    rubric = load_file_text(rubric_path)
    outline = load_file_text(outline_path)

    decisions = []
    for idx in range(len(rows) - 1):
        a = rows[idx]
        b = rows[idx + 1]
        a_id = a["student_id"]
        b_id = b["student_id"]
        prompt = build_prompt(rubric, outline, a_id, texts.get(a_id, ""), b_id, texts.get(b_id, ""))
        response = responses_create(
            model=args.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            reasoning="low",
            routing_path=args.routing,
        )
        content = extract_text(response)
        parsed = parse_json(content)
        decisions.append({
            "pair": [a_id, b_id],
            "decision": parsed.get("decision", "KEEP"),
            "confidence": parsed.get("confidence", "low"),
            "reason": parsed.get("reason", ""),
        })

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": decisions,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Consistency checks saved to {out_path}")

    if args.apply:
        order = [row["student_id"] for row in rows]
        adjusted = apply_swaps(order, decisions, args.min_confidence)
        adjusted_rows = []
        index = {sid: i for i, sid in enumerate(adjusted)}
        for row in rows:
            row = dict(row)
            row["consistency_rank"] = index[row["student_id"]] + 1
            adjusted_rows.append(row)
        adjusted_rows.sort(key=lambda r: r["consistency_rank"])
        out_csv = out_path.with_name("consistency_adjusted.csv")
        with out_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(adjusted_rows[0].keys()))
            writer.writeheader()
            writer.writerows(adjusted_rows)
        print(f"Adjusted ranking saved to {out_csv}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
