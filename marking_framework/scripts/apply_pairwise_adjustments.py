#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path


CONFIDENCE_ORDER = {"low": 0, "med": 1, "high": 2}


def load_rows(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply pairwise review decisions to ranking")
    parser.add_argument("--input", default="outputs/consensus_scores.csv", help="Ranking CSV input")
    parser.add_argument("--decisions", default="assessments/final_review_pairs.json", help="Pair decisions JSON")
    parser.add_argument("--output", default="outputs/final_order.csv", help="Final ranking CSV output")
    parser.add_argument("--min-confidence", default="med", help="Minimum confidence to auto-apply swaps (low|med|high)")
    args = parser.parse_args()

    input_path = Path(args.input)
    decisions_path = Path(args.decisions)

    if not input_path.exists():
        print(f"Error: input not found: {input_path}")
        return 1
    if not decisions_path.exists():
        print(f"Error: decisions not found: {decisions_path}")
        return 1

    rows = load_rows(input_path)
    if not rows:
        print("Error: no rows in input file")
        return 1

    rank_key = "final_rank" if "final_rank" in rows[0] else "consensus_rank"
    rows.sort(key=lambda r: int(r.get(rank_key, 0)))

    decisions = json.loads(decisions_path.read_text(encoding="utf-8")).get("pairs", [])

    min_conf = args.min_confidence.strip().lower()
    if min_conf == "medium":
        min_conf = "med"
    if min_conf not in CONFIDENCE_ORDER:
        print("Invalid --min-confidence. Use low, med, or high.")
        return 1

    applied_swaps = []
    flagged_pairs = []

    # Apply swaps sequentially from top to bottom
    for i, pair in enumerate(decisions):
        action = pair.get("decision", {}).get("action", "keep")
        confidence = pair.get("decision", {}).get("confidence", "low").strip().lower()
        if confidence == "medium":
            confidence = "med"
        if confidence not in CONFIDENCE_ORDER:
            confidence = "low"
        if action == "swap" and CONFIDENCE_ORDER[confidence] >= CONFIDENCE_ORDER[min_conf]:
            if i < len(rows) - 1:
                rows[i], rows[i + 1] = rows[i + 1], rows[i]
                applied_swaps.append(pair)
        elif action == "swap":
            flagged_pairs.append(pair)

    # Assign final ranks
    for idx, row in enumerate(rows, start=1):
        row["final_rank"] = idx

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Write a human-readable summary
    summary_path = output_path.parent / "final_ranking.md"
    with summary_path.open("w", encoding="utf-8") as f:
        f.write("Final Ranking (After Pairwise Review)\n\n")
        for row in rows:
            f.write(f"{row['final_rank']}. {row['student_id']}\n")

    log_path = output_path.parent / "final_review_log.md"
    with log_path.open("w", encoding="utf-8") as f:
        f.write("Final Pairwise Review Decisions\n\n")
        for pair in decisions:
            left = pair.get("left", {}).get("student_id", "")
            right = pair.get("right", {}).get("student_id", "")
            action = pair.get("decision", {}).get("action", "keep")
            reason = pair.get("decision", {}).get("reason", "")
            confidence = pair.get("decision", {}).get("confidence", "low")
            f.write(f"- {left} vs {right}: {action} ({confidence}) | {reason}\n")

    flagged_path = output_path.parent / "final_review_flagged.md"
    with flagged_path.open("w", encoding="utf-8") as f:
        f.write("Flagged Pairwise Decisions (Not Auto-Applied)\n\n")
        if not flagged_pairs:
            f.write("None.\n")
        else:
            for pair in flagged_pairs:
                left = pair.get("left", {}).get("student_id", "")
                right = pair.get("right", {}).get("student_id", "")
                reason = pair.get("decision", {}).get("reason", "")
                confidence = pair.get("decision", {}).get("confidence", "low")
                f.write(f"- {left} vs {right}: swap ({confidence}) | {reason}\n")

    print(f"Wrote final ranking: {output_path}")
    print(f"Auto-applied swaps: {len(applied_swaps)} (min confidence: {min_conf})")
    if flagged_pairs:
        print(f"Flagged pairs (manual review): {flagged_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
