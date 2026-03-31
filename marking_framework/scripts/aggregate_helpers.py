#!/usr/bin/env python3
import csv
import json
import math
import bisect
from pathlib import Path


def load_config(path: Path, logger=None) -> dict:
    if logger:
        logger.info(f"Loading config from {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_pass1(pass1_dir: Path, logger):
    data = []
    errors = []
    for path in sorted(pass1_dir.glob("*.json")):
        logger.info(f"Reading Pass 1 file: {path.name}")
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {path.name}: {e}")
            errors.append(e)
            continue

        if "assessor_id" not in item:
            err = ValueError(f"{path.name} missing 'assessor_id' field")
            logger.error(str(err))
            errors.append(err)
            continue
        if "scores" not in item:
            err = ValueError(f"{path.name} missing 'scores' field")
            logger.error(str(err))
            errors.append(err)
            continue
        for score in item.get("scores", []):
            if isinstance(score.get("student_id"), str):
                score["student_id"] = score["student_id"].strip()
        data.append(item)

    if errors and not data:
        raise errors[0]
    if errors and data:
        logger.warning(f"Skipped {len(errors)} invalid Pass 1 files")
    logger.info(f"Loaded {len(data)} Pass 1 assessments")
    return data


def read_pass2(pass2_dir: Path, logger):
    rankings = []
    for path in sorted(pass2_dir.glob("*")):
        if not path.is_file():
            continue
        logger.info(f"Reading Pass 2 file: {path.name}")
        lines = []
        seen = set()
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped in seen:
                continue
            seen.add(stripped)
            lines.append(stripped)
        if lines:
            rankings.append({"assessor_id": path.stem, "ranking": lines})
    logger.info(f"Loaded {len(rankings)} Pass 2 rankings")
    return rankings


def read_conventions_report(path: Path, logger):
    if not path.exists():
        logger.warning(f"Conventions report not found at {path}")
        return {}
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        data = {}
        for row in reader:
            sid = row.get("student_id", "").strip()
            row["student_id"] = sid
            data[sid] = row
    logger.info(f"Loaded conventions data for {len(data)} students")
    return data


def mean(values):
    return sum(values) / len(values) if values else 0.0


def stdev(values):
    if not values:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


def consensus_central(values, method: str = "median"):
    if not values:
        return 0.0
    if method == "mean":
        return mean(values)
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)


def weighted_central(values, weights, method: str = "median"):
    if not values:
        return 0.0
    if not weights or len(weights) != len(values):
        return consensus_central(values, method)
    cleaned = [(float(v), max(0.0, float(w))) for v, w in zip(values, weights)]
    if method == "mean":
        total_w = sum(w for _, w in cleaned)
        if total_w <= 0:
            return consensus_central(values, "mean")
        return sum(v * w for v, w in cleaned) / total_w
    ordered = sorted(cleaned, key=lambda it: it[0])
    total_w = sum(w for _, w in ordered)
    if total_w <= 0:
        return consensus_central(values, "median")
    threshold = total_w / 2.0
    acc = 0.0
    chosen = ordered[-1][0]
    for value, weight in ordered:  # pragma: no branch
        acc += weight
        if acc >= threshold:
            chosen = value
            break
    return float(chosen)


def _piecewise_interpolate(value: float, points: list[dict]) -> float:
    if not points:
        return float(value)
    ordered = sorted(
        [
            (float(p.get("x", 0.0)), float(p.get("y", 0.0)))
            for p in points
            if isinstance(p, dict) and "x" in p and "y" in p
        ],
        key=lambda it: it[0],
    )
    if not ordered:
        return float(value)
    dedup = []
    for x0, y0 in ordered:
        if dedup and x0 == dedup[-1][0]:
            dedup[-1] = (x0, y0)
        else:
            dedup.append((x0, y0))
    ordered = dedup
    x = float(value)
    xs = [pt[0] for pt in ordered]
    idx = bisect.bisect_left(xs, x)
    if idx <= 0:
        return ordered[0][1]
    if idx >= len(ordered):
        return ordered[-1][1]
    x0, y0 = ordered[idx - 1]
    x1, y1 = ordered[idx]
    ratio = (x - x0) / (x1 - x0)
    return y0 + ratio * (y1 - y0)


def resolve_bias_entry(bias_map: dict, assessor_id: str, scope_key: str | None):
    entry = bias_map.get(assessor_id, 0.0)
    if not isinstance(entry, dict):
        return entry
    if scope_key:
        scoped = entry.get("scopes", {}).get(scope_key)
        if isinstance(scoped, dict):
            global_entry = entry.get("global")
            if isinstance(global_entry, dict):
                return _blend_bias_entries(global_entry, scoped)
            return scoped
    if isinstance(entry.get("global"), dict):
        return entry["global"]
    return entry


def _blend_bias_entries(global_entry: dict, scope_entry: dict) -> dict:
    merged = dict(global_entry)
    merged.update(scope_entry)
    scope_samples = float(scope_entry.get("samples", 0) or 0.0)
    if scope_samples <= 0 and ("samples" not in scope_entry and "scope_prior" not in scope_entry):
        alpha = 1.0
    else:
        prior = float(scope_entry.get("scope_prior", 12.0) or 12.0)
        alpha = scope_samples / (scope_samples + max(0.001, prior))
        global_weight = max(0.01, float(global_entry.get("weight", 1.0) or 1.0))
        scope_weight = max(0.01, float(scope_entry.get("weight", global_weight) or global_weight))
        alpha *= min(1.0, scope_weight / global_weight)
        alpha = max(0.0, min(1.0, alpha))
    numeric_keys = (
        "bias",
        "slope",
        "intercept",
        "weight",
        "mae",
        "mae_raw",
        "level_hit_rate",
        "order_position_hit_rate",
        "pairwise_order_agreement",
        "stability_sd",
        "repeat_level_consistency",
    )
    for key in numeric_keys:
        gv = global_entry.get(key)
        sv = scope_entry.get(key)
        if isinstance(gv, (int, float)) and isinstance(sv, (int, float)):
            merged[key] = ((1.0 - alpha) * float(gv)) + (alpha * float(sv))
        elif isinstance(sv, (int, float)):
            merged[key] = float(sv)
    global_points = global_entry.get("map_points")
    scope_points = scope_entry.get("map_points")
    if isinstance(scope_points, list) and scope_points and alpha >= 0.6:
        merged["map_points"] = scope_points
    elif isinstance(global_points, list):
        merged["map_points"] = global_points
    merged["blend_alpha"] = round(alpha, 4)
    return merged


def _bias_entry_reliable(entry: dict) -> bool:
    level_hit = float(entry.get("level_hit_rate", 1.0) or 1.0)
    pairwise = float(entry.get("pairwise_order_agreement", 1.0) or 1.0)
    mae = float(entry.get("mae", 0.0) or 0.0)
    return level_hit >= 0.5 and pairwise >= 0.6 and mae <= 10.0


def apply_bias_correction(total: float, bias_entry, cap: float) -> float:
    if isinstance(bias_entry, dict):
        if not _bias_entry_reliable(bias_entry):
            return max(0.0, min(float(total), float(cap)))
        value = float(total)
        points = bias_entry.get("map_points") or []
        if isinstance(points, list) and points:
            value = _piecewise_interpolate(value, points)
        slope = float(bias_entry.get("slope", 1.0) or 1.0)
        intercept = float(bias_entry.get("intercept", 0.0) or 0.0)
        if "slope" not in bias_entry and "intercept" not in bias_entry and "bias" in bias_entry:
            intercept = -float(bias_entry.get("bias", 0.0) or 0.0)
        value = (float(value) * slope) + intercept
    else:
        bias = float(bias_entry or 0.0)
        value = float(total) - bias
    return max(0.0, min(float(value), float(cap)))


def get_level_bands(config):
    bands = config.get("levels", {}).get("bands", [])
    if bands:
        return sorted(
            bands,
            key=lambda band: float(band.get("min", 0.0) or 0.0),
        )
    return [
        {"level": "1", "min": 50, "max": 59, "letter": "D"},
        {"level": "2", "min": 60, "max": 69, "letter": "C"},
        {"level": "3", "min": 70, "max": 79, "letter": "B"},
        {"level": "4", "min": 80, "max": 89, "letter": "A"},
        {"level": "4+", "min": 90, "max": 100, "letter": "A+"},
    ]


def get_level_band(percent, bands):
    if percent is None or not bands:
        return None
    value = float(percent)
    ordered = sorted(
        bands,
        key=lambda band: float(band.get("min", 0.0) or 0.0),
    )
    if value < float(ordered[0].get("min", 0.0) or 0.0):
        return ordered[0]
    for idx, band in enumerate(ordered):
        band_min = float(band.get("min", 0.0) or 0.0)
        band_max = float(band.get("max", band_min) or band_min)
        next_min = None
        if idx + 1 < len(ordered):
            next_min = float(ordered[idx + 1].get("min", band_max + 1.0) or (band_max + 1.0))
        # Use next band threshold as upper edge, so decimals between integer bins map correctly.
        if next_min is not None and value >= band_min and value < next_min:
            return band
        if value >= band_min and value <= band_max:
            return band
    return ordered[-1]


def level_modifier_from_mistake_rate(mistake_rate_percent, modifier_bands):
    for band in modifier_bands:
        if mistake_rate_percent <= band["max_mistake_rate_percent"]:
            return band["modifier"]
    return ""


def apply_level_drop_penalty(percent, bands, level_drop):
    band = get_level_band(percent, bands)
    if not band:
        return percent
    width = (band["max"] - band["min"] + 1)
    penalty = width * level_drop
    return max(0.0, percent - penalty)


def calculate_irr_metrics(rubric_by_student, rankings_by_student, num_assessors_rubric, num_assessors_rank):
    rubric_sds = [stdev(scores) for scores in rubric_by_student.values() if len(scores) >= 2]
    mean_rubric_sd = mean(rubric_sds) if rubric_sds else 0.0

    rank_sds = [stdev(ranks) for ranks in rankings_by_student.values() if len(ranks) >= 2]
    mean_rank_sd = mean(rank_sds) if rank_sds else 0.0

    all_scores = [score for scores in rubric_by_student.values() for score in scores]
    if all_scores and len(rubric_by_student) > 1:
        student_means = [mean(scores) for scores in rubric_by_student.values() if scores]
        grand_mean = mean(all_scores)
        bs_var = sum((sm - grand_mean) ** 2 for sm in student_means) / (len(student_means) - 1) if len(student_means) > 1 else 0
        total_var = sum((score - grand_mean) ** 2 for score in all_scores) / (len(all_scores) - 1) if len(all_scores) > 1 else 1
        rubric_icc = bs_var / total_var if total_var > 0 else 0.0
    else:
        rubric_icc = 0.0

    if rankings_by_student and num_assessors_rank >= 2:
        num_students = len(rankings_by_student)
        rank_sums = [sum(ranks) for ranks in rankings_by_student.values()]
        mean_rank_sum = mean(rank_sums)
        S = sum((rs - mean_rank_sum) ** 2 for rs in rank_sums)
        m = num_assessors_rank
        n = num_students
        denominator = (m ** 2) * (n ** 3 - n)
        kendall_w = (12 * S) / denominator if denominator > 0 else 0.0
    else:
        kendall_w = 0.0

    return {
        "rubric_icc": round(rubric_icc, 3),
        "rank_kendall_w": round(kendall_w, 3),
        "mean_rubric_sd": round(mean_rubric_sd, 2),
        "mean_rank_sd": round(mean_rank_sd, 2),
    }
