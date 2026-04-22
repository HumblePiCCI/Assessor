#!/usr/bin/env python3
import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from scripts.adjudication_source import dedupe_by_precedence, normalize_source
    from scripts.aggregate_helpers import get_level_bands
    from scripts.local_teacher_prior import compute_teacher_preference_adjustments
    from scripts.levels import normalize_level
except ImportError:  # pragma: no cover - Support running as a script
    from adjudication_source import dedupe_by_precedence, normalize_source  # pragma: no cover
    from aggregate_helpers import get_level_bands  # pragma: no cover
    from local_teacher_prior import compute_teacher_preference_adjustments  # pragma: no cover
    from levels import normalize_level  # pragma: no cover


CONFIDENCE_WEIGHTS = {"low": 0.5, "medium": 1.0, "high": 2.0}
DEFAULT_LEVEL_ORDER = {"1": 1.0, "2": 2.0, "3": 3.0, "4": 4.0, "4+": 5.0}
COMMITTEE_DIRECT_EDGE_KIND = "committee_direct_edge"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def current_run_scope(scores_path: Path) -> dict:
    root = scores_path.resolve().parent.parent if scores_path.resolve().parent.name == "outputs" else Path(".").resolve()
    for candidate in [root / "pipeline_manifest.json", root / "outputs" / "pipeline_manifest.json"]:
        payload = load_json(candidate)
        if payload:
            scope = payload.get("run_scope", {})
            return scope if isinstance(scope, dict) else {}
    return {}


def num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    token = str(value or "").strip().lower()
    return token in {"1", "true", "yes", "y"}


def normalize_confidence(value) -> str:
    token = str(value or "").strip().lower()
    if token in {"high"}:
        return "high"
    if token in {"med", "medium"}:
        return "medium"
    return "low"


def normalize_decision(value) -> str:
    token = str(value or "").strip().upper()
    return "SWAP" if token == "SWAP" else "KEEP"


def adjudication_source(item: dict) -> str:
    return normalize_source(item)


def normalize_winner_side(value) -> str:
    token = str(value or "").strip().upper()
    return token if token in {"A", "B"} else ""


def decision_from_winner_side(value) -> str:
    side = normalize_winner_side(value)
    if side == "A":
        return "KEEP"
    if side == "B":
        return "SWAP"
    return ""


def winner_side_from_decision(value) -> str:
    return "B" if normalize_decision(value) == "SWAP" else "A"


def confidence_weight(confidence: str) -> float:
    return float(CONFIDENCE_WEIGHTS.get(normalize_confidence(confidence), CONFIDENCE_WEIGHTS["low"]))


def confidence_rank(confidence: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(normalize_confidence(confidence), 0)


def clamp_exp_input(value: float) -> float:
    return max(-30.0, min(30.0, float(value)))


def rank_key(rows: list[dict]) -> str:
    if not rows:
        return ""
    for key in ("seed_rank", "consensus_rank", "final_rank", "consistency_rank"):
        if key in rows[0]:
            return key
    return ""


def level_order_map(config: dict) -> dict[str, float]:
    ordered = sorted(
        [band for band in get_level_bands(config or {}) if normalize_level(band.get("level"))],
        key=lambda band: float(band.get("min", 0.0) or 0.0),
    )
    if not ordered:
        return dict(DEFAULT_LEVEL_ORDER)
    mapping = {}
    for idx, band in enumerate(ordered, start=1):
        level = normalize_level(band.get("level"))
        if level:
            mapping[level] = float(idx)
    return mapping or dict(DEFAULT_LEVEL_ORDER)


def normalize_feature(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    lo = min(values.values())
    hi = max(values.values())
    if hi <= lo:
        return {key: 0.5 for key in values}
    scale = hi - lo
    return {key: (value - lo) / scale for key, value in values.items()}


def clamp01(value, default=0.0) -> float:
    return max(0.0, min(1.0, num(value, default)))


def seed_percentile(seed_rank: int, student_count: int) -> float:
    if student_count <= 1:
        return 1.0
    return max(0.0, min(1.0, 1.0 - ((int(seed_rank) - 1) / max(student_count - 1, 1))))


def load_seed_rows(path: Path, config: dict) -> list[dict]:
    rows = load_rows(path)
    if not rows:
        return []
    seed_key = rank_key(rows)
    rows_sorted = sorted(
        [dict(row) for row in rows if str(row.get("student_id", "")).strip()],
        key=lambda row: (
            int(num(row.get(seed_key), 0.0) or 0.0),
            str(row.get("student_id", "")).lower(),
        ),
    )
    level_map = level_order_map(config)
    normalized = []
    for idx, row in enumerate(rows_sorted, start=1):
        student_id = str(row.get("student_id", "")).strip()
        level = normalize_level(row.get("adjusted_level") or row.get("base_level"))
        seed_rank = int(num(row.get("seed_rank") or row.get(seed_key), idx) or idx)
        item = dict(row)
        item["student_id"] = student_id
        item["seed_rank"] = seed_rank
        item["_level"] = level or ""
        item["_level_order"] = float(level_map.get(level or "", 0.0))
        item["_rubric_after_penalty_percent"] = num(
            row.get("rubric_after_penalty_percent"),
            num(row.get("rubric_mean_percent"), 0.0),
        )
        item["_composite_score"] = num(row.get("composite_score"), 0.0)
        item["_borda_feature"] = num(row.get("borda_percent"), num(row.get("borda_points"), 0.0))
        flags = {token.strip() for token in str(row.get("flags", "") or "").split(";") if token.strip()}
        item["_draft_completion_floor_applied"] = truthy(row.get("draft_completion_floor_applied")) or ("draft_completion_floor" in flags)
        item["_severe_collapse_rescue"] = "severe_collapse_rescue" in flags
        item["_pre_boundary_calibration_percent"] = num(
            row.get("pre_boundary_calibration_percent"),
            item["_rubric_after_penalty_percent"],
        )
        normalized.append(item)
    return normalized


def load_judgments(path: Path, rows_by_id: dict[str, dict]) -> tuple[dict, list[dict]]:
    payload = load_json(path)
    raw_items = payload.get("checks", payload.get("judgments", [])) if isinstance(payload, dict) else []
    normalized = []
    for idx, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        pair = item.get("pair")
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        seed_order = item.get("seed_order", {}) if isinstance(item.get("seed_order"), dict) else {}
        higher = str(seed_order.get("higher") or pair[0]).strip()
        lower = str(seed_order.get("lower") or pair[1]).strip()
        if higher not in rows_by_id or lower not in rows_by_id:
            continue
        winner_side = normalize_winner_side(item.get("winner_side"))
        decision = decision_from_winner_side(winner_side) or normalize_decision(item.get("decision"))
        if not winner_side:
            winner_side = winner_side_from_decision(decision)
        confidence = normalize_confidence(item.get("confidence"))
        rationale = str(item.get("rationale") or item.get("reason") or "").strip()
        model_metadata = item.get("model_metadata") if isinstance(item.get("model_metadata"), dict) else {}
        criterion_notes = item.get("criterion_notes") if isinstance(item.get("criterion_notes"), list) else []
        decision_basis = str(item.get("decision_basis", "") or "").strip()
        cautions_applied = item.get("cautions_applied") if isinstance(item.get("cautions_applied"), list) else []
        decision_checks = item.get("decision_checks") if isinstance(item.get("decision_checks"), dict) else {}
        committee_edge_trace = item.get("committee_edge_trace") if isinstance(item.get("committee_edge_trace"), dict) else {}
        source = adjudication_source(item)
        winner = higher if decision == "KEEP" else lower
        loser = lower if decision == "KEEP" else higher
        normalized.append(
            {
                "id": idx + 1,
                "pair": [higher, lower],
                "pair_key": pair_key(higher, lower),
                "seed_order": {
                    "higher": higher,
                    "lower": lower,
                    "higher_rank": int(num(seed_order.get("higher_rank"), rows_by_id[higher]["seed_rank"])),
                    "lower_rank": int(num(seed_order.get("lower_rank"), rows_by_id[lower]["seed_rank"])),
                },
                "decision": decision,
                "winner_side": winner_side,
                "confidence": confidence,
                "weight": confidence_weight(confidence),
                "rationale": rationale,
                "criterion_notes": criterion_notes,
                "decision_basis": decision_basis,
                "cautions_applied": cautions_applied,
                "decision_checks": decision_checks,
                "committee_confidence": str(item.get("committee_confidence") or ""),
                "committee_edge_trace": committee_edge_trace,
                "winner": winner,
                "loser": loser,
                "model_metadata": model_metadata,
                "adjudication_source": source,
                "superseded_by_escalation": bool(model_metadata.get("superseded_by_escalation", False)),
            }
        )
    normalized = dedupe_by_precedence(normalized, key_fn=lambda item: item["pair_key"])
    for idx, item in enumerate(normalized, start=1):
        item["id"] = idx
    return payload if isinstance(payload, dict) else {}, normalized


def pair_key(left: str, right: str) -> str:
    ordered = sorted((str(left).strip(), str(right).strip()))
    return f"{ordered[0]}::{ordered[1]}"


def build_pairwise_matrix(rows: list[dict], judgments: list[dict]) -> tuple[dict, dict, dict]:
    rows_by_id = {row["student_id"]: row for row in rows}
    comparisons = {}
    per_student = {
        sid: {
            "support_weight": 0.0,
            "opposition_weight": 0.0,
            "incident_weight": 0.0,
            "judgment_count": 0,
            "high_confidence_edges": 0,
            "medium_confidence_edges": 0,
            "low_confidence_edges": 0,
        }
        for sid in rows_by_id
    }
    directional = defaultdict(float)
    for judgment in judgments:
        higher, lower = judgment["pair"]
        key = judgment["pair_key"]
        comparison = comparisons.setdefault(
            key,
            {
                "pair": [higher, lower],
                "seed_order": dict(judgment["seed_order"]),
                "judgment_count": 0,
                "directional_weight": defaultdict(float),
                "confidence_counts": {"low": 0, "medium": 0, "high": 0},
                "source_counts": defaultdict(int),
                "judgments": [],
            },
        )
        comparison["judgment_count"] += 1
        comparison["directional_weight"][f"{judgment['winner']}>{judgment['loser']}"] += judgment["weight"]
        comparison["confidence_counts"][judgment["confidence"]] += 1
        comparison["source_counts"][judgment.get("adjudication_source", "cheap_pairwise")] += 1
        comparison["judgments"].append(
            {
                "decision": judgment["decision"],
                "winner_side": judgment.get("winner_side", ""),
                "confidence": judgment["confidence"],
                "weight": judgment["weight"],
                "winner": judgment["winner"],
                "loser": judgment["loser"],
                "rationale": judgment["rationale"],
                "criterion_notes": judgment.get("criterion_notes", []),
                "decision_basis": judgment.get("decision_basis", ""),
                "cautions_applied": judgment.get("cautions_applied", []),
                "decision_checks": judgment.get("decision_checks", {}),
                "adjudication_source": judgment.get("adjudication_source", "cheap_pairwise"),
                "model_metadata": judgment["model_metadata"],
            }
        )
        per_student[judgment["winner"]]["support_weight"] += judgment["weight"]
        per_student[judgment["loser"]]["opposition_weight"] += judgment["weight"]
        for sid in (judgment["winner"], judgment["loser"]):
            per_student[sid]["incident_weight"] += judgment["weight"]
            per_student[sid]["judgment_count"] += 1
            bucket = f"{judgment['confidence']}_confidence_edges"
            if bucket in per_student[sid]:
                per_student[sid][bucket] += 1
        directional[(judgment["winner"], judgment["loser"])] += judgment["weight"]

    comparison_list = []
    for key in sorted(comparisons, key=lambda item: (rows_by_id[comparisons[item]["pair"][0]]["seed_rank"], rows_by_id[comparisons[item]["pair"][1]]["seed_rank"])):
        item = comparisons[key]
        left, right = item["pair"]
        left_over_right = float(item["directional_weight"].get(f"{left}>{right}", 0.0))
        right_over_left = float(item["directional_weight"].get(f"{right}>{left}", 0.0))
        comparison_list.append(
            {
                "pair": [left, right],
                "seed_order": dict(item["seed_order"]),
                "judgment_count": int(item["judgment_count"]),
                "left_over_right_weight": round(left_over_right, 6),
                "right_over_left_weight": round(right_over_left, 6),
                "net_preference": round(left_over_right - right_over_left, 6),
                "confidence_counts": dict(item["confidence_counts"]),
                "source_counts": dict(item["source_counts"]),
                "judgments": list(item["judgments"]),
            }
        )
    matrix = {
        "generated_at": now_iso(),
        "student_count": len(rows),
        "comparison_count": len(comparison_list),
        "comparisons": comparison_list,
        "per_student": {
            sid: {
                key: round(value, 6) if isinstance(value, float) else value
                for key, value in per_student[sid].items()
            }
            for sid in sorted(per_student)
        },
        "directional_weight": {
            f"{winner}>{loser}": round(weight, 6)
            for (winner, loser), weight in sorted(directional.items())
        },
    }
    return matrix, per_student, dict(directional)


def build_prior_scores(rows: list[dict]) -> dict[str, float]:
    if not rows:
        return {}
    count = len(rows)
    seed_feature = {}
    composite_feature = {}
    rubric_feature = {}
    borda_feature = {}
    level_feature = {}
    max_level = max((row["_level_order"] for row in rows), default=0.0) or 1.0
    for row in rows:
        sid = row["student_id"]
        seed_feature[sid] = 1.0 if count <= 1 else 1.0 - ((row["seed_rank"] - 1) / max(count - 1, 1))
        composite_feature[sid] = row["_composite_score"]
        rubric_feature[sid] = row["_rubric_after_penalty_percent"]
        borda_feature[sid] = row["_borda_feature"]
        level_feature[sid] = row["_level_order"] / max_level
    composite_feature = normalize_feature(composite_feature)
    rubric_feature = normalize_feature(rubric_feature)
    borda_feature = normalize_feature(borda_feature)
    prior = {}
    for row in rows:
        sid = row["student_id"]
        prior[sid] = round(
            (0.5 * composite_feature.get(sid, 0.5))
            + (0.2 * rubric_feature.get(sid, 0.5))
            + (0.15 * seed_feature.get(sid, 0.5))
            + (0.1 * level_feature.get(sid, 0.0))
            + (0.05 * borda_feature.get(sid, 0.5)),
            6,
        )
    return prior


def level_boundaries_from_config(config: dict) -> list[float]:
    ordered = sorted(
        [float(band.get("min", 0.0) or 0.0) for band in get_level_bands(config or {}) if num(band.get("min"), 0.0) > 0.0]
    )
    return ordered[1:] if len(ordered) > 1 else [60.0, 70.0, 80.0, 90.0]


def is_boundary_row(row: dict, boundaries: list[float], *, margin: float = 1.5) -> bool:
    score = num(row.get("_rubric_after_penalty_percent"), num(row.get("rubric_after_penalty_percent"), 0.0))
    return any(abs(score - edge) <= float(margin) for edge in boundaries)


def pairwise_conflict_stats(rows: list[dict], comparisons: list[dict], boundaries: list[float], *, boundary_margin: float = 1.5) -> tuple[dict[str, dict], dict]:
    rows_by_id = {row["student_id"]: row for row in rows}
    per_student = {
        sid: {
            "conflict_pairs": 0,
            "incident_pairs": 0,
            "boundary_conflict_pairs": 0,
            "pairwise_conflict_density": 0.0,
        }
        for sid in rows_by_id
    }
    total_pairs = 0
    conflicting_pairs = 0
    boundary_disagreements = 0
    total_disagreements = 0
    for item in comparisons:
        left, right = item["pair"]
        total_pairs += 1
        left_over_right = float(item.get("left_over_right", 0.0) or 0.0)
        right_over_left = float(item.get("right_over_left", 0.0) or 0.0)
        has_conflict = left_over_right > 0.0 and right_over_left > 0.0
        left_row = rows_by_id[left]
        right_row = rows_by_id[right]
        score_gap = abs(float(left_row["_rubric_after_penalty_percent"]) - float(right_row["_rubric_after_penalty_percent"]))
        level_gap = abs(float(left_row["_level_order"]) - float(right_row["_level_order"]))
        boundary_pair = (
            level_gap <= 1.0
            and (
                score_gap <= 3.0
                or is_boundary_row(left_row, boundaries, margin=boundary_margin)
                or is_boundary_row(right_row, boundaries, margin=boundary_margin)
            )
        )
        for sid in (left, right):
            per_student[sid]["incident_pairs"] += 1
        if has_conflict:
            conflicting_pairs += 1
            total_disagreements += 1
            for sid in (left, right):
                per_student[sid]["conflict_pairs"] += 1
            if boundary_pair:
                boundary_disagreements += 1
                for sid in (left, right):
                    per_student[sid]["boundary_conflict_pairs"] += 1
    for sid, stats in per_student.items():
        incidents = int(stats["incident_pairs"] or 0)
        conflicts = int(stats["conflict_pairs"] or 0)
        stats["pairwise_conflict_density"] = round((conflicts / incidents) if incidents else 0.0, 6)
    summary = {
        "comparison_count": total_pairs,
        "conflicting_pairs": conflicting_pairs,
        "pairwise_conflict_density": round((conflicting_pairs / total_pairs) if total_pairs else 0.0, 6),
        "boundary_disagreements": boundary_disagreements,
        "total_disagreements": total_disagreements,
        "boundary_disagreement_concentration": round((boundary_disagreements / total_disagreements) if total_disagreements else 0.0, 6),
    }
    return per_student, summary


def student_stability_penalty(row: dict, per_student: dict) -> float:
    sid = row["student_id"]
    metrics = per_student.get(sid, {}) if isinstance(per_student, dict) else {}
    rubric_sd = num(row.get("rubric_sd_points"), 0.0)
    rank_sd = num(row.get("rank_sd"), 0.0)
    flags = {token.strip() for token in str(row.get("flags", "") or "").split(";") if token.strip()}
    conflict_density = num(metrics.get("pairwise_conflict_density"), 0.0)
    penalty = 0.0
    penalty += min(0.35, rubric_sd / 10.0 * 0.35)
    penalty += min(0.2, rank_sd / 3.0 * 0.2)
    penalty += min(0.25, conflict_density * 0.25)
    if "high_disagreement" in flags:
        penalty += 0.1
    if "boundary_case" in flags:
        penalty += 0.05
    return round(min(0.75, penalty), 6)


def optimize_scores(
    student_ids: list[str],
    prior_scores: dict[str, float],
    judgments: list[dict],
    *,
    iterations: int,
    learning_rate: float,
    regularization: float,
) -> dict[str, float]:
    if not student_ids:
        return {}
    scores = {sid: float(prior_scores.get(sid, 0.0) or 0.0) for sid in student_ids}
    if not judgments:
        avg = sum(scores.values()) / len(scores)
        return {sid: round(scores[sid] - avg, 6) for sid in student_ids}
    for _ in range(max(1, iterations)):
        gradients = {
            sid: 2.0 * float(regularization) * (scores[sid] - float(prior_scores.get(sid, 0.0) or 0.0))
            for sid in student_ids
        }
        for judgment in judgments:
            winner = judgment["winner"]
            loser = judgment["loser"]
            weight = float(judgment["weight"] or 0.0)
            diff = clamp_exp_input(scores[winner] - scores[loser])
            loser_probability = 1.0 / (1.0 + math.exp(diff))
            gradients[winner] -= weight * loser_probability
            gradients[loser] += weight * loser_probability
        max_change = 0.0
        for sid in student_ids:
            new_value = scores[sid] - (float(learning_rate) * gradients[sid])
            max_change = max(max_change, abs(new_value - scores[sid]))
            scores[sid] = new_value
        mean_value = sum(scores.values()) / len(scores)
        for sid in student_ids:
            scores[sid] -= mean_value
        if max_change < 1e-7:
            break
    return {sid: round(scores[sid], 6) for sid in student_ids}


def compute_displacement_caps(rows: list[dict], per_student: dict, *, low_cap: int, medium_cap: int, high_cap: int) -> dict[str, dict]:
    count = len(rows)
    caps = {}
    for row in rows:
        sid = row["student_id"]
        stability_penalty = student_stability_penalty(row, per_student)
        incident = float(per_student.get(sid, {}).get("incident_weight", 0.0) or 0.0)
        support = float(per_student.get(sid, {}).get("support_weight", 0.0) or 0.0)
        opposition = float(per_student.get(sid, {}).get("opposition_weight", 0.0) or 0.0)
        effective_incident = incident * max(0.25, 1.0 - stability_penalty)
        effective_support = support * max(0.25, 1.0 - stability_penalty)
        effective_opposition = opposition * max(0.25, 1.0 - stability_penalty)
        high_cap_effective = min(count, max(1, int(high_cap)))
        if stability_penalty >= 0.35:
            high_cap_effective = min(high_cap_effective, max(int(medium_cap), 4))
        if effective_support >= 2.5:
            up_cap = high_cap_effective
        elif effective_support >= 1.0:
            up_cap = min(count, max(1, int(medium_cap)))
        else:
            up_cap = min(count, max(1, int(low_cap)))

        if effective_opposition >= 6.0:
            down_cap = min(count, max(high_cap_effective * 3, 10))
        elif effective_opposition >= 3.0:
            down_cap = min(count, max(int(medium_cap) * 2, 6))
        elif effective_opposition >= 1.0:
            down_cap = min(count, max(int(medium_cap), 4))
        else:
            down_cap = min(count, max(1, int(low_cap)))

        seed_pct = seed_percentile(int(row["seed_rank"]), count)
        borda_pct = clamp01(row.get("_borda_feature"), seed_pct)
        divergence = abs(seed_pct - borda_pct)
        if borda_pct + 0.35 < seed_pct and effective_opposition >= effective_support + 2.0:
            down_cap = max(down_cap, min(count, 8))
        if borda_pct + 0.5 < seed_pct and effective_opposition >= effective_support + 4.0:
            down_cap = max(down_cap, min(count, 12))

        cap = max(up_cap, down_cap)
        if effective_opposition >= effective_support + 2.0 and down_cap > up_cap:
            label = "high_opposition"
        elif effective_support >= 2.5:
            label = "high_support"
        elif effective_incident >= 1.0:
            label = "mixed_evidence"
        else:
            label = "low_support"
        seed_rank = int(row["seed_rank"])
        draft_floor_lock = bool(row.get("_draft_completion_floor_applied"))
        severe_collapse_rescue = bool(row.get("_severe_collapse_rescue"))
        rescue_best_rank = max(1, seed_rank - (2 if num(row.get("_pre_boundary_calibration_percent"), 0.0) < 67.0 else 3))
        best_rank = seed_rank if draft_floor_lock else max(1, seed_rank - up_cap)
        rescue_cap_active = severe_collapse_rescue and not draft_floor_lock and rescue_best_rank > best_rank
        if rescue_cap_active:
            best_rank = rescue_best_rank
        caps[sid] = {
            "cap": cap,
            "label": "completion_floor_lock" if draft_floor_lock else label,
            "best_rank": best_rank,
            "worst_rank": min(count, seed_rank + down_cap),
            "up_cap": up_cap,
            "down_cap": down_cap,
            "stability_penalty": stability_penalty,
            "effective_incident_weight": round(effective_incident, 6),
            "effective_support_weight": round(effective_support, 6),
            "effective_opposition_weight": round(effective_opposition, 6),
            "seed_percentile": round(seed_pct, 6),
            "borda_percentile": round(borda_pct, 6),
            "borda_seed_divergence": round(divergence, 6),
            "draft_completion_floor_lock": draft_floor_lock,
            "severe_collapse_rescue_cap": rescue_cap_active,
        }
    return caps


def direct_weight(direction: dict[tuple[str, str], float], winner: str, loser: str) -> float:
    return float(direction.get((winner, loser), 0.0) or 0.0)


def truthy_metadata_flag(metadata: dict, *keys: str) -> bool:
    for key in keys:
        if truthy(metadata.get(key)):
            return True
    return False


def committee_trace(judgment: dict) -> dict:
    trace = judgment.get("committee_edge_trace")
    return trace if isinstance(trace, dict) else {}


def committee_edge_cycle_suppressed(judgment: dict) -> bool:
    metadata = judgment.get("model_metadata") if isinstance(judgment.get("model_metadata"), dict) else {}
    trace = committee_trace(judgment)
    cycle = trace.get("cycle_resolution") if isinstance(trace.get("cycle_resolution"), dict) else {}
    return (
        truthy_metadata_flag(
            metadata,
            "cycle_suppressed",
            "suppressed_by_cycle",
            "committee_cycle_suppressed",
            "committee_direct_cycle_suppressed",
        )
        or truthy_metadata_flag(
            trace,
            "cycle_suppressed",
            "suppressed_by_cycle",
            "committee_cycle_suppressed",
            "committee_direct_cycle_suppressed",
        )
        or truthy_metadata_flag(cycle, "suppressed", "cycle_suppressed")
    )


def committee_edge_superseded(judgment: dict) -> bool:
    metadata = judgment.get("model_metadata") if isinstance(judgment.get("model_metadata"), dict) else {}
    return any(
        key.startswith("superseded_by_") and truthy(value)
        for key, value in metadata.items()
    )


def committee_confidence_rank(judgment: dict) -> int:
    value = str(judgment.get("committee_confidence") or "").strip().lower()
    if value.endswith("high"):
        return 2
    if value.endswith("medium"):
        return 1
    if value.endswith("low"):
        return 0
    return -1


def committee_read_rank(judgment: dict) -> int:
    metadata = judgment.get("model_metadata") if isinstance(judgment.get("model_metadata"), dict) else {}
    trace = committee_trace(judgment)
    read = str(metadata.get("committee_read") or trace.get("read") or "").strip()
    return {
        "group-neighborhood-calibration": 3,
        "C-placement-calibration": 2,
        "C-placement-calibration-guard": 2,
        "B-polish-trap-audit": 1,
        "A-blind": 0,
    }.get(read, 0)


def protected_committee_direct_edges(judgments: list[dict]) -> list[dict]:
    edges = []
    for judgment in judgments:
        if judgment.get("adjudication_source") != "committee_edge":
            continue
        winner = str(judgment.get("winner") or "").strip()
        loser = str(judgment.get("loser") or "").strip()
        if not winner or not loser or winner == loser:
            continue
        if committee_edge_cycle_suppressed(judgment) or committee_edge_superseded(judgment):
            continue
        edges.append(judgment)
    return sorted(
        edges,
        key=lambda item: (
            -confidence_rank(item.get("confidence")),
            -committee_confidence_rank(item),
            -committee_read_rank(item),
            str(item.get("pair_key") or pair_key(item.get("winner", ""), item.get("loser", ""))),
            str(item.get("winner", "")),
            str(item.get("loser", "")),
        ),
    )


def crossing_allowed(
    lower_row: dict,
    higher_row: dict,
    direction: dict[tuple[str, str], float],
    raw_scores: dict[str, float],
    *,
    max_cross_level_gap: int,
    max_cross_rubric_gap: float,
    min_crossing_margin: float,
) -> tuple[bool, dict]:
    lower = lower_row["student_id"]
    higher = higher_row["student_id"]
    level_gap = int(round(max(0.0, higher_row["_level_order"] - lower_row["_level_order"])))
    lower_support = direct_weight(direction, lower, higher)
    higher_support = direct_weight(direction, higher, lower)
    margin = lower_support - higher_support
    rubric_gap = higher_row["_rubric_after_penalty_percent"] - lower_row["_rubric_after_penalty_percent"]
    allowed = (
        level_gap <= int(max_cross_level_gap)
        and margin >= float(min_crossing_margin)
        and rubric_gap <= float(max_cross_rubric_gap)
        and float(raw_scores.get(lower, 0.0)) > float(raw_scores.get(higher, 0.0))
    )
    return allowed, {
        "lower": lower,
        "higher": higher,
        "level_gap": level_gap,
        "lower_support": round(lower_support, 6),
        "higher_support": round(higher_support, 6),
        "margin": round(margin, 6),
        "rubric_gap": round(rubric_gap, 6),
        "allowed": allowed,
    }


def path_exists(start: str, target: str, adjacency: dict[str, set[str]]) -> bool:
    if start == target:
        return True
    seen = set()
    stack = [start]
    while stack:
        current = stack.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(sorted(adjacency.get(current, set()) - seen))
    return False


def add_edge(
    adjacency: dict[str, set[str]],
    indegree: dict[str, int],
    edge_notes: list[dict],
    src: str,
    dst: str,
    note: dict,
) -> bool:
    if src == dst or dst in adjacency[src]:
        return False
    if path_exists(dst, src, adjacency):
        return False
    adjacency[src].add(dst)
    indegree[dst] += 1
    edge_notes.append(note)
    return True


def build_constraints(
    rows: list[dict],
    raw_scores: dict[str, float],
    direction: dict[tuple[str, str], float],
    caps: dict[str, dict],
    judgments: list[dict] | None = None,
    *,
    max_cross_level_gap: int,
    max_cross_rubric_gap: float,
    min_crossing_margin: float,
    hard_evidence_margin: float,
) -> tuple[dict[str, set[str]], dict[str, int], dict]:
    rows_by_id = {row["student_id"]: row for row in rows}
    student_ids = [row["student_id"] for row in rows]
    adjacency = {sid: set() for sid in student_ids}
    indegree = {sid: 0 for sid in student_ids}
    added_edges = []
    dropped_edges = []
    allowed_crossings = []
    blocked_crossings = []
    overridden_crossings = []

    for judgment in protected_committee_direct_edges(judgments or []):
        winner = str(judgment.get("winner") or "").strip()
        loser = str(judgment.get("loser") or "").strip()
        note = {
            "kind": COMMITTEE_DIRECT_EDGE_KIND,
            "src": winner,
            "dst": loser,
            "detail": {
                "pair": list(judgment.get("pair", [])),
                "pair_key": str(judgment.get("pair_key") or pair_key(winner, loser)),
                "confidence": normalize_confidence(judgment.get("confidence")),
                "committee_confidence": str(judgment.get("committee_confidence") or ""),
                "adjudication_source": judgment.get("adjudication_source", "committee_edge"),
                "decision": normalize_decision(judgment.get("decision")),
                "decision_basis": str(judgment.get("decision_basis") or ""),
                "cautions_applied": list(judgment.get("cautions_applied", [])) if isinstance(judgment.get("cautions_applied"), list) else [],
                "reason": "protected direct committee-edge adjudication",
            },
        }
        if not add_edge(adjacency, indegree, added_edges, winner, loser, note):
            dropped_edges.append({**note, "reason": "committee_direct_cycle_suppressed_by_rerank_safety"})

    draft_floor_rows = [row for row in rows if row.get("_draft_completion_floor_applied")]
    complete_rows = [row for row in rows if not row.get("_draft_completion_floor_applied")]
    for incomplete in draft_floor_rows:
        for complete in complete_rows:
            note = {
                "kind": "completion_floor",
                "src": complete["student_id"],
                "dst": incomplete["student_id"],
                "detail": {
                    "complete_student_id": complete["student_id"],
                    "incomplete_student_id": incomplete["student_id"],
                    "reason": "completed essays outrank hard-floor incomplete scaffold drafts",
                },
            }
            if not add_edge(adjacency, indegree, added_edges, complete["student_id"], incomplete["student_id"], note):
                dropped_edges.append({**note, "reason": "cycle_avoided"})

    for row in sorted(rows, key=lambda item: int(item["seed_rank"])):
        sid = row["student_id"]
        cap_info = caps.get(sid, {})
        if not cap_info.get("severe_collapse_rescue_cap"):
            continue
        best_rank = int(cap_info["best_rank"])
        for other in rows:
            oid = other["student_id"]
            if oid == sid:
                continue
            if int(other["seed_rank"]) < best_rank:
                note = {
                    "kind": "severe_collapse_rescue_cap_up",
                    "src": oid,
                    "dst": sid,
                    "detail": {"seed_rank": row["seed_rank"], "best_rank": best_rank, "cap": cap_info["cap"]},
                }
                if not add_edge(adjacency, indegree, added_edges, oid, sid, note):
                    dropped_edges.append({**note, "reason": "cycle_avoided"})

    seen_pairs = set()
    for (winner, loser), weight in sorted(direction.items()):
        reverse = direct_weight(direction, loser, winner)
        margin = weight - reverse
        pair_token = tuple(sorted((winner, loser)))
        if pair_token in seen_pairs:
            continue
        seen_pairs.add(pair_token)
        if abs(margin) < float(hard_evidence_margin):
            continue
        src, dst = (winner, loser) if margin > 0 else (loser, winner)
        note = {
            "kind": "strong_pairwise_evidence",
            "src": src,
            "dst": dst,
            "detail": {
                "forward_weight": round(direct_weight(direction, src, dst), 6),
                "reverse_weight": round(direct_weight(direction, dst, src), 6),
                "margin": round(abs(margin), 6),
            },
        }
        if not add_edge(adjacency, indegree, added_edges, src, dst, note):
            dropped_edges.append({**note, "reason": "cycle_avoided"})

    for higher in rows:
        for lower in rows:
            if higher["student_id"] == lower["student_id"]:
                continue
            if higher["_level_order"] <= lower["_level_order"]:
                continue
            stability_penalty = (
                float(caps.get(lower["student_id"], {}).get("stability_penalty", 0.0) or 0.0)
                + float(caps.get(higher["student_id"], {}).get("stability_penalty", 0.0) or 0.0)
            ) / 2.0
            dynamic_margin = float(min_crossing_margin) * (1.0 + stability_penalty)
            allowed, detail = crossing_allowed(
                lower,
                higher,
                direction,
                raw_scores,
                max_cross_level_gap=max_cross_level_gap,
                max_cross_rubric_gap=max_cross_rubric_gap,
                min_crossing_margin=dynamic_margin,
            )
            detail["dynamic_margin"] = round(dynamic_margin, 6)
            detail["stability_penalty"] = round(stability_penalty, 6)
            if allowed:
                allowed_crossings.append(detail)
                continue
            blocked_crossings.append(detail)
            reverse_margin = direct_weight(direction, lower["student_id"], higher["student_id"]) - direct_weight(direction, higher["student_id"], lower["student_id"])
            direct_pairwise_override = (
                int(detail.get("level_gap", 99)) <= 1
                and abs(float(detail.get("rubric_gap", 999.0))) <= max(float(max_cross_rubric_gap), 2.0) + 4.0
                and reverse_margin >= float(hard_evidence_margin)
            )
            if direct_pairwise_override:
                overridden_crossings.append(
                    {
                        **detail,
                        "reason": "direct_high_confidence_pairwise_override",
                        "reverse_margin": round(reverse_margin, 6),
                    }
                )
                continue
            note = {"kind": "level_lock", "src": higher["student_id"], "dst": lower["student_id"], "detail": detail}
            if not add_edge(adjacency, indegree, added_edges, higher["student_id"], lower["student_id"], note):
                dropped_edges.append({**note, "reason": "cycle_avoided"})

    for row in sorted(rows, key=lambda item: (caps[item["student_id"]]["cap"], item["seed_rank"], item["student_id"])):
        sid = row["student_id"]
        cap_info = caps[sid]
        best_rank = int(cap_info["best_rank"])
        worst_rank = int(cap_info["worst_rank"])
        for other in rows:
            oid = other["student_id"]
            if oid == sid:
                continue
            if int(other["seed_rank"]) < best_rank:
                note = {
                    "kind": "displacement_cap_up",
                    "src": oid,
                    "dst": sid,
                    "detail": {"seed_rank": row["seed_rank"], "best_rank": best_rank, "cap": cap_info["cap"]},
                }
                if not add_edge(adjacency, indegree, added_edges, oid, sid, note):
                    dropped_edges.append({**note, "reason": "cycle_avoided"})
            elif int(other["seed_rank"]) > worst_rank:
                note = {
                    "kind": "displacement_cap_down",
                    "src": sid,
                    "dst": oid,
                    "detail": {"seed_rank": row["seed_rank"], "worst_rank": worst_rank, "cap": cap_info["cap"]},
                }
                if not add_edge(adjacency, indegree, added_edges, sid, oid, note):
                    dropped_edges.append({**note, "reason": "cycle_avoided"})

    return adjacency, indegree, {
        "added_edges": added_edges,
        "dropped_edges": dropped_edges,
        "allowed_crossings": allowed_crossings,
        "blocked_crossings": blocked_crossings,
        "overridden_crossings": overridden_crossings,
    }


def weighted_topological_order(rows: list[dict], raw_scores: dict[str, float], prior_scores: dict[str, float], adjacency: dict[str, set[str]], indegree: dict[str, int]) -> list[str]:
    rows_by_id = {row["student_id"]: row for row in rows}
    remaining = set(rows_by_id)
    indegree_work = dict(indegree)
    ordered = []

    def sort_key(student_id: str):
        row = rows_by_id[student_id]
        return (
            -float(raw_scores.get(student_id, 0.0) or 0.0),
            -float(prior_scores.get(student_id, 0.0) or 0.0),
            -float(row["_level_order"] or 0.0),
            int(row["seed_rank"]),
            student_id.lower(),
        )

    while remaining:
        available = sorted((sid for sid in remaining if indegree_work[sid] == 0), key=sort_key)
        if not available:
            available = sorted(remaining, key=sort_key)
        chosen = available[0]
        ordered.append(chosen)
        remaining.remove(chosen)
        for neighbor in adjacency.get(chosen, set()):
            indegree_work[neighbor] = max(0, indegree_work[neighbor] - 1)
    return ordered


def build_final_rows(
    rows: list[dict],
    final_order: list[str],
    raw_scores: dict[str, float],
    prior_scores: dict[str, float],
    teacher_adjustments: dict[str, float],
    teacher_diagnostics: dict[str, dict],
    per_student: dict,
    caps: dict[str, dict],
    constraints: dict,
) -> tuple[list[dict], list[dict]]:
    rows_by_id = {row["student_id"]: row for row in rows}
    final_rank_map = {sid: idx for idx, sid in enumerate(final_order, start=1)}
    edge_counts = defaultdict(int)
    for note in constraints.get("added_edges", []):
        edge_counts[(note["kind"], note["src"])] += 1
        edge_counts[(note["kind"], note["dst"])] += 1

    final_rows = []
    score_rows = []
    for sid in final_order:
        base_row = dict(rows_by_id[sid])
        seed_rank = int(base_row["seed_rank"])
        final_rank = int(final_rank_map[sid])
        displacement = final_rank - seed_rank
        per_student_metrics = per_student.get(sid, {})
        teacher_info = teacher_diagnostics.get(sid, {})
        cap_info = caps.get(sid, {"cap": len(rows), "label": "high_support", "best_rank": 1, "worst_rank": len(rows)})
        notes = []
        if displacement < 0:
            notes.append(f"moved_up_{abs(displacement)}")
        elif displacement > 0:
            notes.append(f"moved_down_{abs(displacement)}")
        else:
            notes.append("held_seed_position")
        if abs(displacement) > int(cap_info["cap"]):
            notes.append("cap_relaxed_for_hard_constraints")
        if cap_info.get("draft_completion_floor_lock"):
            notes.append("draft_completion_floor_lock")
        if cap_info.get("severe_collapse_rescue_cap"):
            notes.append("severe_collapse_rescue_cap")
        if per_student_metrics.get("support_weight", 0.0) > per_student_metrics.get("opposition_weight", 0.0):
            notes.append("net_pairwise_support")
        elif per_student_metrics.get("opposition_weight", 0.0) > per_student_metrics.get("support_weight", 0.0):
            notes.append("net_pairwise_opposition")
        base_row["seed_rank"] = seed_rank
        base_row["consistency_rank"] = final_rank
        base_row["final_rank"] = final_rank
        base_row["rerank_score"] = round(float(raw_scores.get(sid, 0.0) or 0.0), 6)
        base_row["rerank_prior_score"] = round(float(prior_scores.get(sid, 0.0) or 0.0), 6)
        base_row["rerank_support_weight"] = round(float(per_student_metrics.get("support_weight", 0.0) or 0.0), 6)
        base_row["rerank_opposition_weight"] = round(float(per_student_metrics.get("opposition_weight", 0.0) or 0.0), 6)
        base_row["rerank_incident_weight"] = round(float(per_student_metrics.get("incident_weight", 0.0) or 0.0), 6)
        base_row["teacher_preference_adjustment"] = round(float(teacher_adjustments.get(sid, 0.0) or 0.0), 6)
        base_row["teacher_preference_uncertainty_gate"] = round(float(teacher_info.get("uncertainty_gate", 0.0) or 0.0), 6)
        base_row["teacher_preference_reasons"] = ";".join(teacher_info.get("reasons", [])) if teacher_info.get("reasons") else ""
        base_row["rerank_displacement"] = displacement
        base_row["rerank_displacement_cap"] = int(cap_info["cap"])
        base_row["rerank_displacement_cap_label"] = cap_info["label"]
        base_row["rerank_best_rank"] = int(cap_info["best_rank"])
        base_row["rerank_worst_rank"] = int(cap_info["worst_rank"])
        base_row["rerank_up_cap"] = int(cap_info.get("up_cap", cap_info["cap"]))
        base_row["rerank_down_cap"] = int(cap_info.get("down_cap", cap_info["cap"]))
        base_row["rerank_notes"] = ";".join(notes)
        final_rows.append(base_row)
        score_rows.append(
            {
                "student_id": sid,
                "seed_rank": seed_rank,
                "final_rank": final_rank,
                "adjusted_level": base_row.get("adjusted_level") or base_row.get("base_level") or "",
                "rubric_after_penalty_percent": base_row.get("rubric_after_penalty_percent") or base_row.get("rubric_mean_percent") or "",
                "composite_score": base_row.get("composite_score", ""),
                "rerank_prior_score": base_row["rerank_prior_score"],
                "rerank_score": base_row["rerank_score"],
                "pairwise_support_weight": base_row["rerank_support_weight"],
                "pairwise_opposition_weight": base_row["rerank_opposition_weight"],
                "pairwise_incident_weight": base_row["rerank_incident_weight"],
                "teacher_preference_adjustment": base_row["teacher_preference_adjustment"],
                "teacher_preference_uncertainty_gate": base_row["teacher_preference_uncertainty_gate"],
                "teacher_preference_reasons": base_row["teacher_preference_reasons"],
                "displacement": displacement,
                "displacement_cap": int(cap_info["cap"]),
                "displacement_cap_label": cap_info["label"],
                "constraint_touch_count": (
                    edge_counts.get(("level_lock", sid), 0)
                    + edge_counts.get(("strong_pairwise_evidence", sid), 0)
                    + edge_counts.get((COMMITTEE_DIRECT_EDGE_KIND, sid), 0)
                ),
                "notes": base_row["rerank_notes"],
            }
        )
    return final_rows, score_rows


def pairwise_agreement(final_rank_map: dict[str, int], judgments: list[dict]) -> float:
    if not judgments:
        return 1.0
    total = 0.0
    agree = 0.0
    for judgment in judgments:
        weight = float(judgment["weight"] or 0.0)
        total += weight
        if final_rank_map[judgment["winner"]] < final_rank_map[judgment["loser"]]:
            agree += weight
    return round((agree / total) if total else 1.0, 6)


def direct_edge_diagnostics(final_rank_map: dict[str, int], judgments: list[dict], constraints: dict | None = None) -> dict:
    constraints = constraints if isinstance(constraints, dict) else {}
    added_edges = {
        (str(item.get("src", "")), str(item.get("dst", "")), str(item.get("kind", "")))
        for item in constraints.get("added_edges", [])
        if isinstance(item, dict)
    }
    dropped_edges = {
        (str(item.get("src", "")), str(item.get("dst", "")), str(item.get("kind", "")))
        for item in constraints.get("dropped_edges", [])
        if isinstance(item, dict)
    }
    violations = []
    satisfied = 0
    committee_total = 0
    committee_satisfied = 0
    committee_violations = 0
    committee_added = 0
    committee_dropped = 0
    total_weight = 0.0
    violated_weight = 0.0
    high_confidence_violations = 0
    for judgment in judgments:
        winner = str(judgment.get("winner", "") or "").strip()
        loser = str(judgment.get("loser", "") or "").strip()
        if winner not in final_rank_map or loser not in final_rank_map or winner == loser:
            continue
        source = str(judgment.get("adjudication_source", "cheap_pairwise") or "cheap_pairwise")
        is_committee = source == "committee_edge"
        committee_edge_added = (winner, loser, COMMITTEE_DIRECT_EDGE_KIND) in added_edges
        committee_edge_dropped = (winner, loser, COMMITTEE_DIRECT_EDGE_KIND) in dropped_edges
        if is_committee:
            committee_total += 1
            committee_added += int(committee_edge_added)
            committee_dropped += int(committee_edge_dropped)
        weight = float(judgment.get("weight", 0.0) or 0.0)
        total_weight += weight
        winner_rank = int(final_rank_map[winner])
        loser_rank = int(final_rank_map[loser])
        if winner_rank < loser_rank:
            satisfied += 1
            if is_committee:
                committee_satisfied += 1
            continue
        violated_weight += weight
        if is_committee:
            committee_violations += 1
        if normalize_confidence(judgment.get("confidence")) == "high":
            high_confidence_violations += 1
        violations.append(
            {
                "pair": list(judgment.get("pair", [])),
                "winner": winner,
                "loser": loser,
                "winner_final_rank": winner_rank,
                "loser_final_rank": loser_rank,
                "adjudication_source": source,
                "confidence": normalize_confidence(judgment.get("confidence")),
                "weight": round(weight, 6),
                "decision": normalize_decision(judgment.get("decision")),
                "decision_basis": str(judgment.get("decision_basis", "") or ""),
                "cautions_applied": list(judgment.get("cautions_applied", [])) if isinstance(judgment.get("cautions_applied"), list) else [],
                "rationale": str(judgment.get("rationale", "") or "").strip(),
                "committee_direct_edge_added": committee_edge_added,
                "committee_direct_edge_dropped": committee_edge_dropped,
                "strong_pairwise_edge_added": (winner, loser, "strong_pairwise_evidence") in added_edges,
                "strong_pairwise_edge_dropped": (winner, loser, "strong_pairwise_evidence") in dropped_edges,
            }
        )
    total = satisfied + len(violations)
    return {
        "direct_edge_count": total,
        "direct_edge_satisfied_count": satisfied,
        "direct_edge_violation_count": len(violations),
        "high_confidence_direct_edge_violation_count": high_confidence_violations,
        "committee_direct_edge_count": committee_total,
        "committee_direct_edge_satisfied_count": committee_satisfied,
        "committee_direct_edge_violation_count": committee_violations,
        "committee_direct_edge_added_count": committee_added,
        "committee_direct_edge_dropped_count": committee_dropped,
        "direct_edge_violation_weight": round(violated_weight, 6),
        "direct_edge_weight": round(total_weight, 6),
        "direct_edge_violation_rate": round((len(violations) / total) if total else 0.0, 6),
        "direct_edge_weighted_violation_rate": round((violated_weight / total_weight) if total_weight else 0.0, 6),
        "violations": violations,
    }


def write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def run_global_rerank(
    *,
    scores_path: Path,
    judgments_path: Path,
    config_path: Path,
    local_prior_path: Path,
    final_order_path: Path,
    matrix_output_path: Path,
    score_output_path: Path,
    report_output_path: Path,
    legacy_output_path: Path,
    iterations: int,
    learning_rate: float,
    regularization: float,
    low_confidence_max_displacement: int,
    medium_confidence_max_displacement: int,
    high_confidence_max_displacement: int,
    max_cross_level_gap: int,
    max_cross_rubric_gap: float,
    min_crossing_margin: float,
    hard_evidence_margin: float,
) -> dict:
    config = load_json(config_path)
    rows = load_seed_rows(scores_path, config if isinstance(config, dict) else {})
    if not rows:
        raise ValueError(f"No seed ranking rows found in {scores_path}")
    rows_by_id = {row["student_id"]: row for row in rows}
    raw_judgment_payload, judgments = load_judgments(judgments_path, rows_by_id)
    matrix, per_student, directional = build_pairwise_matrix(rows, judgments)
    boundary_conflicts, conflict_summary = pairwise_conflict_stats(
        rows,
        matrix.get("comparisons", []),
        level_boundaries_from_config(config if isinstance(config, dict) else {}),
    )
    for sid, stats in boundary_conflicts.items():
        existing = per_student.setdefault(sid, {})
        existing.update(stats)
    base_prior_scores = build_prior_scores(rows)
    local_prior_payload = load_json(local_prior_path)
    anchor_active = str(os.environ.get("ANCHOR_CALIBRATION_ACTIVE", "") or "").strip().lower() in {"1", "true", "yes"}
    if anchor_active:
        teacher_adjustments = {row["student_id"]: 0.0 for row in rows}
        teacher_meta = {
            "active": False,
            "scope_match": True,
            "reason": "suppressed_by_anchor_calibration",
            "students": {},
        }
    else:
        teacher_adjustments, teacher_meta = compute_teacher_preference_adjustments(
            rows,
            per_student,
            local_prior_payload,
            current_scope=current_run_scope(scores_path),
            boundaries=level_boundaries_from_config(config if isinstance(config, dict) else {}),
        )
    prior_scores = {
        sid: round(float(base_prior_scores.get(sid, 0.0) or 0.0) + float(teacher_adjustments.get(sid, 0.0) or 0.0), 6)
        for sid in base_prior_scores
    }
    student_ids = [row["student_id"] for row in rows]
    raw_scores = optimize_scores(
        student_ids,
        prior_scores,
        judgments,
        iterations=iterations,
        learning_rate=learning_rate,
        regularization=regularization,
    )
    caps = compute_displacement_caps(
        rows,
        per_student,
        low_cap=low_confidence_max_displacement,
        medium_cap=medium_confidence_max_displacement,
        high_cap=high_confidence_max_displacement,
    )
    adjacency, indegree, constraint_meta = build_constraints(
        rows,
        raw_scores,
        directional,
        caps,
        judgments,
        max_cross_level_gap=max_cross_level_gap,
        max_cross_rubric_gap=max_cross_rubric_gap,
        min_crossing_margin=min_crossing_margin,
        hard_evidence_margin=hard_evidence_margin,
    )
    final_order = weighted_topological_order(rows, raw_scores, prior_scores, adjacency, indegree)
    final_rows, score_rows = build_final_rows(
        rows,
        final_order,
        raw_scores,
        prior_scores,
        teacher_adjustments,
        teacher_meta.get("students", {}) if isinstance(teacher_meta, dict) else {},
        per_student,
        caps,
        constraint_meta,
    )
    final_rank_map = {row["student_id"]: int(row["final_rank"]) for row in final_rows}
    agreement = pairwise_agreement(final_rank_map, judgments)
    direct_edges = direct_edge_diagnostics(final_rank_map, judgments, constraint_meta)
    swap_count = sum(1 for judgment in judgments if judgment.get("decision") == "SWAP")
    low_confidence_count = sum(1 for judgment in judgments if judgment.get("confidence") == "low")
    movements = [
        {
            "student_id": row["student_id"],
            "seed_rank": int(row["seed_rank"]),
            "final_rank": int(row["final_rank"]),
            "displacement": int(row["rerank_displacement"]),
            "displacement_cap": int(row["rerank_displacement_cap"]),
            "displacement_cap_label": row["rerank_displacement_cap_label"],
            "rerank_score": row["rerank_score"],
            "rerank_prior_score": row["rerank_prior_score"],
            "support_weight": row["rerank_support_weight"],
            "opposition_weight": row["rerank_opposition_weight"],
            "teacher_preference_adjustment": row["teacher_preference_adjustment"],
            "teacher_preference_uncertainty_gate": row["teacher_preference_uncertainty_gate"],
            "pairwise_conflict_density": round(float(per_student.get(row["student_id"], {}).get("pairwise_conflict_density", 0.0) or 0.0), 6),
            "boundary_conflict_pairs": int(per_student.get(row["student_id"], {}).get("boundary_conflict_pairs", 0) or 0),
            "stability_penalty": round(float(caps.get(row["student_id"], {}).get("stability_penalty", 0.0) or 0.0), 6),
            "notes": row["rerank_notes"].split(";") if row["rerank_notes"] else [],
        }
        for row in final_rows
    ]
    report = {
        "generated_at": now_iso(),
        "method": "regularized_pairwise_logistic_toposort",
        "deterministic": True,
        "inputs": {
            "scores": str(scores_path),
            "judgments": str(judgments_path),
            "config": str(config_path),
            "local_prior": str(local_prior_path),
        },
        "hyperparameters": {
            "iterations": int(iterations),
            "learning_rate": float(learning_rate),
            "regularization": float(regularization),
            "low_confidence_max_displacement": int(low_confidence_max_displacement),
            "medium_confidence_max_displacement": int(medium_confidence_max_displacement),
            "high_confidence_max_displacement": int(high_confidence_max_displacement),
            "max_cross_level_gap": int(max_cross_level_gap),
            "max_cross_rubric_gap": float(max_cross_rubric_gap),
            "min_crossing_margin": float(min_crossing_margin),
            "hard_evidence_margin": float(hard_evidence_margin),
        },
        "summary": {
            "student_count": len(rows),
            "judgment_count": len(judgments),
            "comparison_count": matrix["comparison_count"],
            "pairwise_agreement_with_final_order": agreement,
            "swap_rate": round((swap_count / len(judgments)) if judgments else 0.0, 6),
            "low_confidence_rate": round((low_confidence_count / len(judgments)) if judgments else 0.0, 6),
            "max_displacement": max(abs(int(row["rerank_displacement"])) for row in final_rows),
            "mean_abs_displacement": round(sum(abs(int(row["rerank_displacement"])) for row in final_rows) / len(final_rows), 6),
            "mean_stability_penalty": round(sum(float(caps[row["student_id"]]["stability_penalty"]) for row in rows) / len(rows), 6),
            "pairwise_conflict_density": conflict_summary["pairwise_conflict_density"],
            "boundary_disagreement_concentration": conflict_summary["boundary_disagreement_concentration"],
            "level_lock_edges_added": sum(1 for item in constraint_meta["added_edges"] if item["kind"] == "level_lock"),
            "strong_pairwise_edges_added": sum(1 for item in constraint_meta["added_edges"] if item["kind"] == "strong_pairwise_evidence"),
            "committee_direct_edges_added": sum(1 for item in constraint_meta["added_edges"] if item["kind"] == COMMITTEE_DIRECT_EDGE_KIND),
            "cap_edges_added": sum(1 for item in constraint_meta["added_edges"] if item["kind"].startswith("displacement_cap")),
            "dropped_edges": len(constraint_meta["dropped_edges"]),
            "allowed_crossings": len(constraint_meta["allowed_crossings"]),
            "blocked_crossings": len(constraint_meta["blocked_crossings"]),
            "direct_edge_violations": direct_edges["direct_edge_violation_count"],
            "high_confidence_direct_edge_violations": direct_edges["high_confidence_direct_edge_violation_count"],
            "committee_direct_edge_violations": direct_edges["committee_direct_edge_violation_count"],
            "direct_edge_weighted_violation_rate": direct_edges["direct_edge_weighted_violation_rate"],
        },
        "constraints": constraint_meta,
        "direct_edge_diagnostics": direct_edges,
        "movements": movements,
        "teacher_prior": {
            "active": bool(teacher_meta.get("active", False)) if isinstance(teacher_meta, dict) else False,
            "scope_match": bool(teacher_meta.get("scope_match", True)) if isinstance(teacher_meta, dict) else True,
            "reason": str(teacher_meta.get("reason", "") or "") if isinstance(teacher_meta, dict) else "",
            "weights": local_prior_payload.get("weights", {}) if isinstance(local_prior_payload, dict) else {},
            "support": local_prior_payload.get("support", {}) if isinstance(local_prior_payload, dict) else {},
            "suppressed_by_anchor_calibration": anchor_active,
        },
        "raw_judgments": {
            "generated_at": raw_judgment_payload.get("generated_at", ""),
            "model": raw_judgment_payload.get("model", ""),
            "comparison_window": raw_judgment_payload.get("comparison_window"),
        },
    }
    matrix["pairwise_agreement_with_final_order"] = agreement
    matrix["source_judgments"] = str(judgments_path)
    score_output_path.parent.mkdir(parents=True, exist_ok=True)
    final_order_path.parent.mkdir(parents=True, exist_ok=True)
    matrix_output_path.parent.mkdir(parents=True, exist_ok=True)
    report_output_path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(score_output_path, score_rows)
    write_csv(final_order_path, final_rows)
    write_csv(legacy_output_path, final_rows)
    matrix_output_path.write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    report_output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {
        "final_rows": final_rows,
        "score_rows": score_rows,
        "matrix": matrix,
        "report": report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fit a deterministic global reranker from seed scores and pairwise evidence.")
    parser.add_argument("--input", default="outputs/consensus_scores.csv", help="Seed ranking CSV")
    parser.add_argument("--judgments", default="outputs/consistency_checks.json", help="Pairwise judgments JSON")
    parser.add_argument("--config", default="config/marking_config.json", help="Marking config JSON")
    parser.add_argument("--local-prior", default="outputs/local_teacher_prior.json", help="Local teacher prior JSON")
    parser.add_argument("--output", default="outputs/final_order.csv", help="Final reranked CSV")
    parser.add_argument("--matrix-output", default="outputs/pairwise_matrix.json", help="Pairwise matrix JSON")
    parser.add_argument("--scores-output", default="outputs/rerank_scores.csv", help="Rerank score CSV")
    parser.add_argument("--report", default="outputs/consistency_report.json", help="Consistency report JSON")
    parser.add_argument("--legacy-output", default="outputs/consistency_adjusted.csv", help="Compatibility CSV alias")
    parser.add_argument("--iterations", type=int, default=300, help="Gradient iterations")
    parser.add_argument("--learning-rate", type=float, default=0.18, help="Gradient learning rate")
    parser.add_argument("--regularization", type=float, default=0.75, help="Prior regularization strength")
    parser.add_argument("--low-confidence-max-displacement", type=int, default=1, help="Max displacement for low-support rows")
    parser.add_argument("--medium-confidence-max-displacement", type=int, default=3, help="Max displacement for medium-support rows")
    parser.add_argument("--high-confidence-max-displacement", type=int, default=999999, help="Max displacement for high-support rows")
    parser.add_argument("--max-cross-level-gap", type=int, default=1, help="Maximum level gap eligible for a justified crossing")
    parser.add_argument("--max-cross-rubric-gap", type=float, default=2.0, help="Maximum rubric gap allowed for a boundary crossing")
    parser.add_argument("--min-crossing-margin", type=float, default=1.5, help="Minimum direct evidence margin required for a boundary crossing")
    parser.add_argument("--hard-evidence-margin", type=float, default=1.5, help="Minimum direct evidence margin to add a hard pairwise precedence edge")
    args = parser.parse_args()

    try:
        result = run_global_rerank(
            scores_path=Path(args.input),
            judgments_path=Path(args.judgments),
            config_path=Path(args.config),
            local_prior_path=Path(args.local_prior),
            final_order_path=Path(args.output),
            matrix_output_path=Path(args.matrix_output),
            score_output_path=Path(args.scores_output),
            report_output_path=Path(args.report),
            legacy_output_path=Path(args.legacy_output),
            iterations=args.iterations,
            learning_rate=args.learning_rate,
            regularization=args.regularization,
            low_confidence_max_displacement=args.low_confidence_max_displacement,
            medium_confidence_max_displacement=args.medium_confidence_max_displacement,
            high_confidence_max_displacement=args.high_confidence_max_displacement,
            max_cross_level_gap=args.max_cross_level_gap,
            max_cross_rubric_gap=args.max_cross_rubric_gap,
            min_crossing_margin=args.min_crossing_margin,
            hard_evidence_margin=args.hard_evidence_margin,
        )
    except ValueError as exc:
        print(exc)
        return 1

    print(f"Wrote {args.output}")
    print(f"Wrote {args.matrix_output}")
    print(f"Wrote {args.scores_output}")
    print(f"Wrote {args.report}")
    print(
        json.dumps(
            {
                "student_count": result["report"]["summary"]["student_count"],
                "judgment_count": result["report"]["summary"]["judgment_count"],
                "pairwise_agreement_with_final_order": result["report"]["summary"]["pairwise_agreement_with_final_order"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
