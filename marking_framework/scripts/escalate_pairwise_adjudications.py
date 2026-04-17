#!/usr/bin/env python3
import argparse
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.assessor_utils import load_file_text, resolve_input_path
    from scripts import verify_consistency as vc
except ImportError:  # pragma: no cover - Support running as a script
    from assessor_utils import load_file_text, resolve_input_path  # pragma: no cover
    import verify_consistency as vc  # type: ignore  # pragma: no cover


DEFAULT_CANDIDATES = "outputs/pairwise_escalation_candidates.json"
DEFAULT_ESCALATIONS = "outputs/pairwise_escalations.json"
DEFAULT_MERGED = "outputs/consistency_checks.escalated.json"
SURFACE_BASES = {"organization", "language_control"}
CAUTION_TRIGGERS = {
    "rougher_but_stronger_content",
    "formulaic_but_thin",
    "polished_but_shallow",
    "mechanics_impede_meaning",
}
LARGE_MOVER_REASONS = {
    "large_mover_top_pack",
    "large_mover_neighborhood",
    "aggregate_divergence_reach",
}
UNCERTAINTY_REASONS = {
    "uncertainty_challenger",
}
DEFAULT_TOP_PACK_SIZE = 10


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def pair_key(left: str, right: str) -> str:
    ordered = sorted((str(left).strip(), str(right).strip()))
    return f"{ordered[0]}::{ordered[1]}"


def pair_key_from_item(item: dict) -> str:
    pair = item.get("pair") if isinstance(item.get("pair"), list) else []
    if len(pair) != 2:
        return ""
    left, right = str(pair[0] or "").strip(), str(pair[1] or "").strip()
    return pair_key(left, right) if left and right and left != right else ""


def normalized_source(item: dict) -> str:
    metadata = item.get("model_metadata") if isinstance(item.get("model_metadata"), dict) else {}
    source = str(metadata.get("adjudication_source") or item.get("adjudication_source") or "").strip()
    if source:
        return source
    if isinstance(metadata.get("orientation_audit"), dict):
        return "orientation_audit"
    return "cheap_pairwise"


def task_config(routing: dict, task_name: str) -> dict:
    tasks = routing.get("tasks", {}) if isinstance(routing.get("tasks"), dict) else {}
    item = tasks.get(task_name, {}) if isinstance(tasks, dict) else {}
    return item if isinstance(item, dict) else {}


def confidence_is_low_or_medium(value) -> bool:
    return vc.normalize_confidence(value) in {"low", "medium"}


def row_support(row: dict, student_count: int) -> float:
    seed_pct = vc.seed_percentile(int(row.get("seed_rank", 1) or 1), max(1, int(student_count or 1)))
    return max(
        vc.clamp01(row.get("borda_percent"), seed_pct),
        vc.clamp01(row.get("composite_score"), seed_pct),
        0.0,
    )


def rank_bucket(row: dict, student_count: int) -> float:
    return vc.seed_percentile(int(row.get("seed_rank", 1) or 1), student_count)


def level_value(row: dict) -> str:
    return str(row.get("level") or row.get("adjusted_level") or row.get("base_level") or "").strip()


def compact_judgment(item: dict) -> dict:
    metadata = item.get("model_metadata") if isinstance(item.get("model_metadata"), dict) else {}
    audit = metadata.get("orientation_audit") if isinstance(metadata.get("orientation_audit"), dict) else {}
    pair = list(item.get("pair", [])) if isinstance(item.get("pair"), list) else []
    seed_order = dict(item.get("seed_order", {})) if isinstance(item.get("seed_order"), dict) else {}
    higher = str(seed_order.get("higher") or (pair[0] if len(pair) > 0 else "") or "").strip()
    lower = str(seed_order.get("lower") or (pair[1] if len(pair) > 1 else "") or "").strip()
    decision = vc.decision_from_winner_side(item.get("winner_side")) or vc.normalize_decision(item.get("decision"))
    winner = str(item.get("winner", "") or "").strip() or (lower if decision == "SWAP" else higher)
    loser = str(item.get("loser", "") or "").strip() or (higher if decision == "SWAP" else lower)
    return {
        "pair": pair,
        "seed_order": seed_order,
        "winner": winner,
        "loser": loser,
        "winner_side": vc.normalize_winner_side(item.get("winner_side")) or vc.winner_side_from_decision(item.get("decision")),
        "decision": decision,
        "confidence": vc.normalize_confidence(item.get("confidence")),
        "decision_basis": vc.normalize_decision_basis(item.get("decision_basis")),
        "cautions_applied": vc.normalize_cautions(item.get("cautions_applied")),
        "decision_checks": vc.normalize_decision_checks(item.get("decision_checks")),
        "selection_reasons": list(item.get("selection_reasons", [])) if isinstance(item.get("selection_reasons"), list) else [],
        "rationale": str(item.get("rationale", "") or "")[:900],
        "adjudication_source": normalized_source(item),
        "orientation_audit_status": str(audit.get("status", "") or ""),
    }


def seed_order_for_pair(item: dict, rows_by_id: dict[str, dict]) -> tuple[dict, dict] | None:
    pair = item.get("pair") if isinstance(item.get("pair"), list) else []
    if len(pair) != 2:
        return None
    left_id, right_id = str(pair[0] or "").strip(), str(pair[1] or "").strip()
    if left_id not in rows_by_id or right_id not in rows_by_id:
        return None
    left, right = rows_by_id[left_id], rows_by_id[right_id]
    ordered = sorted([left, right], key=lambda row: (int(row.get("seed_rank", 999999) or 999999), row["student_id"]))
    return ordered[0], ordered[1]


def winner_loser_from_item(item: dict, rows_by_id: dict[str, dict]) -> tuple[str, str]:
    pair_order = seed_order_for_pair(item, rows_by_id)
    if not pair_order:
        return "", ""
    higher, lower = pair_order
    winner = str(item.get("winner", "") or "").strip()
    loser = str(item.get("loser", "") or "").strip()
    if winner in rows_by_id and loser in rows_by_id and winner != loser:
        return winner, loser
    decision = vc.decision_from_winner_side(item.get("winner_side")) or vc.normalize_decision(item.get("decision"))
    winner = vc.pair_winner_from_decision(higher, lower, decision)
    loser = vc.pair_loser_from_decision(higher, lower, decision)
    return winner, loser


def band_seam_pair_keys(report: dict) -> set[str]:
    keys = set()
    for item in report.get("pairwise_checks_needed", []) if isinstance(report.get("pairwise_checks_needed"), list) else []:
        if not isinstance(item, dict):
            continue
        left = str(item.get("higher_candidate") or item.get("student_id") or "").strip()
        right = str(item.get("lower_candidate") or item.get("comparison_student_id") or "").strip()
        if left and right and left != right:
            keys.add(pair_key(left, right))
    return keys


def matrix_direct_support(matrix: dict) -> dict[str, dict]:
    support = {}
    comparisons = matrix.get("comparisons", []) if isinstance(matrix.get("comparisons"), list) else []
    for comparison in comparisons:
        if not isinstance(comparison, dict):
            continue
        pair = comparison.get("pair") if isinstance(comparison.get("pair"), list) else []
        if len(pair) != 2:
            continue
        left, right = str(pair[0] or "").strip(), str(pair[1] or "").strip()
        if not left or not right or left == right:
            continue
        support[pair_key(left, right)] = {
            "pair": [left, right],
            "left_over_right_weight": float(comparison.get("left_over_right_weight", 0.0) or 0.0),
            "right_over_left_weight": float(comparison.get("right_over_left_weight", 0.0) or 0.0),
            "net_preference": float(comparison.get("net_preference", 0.0) or 0.0),
            "judgment_count": int(comparison.get("judgment_count", 0) or 0),
            "confidence_counts": dict(comparison.get("confidence_counts", {})) if isinstance(comparison.get("confidence_counts"), dict) else {},
        }
    return support


def aggregate_support_detail(row: dict, student_count: int) -> dict:
    seed_pct = rank_bucket(row, student_count)
    borda_pct = vc.clamp01(row.get("borda_percent"), seed_pct)
    composite_pct = vc.clamp01(row.get("composite_score"), seed_pct)
    return {
        "student_id": row["student_id"],
        "seed_rank": int(row.get("seed_rank", 0) or 0),
        "seed_percentile": round(seed_pct, 6),
        "borda_percent": round(borda_pct, 6),
        "composite_score": round(composite_pct, 6),
        "support_peak": round(max(borda_pct, composite_pct), 6),
        "positive_support_divergence": round(vc.positive_support_divergence(row, student_count), 6),
        "rank_divergence": round(vc.rank_divergence(row, student_count), 6),
        "level": level_value(row),
    }


def selection_detail_lines(candidate: dict) -> list[str]:
    lines = [
        "Escalated adjudication: a cheaper broad-screen pairwise judgment hit one or more instability guards.",
        f"Escalation triggers: {', '.join(candidate.get('triggers', [])) or 'unspecified'}",
    ]
    cheap = candidate.get("cheap_judgment", {})
    if cheap:
        lines.append(
            "Cheap judgment summary: "
            f"winner={cheap.get('winner', '')}, confidence={cheap.get('confidence', '')}, "
            f"basis={cheap.get('decision_basis', '')}, cautions={cheap.get('cautions_applied', [])}."
        )
    support = candidate.get("aggregate_support", {})
    for side in ("left", "right"):
        item = support.get(side, {}) if isinstance(support.get(side), dict) else {}
        if item:
            lines.append(
                f"Aggregate support for {item.get('student_id', side)}: seed_rank={item.get('seed_rank')}, "
                f"Borda={item.get('borda_percent')}, composite={item.get('composite_score')}, level={item.get('level')}."
            )
    direct = candidate.get("direct_support", {})
    if direct:
        lines.append(f"Existing direct pairwise support for this pair: {direct}.")
    lines.append(
        "Use these signals only as instability context. The final winner must come from re-reading the essays against the rubric and assignment."
    )
    return lines


def candidate_triggers(
    item: dict,
    rows_by_id: dict[str, dict],
    *,
    student_count: int,
    genre: str,
    band_keys: set[str],
    matrix_support: dict[str, dict],
    top_pack_size: int,
    support_margin: float,
) -> tuple[list[str], dict]:
    key = pair_key_from_item(item)
    if not key:
        return [], {}
    pair_order = seed_order_for_pair(item, rows_by_id)
    if not pair_order:
        return [], {}
    higher, lower = pair_order
    winner, loser = winner_loser_from_item(item, rows_by_id)
    winner_row = rows_by_id.get(winner, {})
    loser_row = rows_by_id.get(loser, {})
    reasons = set(str(reason or "").strip() for reason in item.get("selection_reasons", []) if str(reason or "").strip()) if isinstance(item.get("selection_reasons"), list) else set()
    metadata = item.get("model_metadata") if isinstance(item.get("model_metadata"), dict) else {}
    audit = metadata.get("orientation_audit") if isinstance(metadata.get("orientation_audit"), dict) else {}
    decision_basis = vc.normalize_decision_basis(item.get("decision_basis"))
    cautions = set(vc.normalize_cautions(item.get("cautions_applied")))
    triggers = []
    details = {}

    if "top_pack" in reasons or (int(higher.get("seed_rank", 999999) or 999999) <= top_pack_size and int(lower.get("seed_rank", 999999) or 999999) <= top_pack_size):
        triggers.append("top_pack")
    if "band_seam_requested" in reasons or key in band_keys:
        triggers.append("band_seam_requested")
    if reasons & LARGE_MOVER_REASONS or any(vc.rank_divergence(row, student_count) >= 0.35 for row in (higher, lower)):
        triggers.append("large_mover")
    if reasons & UNCERTAINTY_REASONS:
        triggers.append("uncertainty_challenger")
    if audit and str(audit.get("status", "") or "") != "agreement":
        triggers.append("orientation_audit_conflict")
        details["orientation_audit_status"] = audit.get("status", "")
    if genre == "literary_analysis" and confidence_is_low_or_medium(item.get("confidence")):
        triggers.append("low_medium_confidence_literary")
    if decision_basis in SURFACE_BASES or (decision_basis == "completion" and ("incomplete_or_scaffold" not in cautions)):
        triggers.append("surface_form_winner")
    if cautions & CAUTION_TRIGGERS:
        triggers.append("caution_risk")
        details["cautions"] = sorted(cautions & CAUTION_TRIGGERS)
    if winner_row and loser_row:
        winner_support = row_support(winner_row, student_count)
        loser_support = row_support(loser_row, student_count)
        if loser_support - winner_support >= float(support_margin):
            triggers.append("contradicts_aggregate_support")
            details["aggregate_support_margin"] = round(loser_support - winner_support, 6)
    if key in matrix_support:
        direct = matrix_support[key]
        pair = direct.get("pair", [])
        if len(pair) == 2 and winner in pair and loser in pair:
            winner_direction = f"{winner}>{loser}"
            # The matrix stores oriented left/right weights; convert only for the two possible directions.
            if winner == pair[0] and loser == pair[1]:
                loser_weight = float(direct.get("right_over_left_weight", 0.0) or 0.0)
                winner_weight = float(direct.get("left_over_right_weight", 0.0) or 0.0)
            elif winner == pair[1] and loser == pair[0]:
                loser_weight = float(direct.get("left_over_right_weight", 0.0) or 0.0)
                winner_weight = float(direct.get("right_over_left_weight", 0.0) or 0.0)
            else:
                loser_weight = winner_weight = 0.0
            if loser_weight - winner_weight >= 1.5:
                triggers.append("contradicts_direct_comparative_support")
                details["direct_support_margin"] = round(loser_weight - winner_weight, 6)
                details["winner_direction"] = winner_direction
    top_boundary = int(higher.get("seed_rank", 999999) or 999999) <= 10 or int(lower.get("seed_rank", 999999) or 999999) <= 10
    top_cross = (
        int(higher.get("seed_rank", 999999) or 999999) <= 10 < int(lower.get("seed_rank", 999999) or 999999)
        or int(lower.get("seed_rank", 999999) or 999999) <= 10 < int(higher.get("seed_rank", 999999) or 999999)
    )
    level_cross = level_value(higher) and level_value(lower) and level_value(higher) != level_value(lower)
    details["top10_involved"] = bool(top_boundary)
    details["top10_cross"] = bool(top_cross)
    details["level_cross"] = bool(level_cross)
    if top_boundary or top_cross or level_cross:
        triggers.append("top10_or_level_boundary")
    return sorted(set(triggers)), details


def candidate_priority(candidate: dict) -> tuple[int, int, int, str]:
    triggers = set(candidate.get("triggers", []))
    details = candidate.get("trigger_details", {}) if isinstance(candidate.get("trigger_details"), dict) else {}
    selection_reasons = set(candidate.get("selection_reasons", [])) if isinstance(candidate.get("selection_reasons"), list) else set()
    seed_order = candidate.get("seed_order", {}) if isinstance(candidate.get("seed_order"), dict) else {}
    higher_rank = int(seed_order.get("higher_rank", 999999) or 999999)
    lower_rank = int(seed_order.get("lower_rank", 999999) or 999999)
    score = 0
    if "top_pack" in triggers:
        score += 120
    if "large_mover_top_pack" in selection_reasons:
        score += 100
    if "band_seam_requested" in triggers:
        score += 95
    if "cross_band_challenger" in selection_reasons:
        score += 90
    if "uncertainty_challenger" in triggers:
        score += 120
        if details.get("top10_cross"):
            score += 180
        if details.get("level_cross"):
            score += 80
        if higher_rank <= 4:
            score += 90
        elif higher_rank <= 10:
            score += 35
    if is_cross_band_frontier_candidate(candidate):
        score += 300
        if "contradicts_aggregate_support" in triggers:
            score += 80
        if "orientation_audit_conflict" in triggers:
            score += 50
        if "caution_risk" in triggers:
            score += 40
        if higher_rank == 1:
            score += 40
        elif higher_rank <= 3:
            score += 25
    if higher_rank <= 6 and lower_rank <= 12:
        score += 55
    elif higher_rank <= 10 and lower_rank <= 15:
        score += 35
    if details.get("level_cross"):
        score += 75
    if "orientation_audit_conflict" in triggers:
        score += 65
    if "contradicts_direct_comparative_support" in triggers:
        score += 80
    if "contradicts_aggregate_support" in triggers:
        score += 75
    if "caution_risk" in triggers:
        score += 55
    if "surface_form_winner" in triggers:
        score += 52
    if "low_medium_confidence_literary" in triggers:
        score += 50
    if details.get("top10_cross"):
        score += 42
    elif "top10_or_level_boundary" in triggers:
        score += 30
    if "large_mover" in triggers:
        score += 25
    return (-score, higher_rank, lower_rank, str(candidate.get("pair_key", "")))


def is_cross_band_frontier_candidate(candidate: dict) -> bool:
    selection_reasons = set(candidate.get("selection_reasons", [])) if isinstance(candidate.get("selection_reasons"), list) else set()
    if "cross_band_challenger" not in selection_reasons:
        return False
    seed_order = candidate.get("seed_order", {}) if isinstance(candidate.get("seed_order"), dict) else {}
    higher_rank = int(seed_order.get("higher_rank", 999999) or 999999)
    lower_rank = int(seed_order.get("lower_rank", 999999) or 999999)
    top_pack_size = int(candidate.get("top_pack_size", DEFAULT_TOP_PACK_SIZE) or DEFAULT_TOP_PACK_SIZE)
    anchor_cutoff = max(4, top_pack_size // 2)
    return higher_rank <= anchor_cutoff and top_pack_size < lower_rank <= top_pack_size + 2


def budget_bucket(candidate: dict) -> str:
    triggers = set(candidate.get("triggers", []))
    details = candidate.get("trigger_details", {}) if isinstance(candidate.get("trigger_details"), dict) else {}
    selection_reasons = set(candidate.get("selection_reasons", [])) if isinstance(candidate.get("selection_reasons"), list) else set()
    if "band_seam_requested" in triggers or details.get("level_cross"):
        return "band_boundary"
    if "cross_band_challenger" in selection_reasons:
        return "band_boundary"
    if "uncertainty_challenger" in triggers:
        return "large_mover"
    if "top_pack" in triggers:
        return "top_pack"
    if "large_mover" in triggers:
        return "large_mover"
    return "other"


def select_candidates_for_execution(
    candidates: list[dict],
    *,
    max_escalations: int,
    max_top_pack_escalations: int,
    max_band_boundary_escalations: int,
    max_large_mover_escalations: int,
) -> tuple[list[dict], list[dict], dict]:
    total_cap = max(0, int(max_escalations))
    bucket_caps = {
        "top_pack": max(0, int(max_top_pack_escalations)),
        "band_boundary": max(0, int(max_band_boundary_escalations)),
        "large_mover": max(0, int(max_large_mover_escalations)),
    }
    selected = []
    skipped = []
    bucket_counts = {"top_pack": 0, "band_boundary": 0, "large_mover": 0, "other": 0}
    for raw in sorted(candidates, key=candidate_priority):
        candidate = copy.deepcopy(raw)
        bucket = budget_bucket(candidate)
        candidate["budget_bucket"] = bucket
        reason = ""
        if total_cap and len(selected) >= total_cap:
            reason = "max_escalations_exceeded"
        elif bucket in bucket_caps and bucket_caps[bucket] and bucket_counts[bucket] >= bucket_caps[bucket]:
            reason = f"max_{bucket}_escalations_exceeded"
        if reason:
            candidate["execution_status"] = "skipped_budget_cap"
            candidate["skip_reason"] = reason
            skipped.append(candidate)
            continue
        candidate["execution_status"] = "selected"
        candidate["skip_reason"] = ""
        selected.append(candidate)
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
    return selected, skipped, {
        "max_escalations": total_cap,
        "max_top_pack_escalations": bucket_caps["top_pack"],
        "max_band_boundary_escalations": bucket_caps["band_boundary"],
        "max_large_mover_escalations": bucket_caps["large_mover"],
        "selected_count": len(selected),
        "skipped_count": len(skipped),
        "selected_bucket_counts": bucket_counts,
    }


def build_candidates(
    checks: list[dict],
    rows: list[dict],
    band_report: dict,
    matrix: dict,
    *,
    genre: str,
    top_pack_size: int,
    support_margin: float,
) -> list[dict]:
    rows_by_id = {row["student_id"]: row for row in rows}
    student_count = len(rows)
    band_keys = band_seam_pair_keys(band_report)
    matrix_support = matrix_direct_support(matrix)
    candidates: dict[str, dict] = {}
    for item in checks:
        if not isinstance(item, dict):
            continue
        metadata = item.get("model_metadata") if isinstance(item.get("model_metadata"), dict) else {}
        if normalized_source(item) == "escalated_adjudication" or bool(metadata.get("superseded_by_escalation", False)):
            continue
        key = pair_key_from_item(item)
        if not key:
            continue
        triggers, details = candidate_triggers(
            item,
            rows_by_id,
            student_count=student_count,
            genre=genre,
            band_keys=band_keys,
            matrix_support=matrix_support,
            top_pack_size=top_pack_size,
            support_margin=support_margin,
        )
        if not triggers:
            continue
        pair_order = seed_order_for_pair(item, rows_by_id)
        if not pair_order:
            continue
        higher, lower = pair_order
        pair = item.get("pair")
        left_id, right_id = str(pair[0]).strip(), str(pair[1]).strip()
        existing = candidates.setdefault(
            key,
            {
                "pair_key": key,
                "pair": [left_id, right_id],
                "top_pack_size": int(top_pack_size),
                "seed_order": {
                    "higher": higher["student_id"],
                    "lower": lower["student_id"],
                    "higher_rank": int(higher.get("seed_rank", 0) or 0),
                    "lower_rank": int(lower.get("seed_rank", 0) or 0),
                },
                "triggers": [],
                "trigger_details": {},
                "selection_reasons": [],
                "selection_details": [],
                "aggregate_support": {
                    "left": aggregate_support_detail(rows_by_id[left_id], student_count),
                    "right": aggregate_support_detail(rows_by_id[right_id], student_count),
                },
                "direct_support": matrix_support.get(key, {}),
                "cheap_judgment": compact_judgment(item),
                "cheap_judgments": [],
            },
        )
        existing["triggers"] = sorted(set(existing["triggers"]) | set(triggers))
        existing["trigger_details"].update(details)
        for reason in item.get("selection_reasons", []) if isinstance(item.get("selection_reasons"), list) else []:
            token = str(reason or "").strip()
            if token and token not in existing["selection_reasons"]:
                existing["selection_reasons"].append(token)
        for detail in item.get("selection_details", []) if isinstance(item.get("selection_details"), list) else []:
            token = str(detail or "").strip()
            if token and token not in existing["selection_details"]:
                existing["selection_details"].append(token)
        existing["cheap_judgments"].append(compact_judgment(item))

    return sorted(
        candidates.values(),
        key=lambda candidate: (
            int(candidate["seed_order"].get("higher_rank", 999999) or 999999),
            int(candidate["seed_order"].get("lower_rank", 999999) or 999999),
            candidate["pair_key"],
        ),
    )


def annotate_source(item: dict, source: str) -> dict:
    updated = copy.deepcopy(item)
    metadata = updated.setdefault("model_metadata", {})
    if isinstance(metadata, dict):
        metadata.setdefault("adjudication_source", source)
    else:
        updated["model_metadata"] = {"adjudication_source": source}
    return updated


def source_for_original(item: dict) -> str:
    source = normalized_source(item)
    return source if source in {"orientation_audit", "escalated_adjudication"} else "cheap_pairwise"


def escalate_candidates(
    candidates: list[dict],
    *,
    rows_by_id: dict[str, dict],
    texts: dict[str, str],
    rubric: str,
    outline: str,
    metadata: dict,
    genre: str,
    model: str,
    routing: str,
    reasoning: str,
    max_output_tokens: int,
    anchor_dir: str,
    orientation_audit: bool,
) -> list[dict]:
    escalations = []
    for candidate in candidates:
        seed_order = candidate.get("seed_order", {}) if isinstance(candidate.get("seed_order"), dict) else {}
        higher_id = str(seed_order.get("higher", "") or "").strip()
        lower_id = str(seed_order.get("lower", "") or "").strip()
        if higher_id not in rows_by_id or lower_id not in rows_by_id:
            continue
        higher, lower = rows_by_id[higher_id], rows_by_id[lower_id]
        reasons = list(candidate.get("selection_reasons", []))
        if "escalated_adjudication" not in reasons:
            reasons.append("escalated_adjudication")
        details = list(candidate.get("selection_details", [])) + selection_detail_lines(candidate)
        judgment = vc.judge_pair_with_orientation_audit(
            rubric,
            outline,
            higher,
            lower,
            texts.get(higher_id, ""),
            texts.get(lower_id, ""),
            model=model,
            routing=routing,
            reasoning=reasoning,
            max_output_tokens=max_output_tokens,
            genre=genre,
            metadata=metadata,
            selection_reasons=reasons,
            selection_details=details,
            anchor_dir=anchor_dir,
            orientation_audit=orientation_audit,
            student_count=len(rows_by_id),
        )
        judgment["selection_reasons"] = reasons
        judgment["selection_details"] = details
        judgment["escalation_candidate"] = {
            "pair_key": candidate.get("pair_key", ""),
            "triggers": list(candidate.get("triggers", [])),
            "trigger_details": dict(candidate.get("trigger_details", {})),
        }
        model_metadata = judgment.setdefault("model_metadata", {})
        model_metadata["adjudication_source"] = "escalated_adjudication"
        model_metadata["escalation_triggers"] = list(candidate.get("triggers", []))
        model_metadata["supersedes_pair_key"] = candidate.get("pair_key", "")
        model_metadata["cheap_judgment"] = candidate.get("cheap_judgment", {})
        escalations.append(judgment)
    return escalations


def merged_payload(
    original_payload: dict,
    checks: list[dict],
    escalations: list[dict],
    candidates: list[dict],
    budget: dict,
    *,
    model: str,
    routing: str,
    reasoning: str,
) -> dict:
    escalated_keys = {pair_key_from_item(item) for item in escalations if pair_key_from_item(item)}
    annotated = []
    for item in checks:
        updated = annotate_source(item, source_for_original(item))
        key = pair_key_from_item(updated)
        if key in escalated_keys:
            updated.setdefault("model_metadata", {})["superseded_by_escalation"] = True
        annotated.append(updated)
    merged = copy.deepcopy(original_payload) if isinstance(original_payload, dict) else {}
    merged["generated_at"] = now_iso()
    merged["checks"] = annotated + [annotate_source(item, "escalated_adjudication") for item in escalations]
    merged["pairwise_escalation"] = {
        "generated_at": now_iso(),
        "candidate_count": len(candidates),
        "escalation_count": len(escalations),
        "selected_count": int(budget.get("selected_count", len(escalations)) or 0),
        "skipped_count": int(budget.get("skipped_count", 0) or 0),
        "escalated_pair_keys": sorted(escalated_keys),
        "model": model,
        "routing": routing,
        "reasoning": reasoning,
        "budget": budget,
        "source_checks_generated_at": original_payload.get("generated_at", "") if isinstance(original_payload, dict) else "",
    }
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="Escalate unstable/high-leverage pairwise judgments with a stronger adjudicator.")
    parser.add_argument("--checks", default="outputs/consistency_checks.json", help="Cheap pairwise consistency checks JSON")
    parser.add_argument("--matrix", default="outputs/pairwise_matrix.json", help="Optional pairwise matrix JSON for direct support metadata")
    parser.add_argument("--band-seam-report", default="outputs/band_seam_report.json", help="Band seam report JSON")
    parser.add_argument("--scores", default="outputs/consensus_scores.csv", help="Consensus scores CSV")
    parser.add_argument("--texts", default="processing/normalized_text", help="Essay text directory")
    parser.add_argument("--rubric", default="inputs/rubric.md", help="Rubric file")
    parser.add_argument("--outline", default="inputs/assignment_outline.md", help="Assignment outline file")
    parser.add_argument("--class-metadata", default="inputs/class_metadata.json", help="Class metadata JSON")
    parser.add_argument("--routing", default="config/llm_routing.json", help="Routing config JSON")
    parser.add_argument("--model", default="", help="Override escalator model")
    parser.add_argument("--reasoning", default="", help="Override escalator reasoning effort")
    parser.add_argument("--max-output-tokens", type=int, default=0, help="Override escalator output token budget")
    parser.add_argument("--top-pack-size", type=int, default=DEFAULT_TOP_PACK_SIZE, help="Seed/top-pack rank cutoff treated as high leverage")
    parser.add_argument("--support-margin", type=float, default=0.2, help="Aggregate support margin that triggers contradiction escalation")
    parser.add_argument("--max-escalations", type=int, default=44, help="Maximum stronger-model escalations per cohort; 0 means no total cap")
    parser.add_argument("--max-top-pack-escalations", type=int, default=8, help="Maximum selected top-pack escalations; 0 means no top-pack cap")
    parser.add_argument("--max-band-boundary-escalations", type=int, default=20, help="Maximum selected band-boundary escalations; 0 means no boundary cap")
    parser.add_argument("--max-large-mover-escalations", type=int, default=16, help="Maximum selected large-mover escalations; 0 means no large-mover cap")
    parser.add_argument("--anchor-dir", default=str(vc.DEFAULT_PAIRWISE_ANCHOR_DIR), help="Pairwise anchor directory")
    parser.add_argument("--disable-orientation-audit", action="store_true", help="Disable swapped-read orientation auditing for escalations")
    parser.add_argument("--candidate-output", default=DEFAULT_CANDIDATES, help="Escalation candidate artifact")
    parser.add_argument("--escalations-output", default=DEFAULT_ESCALATIONS, help="Escalated judgments artifact")
    parser.add_argument("--merged-output", default=DEFAULT_MERGED, help="Merged checks JSON with escalations")
    args = parser.parse_args()

    routing_payload = load_json(Path(args.routing))
    task = task_config(routing_payload, "pairwise_escalator")
    mode = os.environ.get("LLM_MODE") or routing_payload.get("mode", "openai")
    model = args.model or task.get("model") or routing_payload.get("default_model") or "gpt-5.4"
    reasoning = args.reasoning or task.get("reasoning") or "medium"
    max_output_tokens = int(args.max_output_tokens or task.get("max_output_tokens") or 900)

    rows = vc.prepare_rows(vc.load_rows(Path(args.scores)))
    if not rows:
        print(f"No score rows found in {args.scores}")
        return 1
    checks_payload = load_json(Path(args.checks))
    checks = checks_payload.get("checks", checks_payload.get("judgments", [])) if isinstance(checks_payload, dict) else []
    if not isinstance(checks, list):
        checks = []

    metadata = vc.load_pairwise_metadata(Path(args.class_metadata))
    genre = vc.resolve_pairwise_genre(metadata)
    band_report = load_json(Path(args.band_seam_report))
    matrix = load_json(Path(args.matrix))
    candidates = build_candidates(
        checks,
        rows,
        band_report,
        matrix,
        genre=genre,
        top_pack_size=max(1, int(args.top_pack_size)),
        support_margin=max(0.0, float(args.support_margin)),
    )
    selected_candidates, skipped_candidates, budget = select_candidates_for_execution(
        candidates,
        max_escalations=max(0, int(args.max_escalations)),
        max_top_pack_escalations=max(0, int(args.max_top_pack_escalations)),
        max_band_boundary_escalations=max(0, int(args.max_band_boundary_escalations)),
        max_large_mover_escalations=max(0, int(args.max_large_mover_escalations)),
    )
    candidate_status = {candidate["pair_key"]: candidate for candidate in selected_candidates + skipped_candidates}
    annotated_candidates = []
    for candidate in candidates:
        updated = copy.deepcopy(candidate)
        status = candidate_status.get(candidate.get("pair_key", ""), {})
        updated["execution_status"] = status.get("execution_status", "selected")
        updated["budget_bucket"] = status.get("budget_bucket", budget_bucket(candidate))
        updated["skip_reason"] = status.get("skip_reason", "")
        annotated_candidates.append(updated)
    estimated_max_model_calls = len(selected_candidates) * (2 if not args.disable_orientation_audit else 1)
    budget["estimated_max_model_calls"] = estimated_max_model_calls
    budget["estimated_max_output_tokens"] = estimated_max_model_calls * max(512, max_output_tokens)
    candidates_payload = {
        "generated_at": now_iso(),
        "source_checks": args.checks,
        "source_scores": args.scores,
        "band_seam_report": args.band_seam_report,
        "pairwise_matrix": args.matrix,
        "top_pack_size": max(1, int(args.top_pack_size)),
        "support_margin": max(0.0, float(args.support_margin)),
        "candidate_count": len(candidates),
        "selected_count": len(selected_candidates),
        "skipped_count": len(skipped_candidates),
        "budget": budget,
        "candidates": annotated_candidates,
        "selected_candidates": selected_candidates,
        "skipped_candidates": skipped_candidates,
    }
    write_json(Path(args.candidate_output), candidates_payload)

    if mode != "codex_local" and selected_candidates and not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. Aborting before escalated adjudication.")
        return 1

    rubric_path = resolve_input_path(Path(args.rubric), "rubric")
    outline_path = resolve_input_path(Path(args.outline), "assignment_outline")
    texts = vc.load_texts(Path(args.texts))
    rubric_text = load_file_text(rubric_path)
    outline_text = load_file_text(outline_path)
    rows_by_id = {row["student_id"]: row for row in rows}
    escalations = escalate_candidates(
        selected_candidates,
        rows_by_id=rows_by_id,
        texts=texts,
        rubric=rubric_text,
        outline=outline_text,
        metadata=metadata if isinstance(metadata, dict) else {},
        genre=genre,
        model=model,
        routing=args.routing,
        reasoning=reasoning,
        max_output_tokens=max(512, max_output_tokens),
        anchor_dir=args.anchor_dir,
        orientation_audit=not args.disable_orientation_audit,
    )
    escalations_payload = {
        "generated_at": now_iso(),
        "source_checks": args.checks,
        "candidate_output": args.candidate_output,
        "model": model,
        "routing": args.routing,
        "reasoning": reasoning,
        "budget": budget,
        "selected_count": len(selected_candidates),
        "skipped_count": len(skipped_candidates),
        "escalation_count": len(escalations),
        "checks": escalations,
    }
    write_json(Path(args.escalations_output), escalations_payload)
    write_json(
        Path(args.merged_output),
        merged_payload(checks_payload, checks, escalations, annotated_candidates, budget, model=model, routing=args.routing, reasoning=reasoning),
    )
    print(f"Wrote {args.candidate_output}")
    print(f"Wrote {args.escalations_output}")
    print(f"Wrote {args.merged_output}")
    print(
        json.dumps(
            {
                "candidate_count": len(candidates),
                "selected_count": len(selected_candidates),
                "skipped_count": len(skipped_candidates),
                "escalation_count": len(escalations),
                "estimated_max_model_calls": estimated_max_model_calls,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
