#!/usr/bin/env python3
"""Phase 1 scaffold for routed committee-edge adjudication."""

from __future__ import annotations

import argparse
import copy
import csv
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.adjudication_source import (
        dedupe_by_precedence,
        mark_superseded,
        normalize_source,
        pair_key_from_item,
        precedence_rank,
    )
    from scripts.literary_surface_features import compute_surface_features, polish_vs_substance_gap
except ImportError:  # pragma: no cover - Support running as a standalone script
    from adjudication_source import (  # type: ignore  # pragma: no cover
        dedupe_by_precedence,
        mark_superseded,
        normalize_source,
        pair_key_from_item,
        precedence_rank,
    )
    from literary_surface_features import compute_surface_features, polish_vs_substance_gap  # type: ignore  # pragma: no cover


DEFAULT_ESCALATED = "outputs/consistency_checks.escalated.json"
DEFAULT_ESCALATION_CANDIDATES = "outputs/pairwise_escalation_candidates.json"
DEFAULT_ESCALATIONS = "outputs/pairwise_escalations.json"
DEFAULT_MATRIX = "outputs/pairwise_matrix.json"
DEFAULT_SCORES = "outputs/consensus_scores.csv"
DEFAULT_BAND_SEAM = "outputs/band_seam_report.json"
DEFAULT_COHORT_CONFIDENCE = "outputs/cohort_confidence.json"
DEFAULT_CLASS_METADATA = "inputs/class_metadata.json"
DEFAULT_TEXTS = "processing/normalized_text"
DEFAULT_CANDIDATES_OUT = "outputs/committee_edge_candidates.json"
DEFAULT_DECISIONS_OUT = "outputs/committee_edge_decisions.json"
DEFAULT_REPORT_OUT = "outputs/committee_edge_report.json"
DEFAULT_MERGED_OUT = "outputs/consistency_checks.committee_edge.json"

TRIGGER_POINTS = {
    "escalated_vs_direct_matrix_conflict": 90,
    "escalated_vs_aggregate_conflict": 70,
    "polish_bias_suspected": 100,
    "rougher_but_stronger_latent": 80,
    "low_medium_confidence_high_leverage": 60,
    "top10_or_boundary": 40,
    "completion_ordering_instability": 55,
    "cohort_confidence_unstable": 30,
}
HARD_EVIDENCE_MARGIN = 1.5
TOP_PACK_SIZE = 10


@dataclass(frozen=True)
class CandidateConfig:
    max_candidates: int = 12
    max_top_pack: int = 6
    max_level_boundary: int = 4
    max_rougher_stronger: int = 6
    max_completion_ordering: int = 2
    min_trigger_score: int = 80
    support_margin: float = 0.20
    polish_bias_surface_sd: float = 1.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_required_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected JSON object")
    return payload


def load_optional_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_decisions(path: Path | None) -> list[dict]:
    if path is None:
        return []
    payload = load_required_json(path)
    if isinstance(payload.get("decisions"), list):
        items = payload["decisions"]
    elif isinstance(payload.get("checks"), list):
        items = payload["checks"]
    else:
        items = []
    normalized = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = copy.deepcopy(raw)
        metadata = item.get("model_metadata") if isinstance(item.get("model_metadata"), dict) else {}
        metadata = dict(metadata)
        metadata["adjudication_source"] = "committee_edge"
        metadata.setdefault("phase", 1)
        item["model_metadata"] = metadata
        item["adjudication_source"] = "committee_edge"
        item["pair_key"] = pair_key_from_item(item)
        normalized.append(item)
    return normalized


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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


def normalize_metric(value) -> float:
    raw = num(value, 0.0)
    if raw > 1.0:
        return raw / 100.0 if raw <= 100.0 else raw
    return raw


def rank_key(rows: list[dict]) -> str:
    if not rows:
        return ""
    for key in ("seed_rank", "consensus_rank", "final_rank", "consistency_rank"):
        if key in rows[0]:
            return key
    return ""


def normalize_rows(rows: list[dict]) -> list[dict]:
    key = rank_key(rows)
    normalized = []
    for idx, row in enumerate(rows, start=1):
        student_id = str(row.get("student_id") or "").strip()
        if not student_id:
            continue
        flags = {token.strip() for token in str(row.get("flags", "") or "").split(";") if token.strip()}
        seed_rank = int(num(row.get("seed_rank") or row.get(key), idx) or idx)
        item = dict(row)
        item["student_id"] = student_id
        item["seed_rank"] = seed_rank
        item["_level"] = str(row.get("adjusted_level") or row.get("base_level") or row.get("level") or "").strip()
        item["_composite_score"] = normalize_metric(row.get("composite_score"))
        item["_borda_feature"] = normalize_metric(row.get("borda_percent") or row.get("borda_points"))
        item["_draft_completion_floor_applied"] = truthy(row.get("draft_completion_floor_applied")) or "draft_completion_floor" in flags
        normalized.append(item)
    return sorted(normalized, key=lambda row: (int(row.get("seed_rank", 999999) or 999999), row["student_id"]))


def seed_percentile(seed_rank: int, student_count: int) -> float:
    if student_count <= 1:
        return 1.0
    return max(0.0, min(1.0, 1.0 - ((int(seed_rank) - 1) / max(student_count - 1, 1))))


def row_support(row: dict, student_count: int) -> float:
    return max(
        normalize_metric(row.get("_composite_score")),
        normalize_metric(row.get("_borda_feature")),
        seed_percentile(int(row.get("seed_rank", student_count) or student_count), student_count),
    )


def normalize_decision(value) -> str:
    token = str(value or "").strip().upper()
    return "SWAP" if token == "SWAP" else "KEEP"


def normalize_winner_side(value) -> str:
    token = str(value or "").strip().upper()
    return token if token in {"A", "B"} else ""


def winner_loser_from_check(item: dict) -> tuple[str, str, str, str]:
    pair = item.get("pair") if isinstance(item.get("pair"), list) else []
    seed_order = item.get("seed_order") if isinstance(item.get("seed_order"), dict) else {}
    higher = str(seed_order.get("higher") or (pair[0] if len(pair) > 0 else "")).strip()
    lower = str(seed_order.get("lower") or (pair[1] if len(pair) > 1 else "")).strip()
    explicit_winner = str(item.get("winner") or "").strip()
    explicit_loser = str(item.get("loser") or "").strip()
    if explicit_winner in {higher, lower} and explicit_loser in {higher, lower} and explicit_winner != explicit_loser:
        side = "A" if explicit_winner == higher else "B"
        return explicit_winner, explicit_loser, side, normalize_decision(item.get("decision"))
    winner_side = normalize_winner_side(item.get("winner_side"))
    decision = "KEEP" if winner_side == "A" else "SWAP" if winner_side == "B" else normalize_decision(item.get("decision"))
    winner = higher if decision == "KEEP" else lower
    loser = lower if decision == "KEEP" else higher
    return winner, loser, winner_side or ("A" if decision == "KEEP" else "B"), decision


def source_checks(payload: dict) -> list[dict]:
    checks = payload.get("checks", payload.get("judgments", []))
    return checks if isinstance(checks, list) else []


def escalation_candidate_map(payload: dict) -> dict[str, dict]:
    candidates = []
    for key in ("candidates", "skipped", "skipped_candidates"):
        if isinstance(payload.get(key), list):
            candidates.extend(item for item in payload[key] if isinstance(item, dict))
    return {str(item.get("pair_key") or pair_key_from_item(item)).strip(): item for item in candidates}


def matrix_comparison_map(matrix: dict) -> dict[str, dict]:
    comparisons = matrix.get("comparisons")
    if isinstance(comparisons, dict):
        return {str(key): value for key, value in comparisons.items() if isinstance(value, dict)}
    if not isinstance(comparisons, list):
        return {}
    mapped = {}
    for comparison in comparisons:
        if not isinstance(comparison, dict):
            continue
        key = pair_key_from_item(comparison)
        if key:
            mapped[key] = comparison
    return mapped


def direct_matrix_margin(comparison: dict, winner: str, loser: str) -> float:
    if not comparison:
        return 0.0
    directional = comparison.get("directional_weight") if isinstance(comparison.get("directional_weight"), dict) else {}
    if directional:
        return num(directional.get(f"{loser}>{winner}")) - num(directional.get(f"{winner}>{loser}"))
    pair = comparison.get("pair") if isinstance(comparison.get("pair"), list) else []
    if len(pair) != 2:
        return 0.0
    left = str(pair[0]).strip()
    right = str(pair[1]).strip()
    left_over_right = num(comparison.get("left_over_right_weight"))
    right_over_left = num(comparison.get("right_over_left_weight"))
    if winner == left and loser == right:
        return right_over_left - left_over_right
    if winner == right and loser == left:
        return left_over_right - right_over_left
    return 0.0


def collect_band_seam_pair_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        pair = value.get("pair")
        if isinstance(pair, list) and len(pair) == 2:
            key = pair_key_from_item(value)
            if key:
                keys.add(key)
        high = value.get("higher_candidate") or value.get("higher")
        low = value.get("lower_candidate") or value.get("lower")
        if high and low:
            keys.add("::".join(sorted((str(high).strip(), str(low).strip()))))
        for child in value.values():
            keys.update(collect_band_seam_pair_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(collect_band_seam_pair_keys(child))
    return {key for key in keys if "::" in key}


def read_texts(root: Path, student_ids: set[str]) -> dict[str, str]:
    texts = {}
    for student_id in student_ids:
        path = root / f"{student_id}.txt"
        if path.exists():
            texts[student_id] = path.read_text(encoding="utf-8", errors="ignore")
        else:
            texts[student_id] = ""
    return texts


def score_candidate(triggers: set[str], details: dict, config: CandidateConfig) -> int:
    return int(sum(TRIGGER_POINTS.get(trigger, 0) for trigger in triggers))


def candidate_bucket(triggers: set[str], details: dict, config: CandidateConfig) -> str:
    if details.get("level_cross") or details.get("band_seam_pair"):
        return "level_boundary"
    if details.get("higher_rank", 999999) <= TOP_PACK_SIZE or details.get("lower_rank", 999999) <= TOP_PACK_SIZE:
        return "top_pack"
    if "rougher_but_stronger_latent" in triggers or "polish_bias_suspected" in triggers:
        return "rougher_stronger"
    if "completion_ordering_instability" in triggers:
        return "completion_ordering"
    return "other"


def _surface_block(winner_text: str, loser_text: str) -> dict:
    winner_features = compute_surface_features(winner_text)
    loser_features = compute_surface_features(loser_text)
    return {
        "winner": winner_features.to_dict(),
        "loser": loser_features.to_dict(),
        "gap": polish_vs_substance_gap(winner_features, loser_features),
    }


def build_candidates(
    *,
    escalated_checks: list[dict],
    escalation_candidates: list[dict] | dict,
    matrix: dict,
    rows: list[dict],
    band_seam_report: dict,
    cohort_confidence: dict,
    genre: str,
    config: CandidateConfig,
    texts_by_id: dict[str, str] | None = None,
) -> list[dict]:
    texts_by_id = texts_by_id or {}
    normalized_rows = normalize_rows(rows)
    rows_by_id = {row["student_id"]: row for row in normalized_rows}
    student_count = max(1, len(normalized_rows))
    active_checks = dedupe_by_precedence(
        [item for item in escalated_checks if isinstance(item, dict)],
        key_fn=pair_key_from_item,
    )
    candidate_source = (
        escalation_candidates if isinstance(escalation_candidates, dict) else {"candidates": escalation_candidates}
    )
    escalation_map = escalation_candidate_map(candidate_source)
    matrix_map = matrix_comparison_map(matrix)
    band_seam_keys = collect_band_seam_pair_keys(band_seam_report)
    unstable_cohort = bool(
        cohort_confidence
        and str(cohort_confidence.get("effective_runtime_state") or "").strip() != "auto_publish_ready"
    )

    candidates = []
    for item in sorted(active_checks, key=pair_key_from_item):
        pair_key = pair_key_from_item(item)
        if not pair_key or normalize_source(item) == "committee_edge":
            continue
        winner, loser, winner_side, decision = winner_loser_from_check(item)
        seed_order = item.get("seed_order") if isinstance(item.get("seed_order"), dict) else {}
        pair = item.get("pair") if isinstance(item.get("pair"), list) and len(item.get("pair")) == 2 else [winner, loser]
        higher = str(seed_order.get("higher") or pair[0]).strip()
        lower = str(seed_order.get("lower") or pair[1]).strip()
        if higher not in rows_by_id or lower not in rows_by_id or winner not in rows_by_id or loser not in rows_by_id:
            continue
        higher_row = rows_by_id[higher]
        lower_row = rows_by_id[lower]
        winner_row = rows_by_id[winner]
        loser_row = rows_by_id[loser]
        higher_rank = int(num(seed_order.get("higher_rank"), higher_row.get("seed_rank", 999999)) or 999999)
        lower_rank = int(num(seed_order.get("lower_rank"), lower_row.get("seed_rank", 999999)) or 999999)
        level_cross = bool(higher_row.get("_level") and lower_row.get("_level") and higher_row.get("_level") != lower_row.get("_level"))
        top10_involved = higher_rank <= TOP_PACK_SIZE or lower_rank <= TOP_PACK_SIZE
        top10_cross = (higher_rank <= TOP_PACK_SIZE < lower_rank) or (lower_rank <= TOP_PACK_SIZE < higher_rank)
        escalation_detail = escalation_map.get(pair_key, {})
        escalation_trigger_details = (
            escalation_detail.get("trigger_details") if isinstance(escalation_detail.get("trigger_details"), dict) else {}
        )
        level_cross = bool(level_cross or escalation_trigger_details.get("level_cross"))
        top10_involved = bool(top10_involved or escalation_trigger_details.get("top10_involved"))
        top10_cross = bool(top10_cross or escalation_trigger_details.get("top10_cross"))
        surface_features = _surface_block(texts_by_id.get(winner, ""), texts_by_id.get(loser, ""))
        decision_basis = str(item.get("decision_basis") or "").strip()
        confidence = str(item.get("confidence") or "low").strip().lower()
        cautions = item.get("cautions_applied") if isinstance(item.get("cautions_applied"), list) else []
        cautions_set = {str(caution).strip() for caution in cautions}
        direct_margin = direct_matrix_margin(matrix_map.get(pair_key, {}), winner, loser)
        support_margin = round(row_support(loser_row, student_count) - row_support(winner_row, student_count), 6)

        triggers: set[str] = set()
        if direct_margin >= HARD_EVIDENCE_MARGIN:
            triggers.add("escalated_vs_direct_matrix_conflict")
        if support_margin >= config.support_margin:
            triggers.add("escalated_vs_aggregate_conflict")
        if (
            decision_basis in {"organization", "language_control"}
            and "polished_but_shallow" not in cautions_set
            and surface_features["gap"]["polish_bias_flag"]
        ):
            triggers.add("polish_bias_suspected")
        if (
            num(loser_row.get("_composite_score")) > num(winner_row.get("_composite_score"))
            and num(loser_row.get("_borda_feature")) > num(winner_row.get("_borda_feature"))
            and "rougher_but_stronger_content" not in cautions_set
        ):
            triggers.add("rougher_but_stronger_latent")
        if confidence in {"low", "medium"} and (top10_involved or level_cross):
            triggers.add("low_medium_confidence_high_leverage")
        if top10_involved or level_cross or top10_cross:
            triggers.add("top10_or_boundary")
        if (
            (winner_row.get("_draft_completion_floor_applied") or loser_row.get("_draft_completion_floor_applied"))
            and decision_basis != "completion"
        ):
            triggers.add("completion_ordering_instability")
        if unstable_cohort and confidence == "low":
            triggers.add("cohort_confidence_unstable")

        details = {
            "escalated_decision_basis": decision_basis,
            "escalated_cautions": sorted(cautions_set),
            "direct_matrix_margin": round(direct_margin, 6),
            "aggregate_support_margin": support_margin,
            "top10_involved": bool(top10_involved),
            "top10_cross": bool(top10_cross),
            "level_cross": bool(level_cross),
            "band_seam_pair": pair_key in band_seam_keys,
            "higher_rank": higher_rank,
            "lower_rank": lower_rank,
            "winner_source": normalize_source(item),
            "genre": genre,
        }
        score = score_candidate(triggers, details, config)
        if score < config.min_trigger_score:
            continue
        bucket = candidate_bucket(triggers, details, config)
        candidates.append(
            {
                "pair": [higher, lower],
                "pair_key": pair_key,
                "seed_order": {
                    "higher": higher,
                    "lower": lower,
                    "higher_rank": higher_rank,
                    "lower_rank": lower_rank,
                },
                "bucket": bucket,
                "committee_score": score,
                "triggers": sorted(triggers),
                "trigger_details": details,
                "selection_reasons": sorted(set(escalation_detail.get("selection_reasons", [])) if isinstance(escalation_detail.get("selection_reasons"), list) else []),
                "escalated_summary": {
                    "winner": winner,
                    "loser": loser,
                    "winner_side": winner_side,
                    "decision": decision,
                    "confidence": confidence,
                    "decision_basis": decision_basis,
                    "adjudication_source": normalize_source(item),
                },
                "surface_features": surface_features,
                "selection_status": "",
                "skip_reason": "",
            }
        )
    return sorted(candidates, key=lambda candidate: str(candidate.get("pair_key", "")))


def candidate_priority(candidate: dict) -> tuple[int, int, int, str]:
    seed_order = candidate.get("seed_order") if isinstance(candidate.get("seed_order"), dict) else {}
    return (
        -int(candidate.get("committee_score", 0) or 0),
        int(seed_order.get("higher_rank", 999999) or 999999),
        int(seed_order.get("lower_rank", 999999) or 999999),
        str(candidate.get("pair_key") or ""),
    )


def select_within_budget(
    candidates: list[dict], *, config: CandidateConfig
) -> tuple[list[dict], list[dict], dict]:
    bucket_caps = {
        "top_pack": max(0, int(config.max_top_pack)),
        "level_boundary": max(0, int(config.max_level_boundary)),
        "rougher_stronger": max(0, int(config.max_rougher_stronger)),
        "completion_ordering": max(0, int(config.max_completion_ordering)),
    }
    bucket_counts = {"top_pack": 0, "level_boundary": 0, "rougher_stronger": 0, "completion_ordering": 0, "other": 0}
    selected = []
    skipped = []
    for raw in sorted(candidates, key=candidate_priority):
        candidate = copy.deepcopy(raw)
        bucket = str(candidate.get("bucket") or "other")
        reason = ""
        if len(selected) >= max(0, int(config.max_candidates)):
            reason = "max_candidates_exceeded"
        elif bucket in bucket_caps and bucket_counts.get(bucket, 0) >= bucket_caps[bucket]:
            reason = f"max_{bucket}_committee_edges_exceeded"
        if reason:
            candidate["selection_status"] = "skipped_budget_cap"
            candidate["skip_reason"] = reason
            skipped.append(candidate)
            continue
        candidate["selection_status"] = "selected"
        candidate["skip_reason"] = ""
        selected.append(candidate)
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
    return selected, skipped, {
        "max_candidates": int(config.max_candidates),
        "selected": len(selected),
        "skipped": len(skipped),
        "selected_bucket_counts": bucket_counts,
    }


def normalize_committee_decision(decision: dict, candidate_by_key: dict[str, dict]) -> dict:
    item = copy.deepcopy(decision)
    metadata = item.get("model_metadata") if isinstance(item.get("model_metadata"), dict) else {}
    metadata = dict(metadata)
    metadata["adjudication_source"] = "committee_edge"
    metadata.setdefault("phase", 1)
    item["model_metadata"] = metadata
    item["adjudication_source"] = "committee_edge"
    item["pair_key"] = pair_key_from_item(item)
    trace = item.get("committee_edge_trace") if isinstance(item.get("committee_edge_trace"), dict) else {}
    candidate = candidate_by_key.get(item["pair_key"])
    if candidate:
        trace = {
            **trace,
            "triggers": candidate.get("triggers", []),
            "committee_score": candidate.get("committee_score", 0),
        }
    item["committee_edge_trace"] = trace
    return item


def merged_checks_payload(
    *,
    escalated_payload: dict,
    escalated_checks: list[dict],
    decisions: list[dict],
    candidates: list[dict],
    budget: dict,
) -> dict:
    generated_at = now_iso()
    candidate_by_key = {str(candidate.get("pair_key")): candidate for candidate in candidates}
    normalized_decisions = [normalize_committee_decision(decision, candidate_by_key) for decision in decisions]
    decision_keys = {pair_key_from_item(decision) for decision in normalized_decisions if pair_key_from_item(decision)}
    passthrough = not normalized_decisions
    payload = copy.deepcopy(escalated_payload)
    payload["generated_at"] = generated_at
    if passthrough:
        payload["checks"] = copy.deepcopy(escalated_checks)
        superseded_keys: list[str] = []
    else:
        marked = mark_superseded(escalated_checks, {key: "committee_edge" for key in decision_keys})
        payload["checks"] = marked + normalized_decisions
        superseded_keys = sorted(decision_keys)
    payload["committee_edge"] = {
        "generated_at": generated_at,
        "phase": 1,
        "passthrough": passthrough,
        "candidate_count": len(candidates),
        "decision_count": len(normalized_decisions),
        "budget": budget,
        "superseded_pair_keys": superseded_keys,
        "source_checks_generated_at": escalated_payload.get("generated_at", ""),
    }
    return payload


def artifact_source_paths(args: argparse.Namespace) -> dict:
    return {
        "escalated_checks": str(args.escalated),
        "escalation_candidates": str(args.escalation_candidates),
        "escalations": str(args.escalations),
        "pairwise_matrix": str(args.matrix),
        "scores": str(args.scores),
        "band_seam_report": str(args.band_seam),
        "cohort_confidence": str(args.cohort_confidence),
        "class_metadata": str(args.class_metadata),
        "texts": str(args.texts),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Phase 1 committee-edge resolver artifacts.")
    parser.add_argument("--escalated", type=Path, default=Path(DEFAULT_ESCALATED))
    parser.add_argument("--escalation-candidates", type=Path, default=Path(DEFAULT_ESCALATION_CANDIDATES))
    parser.add_argument("--escalations", type=Path, default=Path(DEFAULT_ESCALATIONS))
    parser.add_argument("--matrix", type=Path, default=Path(DEFAULT_MATRIX))
    parser.add_argument("--scores", type=Path, default=Path(DEFAULT_SCORES))
    parser.add_argument("--band-seam", type=Path, default=Path(DEFAULT_BAND_SEAM))
    parser.add_argument("--cohort-confidence", type=Path, default=Path(DEFAULT_COHORT_CONFIDENCE))
    parser.add_argument("--class-metadata", type=Path, default=Path(DEFAULT_CLASS_METADATA))
    parser.add_argument("--texts", type=Path, default=Path(DEFAULT_TEXTS))
    parser.add_argument("--decisions", type=Path, default=None, help="Optional Phase 1 fixture/manual committee decisions JSON.")
    parser.add_argument("--candidates-output", type=Path, default=Path(DEFAULT_CANDIDATES_OUT))
    parser.add_argument("--decisions-output", type=Path, default=Path(DEFAULT_DECISIONS_OUT))
    parser.add_argument("--report-output", type=Path, default=Path(DEFAULT_REPORT_OUT))
    parser.add_argument("--merged-output", type=Path, default=Path(DEFAULT_MERGED_OUT))
    parser.add_argument("--max-candidates", type=int, default=CandidateConfig.max_candidates)
    parser.add_argument("--max-top-pack", type=int, default=CandidateConfig.max_top_pack)
    parser.add_argument("--max-level-boundary", type=int, default=CandidateConfig.max_level_boundary)
    parser.add_argument("--max-rougher-stronger", type=int, default=CandidateConfig.max_rougher_stronger)
    parser.add_argument("--max-completion-ordering", type=int, default=CandidateConfig.max_completion_ordering)
    parser.add_argument("--min-trigger-score", type=int, default=CandidateConfig.min_trigger_score)
    parser.add_argument("--support-margin", type=float, default=CandidateConfig.support_margin)
    parser.add_argument("--polish-bias-surface-sd", type=float, default=CandidateConfig.polish_bias_surface_sd)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    generated_at = now_iso()
    source_paths = artifact_source_paths(args)
    try:
        escalated_payload = load_required_json(args.escalated)
        escalated_checks = source_checks(escalated_payload)
        escalation_candidates = load_optional_json(args.escalation_candidates)
        matrix = load_optional_json(args.matrix)
        rows = load_rows(args.scores)
        band_seam_report = load_optional_json(args.band_seam)
        cohort_confidence = load_optional_json(args.cohort_confidence)
        class_metadata = load_optional_json(args.class_metadata)
        decisions = load_decisions(args.decisions)
    except Exception as exc:
        report = {
            "generated_at": generated_at,
            "phase": 1,
            "passthrough": True,
            "source_paths": source_paths,
            "error": str(exc),
        }
        write_json(args.report_output, report)
        return 1

    config = CandidateConfig(
        max_candidates=args.max_candidates,
        max_top_pack=args.max_top_pack,
        max_level_boundary=args.max_level_boundary,
        max_rougher_stronger=args.max_rougher_stronger,
        max_completion_ordering=args.max_completion_ordering,
        min_trigger_score=args.min_trigger_score,
        support_margin=args.support_margin,
        polish_bias_surface_sd=args.polish_bias_surface_sd,
    )
    genre = str(class_metadata.get("assignment_genre") or class_metadata.get("genre") or "literary_analysis").strip()
    student_ids = set()
    for check in escalated_checks:
        if isinstance(check, dict) and isinstance(check.get("pair"), list):
            student_ids.update(str(item).strip() for item in check["pair"] if str(item).strip())
    texts_by_id = read_texts(args.texts, student_ids)
    candidates = build_candidates(
        escalated_checks=escalated_checks,
        escalation_candidates=escalation_candidates,
        matrix=matrix,
        rows=rows,
        band_seam_report=band_seam_report,
        cohort_confidence=cohort_confidence,
        genre=genre,
        config=config,
        texts_by_id=texts_by_id,
    )
    selected, skipped, budget = select_within_budget(candidates, config=config)
    merged_candidates = selected + skipped
    merged_payload = merged_checks_payload(
        escalated_payload=escalated_payload,
        escalated_checks=escalated_checks,
        decisions=decisions,
        candidates=merged_candidates,
        budget=budget,
    )
    passthrough = not decisions
    candidate_payload = {
        "generated_at": generated_at,
        "phase": 1,
        "passthrough": passthrough,
        "source_paths": source_paths,
        "config": asdict(config),
        "counts": {
            "considered": len(dedupe_by_precedence([item for item in escalated_checks if isinstance(item, dict)], key_fn=pair_key_from_item)),
            "triggered": len(candidates),
            "selected": len(selected),
            "skipped": len(skipped),
        },
        "candidates": selected,
        "skipped": skipped,
    }
    normalized_decisions = [
        normalize_committee_decision(decision, {str(candidate.get("pair_key")): candidate for candidate in merged_candidates})
        for decision in decisions
    ]
    decisions_payload = {
        "generated_at": generated_at,
        "phase": 1,
        "passthrough": passthrough,
        "source_paths": source_paths,
        "decisions": normalized_decisions,
    }
    trigger_counts = Counter()
    bucket_counts = Counter()
    for candidate in merged_candidates:
        trigger_counts.update(candidate.get("triggers", []))
        bucket_counts[str(candidate.get("bucket") or "other")] += 1
    report_payload = {
        "generated_at": generated_at,
        "phase": 1,
        "passthrough": passthrough,
        "source_paths": source_paths,
        "trigger_counts": dict(sorted(trigger_counts.items())),
        "bucket_counts": dict(sorted(bucket_counts.items())),
        "budget": budget,
        "decisions": {
            "count": len(normalized_decisions),
            "overrides_escalated": sum(
                1
                for decision in normalized_decisions
                if any(
                    pair_key_from_item(check) == decision.get("pair_key")
                    and precedence_rank(normalize_source(check)) > precedence_rank("committee_edge")
                    for check in escalated_checks
                    if isinstance(check, dict)
                )
            ),
            "ambiguous": sum(1 for decision in normalized_decisions if str(decision.get("committee_confidence", "")).endswith("ambiguous")),
        },
        "phase2_ready": True,
    }
    write_json(args.candidates_output, candidate_payload)
    write_json(args.decisions_output, decisions_payload)
    write_json(args.report_output, report_payload)
    write_json(args.merged_output, merged_payload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
