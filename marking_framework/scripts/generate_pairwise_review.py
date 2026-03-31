#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path


def load_rows(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate adjacent pairs for final review")
    parser.add_argument("--input", default="outputs/consensus_scores.csv", help="Ranking CSV input")
    parser.add_argument("--output", default="assessments/final_review_pairs.json", help="Pairs JSON output")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input not found: {input_path}")
        return 1

    rows = load_rows(input_path)
    if not rows:
        print("Error: no rows in input file")
        return 1

    rank_key = "final_rank" if "final_rank" in rows[0] else "consensus_rank"
    rows.sort(key=lambda r: int(r.get(rank_key, 0)))

    pairs = []
    for i in range(len(rows) - 1):
        left = rows[i]
        right = rows[i + 1]
        pair = {
            "pair_id": i + 1,
            "left": {
                "student_id": left.get("student_id"),
                "rank": left.get(rank_key),
                "rubric_mean_percent": left.get("rubric_mean_percent"),
                "rubric_after_penalty_percent": left.get("rubric_after_penalty_percent"),
                "conventions_mistake_rate_percent": left.get("conventions_mistake_rate_percent"),
                "level_with_modifier": left.get("level_with_modifier"),
                "composite_score": left.get("composite_score"),
                "flags": left.get("flags"),
            },
            "right": {
                "student_id": right.get("student_id"),
                "rank": right.get(rank_key),
                "rubric_mean_percent": right.get("rubric_mean_percent"),
                "rubric_after_penalty_percent": right.get("rubric_after_penalty_percent"),
                "conventions_mistake_rate_percent": right.get("conventions_mistake_rate_percent"),
                "level_with_modifier": right.get("level_with_modifier"),
                "composite_score": right.get("composite_score"),
                "flags": right.get("flags"),
            },
            "decision": {
                "action": "keep",  # keep | swap
                "reason": ""
            }
        }
        pairs.append(pair)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"pairs": pairs}, indent=2), encoding="utf-8")
    print(f"Wrote pairwise review file: {output_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
