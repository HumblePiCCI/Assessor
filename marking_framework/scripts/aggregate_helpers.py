#!/usr/bin/env python3
import csv
import json
import math
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
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
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


def get_level_bands(config):
    bands = config.get("levels", {}).get("bands", [])
    if bands:
        return bands
    return [
        {"level": "1", "min": 50, "max": 59, "letter": "D"},
        {"level": "2", "min": 60, "max": 69, "letter": "C"},
        {"level": "3", "min": 70, "max": 79, "letter": "B"},
        {"level": "4", "min": 80, "max": 89, "letter": "A"},
        {"level": "4+", "min": 90, "max": 100, "letter": "A+"},
    ]


def get_level_band(percent, bands):
    if percent is None:
        return None
    for band in bands:
        if percent >= band["min"] and percent <= band["max"]:
            return band
    if percent < bands[0]["min"]:
        return bands[0]
    return bands[-1]


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
