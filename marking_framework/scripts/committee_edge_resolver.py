#!/usr/bin/env python3
"""Routed committee-edge adjudication.

Phase 1 shipped the scaffold (passthrough + precedence + basic triggers).
Phase 2a (this revision) calibrates the trigger set so the resolver routes
"caution raised but ignored" pairs — the primary failure mode on the Ghost
Grade-7 literary cohort. Still no live model reads; Phase 2b will add those
behind a --live flag.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.assessor_utils import load_file_text, resolve_input_path
    from scripts.adjudication_source import (
        dedupe_by_precedence,
        mark_superseded,
        normalize_source,
        pair_key_from_item,
        precedence_rank,
    )
    from scripts.literary_surface_features import (
        compute_surface_features,
        interpretive_density_delta,
        polish_vs_substance_gap,
    )
    from scripts import verify_consistency as vc
except ImportError:  # pragma: no cover - Support running as a standalone script
    from assessor_utils import load_file_text, resolve_input_path  # pragma: no cover
    from adjudication_source import (  # type: ignore  # pragma: no cover
        dedupe_by_precedence,
        mark_superseded,
        normalize_source,
        pair_key_from_item,
        precedence_rank,
    )
    from literary_surface_features import (  # type: ignore  # pragma: no cover
        compute_surface_features,
        interpretive_density_delta,
        polish_vs_substance_gap,
    )
    import verify_consistency as vc  # type: ignore  # pragma: no cover


DEFAULT_ESCALATED = "outputs/consistency_checks.escalated.json"
DEFAULT_ESCALATION_CANDIDATES = "outputs/pairwise_escalation_candidates.json"
DEFAULT_ESCALATIONS = "outputs/pairwise_escalations.json"
DEFAULT_MATRIX = "outputs/pairwise_matrix.json"
DEFAULT_SCORES = "outputs/consensus_scores.csv"
DEFAULT_BAND_SEAM = "outputs/band_seam_report.json"
DEFAULT_COHORT_CONFIDENCE = "outputs/cohort_confidence.json"
DEFAULT_CLASS_METADATA = "inputs/class_metadata.json"
DEFAULT_TEXTS = "processing/normalized_text"
DEFAULT_RUBRIC = "inputs/rubric.md"
DEFAULT_OUTLINE = "inputs/assignment_outline.md"
DEFAULT_ROUTING = "config/llm_routing.json"
DEFAULT_COMMITTEE_ANCHOR = "inputs/pairwise_anchors/literary_analysis.committee.json"
DEFAULT_CANDIDATES_OUT = "outputs/committee_edge_candidates.json"
DEFAULT_DECISIONS_OUT = "outputs/committee_edge_decisions.json"
DEFAULT_REPORT_OUT = "outputs/committee_edge_report.json"
DEFAULT_MERGED_OUT = "outputs/consistency_checks.committee_edge.json"
DEFAULT_MAX_READS = 12

COMMITTEE_RESPONSE_FORMAT = copy.deepcopy(vc.RESPONSE_FORMAT)
COMMITTEE_DECISION_CHECKS = COMMITTEE_RESPONSE_FORMAT["schema"]["properties"]["decision_checks"]
COMMITTEE_DECISION_CHECKS["properties"].update(
    {
        "interpretation_depth": {"type": "string", "enum": ["A", "B", "tie"]},
        "proof_sufficiency": {"type": "string", "enum": ["A", "B", "tie"]},
        "polish_trap": {"type": "boolean"},
        "rougher_but_stronger_latent": {"type": "boolean"},
        "alternate_theme_validity": {"type": "string", "enum": ["A", "B", "tie"]},
        "mechanics_block_meaning": {"type": "boolean"},
        "completion_floor_applied": {"type": "boolean"},
    }
)
COMMITTEE_DECISION_CHECKS["required"] = list(COMMITTEE_DECISION_CHECKS["required"]) + [
    "interpretation_depth",
    "proof_sufficiency",
    "polish_trap",
    "rougher_but_stronger_latent",
    "alternate_theme_validity",
    "mechanics_block_meaning",
    "completion_floor_applied",
]

TRIGGER_POINTS = {
    # Phase 1 triggers (retained as-is)
    "escalated_vs_direct_matrix_conflict": 90,
    "escalated_vs_aggregate_conflict": 70,
    "polish_bias_suspected": 100,
    "rougher_but_stronger_latent": 80,
    "low_medium_confidence_high_leverage": 60,
    "top10_or_boundary": 40,
    "completion_ordering_instability": 55,
    "cohort_confidence_unstable": 30,
    # Phase 2a triggers (caution-raised-but-ignored + non-escalated leverage)
    "caution_raised_but_winner_polish_like": 85,
    "caution_raised_but_ignored_rougher_stronger": 85,
    "surface_substance_inversion": 70,
    "never_escalated_high_leverage": 55,
}
HARD_EVIDENCE_MARGIN = 1.5
TOP_PACK_SIZE = 10

# Caution vocabularies used by Phase 2a triggers. Aligned with the cautions the
# cheap/orientation/escalated judges emit for literary analysis. incomplete_or_scaffold
# is grouped with the rougher-stronger cautions because it is the judge flagging the
# loser as fragmented/scaffold-ish — the same failure mode the product cares about.
POLISH_LIKE_CAUTIONS = frozenset({"polished_but_shallow", "formulaic_but_thin"})
ROUGHER_STRONGER_CAUTIONS = frozenset(
    {"rougher_but_stronger_content", "mechanics_impede_meaning", "incomplete_or_scaffold"}
)
NON_ESCALATED_SOURCES = frozenset({"cheap_pairwise", "orientation_audit"})
CAUTION_IGNORED_TRIGGERS = frozenset(
    {
        "caution_raised_but_winner_polish_like",
        "caution_raised_but_ignored_rougher_stronger",
        "surface_substance_inversion",
        "never_escalated_high_leverage",
    }
)


@dataclass(frozen=True)
class CandidateConfig:
    # Overall budget. Phase 2a introduces the caution_ignored bucket and a
    # four-level priority tiering (0=polished_but_shallow KEEP, 1=escalated
    # judge ignored caution despite text evidence, 2=non-escalated KEEP with
    # caution+text or SWAP overcorrection, 3=generic bucket member). Residual
    # pairs on Ghost Grade-7 land in tiers 0–2; the cap must be big enough
    # to cover all of tiers 0–2 up through the lowest-ranked residual in
    # tier 2 (s004::s008 at tier-2 rank 44 on Ghost live data → 3+5+44 = 52
    # with a small buffer). Phase 2b will further rank via model vote.
    #
    # NB: bucket caps for top_pack / level / rougher_stronger / completion
    # stay tight because those routes have not changed.
    max_candidates: int = 72           # Phase 1: 12 → Phase 2a: 72 (fits caution_ignored
                                       # window + existing bucket caps)
    max_top_pack: int = 8              # Phase 1: 6  → Phase 2a: 8
    max_level_boundary: int = 4
    max_rougher_stronger: int = 6
    max_completion_ordering: int = 2
    max_caution_ignored: int = 56      # Phase 2a: cap tuned to fit all five Ghost
                                       # residuals under priority-tier ordering with
                                       # a small buffer. Tier 0 (3) + Tier 1 (5) +
                                       # top 48 of Tier 2 fit in 56 slots on live data.
    min_trigger_score: int = 80
    caution_ignored_min_trigger_score: int = 70  # Bucket-specific threshold for caution_ignored
    support_margin: float = 0.20
    polish_bias_surface_sd: float = 1.0
    interpretive_density_delta: float = 0.03  # loser-minus-winner threshold for "stronger interpretation"


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


def load_blind_read_fixture(path: Path | None) -> dict[str, dict]:
    if path is None:
        return {}
    payload = load_required_json(path)
    raw_items = payload.get("reads")
    if not isinstance(raw_items, list):
        raw_items = payload.get("decisions") if isinstance(payload.get("decisions"), list) else []
    fixture = {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("pair_key") or pair_key_from_item(raw) or "").strip()
        if key:
            fixture[key] = copy.deepcopy(raw)
    return fixture


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


def task_config(routing: dict, task_name: str) -> dict:
    tasks = routing.get("tasks", {}) if isinstance(routing.get("tasks"), dict) else {}
    task = tasks.get(task_name, {}) if isinstance(tasks, dict) else {}
    return task if isinstance(task, dict) else {}


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
    # Phase 2a: caution_ignored takes precedence over other buckets. When any of the
    # caution-raised-but-ignored / surface-substance-inversion / never-escalated
    # triggers fires, this pair represents the primary Phase 2a failure mode and
    # must land in its own bounded bucket for downstream routing.
    if set(triggers) & CAUTION_IGNORED_TRIGGERS:
        return "caution_ignored"
    if details.get("level_cross") or details.get("band_seam_pair"):
        return "level_boundary"
    if details.get("higher_rank", 999999) <= TOP_PACK_SIZE or details.get("lower_rank", 999999) <= TOP_PACK_SIZE:
        return "top_pack"
    if "rougher_but_stronger_latent" in triggers or "polish_bias_suspected" in triggers:
        return "rougher_stronger"
    if "completion_ordering_instability" in triggers:
        return "completion_ordering"
    return "other"


def effective_min_trigger_score(bucket: str, config: CandidateConfig) -> int:
    """Bucket-specific minimum trigger score.

    caution_ignored uses a relaxed threshold so that the broadest heuristic
    (surface_substance_inversion, 70 pts) can fire on its own and still be
    bucket-capped. Other buckets keep the stricter default threshold.
    """
    if bucket == "caution_ignored":
        return int(config.caution_ignored_min_trigger_score)
    return int(config.min_trigger_score)


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
        winner_text = texts_by_id.get(winner, "")
        loser_text = texts_by_id.get(loser, "")
        winner_features = compute_surface_features(winner_text)
        loser_features = compute_surface_features(loser_text)
        gap = polish_vs_substance_gap(winner_features, loser_features)
        surface_features = {
            "winner": winner_features.to_dict(),
            "loser": loser_features.to_dict(),
            "gap": gap,
        }
        density_delta_loser = interpretive_density_delta(winner_features, loser_features)
        verb_delta_loser = loser_features.interpretive_verb_count - winner_features.interpretive_verb_count
        decision_basis = str(item.get("decision_basis") or "").strip()
        confidence = str(item.get("confidence") or "low").strip().lower()
        cautions = item.get("cautions_applied") if isinstance(item.get("cautions_applied"), list) else []
        cautions_set = {str(caution).strip() for caution in cautions}
        source = normalize_source(item)
        direct_margin = direct_matrix_margin(matrix_map.get(pair_key, {}), winner, loser)
        support_margin = round(row_support(loser_row, student_count) - row_support(winner_row, student_count), 6)
        completion_floor_flag = bool(
            winner_row.get("_draft_completion_floor_applied") or loser_row.get("_draft_completion_floor_applied")
        )

        # Secondary "loser interpretation dominates" evidence the Phase 2a caution
        # triggers use to reinforce the caution signal. We accept density delta OR
        # verb-count delta — the latter catches short-essay cases where density
        # is misleading. We do NOT relax on non-escalated source alone: the
        # orientation_audit layer raises rougher_but_stronger_content on ~47% of
        # pairs as boilerplate, so source alone is not discriminating (it'd flood
        # the caution_ignored bucket with orientation-audit boilerplate).
        loser_interpretation_dominant = bool(
            density_delta_loser >= config.interpretive_density_delta
            or verb_delta_loser >= 2
        )
        polished_but_shallow_raised = "polished_but_shallow" in cautions_set
        # basis=completion pairs encode the completion-floor rule directly; the
        # rougher-stronger caution on these pairs is almost always subordinate to
        # the correct completion-based decision. Veto the Phase 2a caution and
        # never-escalated triggers here to prevent completion-floor comparisons
        # from flooding the bucket.
        completion_basis_veto = decision_basis == "completion"
        keep_decision = decision == "KEEP"
        swap_decision = decision == "SWAP"

        triggers: set[str] = set()
        if direct_margin >= HARD_EVIDENCE_MARGIN:
            triggers.add("escalated_vs_direct_matrix_conflict")
        if support_margin >= config.support_margin:
            triggers.add("escalated_vs_aggregate_conflict")
        if (
            decision_basis in {"organization", "language_control"}
            and "polished_but_shallow" not in cautions_set
            and gap["polish_bias_flag"]
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
            completion_floor_flag
            and decision_basis != "completion"
        ):
            triggers.add("completion_ordering_instability")
        if unstable_cohort and confidence == "low":
            triggers.add("cohort_confidence_unstable")

        # --- Phase 2a triggers --------------------------------------------------
        # "Caution raised but ignored" is the primary Phase 2a failure mode: the
        # cheap/orientation/escalated judge explicitly flagged polish-bias or
        # rougher-stronger risk, then still picked the surface-clean side with a
        # KEEP decision. A SWAP on the same caution usually means the judge
        # absorbed the signal correctly, so we only fire on KEEP (except the
        # narrow SWAP-overcorrection branch in rougher_stronger below).
        polish_like_caution_raised = bool(cautions_set & POLISH_LIKE_CAUTIONS)
        if (
            polish_like_caution_raised
            and keep_decision
            and not completion_basis_veto
            and (loser_interpretation_dominant or polished_but_shallow_raised)
        ):
            triggers.add("caution_raised_but_winner_polish_like")

        rougher_stronger_caution_raised = bool(cautions_set & ROUGHER_STRONGER_CAUTIONS)
        # Two failure paths for rougher-stronger caution:
        #   (a) KEEP that ignored the caution: judge flagged loser as
        #       rougher-but-stronger, then kept the surface-clean winner anyway.
        #   (b) SWAP overcorrection from a non-escalated judge: the caution
        #       was raised, a SWAP followed, but interpretive density says the
        #       new loser was actually the more interpretive side — the swap
        #       went the wrong way. This mirrors the Ghost s019::s022 pattern
        #       where orientation_audit flipped the seed order incorrectly.
        rougher_stronger_keep_ignored = (
            keep_decision and loser_interpretation_dominant
        )
        rougher_stronger_swap_overcorrection = (
            swap_decision
            and source in NON_ESCALATED_SOURCES
            and density_delta_loser <= -config.interpretive_density_delta
        )
        if (
            rougher_stronger_caution_raised
            and not completion_basis_veto
            and (rougher_stronger_keep_ignored or rougher_stronger_swap_overcorrection)
        ):
            triggers.add("caution_raised_but_ignored_rougher_stronger")

        # Dedup: when the caution-raised trigger fires, the rougher_but_stronger
        # _latent trigger is encoding the same signal (just via aggregate data
        # instead of text+caution). Suppress the latent trigger to prevent
        # score stacking from pushing borderline pairs above residual patterns.
        if (
            "caution_raised_but_ignored_rougher_stronger" in triggers
            and "rougher_but_stronger_latent" in triggers
        ):
            triggers.discard("rougher_but_stronger_latent")

        # surface_substance_inversion is the broadest heuristic and is intentionally
        # strict (surface_delta ≥ polish_bias_surface_sd AND substance_delta ≤ 0). It
        # lives in the caution_ignored bucket so it is always bucket-capped and
        # heavily logged (see surface_substance_inversion_log below + the
        # surface_substance_inversion_fires report list).
        surface_substance_inversion_fires_here = bool(
            gap["surface_delta"] >= config.polish_bias_surface_sd
            and gap["substance_delta"] <= 0.0
        )
        if surface_substance_inversion_fires_here:
            triggers.add("surface_substance_inversion")

        # Tightened leverage: top10_involved alone (both seeds in top-10) is too
        # broad — it fires on most Ghost pairs. Require an actual crossing
        # (level_cross or top10_cross), a completion-floor edge, or a strong
        # caution that signals the judge flagged rougher-stronger risk.
        never_escalated_leverage_signal = bool(
            level_cross
            or top10_cross
            or completion_floor_flag
            or (cautions_set & {"rougher_but_stronger_content", "mechanics_impede_meaning"})
        )
        if (
            source in NON_ESCALATED_SOURCES
            and not completion_basis_veto
            and never_escalated_leverage_signal
        ):
            triggers.add("never_escalated_high_leverage")

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
            "winner_source": source,
            "genre": genre,
            # Phase 2a diagnostics — these land in committee_edge_candidates.json
            # so humans can audit why each pair was (or was not) routed.
            "interpretive_density_delta_loser": round(density_delta_loser, 6),
            "interpretive_verb_delta_loser": int(verb_delta_loser),
            "polish_like_caution_raised": polish_like_caution_raised,
            "rougher_stronger_caution_raised": rougher_stronger_caution_raised,
            "polished_but_shallow_raised": polished_but_shallow_raised,
            "loser_interpretation_dominant": loser_interpretation_dominant,
            "non_escalated_source": source in NON_ESCALATED_SOURCES,
            "completion_basis_veto": completion_basis_veto,
            "completion_floor_flag": completion_floor_flag,
            "keep_decision": keep_decision,
            "swap_decision": swap_decision,
        }

        # Heavy logging for surface_substance_inversion: user explicitly asked this
        # trigger be bucket-capped AND audited every time it fires. The log captures
        # the deltas, cautions, source, and whether any caution was actually raised.
        if surface_substance_inversion_fires_here:
            details["surface_substance_inversion_log"] = {
                "surface_delta": gap["surface_delta"],
                "substance_delta": gap["substance_delta"],
                "polish_bias_flag": gap["polish_bias_flag"],
                "cautions_raised": sorted(cautions_set),
                "any_caution_raised": bool(cautions_set),
                "winner_source": source,
                "higher_rank": higher_rank,
                "lower_rank": lower_rank,
            }

        score = score_candidate(triggers, details, config)
        bucket = candidate_bucket(triggers, details, config)
        if score < effective_min_trigger_score(bucket, config):
            continue
        # Caution_ignored priority tier. When the bucket is over-subscribed,
        # residual-like signals should be selected before generic ones. Lower
        # tier = higher priority. Tier 0 is the rarest pattern (polished_but_shallow
        # caution explicitly raised), Tier 1 is "escalated judge ignored a caution
        # despite text evidence" (the most rigorous layer still went polish-first),
        # Tier 2 is "non-escalated judge ignored a caution with text evidence or
        # SWAP overcorrection", Tier 3 is everything else in the bucket.
        caution_ignored_priority_tier = 3
        if bucket == "caution_ignored":
            if polished_but_shallow_raised and keep_decision:
                caution_ignored_priority_tier = 0
            elif (
                source == "escalated_adjudication"
                and keep_decision
                and (polish_like_caution_raised or rougher_stronger_caution_raised)
                and loser_interpretation_dominant
            ):
                caution_ignored_priority_tier = 1
            elif (
                source in NON_ESCALATED_SOURCES
                and (
                    (keep_decision
                     and (polish_like_caution_raised or rougher_stronger_caution_raised)
                     and (loser_interpretation_dominant or polished_but_shallow_raised))
                    or (swap_decision
                        and rougher_stronger_caution_raised
                        and density_delta_loser <= -config.interpretive_density_delta)
                )
            ):
                caution_ignored_priority_tier = 2
        details["caution_ignored_priority_tier"] = caution_ignored_priority_tier
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
                "caution_ignored_priority_tier": caution_ignored_priority_tier,
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


def candidate_priority(candidate: dict) -> tuple[int, int, int, int, str]:
    seed_order = candidate.get("seed_order") if isinstance(candidate.get("seed_order"), dict) else {}
    # Caution-ignored tiering: pairs outside the caution_ignored bucket sort
    # purely by score (tier=3 default), while caution_ignored pairs can claim
    # a lower tier (0–2) if they match a residual-like pattern. This ensures
    # the Ghost hard-pair residuals are selected before generic bucket members
    # when the cap is tight. NB: do not use `x or 3` short-circuit here — it
    # would collapse tier 0 (a falsy int) to tier 3.
    raw_tier = candidate.get("caution_ignored_priority_tier")
    if raw_tier is None:
        tier = 3
    else:
        try:
            tier = int(raw_tier)
        except (TypeError, ValueError):
            tier = 3
    if candidate.get("bucket") != "caution_ignored":
        tier = 3
    return (
        tier,
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
        "caution_ignored": max(0, int(config.max_caution_ignored)),
    }
    bucket_counts = {
        "top_pack": 0,
        "level_boundary": 0,
        "rougher_stronger": 0,
        "completion_ordering": 0,
        "caution_ignored": 0,
        "other": 0,
    }
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


def committee_anchor_selection_details(path: Path) -> list[str]:
    payload = load_optional_json(path)
    if not payload:
        return []
    details = ["Committee literary calibration anchors are active for this blind read."]
    axes = payload.get("decision_axes") if isinstance(payload.get("decision_axes"), list) else []
    if axes:
        details.append(
            "Decision axes: "
            + "; ".join(
                f"{str(axis.get('id', '')).strip()}: {str(axis.get('prompt', '')).strip()}"
                for axis in axes
                if isinstance(axis, dict) and str(axis.get("id", "")).strip()
            )
        )
    anchors = payload.get("anchors") if isinstance(payload.get("anchors"), list) else []
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        title = str(anchor.get("title", "") or "").strip()
        rule = str(anchor.get("decision_rule", "") or "").strip()
        if title and rule:
            details.append(f"{title}: {rule}")
    return [detail for detail in details if detail.strip()]


def candidate_selection_detail_lines(candidate: dict) -> list[str]:
    details = candidate.get("trigger_details") if isinstance(candidate.get("trigger_details"), dict) else {}
    return [
        "This is a blind committee read. Do not rely on prior pairwise decisions, seed order, aggregate rank, Borda support, or committee trigger labels as evidence.",
        "Resolve the pair using the rubric, assignment, committee anchors, and essay texts only.",
        f"Candidate bucket for audit logging: {candidate.get('bucket', '')}.",
        f"Surface/substance deltas for audit logging only: {details.get('surface_substance_inversion_log', {}) or candidate.get('surface_features', {}).get('gap', {})}.",
    ]


def normalize_committee_read(candidate: dict, read: dict) -> dict:
    seed_order = candidate.get("seed_order") if isinstance(candidate.get("seed_order"), dict) else {}
    higher = str(seed_order.get("higher") or "").strip()
    lower = str(seed_order.get("lower") or "").strip()
    pair = [higher, lower]
    item = copy.deepcopy(read)
    winner = str(item.get("winner") or "").strip()
    if winner not in {higher, lower}:
        side = normalize_winner_side(item.get("winner_side"))
        decision = "KEEP" if side == "A" else "SWAP" if side == "B" else normalize_decision(item.get("decision"))
        winner = higher if decision == "KEEP" else lower
    loser = lower if winner == higher else higher
    winner_side = "A" if winner == higher else "B"
    decision = "KEEP" if winner_side == "A" else "SWAP"
    checks = item.get("decision_checks") if isinstance(item.get("decision_checks"), dict) else {}
    checks = normalize_committee_decision_checks(checks)
    item.update(
        {
            "pair": pair,
            "pair_key": pair_key_from_item({"pair": pair}),
            "seed_order": {
                "higher": higher,
                "lower": lower,
                "higher_rank": int(seed_order.get("higher_rank", 999999) or 999999),
                "lower_rank": int(seed_order.get("lower_rank", 999999) or 999999),
            },
            "winner": winner,
            "loser": loser,
            "winner_side": winner_side,
            "decision": decision,
            "confidence": vc.normalize_confidence(item.get("confidence")),
            "decision_basis": vc.normalize_decision_basis(item.get("decision_basis")),
            "cautions_applied": vc.normalize_cautions(item.get("cautions_applied")),
            "decision_checks": checks,
            "rationale": str(item.get("rationale", "") or "").strip(),
        }
    )
    metadata = item.get("model_metadata") if isinstance(item.get("model_metadata"), dict) else {}
    metadata = dict(metadata)
    metadata.setdefault("adjudication_source", "committee_read_a")
    metadata.setdefault("committee_read", "A-blind")
    item["model_metadata"] = metadata
    return item


def normalize_committee_decision_checks(value: dict) -> dict:
    base = vc.normalize_decision_checks(value)
    base["interpretation_depth"] = vc.normalize_side(value.get("interpretation_depth") or value.get("deeper_interpretation"))
    base["proof_sufficiency"] = vc.normalize_side(value.get("proof_sufficiency") or value.get("better_text_evidence_explanation"))
    base["polish_trap"] = truthy(value.get("polish_trap"))
    base["rougher_but_stronger_latent"] = truthy(value.get("rougher_but_stronger_latent"))
    base["alternate_theme_validity"] = vc.normalize_side(value.get("alternate_theme_validity"))
    base["mechanics_block_meaning"] = truthy(value.get("mechanics_block_meaning"))
    base["completion_floor_applied"] = truthy(value.get("completion_floor_applied"))
    return base


def run_blind_read_a(
    candidate: dict,
    rows_by_id: dict[str, dict],
    texts: dict[str, str],
    rubric: str,
    outline: str,
    metadata: dict,
    *,
    model: str,
    routing: str,
    reasoning: str,
    max_output_tokens: int,
    anchor_dir: Path,
    committee_anchor: Path,
) -> dict:
    seed_order = candidate.get("seed_order") if isinstance(candidate.get("seed_order"), dict) else {}
    higher_id = str(seed_order.get("higher", "") or "").strip()
    lower_id = str(seed_order.get("lower", "") or "").strip()
    if higher_id not in rows_by_id or lower_id not in rows_by_id:
        raise ValueError(f"Candidate {candidate.get('pair_key', '')}: missing row for blind read")
    selection_details = committee_anchor_selection_details(committee_anchor) + candidate_selection_detail_lines(candidate)
    judgment = vc.judge_pair_with_orientation_audit(
        rubric,
        outline,
        rows_by_id[higher_id],
        rows_by_id[lower_id],
        texts.get(higher_id, ""),
        texts.get(lower_id, ""),
        model=model,
        routing=routing,
        reasoning=reasoning,
        max_output_tokens=max_output_tokens,
        genre=str(metadata.get("assignment_genre") or metadata.get("genre") or ""),
        metadata=metadata,
        selection_reasons=["committee_edge_read_a_blind"],
        selection_details=selection_details,
        anchor_dir=anchor_dir,
        orientation_audit=False,
        student_count=len(rows_by_id),
        response_format=COMMITTEE_RESPONSE_FORMAT,
    )
    return normalize_committee_read(candidate, judgment)


def read_from_fixture(candidate: dict, fixture_by_key: dict[str, dict]) -> dict | None:
    key = str(candidate.get("pair_key") or "").strip()
    if key not in fixture_by_key:
        return None
    return normalize_committee_read(candidate, fixture_by_key[key])


def side_favors_winner(value, winner_side: str) -> bool:
    return vc.normalize_side(value) == normalize_winner_side(winner_side)


def read_a_override_decision(candidate: dict, read: dict) -> tuple[bool, str]:
    current_winner = str((candidate.get("escalated_summary") or {}).get("winner") or "").strip()
    read_winner = str(read.get("winner") or "").strip()
    if not current_winner or not read_winner:
        return False, "committee_read_a_incomplete"
    if read_winner == current_winner:
        return False, "committee_read_a_concurred"
    confidence = vc.normalize_confidence(read.get("confidence"))
    if confidence not in {"medium", "high"}:
        return False, "committee_read_a_low_confidence"
    checks = normalize_committee_decision_checks(read.get("decision_checks") if isinstance(read.get("decision_checks"), dict) else {})
    if checks["mechanics_block_meaning"] or checks["completion_floor_applied"]:
        return False, "committee_read_a_blocked_by_mechanics_or_completion"
    winner_side = normalize_winner_side(read.get("winner_side"))
    interpretation_favors_winner = side_favors_winner(checks.get("interpretation_depth"), winner_side)
    if (
        checks["polish_trap"]
        or checks["rougher_but_stronger_latent"]
        or (confidence == "high" and interpretation_favors_winner)
    ):
        return True, "committee_read_a_override"
    return False, "committee_read_a_inconclusive"


def decision_from_committee_read(candidate: dict, read: dict, reason: str) -> dict:
    item = copy.deepcopy(read)
    metadata = item.get("model_metadata") if isinstance(item.get("model_metadata"), dict) else {}
    metadata = dict(metadata)
    metadata.update(
        {
            "adjudication_source": "committee_edge",
            "committee_read": "A-blind",
            "committee_override_reason": reason,
            "supersedes_pair_key": candidate.get("pair_key", ""),
            "phase": "2b",
        }
    )
    item["model_metadata"] = metadata
    item["adjudication_source"] = "committee_edge"
    item["committee_confidence"] = f"read_a_{vc.normalize_confidence(item.get('confidence'))}"
    item["committee_edge_trace"] = {
        "read": "A-blind",
        "override_reason": reason,
        "triggers": list(candidate.get("triggers", [])),
        "committee_score": candidate.get("committee_score", 0),
        "prior_winner": (candidate.get("escalated_summary") or {}).get("winner", ""),
    }
    return item


def run_read_a_path(
    *,
    selected: list[dict],
    rows: list[dict],
    texts_by_id: dict[str, str],
    rubric: str,
    outline: str,
    metadata: dict,
    model: str,
    routing: str,
    reasoning: str,
    max_output_tokens: int,
    anchor_dir: Path,
    committee_anchor: Path,
    max_reads: int,
    live: bool,
    fixture_by_key: dict[str, dict],
) -> tuple[list[dict], list[dict], dict]:
    rows_by_id = {row["student_id"]: row for row in vc.prepare_rows(rows)}
    read_results = []
    decisions = []
    read_cap = max(0, int(max_reads))
    read_count = 0
    for candidate in selected:
        record = {
            "pair_key": candidate.get("pair_key", ""),
            "bucket": candidate.get("bucket", ""),
            "committee_score": candidate.get("committee_score", 0),
            "status": "",
            "override_emitted": False,
        }
        if read_cap and read_count >= read_cap:
            record["status"] = "max_reads_exceeded"
            read_results.append(record)
            continue
        read = read_from_fixture(candidate, fixture_by_key)
        if read is None and live:
            read = run_blind_read_a(
                candidate,
                rows_by_id,
                texts_by_id,
                rubric,
                outline,
                metadata,
                model=model,
                routing=routing,
                reasoning=reasoning,
                max_output_tokens=max_output_tokens,
                anchor_dir=anchor_dir,
                committee_anchor=committee_anchor,
            )
        if read is None:
            record["status"] = "not_read"
            read_results.append(record)
            continue
        read_count += 1
        should_override, reason = read_a_override_decision(candidate, read)
        record.update(
            {
                "status": reason,
                "read": read,
                "override_emitted": bool(should_override),
                "read_winner": read.get("winner", ""),
                "prior_winner": (candidate.get("escalated_summary") or {}).get("winner", ""),
            }
        )
        if should_override:
            decisions.append(decision_from_committee_read(candidate, read, reason))
        read_results.append(record)
    return decisions, read_results, {
        "enabled": bool(live or fixture_by_key),
        "live": bool(live),
        "fixture": bool(fixture_by_key),
        "max_reads": read_cap,
        "read_count": read_count,
        "override_count": len(decisions),
        "skipped_max_reads": sum(1 for item in read_results if item.get("status") == "max_reads_exceeded"),
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
        "rubric": str(args.rubric),
        "outline": str(args.outline),
        "routing": str(args.routing),
        "committee_anchor": str(args.committee_anchor),
        "blind_read_fixture": str(args.blind_read_fixture) if args.blind_read_fixture else "",
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
    parser.add_argument("--blind-read-fixture", type=Path, default=None, help="Optional offline Read-A fixture keyed by pair_key; no model call.")
    parser.add_argument("--live", action="store_true", help="Run live single-read committee adjudication for selected candidates.")
    parser.add_argument("--max-reads", type=int, default=DEFAULT_MAX_READS, help="Maximum selected candidates to read in live/fixture mode.")
    parser.add_argument("--rubric", type=Path, default=Path(DEFAULT_RUBRIC))
    parser.add_argument("--outline", type=Path, default=Path(DEFAULT_OUTLINE))
    parser.add_argument("--routing", type=Path, default=Path(DEFAULT_ROUTING))
    parser.add_argument("--committee-anchor", type=Path, default=Path(DEFAULT_COMMITTEE_ANCHOR))
    parser.add_argument("--model", default="", help="Override literary committee model")
    parser.add_argument("--reasoning", default="", help="Override literary committee reasoning")
    parser.add_argument("--max-output-tokens", type=int, default=0, help="Override literary committee max output tokens")
    parser.add_argument("--candidates-output", type=Path, default=Path(DEFAULT_CANDIDATES_OUT))
    parser.add_argument("--decisions-output", type=Path, default=Path(DEFAULT_DECISIONS_OUT))
    parser.add_argument("--report-output", type=Path, default=Path(DEFAULT_REPORT_OUT))
    parser.add_argument("--merged-output", type=Path, default=Path(DEFAULT_MERGED_OUT))
    parser.add_argument("--max-candidates", type=int, default=CandidateConfig.max_candidates)
    parser.add_argument("--max-top-pack", type=int, default=CandidateConfig.max_top_pack)
    parser.add_argument("--max-level-boundary", type=int, default=CandidateConfig.max_level_boundary)
    parser.add_argument("--max-rougher-stronger", type=int, default=CandidateConfig.max_rougher_stronger)
    parser.add_argument("--max-completion-ordering", type=int, default=CandidateConfig.max_completion_ordering)
    parser.add_argument("--max-caution-ignored", type=int, default=CandidateConfig.max_caution_ignored)
    parser.add_argument("--min-trigger-score", type=int, default=CandidateConfig.min_trigger_score)
    parser.add_argument(
        "--caution-ignored-min-trigger-score",
        type=int,
        default=CandidateConfig.caution_ignored_min_trigger_score,
    )
    parser.add_argument("--support-margin", type=float, default=CandidateConfig.support_margin)
    parser.add_argument("--polish-bias-surface-sd", type=float, default=CandidateConfig.polish_bias_surface_sd)
    parser.add_argument(
        "--interpretive-density-delta",
        type=float,
        default=CandidateConfig.interpretive_density_delta,
    )
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
        manual_decisions = load_decisions(args.decisions)
        blind_read_fixture = load_blind_read_fixture(args.blind_read_fixture)
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
        max_caution_ignored=args.max_caution_ignored,
        min_trigger_score=args.min_trigger_score,
        caution_ignored_min_trigger_score=args.caution_ignored_min_trigger_score,
        support_margin=args.support_margin,
        polish_bias_surface_sd=args.polish_bias_surface_sd,
        interpretive_density_delta=args.interpretive_density_delta,
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
    read_a_decisions = []
    read_a_results = []
    read_a_summary = {
        "enabled": False,
        "live": False,
        "fixture": False,
        "max_reads": int(args.max_reads),
        "read_count": 0,
        "override_count": 0,
        "skipped_max_reads": 0,
    }
    if args.live or blind_read_fixture:
        try:
            routing_payload = load_optional_json(args.routing)
            task = task_config(routing_payload, "literary_committee")
            model = args.model or task.get("model") or routing_payload.get("default_model") or "gpt-5.4"
            reasoning = args.reasoning or task.get("reasoning") or "high"
            max_output_tokens = int(args.max_output_tokens or task.get("max_output_tokens") or 2000)
            rubric = ""
            outline = ""
            if args.live:
                rubric_path = resolve_input_path(args.rubric, "rubric")
                outline_path = resolve_input_path(args.outline, "assignment_outline")
                rubric = load_file_text(rubric_path)
                outline = load_file_text(outline_path)
                if not rubric.strip():
                    raise ValueError(f"Rubric text is empty. Check file at {rubric_path}.")
            read_a_decisions, read_a_results, read_a_summary = run_read_a_path(
                selected=selected,
                rows=rows,
                texts_by_id=texts_by_id,
                rubric=rubric,
                outline=outline,
                metadata=class_metadata,
                model=model,
                routing=str(args.routing),
                reasoning=str(reasoning),
                max_output_tokens=max_output_tokens,
                anchor_dir=args.committee_anchor.parent,
                committee_anchor=args.committee_anchor,
                max_reads=args.max_reads,
                live=bool(args.live),
                fixture_by_key=blind_read_fixture,
            )
        except Exception as exc:
            report = {
                "generated_at": generated_at,
                "phase": 2,
                "passthrough": True,
                "source_paths": source_paths,
                "error": str(exc),
                "read_a": read_a_summary,
            }
            write_json(args.report_output, report)
            return 1
    decisions = manual_decisions + read_a_decisions
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
        "read_a": read_a_summary,
        "read_a_results": read_a_results,
    }
    trigger_counts = Counter()
    bucket_counts = Counter()
    surface_substance_inversion_fires = []
    caution_ignored_selected = []
    for candidate in merged_candidates:
        triggers_on_candidate = candidate.get("triggers", []) or []
        trigger_counts.update(triggers_on_candidate)
        bucket = str(candidate.get("bucket") or "other")
        bucket_counts[bucket] += 1
        # Heavy logging for surface_substance_inversion: every fire is recorded in a
        # dedicated report list so humans can audit the broadest (and therefore
        # noisiest) heuristic independently from the per-candidate diagnostics.
        details = candidate.get("trigger_details") if isinstance(candidate.get("trigger_details"), dict) else {}
        log = details.get("surface_substance_inversion_log") if isinstance(details.get("surface_substance_inversion_log"), dict) else None
        if "surface_substance_inversion" in triggers_on_candidate and log is not None:
            surface_substance_inversion_fires.append(
                {
                    "pair_key": candidate.get("pair_key"),
                    "selection_status": candidate.get("selection_status"),
                    "bucket": bucket,
                    "committee_score": candidate.get("committee_score"),
                    **log,
                }
            )
        if bucket == "caution_ignored" and candidate.get("selection_status") == "selected":
            caution_ignored_selected.append(
                {
                    "pair_key": candidate.get("pair_key"),
                    "committee_score": candidate.get("committee_score"),
                    "triggers": triggers_on_candidate,
                    "escalated_cautions": details.get("escalated_cautions", []),
                    "winner_source": details.get("winner_source"),
                }
            )
    report_payload = {
        "generated_at": generated_at,
        "phase": 1,
        "passthrough": passthrough,
        "source_paths": source_paths,
        "trigger_counts": dict(sorted(trigger_counts.items())),
        "bucket_counts": dict(sorted(bucket_counts.items())),
        "budget": budget,
        "surface_substance_inversion_fires": surface_substance_inversion_fires,
        "caution_ignored_selected": caution_ignored_selected,
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
        "read_a": read_a_summary,
        "phase2_ready": True,
    }
    write_json(args.candidates_output, candidate_payload)
    write_json(args.decisions_output, decisions_payload)
    write_json(args.report_output, report_payload)
    write_json(args.merged_output, merged_payload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
