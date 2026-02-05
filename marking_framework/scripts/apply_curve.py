#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def round_grade(value: float, mode: str) -> int:
    if mode == "floor":
        return int(value // 1)
    if mode == "ceil":
        return int(-(-value // 1))
    return int(round(value))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to marking_config.json")
    parser.add_argument("--input", required=True, help="Consensus CSV input")
    parser.add_argument("--output", required=True, help="Grade curve CSV output")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    curve = config.get("curve", {})
    top = curve.get("top", 92)
    bottom = curve.get("bottom", 58)
    rounding = curve.get("rounding", "nearest")

    rows = []
    with Path(args.input).open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return 0

    # Ensure rows are ordered by consensus_rank if present
    if "consensus_rank" in rows[0]:
        rows.sort(key=lambda r: int(r["consensus_rank"]))

    n = len(rows)
    for idx, row in enumerate(rows):
        if n == 1:
            grade = top
        else:
            grade = top - (top - bottom) * (idx / (n - 1))
        row["final_grade"] = round_grade(grade, rounding)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
