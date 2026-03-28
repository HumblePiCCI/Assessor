#!/usr/bin/env python3
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

try:
    from scripts.apply_curve import calculate_curve_rows, round_grade, sort_rows
except ImportError:  # pragma: no cover - Support running as a script
    from apply_curve import calculate_curve_rows, round_grade, sort_rows  # pragma: no cover


DEFAULT_INPUTS = (
    Path("outputs/final_order.csv"),
    Path("outputs/consistency_adjusted.csv"),
    Path("outputs/consensus_scores.csv"),
)


def display_ranking_summary(rows, limit=10):
    print("\n" + "=" * 78)
    print("CONSENSUS RANKING SUMMARY")
    print("=" * 78)
    print(f"{'Rank':<6} {'Student ID':<28} {'Rubric %':<10} {'Conv %':<10} {'Flags':<20}")
    print("-" * 78)
    for row in rows[:limit]:
        rank = row.get("final_rank") or row.get("consistency_rank") or row.get("consensus_rank") or ""
        print(
            f"{rank:<6} {row.get('student_id',''):<28} "
            f"{row.get('rubric_mean_percent',''):<10} {row.get('conventions_mistake_rate_percent',''):<10} "
            f"{row.get('flags',''):<20}"
        )
    if len(rows) > limit:
        print(f"... ({len(rows) - limit} more students)")
    print()


def preview_curve(rows, top, bottom, rounding, config=None):
    config_data = dict(config or {})
    config_data["curve"] = dict(config_data.get("curve", {}))
    config_data["curve"]["top"] = top
    config_data["curve"]["bottom"] = bottom
    config_data["curve"]["rounding"] = rounding
    graded_rows, meta = calculate_curve_rows(rows, config_data, top=top, bottom=bottom, rounding=rounding)
    grades = [int(row["final_grade"]) for row in graded_rows]
    if not grades:
        return []

    print(
        f"\nCURVE PREVIEW (top={top}, bottom={bottom}, rounding={rounding}, "
        f"profile={meta['profile']}, rank={meta['rank_key'] or 'input-order'})"
    )
    print("-" * 60)
    print(f"Highest grade: {grades[0]}")
    print(f"Median grade: {grades[len(grades) // 2]}")
    print(f"Lowest grade: {grades[-1]}")
    print(f"Mean: {sum(grades) / len(grades):.1f}")
    print(f"Range: {grades[0] - grades[-1]}")

    hist = Counter(grades)
    print("\nGrade Distribution:")
    for grade in sorted(hist.keys(), reverse=True):
        count = hist[grade]
        bar = "*" * count
        print(f"{grade:3d}: {bar} ({count})")
    print()
    return grades


def get_user_input(prompt, default, value_type=int):
    while True:
        response = input(f"{prompt} [{default}]: ").strip()
        if not response:
            return default
        try:
            return value_type(response)
        except ValueError:
            print(f"Invalid input. Please enter a {value_type.__name__}.")


def resolve_input_path(explicit: str) -> Path:
    if explicit:
        return Path(explicit)
    for candidate in DEFAULT_INPUTS:
        if candidate.exists():
            return candidate
    return DEFAULT_INPUTS[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Review consensus ranking and apply grade curve interactively")
    parser.add_argument("--input", default="", help="Ranking CSV input (defaults to final_order.csv, then consistency_adjusted.csv, then consensus_scores.csv)")
    parser.add_argument("--config", default="config/marking_config.json", help="Marking config JSON")
    parser.add_argument("--output", default="outputs/grade_curve.csv", help="Final grades output")
    parser.add_argument("--non-interactive", action="store_true", help="Use config defaults without prompts")
    args = parser.parse_args()

    config_path = Path(args.config)
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        config = {}

    curve_config = config.get("curve", {})
    default_top = curve_config.get("top", 92)
    default_bottom = curve_config.get("bottom", 58)
    default_rounding = curve_config.get("rounding", "nearest")

    input_path = resolve_input_path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        return 1

    with input_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("Error: No data in consensus scores file")
        return 1

    rows, _rank_key = sort_rows(rows)

    display_ranking_summary(rows)

    flagged = [r for r in rows if r.get("flags")]
    if flagged:
        print(f"WARNING: {len(flagged)} students have disagreement flags:")
        for r in flagged[:5]:
            print(f"  - {r.get('student_id')}: {r.get('flags')}")
        if len(flagged) > 5:
            print(f"  ... and {len(flagged) - 5} more")
        print()

    if args.non_interactive:
        top = default_top
        bottom = default_bottom
        rounding = default_rounding
        print(f"Using default curve: top={top}, bottom={bottom}, rounding={rounding}")
    else:
        print("\nCURVE CONFIGURATION")
        print("Adjust grade curve parameters (or press Enter to use defaults)")
        print()

        confirmed = False
        while not confirmed:
            top = get_user_input("Top grade (highest-ranked student)", default_top, int)
            bottom = get_user_input("Bottom grade (lowest-ranked student)", default_bottom, int)

            if top <= bottom:
                print(f"Error: Top grade ({top}) must be > bottom grade ({bottom})")
                continue
            if top > 100 or bottom < 0:
                print("Warning: Grades outside 0-100 range")

            preview_curve(rows, top, bottom, default_rounding, config)

            response = input("Apply this curve? (yes/no/adjust) [yes]: ").strip().lower()
            if response in ("", "y", "yes"):
                confirmed = True
            elif response in ("n", "no"):
                print("Aborted. No grades applied.")
                return 0

        rounding = default_rounding

    graded_rows, _curve_meta = calculate_curve_rows(rows, config, top=top, bottom=bottom, rounding=rounding)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(graded_rows[0].keys()))
        writer.writeheader()
        writer.writerows(graded_rows)

    print(f"\nGrades written to: {output_path}")
    print(f"Students graded: {len(graded_rows)}")
    print(f"Grade range: {graded_rows[0]['final_grade']} (top) to {graded_rows[-1]['final_grade']} (bottom)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
