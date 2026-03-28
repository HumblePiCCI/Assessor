#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path
from statistics import NormalDist

try:
    from scripts.aggregate_helpers import get_level_bands
    from scripts.levels import normalize_level
except ImportError:  # pragma: no cover - Support running as a script
    from aggregate_helpers import get_level_bands  # pragma: no cover
    from levels import normalize_level  # pragma: no cover


DEFAULT_RANK_KEYS = ("final_rank", "consistency_rank", "consensus_rank")


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def round_grade(value: float, mode: str) -> int:
    if mode == "floor":
        return int(value // 1)
    if mode == "ceil":
        return int(-(-value // 1))
    return int(round(value))


def num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, lo: float, hi: float) -> float:
    return max(float(lo), min(float(hi), float(value)))


def select_rank_key(rows: list[dict]) -> str:
    if not rows:
        return ""
    for key in DEFAULT_RANK_KEYS:
        if key in rows[0]:
            return key
    return ""


def sort_rows(rows: list[dict]) -> tuple[list[dict], str]:
    ordered = [dict(row) for row in rows]
    rank_key = select_rank_key(ordered)
    if rank_key:
        ordered.sort(
            key=lambda row: (
                int(num(row.get(rank_key), 0.0) or 0.0),
                str(row.get("student_id", "")).lower(),
            )
        )
    return ordered, rank_key


def resolve_level_band(level_bands: list[dict], level: str | None) -> dict | None:
    normalized = normalize_level(level)
    if not normalized:
        return None
    for band in level_bands:
        if normalize_level(band.get("level")) == normalized:
            return band
    return None


def resolve_row_level(row: dict) -> str | None:
    for key in ("adjusted_level", "base_level"):
        normalized = normalize_level(row.get(key))
        if normalized:
            return normalized
    return None


def effective_rubric_grade(row: dict) -> float | None:
    for key in ("rubric_after_penalty_percent", "rubric_mean_percent"):
        value = num(row.get(key))
        if value is not None:
            return float(value)
    return None


def curve_position(index: int, count: int, profile: str, *, singleton: float = 1.0) -> float:
    if count <= 1:
        return float(singleton)
    if profile == "linear":
        return 1.0 - (index / (count - 1))
    low_p = 0.5 / count
    high_p = 1.0 - low_p
    percentile = high_p - (index * (high_p - low_p) / (count - 1))
    dist = NormalDist()
    low_z = dist.inv_cdf(low_p)
    high_z = dist.inv_cdf(high_p)
    curr_z = dist.inv_cdf(percentile)
    if high_z == low_z:
        return 1.0 - (index / (count - 1))
    return (curr_z - low_z) / (high_z - low_z)


def rank_grade(index: int, count: int, top: float, bottom: float, profile: str) -> float:
    position = curve_position(index, count, profile, singleton=1.0)
    return float(bottom) + ((float(top) - float(bottom)) * position)


def band_grade(index: int, count: int, band: dict, profile: str) -> float:
    band_min = float(band.get("min", 0.0) or 0.0)
    band_max = float(band.get("max", band_min) or band_min)
    position = curve_position(index, count, profile, singleton=0.5)
    return band_min + ((band_max - band_min) * position)


def calculate_curve_rows(
    rows: list[dict],
    config: dict,
    *,
    top: float | None = None,
    bottom: float | None = None,
    rounding: str | None = None,
) -> tuple[list[dict], dict]:
    curve = config.get("curve", {})
    top = float(curve.get("top", 92) if top is None else top)
    bottom = float(curve.get("bottom", 58) if bottom is None else bottom)
    rounding = str(curve.get("rounding", "nearest") if rounding is None else rounding)
    profile = str(curve.get("profile", "bell") or "bell").lower()
    level_lock = bool(curve.get("level_lock", True))
    rubric_weight = float(curve.get("rubric_weight", 0.65) or 0.65)
    rank_weight = float(curve.get("rank_weight", 0.35) or 0.35)
    total_weight = rubric_weight + rank_weight
    if total_weight <= 0:
        rubric_weight = 1.0
        rank_weight = 0.0
        total_weight = 1.0
    rubric_weight /= total_weight
    rank_weight /= total_weight

    ordered, rank_key = sort_rows(rows)
    if not ordered:
        return [], {
            "top": top,
            "bottom": bottom,
            "rounding": rounding,
            "profile": profile,
            "rank_key": rank_key,
            "level_lock": level_lock,
            "rubric_weight": rubric_weight,
            "rank_weight": rank_weight,
        }

    level_bands = get_level_bands(config)
    grouped_rows: dict[str, list[dict]] = {}
    for row in ordered:
        row_level = resolve_row_level(row)
        if not row_level:
            continue
        grouped_rows.setdefault(row_level, []).append(row)

    band_grades = {}
    for level, group in grouped_rows.items():
        band = resolve_level_band(level_bands, level)
        if band is None:
            continue
        for idx, row in enumerate(group):
            band_grades[id(row)] = band_grade(idx, len(group), band, profile)

    raw_grades = []
    last_grade = float(top)
    for idx, row in enumerate(ordered):
        level = resolve_row_level(row)
        band = resolve_level_band(level_bands, level)
        rank_component = rank_grade(idx, len(ordered), top, bottom, profile)
        band_component = band_grades.get(id(row), rank_component)
        rubric_component = effective_rubric_grade(row)
        if rubric_component is None:
            rubric_component = band_component
        if band is not None:
            band_min = float(band.get("min", 0.0) or 0.0)
            band_max = float(band.get("max", band_min) or band_min)
            rubric_component = clamp(rubric_component, band_min, band_max)
        raw_grade = (rubric_weight * rubric_component) + (rank_weight * band_component)
        if band is not None and level_lock:
            raw_grade = clamp(raw_grade, band_min, band_max)
        raw_grade = clamp(raw_grade, bottom, top)
        raw_grade = min(raw_grade, last_grade)
        last_grade = raw_grade
        raw_grades.append(raw_grade)
        row["curve_top"] = top
        row["curve_bottom"] = bottom
        row["curve_profile"] = profile
        row["curve_rank_key"] = rank_key
        row["curve_grade_raw"] = round(raw_grade, 2)
        row["curve_grade_band"] = round(band_component, 2)
        row["curve_grade_rubric"] = round(rubric_component, 2)

    rounded_grades = [round_grade(value, rounding) for value in raw_grades]
    for idx in range(1, len(rounded_grades)):
        if rounded_grades[idx] > rounded_grades[idx - 1]:
            rounded_grades[idx] = rounded_grades[idx - 1]

    for row, grade in zip(ordered, rounded_grades):
        row["final_grade"] = grade

    return ordered, {
        "top": top,
        "bottom": bottom,
        "rounding": rounding,
        "profile": profile,
        "rank_key": rank_key,
        "level_lock": level_lock,
        "rubric_weight": rubric_weight,
        "rank_weight": rank_weight,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to marking_config.json")
    parser.add_argument("--input", required=True, help="Consensus CSV input")
    parser.add_argument("--output", required=True, help="Grade curve CSV output")
    args = parser.parse_args()

    config = load_config(Path(args.config))

    rows = []
    with Path(args.input).open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return 0

    rows, _curve_meta = calculate_curve_rows(rows, config)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
