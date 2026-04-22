#!/usr/bin/env python3
"""Routed committee-edge adjudication.

Phase 1 shipped the scaffold (passthrough + precedence + basic triggers).
Phase 2a calibrated the trigger set so the resolver routes "caution raised
but ignored" pairs — the primary failure mode on the Ghost Grade-7 literary
cohort. Later phases add routed live committee reads behind explicit flags:
Read A blind, Read B polish-trap audit, and Read C placement calibration.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import sys
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
    from scripts.evidence_map import (
        DEFAULT_MAX_GROUP_PACKETS,
        DEFAULT_MAX_PACKET_STUDENTS,
        build_evidence_group_calibration_packets,
        build_evidence_neighborhood_report,
        compare_evidence_maps,
        evidence_map_summary,
    )
    from scripts.openai_client import extract_text, responses_create
    from scripts.source_calibration import (
        DEFAULT_SOURCE_CALIBRATION,
        format_source_calibration_lines,
        load_source_calibration,
        parse_grade_level,
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
    from evidence_map import (  # type: ignore  # pragma: no cover
        DEFAULT_MAX_GROUP_PACKETS,
        DEFAULT_MAX_PACKET_STUDENTS,
        build_evidence_group_calibration_packets,
        build_evidence_neighborhood_report,
        compare_evidence_maps,
        evidence_map_summary,
    )
    from openai_client import extract_text, responses_create  # type: ignore  # pragma: no cover
    from source_calibration import (  # type: ignore  # pragma: no cover
        DEFAULT_SOURCE_CALIBRATION,
        format_source_calibration_lines,
        load_source_calibration,
        parse_grade_level,
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
DEFAULT_SOURCE_CALIBRATION_PATH = str(DEFAULT_SOURCE_CALIBRATION.relative_to(Path(__file__).resolve().parents[1]))
DEFAULT_EVIDENCE_MAP = "outputs/evidence_map.json"
DEFAULT_EVIDENCE_NEIGHBORHOOD_OUT = "outputs/evidence_neighborhood_report.json"
DEFAULT_EVIDENCE_GROUP_PACKETS_OUT = "outputs/evidence_group_calibration_packets.json"
DEFAULT_CANDIDATES_OUT = "outputs/committee_edge_candidates.json"
DEFAULT_DECISIONS_OUT = "outputs/committee_edge_decisions.json"
DEFAULT_REPORT_OUT = "outputs/committee_edge_report.json"
DEFAULT_MERGED_OUT = "outputs/consistency_checks.committee_edge.json"
DEFAULT_LIVE_TRACE_OUT = "outputs/committee_edge_live_trace.json"
DEFAULT_MAX_READS = 12
DEFAULT_MAX_GROUP_CALIBRATIONS = 1
DEFAULT_MAX_GROUP_STUDENTS = 12
DEFAULT_GROUP_MAX_OUTPUT_TOKENS = 6000

COMMITTEE_RESPONSE_FORMAT = copy.deepcopy(vc.RESPONSE_FORMAT)
COMMITTEE_DECISION_CHECKS = COMMITTEE_RESPONSE_FORMAT["schema"]["properties"]["decision_checks"]
LEDGER_SIDE_SCHEMA = {
    "type": "object",
    "properties": {
        "central_claim": {"type": "string"},
        "specific_text_moments": {"type": "array", "items": {"type": "string"}},
        "explained_moment_count": {"type": "integer"},
        "interpretation_depth": {"type": "string", "enum": ["none", "weak", "adequate", "strong"]},
        "proof_sufficiency": {"type": "string", "enum": ["none", "weak", "adequate", "strong"]},
        "plot_summary_only": {"type": "boolean"},
        "formulaic_control_only": {"type": "boolean"},
        "mechanics_block_meaning": {"type": "boolean"},
        "completion_floor_applied": {"type": "boolean"},
        "strongest_substance_reason": {"type": "string"},
    },
    "required": [
        "central_claim",
        "specific_text_moments",
        "explained_moment_count",
        "interpretation_depth",
        "proof_sufficiency",
        "plot_summary_only",
        "formulaic_control_only",
        "mechanics_block_meaning",
        "completion_floor_applied",
        "strongest_substance_reason",
    ],
    "additionalProperties": False,
}
SOURCE_CALIBRATION_CHECKS_SCHEMA = {
    "type": "object",
    "properties": {
        "source_calibrated_winner": {"type": "string", "enum": ["A", "B", "tie"]},
        "evidence_explained_not_named": {"type": "string", "enum": ["A", "B", "tie"]},
        "commentary_depth": {"type": "string", "enum": ["A", "B", "tie"]},
        "surface_control_advantage": {"type": "string", "enum": ["A", "B", "tie"]},
        "surface_control_is_decisive": {"type": "boolean"},
        "mature_theme_without_proof": {"type": "string", "enum": ["A", "B", "none"]},
        "completion_floor_has_observable_scaffold": {"type": "boolean"},
        "active_rubric_remains_authority": {"type": "boolean"},
        "source_calibration_rationale": {"type": "string"},
    },
    "required": [
        "source_calibrated_winner",
        "evidence_explained_not_named",
        "commentary_depth",
        "surface_control_advantage",
        "surface_control_is_decisive",
        "mature_theme_without_proof",
        "completion_floor_has_observable_scaffold",
        "active_rubric_remains_authority",
        "source_calibration_rationale",
    ],
    "additionalProperties": False,
}
COMMITTEE_DECISION_CHECKS["properties"].update(
    {
        "interpretation_depth": {"type": "string", "enum": ["A", "B", "tie"]},
        "proof_sufficiency": {"type": "string", "enum": ["A", "B", "tie"]},
        "polish_trap": {"type": "boolean"},
        "rougher_but_stronger_latent": {"type": "boolean"},
        "alternate_theme_validity": {"type": "string", "enum": ["A", "B", "tie"]},
        "mechanics_block_meaning": {"type": "boolean"},
        "completion_floor_applied": {"type": "boolean"},
        "evidence_ledger": {
            "type": "object",
            "properties": {"A": LEDGER_SIDE_SCHEMA, "B": LEDGER_SIDE_SCHEMA},
            "required": ["A", "B"],
            "additionalProperties": False,
        },
        "source_calibration_checks": SOURCE_CALIBRATION_CHECKS_SCHEMA,
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
    "evidence_ledger",
    "source_calibration_checks",
]

GROUP_CALIBRATION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "ordered_student_ids": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "rationale": {"type": "string"},
            "placement_notes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "student_id": {"type": "string"},
                        "placement_band": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["student_id", "placement_band", "reason"],
                    "additionalProperties": False,
                },
            },
            "edge_decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "pair_key": {"type": "string"},
                        "winner": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                        "rationale": {"type": "string"},
                        "polish_trap": {"type": "boolean"},
                        "rougher_but_stronger_latent": {"type": "boolean"},
                        "mechanics_block_meaning": {"type": "boolean"},
                        "completion_floor_applied": {"type": "boolean"},
                        "interpretive_claim_winner": {"type": "string"},
                        "proof_quality_winner": {"type": "string"},
                        "textual_specificity_winner": {"type": "string"},
                        "surface_control_winner": {"type": "string"},
                        "completion_coherence_winner": {"type": "string"},
                        "decisive_axis": {
                            "type": "string",
                            "enum": [
                                "interpretive_claim",
                                "proof_quality",
                                "textual_specificity",
                                "surface_control",
                                "completion_coherence",
                                "mechanics",
                                "completion_floor",
                                "tie_or_ambiguous",
                            ],
                        },
                        "routed_cautions": {"type": "array", "items": {"type": "string"}},
                        "caution_honored": {"type": "boolean"},
                        "caution_not_decisive_reason": {"type": "string"},
                        "winner_text_moments": {"type": "array", "items": {"type": "string"}},
                        "loser_text_moments": {"type": "array", "items": {"type": "string"}},
                        "loser_interpretive_claim": {"type": "string"},
                        "winner_counterclaim": {"type": "string"},
                        "loser_claim_refutation": {"type": "string"},
                        "claim_refutation_text_moments": {"type": "array", "items": {"type": "string"}},
                        "mechanics_blocked_student": {"type": "string"},
                        "mechanics_blocker_evidence": {"type": "array", "items": {"type": "string"}},
                        "mechanics_blocker_reason": {"type": "string"},
                    },
                    "required": [
                        "pair_key",
                        "winner",
                        "confidence",
                        "rationale",
                        "polish_trap",
                        "rougher_but_stronger_latent",
                        "mechanics_block_meaning",
                        "completion_floor_applied",
                        "interpretive_claim_winner",
                        "proof_quality_winner",
                        "textual_specificity_winner",
                        "surface_control_winner",
                        "completion_coherence_winner",
                        "decisive_axis",
                        "routed_cautions",
                        "caution_honored",
                        "caution_not_decisive_reason",
                        "winner_text_moments",
                        "loser_text_moments",
                        "loser_interpretive_claim",
                        "winner_counterclaim",
                        "loser_claim_refutation",
                        "claim_refutation_text_moments",
                        "mechanics_blocked_student",
                        "mechanics_blocker_evidence",
                        "mechanics_blocker_reason",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["ordered_student_ids", "confidence", "rationale", "placement_notes", "edge_decisions"],
        "additionalProperties": False,
    },
}

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
INTERPRETATION_CONTENT_CAUTIONS = frozenset(
    {"formulaic_but_thin", "polished_but_shallow", "rougher_but_stronger_content", "incomplete_or_scaffold"}
)
CAUTION_REASON_KEYWORDS = {
    "formulaic_but_thin": frozenset(
        {"formula", "formulaic", "thin", "repetitive", "repetition", "surface", "organized", "organization"}
    ),
    "polished_but_shallow": frozenset(
        {"polish", "polished", "shallow", "surface", "formula", "formulaic", "organized", "organization"}
    ),
    "rougher_but_stronger_content": frozenset(
        {"rough", "rougher", "content", "meaning", "substance", "interpret", "interpretive", "interpretation"}
    ),
    "mechanics_impede_meaning": frozenset(
        {"mechanic", "mechanics", "error", "errors", "grammar", "sentence", "unclear", "meaning", "block"}
    ),
    "incomplete_or_scaffold": frozenset(
        {"incomplete", "scaffold", "unfinished", "fragment", "draft", "completion", "floor"}
    ),
}
GENERIC_CAUTION_REASON_PHRASES = frozenset(
    {
        "more proof",
        "stronger proof",
        "more concrete",
        "concrete evidence",
        "more evidence",
        "text grounded",
        "text-grounded",
        "clearer consequences",
        "better support",
        "more specific events",
    }
)
CLAIM_REFUTATION_GENERIC_PHRASES = frozenset(
    {
        "more proof",
        "stronger proof",
        "more concrete",
        "concrete evidence",
        "more evidence",
        "text grounded",
        "text-grounded",
        "clearer consequences",
        "better support",
        "more specific events",
        "more examples",
        "better examples",
        "more textual evidence",
        "more text evidence",
        "more plot events",
        "names more events",
        "stronger evidence",
        "better evidence",
        "clearer proof",
        "proof is stronger",
    }
)
CLAIM_REFUTATION_MARKERS = frozenset(
    {
        "because",
        "but",
        "whereas",
        "while",
        "although",
        "fails",
        "does not",
        "doesn't",
        "not actually",
        "only",
        "rather than",
        "instead",
        "mostly",
        "unsupported",
        "underdeveloped",
    }
)
CLAIM_REFUTATION_CONTENT_KEYWORDS = frozenset(
    {
        "interpret",
        "interpretive",
        "interpretation",
        "meaning",
        "claim",
        "theme",
        "content",
        "accountability",
        "identity",
        "trauma",
        "healing",
        "trust",
        "support",
        "consequence",
        "consequences",
        "growth",
        "change",
        "responsibility",
        "character",
        "lesson",
        "why",
        "shows",
        "reveals",
        "suggests",
        "proves",
    }
)
MECHANICS_BLOCKING_KEYWORDS = frozenset(
    {
        "unrecoverable",
        "meaning is unrecoverable",
        "meaning is not recoverable",
        "not reliably recoverable",
        "cannot recover",
        "can't recover",
        "cannot follow",
        "can't follow",
        "not understandable",
        "incomprehensible",
        "unreadable",
        "block meaning",
        "blocks meaning",
        "blocks",
        "blocked",
        "prevents",
        "precluded",
        "collapses",
    }
)
MECHANICS_SURFACE_ONLY_PHRASES = frozenset(
    {
        "grammar errors",
        "grammatical errors",
        "word-choice",
        "word choice",
        "sentence errors",
        "sentence-level breakdown",
        "sentence level breakdown",
        "sentence breakdown",
        "breakdowns",
        "spelling errors",
        "punctuation errors",
        "rough mechanics",
        "mechanically rough",
        "harder to follow",
        "hard to follow",
        "hard to recover",
        "hard to recover reliably",
        "vague claims",
        "vagueness",
        "awkward wording",
        "run-on",
        "fragments",
    }
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
EVIDENCE_MAP_GUARD_MIN_MEDIUM_MARGIN = 0.75
UNRESOLVED_GROUP_STATUSES = frozenset(
    {
        "committee_read_ab_concurred",
        "committee_read_ab_split_b_confirms_prior",
        "committee_read_ab_split_no_trap",
        "committee_read_ab_weak_agreement",
        "committee_read_c_confirms_prior",
        "committee_read_c_not_high_confidence",
        "committee_read_c_no_substantive_basis",
        "committee_read_c_not_available",
        "committee_read_c_not_needed",
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


def progress(message: str, *, enabled: bool):
    if enabled:
        print(f"[committee_edge] {message}", file=sys.stderr, flush=True)


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


def load_evidence_maps(path: Path | None) -> dict[str, dict]:
    if path is None or not path.exists():
        return {}
    payload = load_optional_json(path)
    students = payload.get("students") if isinstance(payload.get("students"), dict) else {}
    return {str(key): value for key, value in students.items() if isinstance(value, dict)}


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


def load_group_calibration_fixture(path: Path | None) -> list[dict]:
    if path is None:
        return []
    payload = load_required_json(path)
    raw_items = payload.get("calibrations")
    if not isinstance(raw_items, list):
        raw_items = payload.get("groups") if isinstance(payload.get("groups"), list) else []
    return [copy.deepcopy(item) for item in raw_items if isinstance(item, dict)]


def load_evidence_group_packets(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    payload = load_optional_json(path)
    return payload if isinstance(payload, dict) else {}


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
    evidence_maps_by_id: dict[str, dict] | None = None,
) -> list[dict]:
    texts_by_id = texts_by_id or {}
    evidence_maps_by_id = evidence_maps_by_id or {}
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
        evidence_signal = {}
        if winner in evidence_maps_by_id and loser in evidence_maps_by_id:
            evidence_signal = compare_evidence_maps(winner, loser, evidence_maps_by_id)
            evidence_signal["active_winner"] = winner
            evidence_signal["active_loser"] = loser
            evidence_signal["contradicts_active_winner"] = bool(
                evidence_signal.get("recommended_winner") not in {"", "tie", winner}
            )
            evidence_signal["winner_summary"] = evidence_map_summary(evidence_maps_by_id.get(winner, {}))
            evidence_signal["loser_summary"] = evidence_map_summary(evidence_maps_by_id.get(loser, {}))
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
        if evidence_signal:
            details["evidence_map_pair_signal"] = evidence_signal

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
                "evidence_map_pair_signal": evidence_signal,
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


def committee_read_priority(candidate: dict) -> tuple[int, int, float, int, int, int, str]:
    """Per-read bucket reservation for Phase 3a.

    Distinct from `candidate_priority` (which drives selection into the budget).
    This function orders already-selected candidates for the order they are
    *read* by the committee. The goal: residual-shaped pairs (polish-trap
    patterns) are read first, regardless of how they placed in generic bucket
    selection, so a tight --max-reads budget does not starve the high-signal
    pairs.

    Read-tiers (lower = earlier read):
      0: cheap direct KEEP with polished_but_shallow raised. This is the most
         explicit "caution raised but ignored" polish trap.
      1: escalated KEEP across a level seam or inside the top pack where the
         loser is still interpretation-dominant. The stronger layer saw the
         edge and still protected the weaker side.
      2: orientation-audit SWAP with rougher/stronger caution and large top-pack
         movement. This catches non-escalated swaps that can reshape the top 10.
      3: cheap direct rougher/stronger top-pack crossings. These never reached
         escalation and can otherwise starve behind high-score orientation pairs.
      4: orientation-audit KEEP with a single polish-like caution.
      5: remaining surface/substance inversions.
      6: remaining caution_ignored candidates.
      9: everything else.
    """
    details = candidate.get("trigger_details") if isinstance(candidate.get("trigger_details"), dict) else {}
    triggers = set(candidate.get("triggers") or [])
    seed_order = candidate.get("seed_order") if isinstance(candidate.get("seed_order"), dict) else {}
    bucket = str(candidate.get("bucket") or "other")
    cautions = set(details.get("escalated_cautions") or [])
    source = str(details.get("winner_source") or "")
    keep_decision = bool(details.get("keep_decision"))
    swap_decision = bool(details.get("swap_decision"))
    top10_cross = bool(details.get("top10_cross"))
    top10_involved = bool(details.get("top10_involved"))
    level_cross = bool(details.get("level_cross"))
    loser_interpretation_dominant = bool(details.get("loser_interpretation_dominant"))
    polished_but_shallow_raised = bool(details.get("polished_but_shallow_raised"))
    try:
        aggregate_margin = float(details.get("aggregate_support_margin", 0.0) or 0.0)
    except (TypeError, ValueError):
        aggregate_margin = 0.0
    try:
        higher_rank = int(seed_order.get("higher_rank", details.get("higher_rank", 999999)) or 999999)
    except (TypeError, ValueError):
        higher_rank = 999999
    try:
        lower_rank = int(seed_order.get("lower_rank", details.get("lower_rank", 999999)) or 999999)
    except (TypeError, ValueError):
        lower_rank = 999999

    read_tier = 9
    if bucket == "caution_ignored":
        read_tier = 6
        if (
            source == "cheap_pairwise"
            and polished_but_shallow_raised
            and keep_decision
            and (top10_cross or level_cross)
        ):
            read_tier = 0
        elif (
            source == "escalated_adjudication"
            and keep_decision
            and loser_interpretation_dominant
            and (level_cross or (top10_involved and lower_rank <= TOP_PACK_SIZE))
            and (cautions & (POLISH_LIKE_CAUTIONS | ROUGHER_STRONGER_CAUTIONS))
        ):
            read_tier = 1
        elif (
            source == "orientation_audit"
            and swap_decision
            and top10_cross
            and lower_rank >= TOP_PACK_SIZE + 2
            and aggregate_margin >= 0.05
            and (cautions & ROUGHER_STRONGER_CAUTIONS)
        ):
            read_tier = 2
        elif (
            source == "cheap_pairwise"
            and top10_cross
            and (cautions & ROUGHER_STRONGER_CAUTIONS)
            and ((keep_decision and loser_interpretation_dominant) or swap_decision)
        ):
            read_tier = 3
        elif (
            source == "orientation_audit"
            and top10_cross
            and keep_decision
            and (cautions & POLISH_LIKE_CAUTIONS)
            and not (cautions & ROUGHER_STRONGER_CAUTIONS)
        ):
            read_tier = 4
        elif "surface_substance_inversion" in triggers:
            read_tier = 5

    return (
        read_tier,
        0 if (top10_cross or level_cross) else 1,
        abs(aggregate_margin),
        higher_rank,
        lower_rank,
        -int(candidate.get("committee_score", 0) or 0),
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


def committee_anchor_selection_details(
    path: Path,
    *,
    source_calibration: Path | dict | None = None,
    genre: str = "",
    grade_level: int | None = None,
) -> list[str]:
    payload = load_optional_json(path)
    details = []
    if payload:
        details.append("Committee literary calibration anchors are active for this blind read.")
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
    calibration_payload: dict = {}
    if isinstance(source_calibration, dict):
        calibration_payload = source_calibration
    elif source_calibration is not None:
        calibration_payload = load_source_calibration(source_calibration)
    if calibration_payload:
        details.extend(
            format_source_calibration_lines(
                calibration_payload,
                genre=genre,
                grade_level=grade_level,
            )
        )
    return [detail for detail in details if detail.strip()]


def metadata_grade_level(metadata: dict) -> int | None:
    return parse_grade_level(
        metadata.get("grade_level")
        or metadata.get("grade")
        or metadata.get("course_grade")
        or metadata.get("class_grade")
    )


def evidence_ledger_instruction_lines() -> list[str]:
    return [
        (
            "Before choosing winner_side, complete decision_checks.evidence_ledger for Essay A and Essay B. "
            "The ledger must name each essay's central claim, specific text moments, explained-moment count, "
            "interpretation depth, proof sufficiency, plot-summary-only status, formulaic-control-only status, "
            "mechanics blocker, completion blocker, and strongest substance reason."
        ),
        (
            "Do not choose a cleaner/formulaic essay when your own evidence ledger says the other essay has "
            "stronger interpretation and at least equal proof, unless the other essay has mechanics_block_meaning "
            "or completion_floor_applied."
        ),
        (
            "If winner_side conflicts with the evidence ledger, the deterministic committee guard may supersede "
            "your winner using the ledger you supplied."
        ),
        (
            "Also complete decision_checks.source_calibration_checks. source_calibrated_winner must answer: "
            "which essay wins when teacher-scored exemplar rules are applied to the active rubric? "
            "Do not let surface_control_advantage decide unless surface_control_is_decisive is true because "
            "the other essay's meaning is unrecoverable, incomplete, or off task."
        ),
        (
            "Set completion_floor_has_observable_scaffold to true only when the essay has visible scaffold headings, "
            "blank/fragmentary prompt remnants, or an actually unfinished draft. Do not use it for a merely shorter, "
            "rougher, or less formulaic essay."
        ),
    ]


def candidate_selection_detail_lines(candidate: dict) -> list[str]:
    details = candidate.get("trigger_details") if isinstance(candidate.get("trigger_details"), dict) else {}
    lines = evidence_ledger_instruction_lines() + [
        "This is a blind committee read. Do not rely on prior pairwise decisions, seed order, aggregate rank, Borda support, or committee trigger labels as evidence.",
        "Resolve the pair using the rubric, assignment, committee anchors, and essay texts only.",
        f"Candidate bucket for audit logging: {candidate.get('bucket', '')}.",
        f"Surface/substance deltas for audit logging only: {details.get('surface_substance_inversion_log', {}) or candidate.get('surface_features', {}).get('gap', {})}.",
    ]
    evidence_signal = details.get("evidence_map_pair_signal") or candidate.get("evidence_map_pair_signal")
    if isinstance(evidence_signal, dict) and evidence_signal:
        lines.extend(
            [
                "Offline evidence-map signal is active for audit logging; verify it against the essays before relying on it.",
                (
                    "Evidence-map recommendation: "
                    f"{evidence_signal.get('recommended_winner', 'tie')} "
                    f"(confidence={evidence_signal.get('confidence', '')}, margin={evidence_signal.get('margin', '')})."
                ),
                "Evidence-map reasons: " + "; ".join(str(reason) for reason in evidence_signal.get("reasons", [])[:4]),
            ]
        )
    return lines


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
    base["evidence_ledger"] = normalize_evidence_ledger(value.get("evidence_ledger"))
    base["source_calibration_checks"] = normalize_source_calibration_checks(value.get("source_calibration_checks"))
    return base


def normalize_source_calibration_checks(value) -> dict:
    value = value if isinstance(value, dict) else {}
    return {
        "source_calibrated_winner": vc.normalize_side(value.get("source_calibrated_winner")),
        "evidence_explained_not_named": vc.normalize_side(value.get("evidence_explained_not_named")),
        "commentary_depth": vc.normalize_side(value.get("commentary_depth")),
        "surface_control_advantage": vc.normalize_side(value.get("surface_control_advantage")),
        "surface_control_is_decisive": truthy(value.get("surface_control_is_decisive")),
        "mature_theme_without_proof": vc.normalize_side(value.get("mature_theme_without_proof"), allow_none=True),
        "completion_floor_has_observable_scaffold": truthy(value.get("completion_floor_has_observable_scaffold")),
        "active_rubric_remains_authority": truthy(value.get("active_rubric_remains_authority")),
        "source_calibration_rationale": str(value.get("source_calibration_rationale") or "").strip(),
    }


LEDGER_QUALITY = {"none": 0, "weak": 1, "adequate": 2, "strong": 3}


def normalize_ledger_quality(value) -> str:
    token = str(value or "").strip().lower()
    return token if token in LEDGER_QUALITY else "none"


def normalize_ledger_side(value) -> dict:
    value = value if isinstance(value, dict) else {}
    moments = value.get("specific_text_moments") if isinstance(value.get("specific_text_moments"), list) else []
    return {
        "central_claim": str(value.get("central_claim") or "").strip(),
        "specific_text_moments": [str(moment or "").strip() for moment in moments if str(moment or "").strip()],
        "explained_moment_count": max(0, int(num(value.get("explained_moment_count"), 0))),
        "interpretation_depth": normalize_ledger_quality(value.get("interpretation_depth")),
        "proof_sufficiency": normalize_ledger_quality(value.get("proof_sufficiency")),
        "plot_summary_only": truthy(value.get("plot_summary_only")),
        "formulaic_control_only": truthy(value.get("formulaic_control_only")),
        "mechanics_block_meaning": truthy(value.get("mechanics_block_meaning")),
        "completion_floor_applied": truthy(value.get("completion_floor_applied")),
        "strongest_substance_reason": str(value.get("strongest_substance_reason") or "").strip(),
    }


def normalize_evidence_ledger(value) -> dict:
    value = value if isinstance(value, dict) else {}
    return {
        "A": normalize_ledger_side(value.get("A")),
        "B": normalize_ledger_side(value.get("B")),
    }


def ledger_side_blocked(side: dict) -> bool:
    return bool(side.get("mechanics_block_meaning") or side.get("completion_floor_applied"))


def ledger_quality_value(side: dict, key: str) -> int:
    return LEDGER_QUALITY.get(normalize_ledger_quality(side.get(key)), 0)


def ledger_side_score(side: dict) -> int:
    score = ledger_quality_value(side, "interpretation_depth") * 3
    score += ledger_quality_value(side, "proof_sufficiency") * 3
    score += min(3, int(num(side.get("explained_moment_count"), 0)))
    score += min(2, len(side.get("specific_text_moments") or []))
    if str(side.get("central_claim") or "").strip():
        score += 1
    if side.get("plot_summary_only"):
        score -= 3
    if side.get("formulaic_control_only"):
        score -= 2
    if ledger_side_blocked(side):
        score -= 100
    return score


def evidence_ledger_favors_side(ledger: dict, side: str, other: str) -> bool:
    side = normalize_winner_side(side)
    other = normalize_winner_side(other)
    if not side or not other or side == other:
        return False
    normalized = normalize_evidence_ledger(ledger)
    favored = normalized[side]
    opposed = normalized[other]
    if ledger_side_blocked(favored):
        return False
    if ledger_side_blocked(opposed):
        return True
    favored_depth = ledger_quality_value(favored, "interpretation_depth")
    opposed_depth = ledger_quality_value(opposed, "interpretation_depth")
    favored_proof = ledger_quality_value(favored, "proof_sufficiency")
    opposed_proof = ledger_quality_value(opposed, "proof_sufficiency")
    favored_moments = int(num(favored.get("explained_moment_count"), 0))
    opposed_moments = int(num(opposed.get("explained_moment_count"), 0))
    if favored_depth > opposed_depth and favored_proof >= opposed_proof:
        return True
    if favored_proof > opposed_proof and favored_depth >= opposed_depth:
        return True
    if (
        favored_depth >= opposed_depth
        and favored_proof >= opposed_proof
        and favored_moments >= opposed_moments + 2
    ):
        return True
    if (
        ledger_side_score(favored) >= ledger_side_score(opposed) + 4
        and (opposed.get("plot_summary_only") or opposed.get("formulaic_control_only"))
    ):
        return True
    return False


def evidence_ledger_guard_decision(candidate: dict, read: dict, *, read_label: str = "A") -> tuple[dict | None, str]:
    """Flip a self-contradictory committee read when its own ledger proves the other side.

    This guard is intentionally narrow: it only acts on routed high-risk edges,
    only when the read preserved the current active winner, and only when the
    ledger says the other essay wins on interpretation/proof without a mechanics
    or completion blocker.
    """
    prior_winner = str((candidate.get("escalated_summary") or {}).get("winner") or "").strip()
    read_winner = str(read.get("winner") or "").strip()
    if not prior_winner or not read_winner or read_winner != prior_winner:
        return None, "evidence_ledger_guard_not_prior_concurrence"
    confidence = vc.normalize_confidence(read.get("confidence"))
    if confidence not in {"medium", "high"}:
        return None, "evidence_ledger_guard_low_confidence"
    bucket = str(candidate.get("bucket") or "")
    triggers = set(candidate.get("triggers") or [])
    if bucket != "caution_ignored" and not (triggers & CAUTION_IGNORED_TRIGGERS):
        return None, "evidence_ledger_guard_not_high_risk"
    checks = normalize_committee_decision_checks(
        read.get("decision_checks") if isinstance(read.get("decision_checks"), dict) else {}
    )
    winner_side = normalize_winner_side(read.get("winner_side"))
    loser_side = "B" if winner_side == "A" else "A" if winner_side == "B" else ""
    if not winner_side or not loser_side:
        return None, "evidence_ledger_guard_missing_side"
    ledger = checks.get("evidence_ledger") if isinstance(checks.get("evidence_ledger"), dict) else {}
    if not evidence_ledger_favors_side(ledger, loser_side, winner_side):
        return None, "evidence_ledger_guard_ledger_supports_winner"
    flipped = copy.deepcopy(read)
    seed_order = candidate.get("seed_order") if isinstance(candidate.get("seed_order"), dict) else {}
    higher = str(seed_order.get("higher") or "").strip()
    lower = str(seed_order.get("lower") or "").strip()
    new_winner = higher if loser_side == "A" else lower
    new_loser = lower if new_winner == higher else higher
    flipped_checks = normalize_committee_decision_checks(flipped.get("decision_checks") if isinstance(flipped.get("decision_checks"), dict) else {})
    flipped_checks["interpretation_depth"] = loser_side
    flipped_checks["proof_sufficiency"] = loser_side
    flipped_checks["alternate_theme_validity"] = loser_side
    flipped_checks["polish_trap"] = True
    flipped_checks["rougher_but_stronger_latent"] = True
    flipped_checks["mechanics_block_meaning"] = False
    flipped_checks["completion_floor_applied"] = False
    cautions = set(flipped.get("cautions_applied") if isinstance(flipped.get("cautions_applied"), list) else [])
    cautions.update({"rougher_but_stronger_content", "polished_but_shallow"})
    flipped.update(
        {
            "winner": new_winner,
            "loser": new_loser,
            "winner_side": loser_side,
            "decision": "KEEP" if loser_side == "A" else "SWAP",
            "confidence": confidence,
            "decision_basis": "content_reasoning",
            "cautions_applied": sorted(cautions),
            "decision_checks": flipped_checks,
            "rationale": (
                "Evidence-ledger guard: the committee read preserved the prior winner, "
                "but its own ledger gives the other essay stronger interpretation/proof "
                "with no mechanics or completion blocker. "
                + str(flipped.get("rationale") or "").strip()
            ).strip(),
        }
    )
    metadata = dict(flipped.get("model_metadata") or {})
    metadata["committee_read"] = f"{read_label}-evidence-ledger-guard"
    metadata["adjudication_source"] = "committee_evidence_ledger_guard"
    flipped["model_metadata"] = metadata
    flipped["evidence_ledger_guard"] = {
        "prior_winner": prior_winner,
        "original_winner": read_winner,
        "guard_winner": new_winner,
        "guard_winner_side": loser_side,
        "original_winner_side": winner_side,
        "ledger_scores": {
            loser_side: ledger_side_score(normalize_evidence_ledger(ledger)[loser_side]),
            winner_side: ledger_side_score(normalize_evidence_ledger(ledger)[winner_side]),
        },
    }
    return normalize_committee_read(candidate, flipped), f"committee_read_{str(read_label).lower()}_evidence_ledger_override"


def source_calibration_favors_side(checks: dict, side: str, other: str) -> bool:
    side = normalize_winner_side(side)
    other = normalize_winner_side(other)
    if not side or not other or side == other:
        return False
    source_checks = normalize_source_calibration_checks(checks.get("source_calibration_checks"))
    if source_checks.get("source_calibrated_winner") != side:
        return False
    if source_checks.get("mature_theme_without_proof") == side:
        return False
    if source_checks.get("completion_floor_has_observable_scaffold"):
        return False
    if checks.get("mechanics_block_meaning") or checks.get("completion_floor_applied"):
        return False
    evidence_side = source_checks.get("evidence_explained_not_named")
    commentary_side = source_checks.get("commentary_depth")
    surface_side = source_checks.get("surface_control_advantage")
    surface_decisive = bool(source_checks.get("surface_control_is_decisive"))
    if evidence_side == side and commentary_side in {side, "tie"}:
        return True
    if commentary_side == side and evidence_side in {side, "tie"}:
        return True
    if evidence_side == side and commentary_side == side:
        return True
    if surface_side == other and not surface_decisive and (evidence_side == side or commentary_side == side):
        return True
    return False


def source_calibration_guard_decision(candidate: dict, read: dict, *, read_label: str = "A") -> tuple[dict | None, str]:
    """Flip a prior-winner concurrence when the source-calibration checklist contradicts it."""

    prior_winner = str((candidate.get("escalated_summary") or {}).get("winner") or "").strip()
    read_winner = str(read.get("winner") or "").strip()
    if not prior_winner or not read_winner or read_winner != prior_winner:
        return None, "source_calibration_guard_not_prior_concurrence"
    confidence = vc.normalize_confidence(read.get("confidence"))
    if confidence not in {"medium", "high"}:
        return None, "source_calibration_guard_low_confidence"
    bucket = str(candidate.get("bucket") or "")
    triggers = set(candidate.get("triggers") or [])
    if bucket != "caution_ignored" and not (triggers & CAUTION_IGNORED_TRIGGERS):
        return None, "source_calibration_guard_not_high_risk"
    checks = normalize_committee_decision_checks(
        read.get("decision_checks") if isinstance(read.get("decision_checks"), dict) else {}
    )
    winner_side = normalize_winner_side(read.get("winner_side"))
    loser_side = "B" if winner_side == "A" else "A" if winner_side == "B" else ""
    if not winner_side or not loser_side:
        return None, "source_calibration_guard_missing_side"
    if not source_calibration_favors_side(checks, loser_side, winner_side):
        return None, "source_calibration_guard_checklist_supports_winner"
    ledger = checks.get("evidence_ledger") if isinstance(checks.get("evidence_ledger"), dict) else {}
    normalized_ledger = normalize_evidence_ledger(ledger)
    if ledger_side_blocked(normalized_ledger[loser_side]):
        return None, "source_calibration_guard_loser_blocked_by_ledger"

    flipped = copy.deepcopy(read)
    seed_order = candidate.get("seed_order") if isinstance(candidate.get("seed_order"), dict) else {}
    higher = str(seed_order.get("higher") or "").strip()
    lower = str(seed_order.get("lower") or "").strip()
    new_winner = higher if loser_side == "A" else lower
    new_loser = lower if new_winner == higher else higher
    flipped_checks = normalize_committee_decision_checks(
        flipped.get("decision_checks") if isinstance(flipped.get("decision_checks"), dict) else {}
    )
    flipped_checks["interpretation_depth"] = loser_side
    flipped_checks["proof_sufficiency"] = loser_side
    flipped_checks["alternate_theme_validity"] = loser_side
    flipped_checks["polish_trap"] = True
    flipped_checks["rougher_but_stronger_latent"] = True
    flipped_checks["mechanics_block_meaning"] = False
    flipped_checks["completion_floor_applied"] = False
    source_checks = normalize_source_calibration_checks(flipped_checks.get("source_calibration_checks"))
    source_checks["source_calibrated_winner"] = loser_side
    source_checks["evidence_explained_not_named"] = loser_side
    source_checks["commentary_depth"] = loser_side
    source_checks["surface_control_is_decisive"] = False
    source_checks["completion_floor_has_observable_scaffold"] = False
    flipped_checks["source_calibration_checks"] = source_checks
    cautions = set(flipped.get("cautions_applied") if isinstance(flipped.get("cautions_applied"), list) else [])
    cautions.update({"rougher_but_stronger_content", "polished_but_shallow"})
    flipped.update(
        {
            "winner": new_winner,
            "loser": new_loser,
            "winner_side": loser_side,
            "decision": "KEEP" if loser_side == "A" else "SWAP",
            "confidence": confidence,
            "decision_basis": "content_reasoning",
            "cautions_applied": sorted(cautions),
            "decision_checks": flipped_checks,
            "rationale": (
                "Source-calibration guard: the committee read preserved the prior winner, "
                "but its source-calibration checklist gives the other essay stronger explained evidence/commentary "
                "with no observable completion floor or mechanics blocker. "
                + str(flipped.get("rationale") or "").strip()
            ).strip(),
        }
    )
    metadata = dict(flipped.get("model_metadata") or {})
    metadata["committee_read"] = f"{read_label}-source-calibration-guard"
    metadata["adjudication_source"] = "committee_source_calibration_guard"
    flipped["model_metadata"] = metadata
    flipped["source_calibration_guard"] = {
        "prior_winner": prior_winner,
        "original_winner": read_winner,
        "guard_winner": new_winner,
        "guard_winner_side": loser_side,
        "original_winner_side": winner_side,
        "source_calibration_checks": source_checks,
    }
    return normalize_committee_read(candidate, flipped), f"committee_read_{str(read_label).lower()}_source_calibration_override"


def evidence_map_pair_signal(candidate: dict) -> dict:
    details = candidate.get("trigger_details") if isinstance(candidate.get("trigger_details"), dict) else {}
    signal = details.get("evidence_map_pair_signal")
    if not isinstance(signal, dict):
        signal = candidate.get("evidence_map_pair_signal")
    return signal if isinstance(signal, dict) else {}


def evidence_map_guard_signal_is_strong(signal: dict) -> bool:
    confidence = str(signal.get("confidence") or "").strip().lower()
    margin = num(signal.get("margin"), 0.0)
    return bool(
        confidence == "high"
        or (confidence == "medium" and margin >= EVIDENCE_MAP_GUARD_MIN_MEDIUM_MARGIN)
    )


def evidence_map_summary_for(signal: dict, student_id: str) -> dict:
    summaries = signal.get("summaries") if isinstance(signal.get("summaries"), dict) else {}
    summary = summaries.get(student_id)
    if not isinstance(summary, dict):
        if str(signal.get("active_winner") or "") == student_id:
            summary = signal.get("winner_summary")
        elif str(signal.get("active_loser") or "") == student_id:
            summary = signal.get("loser_summary")
    return summary if isinstance(summary, dict) else {}


def evidence_map_recommended_winner_blocked(signal: dict, student_id: str) -> bool:
    summary = evidence_map_summary_for(signal, student_id)
    return bool(summary.get("completion_floor_applied"))


def evidence_map_guard_decision(candidate: dict, read: dict, *, read_label: str = "A") -> tuple[dict | None, str]:
    """Use the deterministic offline evidence map as a guard on committee reads.

    This guard never creates a decision without a committee read. It only acts on
    high-risk routed edges when the model/fixture read either preserves the
    active winner despite a strong evidence-map contradiction, or tries to emit
    an override against a strong evidence-map signal.
    """

    signal = evidence_map_pair_signal(candidate)
    if not signal:
        return None, "evidence_map_guard_missing_signal"
    bucket = str(candidate.get("bucket") or "")
    triggers = set(candidate.get("triggers") or [])
    if bucket != "caution_ignored" and not (triggers & CAUTION_IGNORED_TRIGGERS):
        return None, "evidence_map_guard_not_high_risk"
    recommended = str(signal.get("recommended_winner") or "").strip()
    if not recommended or recommended == "tie":
        return None, "evidence_map_guard_tie"
    if not evidence_map_guard_signal_is_strong(signal):
        return None, "evidence_map_guard_low_confidence"
    seed_order = candidate.get("seed_order") if isinstance(candidate.get("seed_order"), dict) else {}
    higher = str(seed_order.get("higher") or "").strip()
    lower = str(seed_order.get("lower") or "").strip()
    if recommended not in {higher, lower}:
        return None, "evidence_map_guard_incomplete"
    if evidence_map_recommended_winner_blocked(signal, recommended):
        return None, "evidence_map_guard_recommended_winner_blocked"
    prior_winner = str((candidate.get("escalated_summary") or {}).get("winner") or "").strip()
    read_winner = str(read.get("winner") or "").strip()
    if not prior_winner or not read_winner:
        return None, "evidence_map_guard_incomplete"
    if read_winner == recommended:
        return None, "evidence_map_guard_supports_winner"
    if read_winner != prior_winner:
        return None, "evidence_map_guard_blocks_override"
    if recommended == prior_winner:
        return None, "evidence_map_guard_supports_winner"

    flipped = copy.deepcopy(read)
    new_winner = recommended
    new_loser = lower if new_winner == higher else higher
    new_side = "A" if new_winner == higher else "B"
    flipped_checks = normalize_committee_decision_checks(
        flipped.get("decision_checks") if isinstance(flipped.get("decision_checks"), dict) else {}
    )
    flipped_checks["interpretation_depth"] = new_side
    flipped_checks["proof_sufficiency"] = new_side
    flipped_checks["alternate_theme_validity"] = new_side
    flipped_checks["polish_trap"] = True
    flipped_checks["rougher_but_stronger_latent"] = True
    flipped_checks["mechanics_block_meaning"] = False
    flipped_checks["completion_floor_applied"] = False
    cautions = set(flipped.get("cautions_applied") if isinstance(flipped.get("cautions_applied"), list) else [])
    cautions.update({"rougher_but_stronger_content", "polished_but_shallow"})
    confidence = vc.normalize_confidence(flipped.get("confidence"))
    flipped.update(
        {
            "winner": new_winner,
            "loser": new_loser,
            "winner_side": new_side,
            "decision": "KEEP" if new_side == "A" else "SWAP",
            "confidence": confidence if confidence in {"medium", "high"} else "medium",
            "decision_basis": "content_reasoning",
            "cautions_applied": sorted(cautions),
            "decision_checks": flipped_checks,
            "rationale": (
                "Evidence-map guard: the committee read preserved the active winner, "
                "but the deterministic offline claim/evidence/commentary map strongly "
                "favored the other essay with no completion blocker. "
                + str(flipped.get("rationale") or "").strip()
            ).strip(),
        }
    )
    metadata = dict(flipped.get("model_metadata") or {})
    metadata["committee_read"] = f"{read_label}-evidence-map-guard"
    metadata["adjudication_source"] = "committee_evidence_map_guard"
    flipped["model_metadata"] = metadata
    flipped["evidence_map_guard"] = {
        "prior_winner": prior_winner,
        "original_winner": read_winner,
        "guard_winner": new_winner,
        "guard_winner_side": new_side,
        "original_winner_side": normalize_winner_side(read.get("winner_side")),
        "confidence": signal.get("confidence", ""),
        "margin": signal.get("margin", 0.0),
        "evidence_map_reasons": list(signal.get("reasons") or [])[:6],
        "active_winner": signal.get("active_winner", prior_winner),
        "scores": signal.get("scores", {}),
    }
    return normalize_committee_read(candidate, flipped), f"committee_read_{str(read_label).lower()}_evidence_map_override"


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
    source_calibration: Path | dict | None = None,
) -> dict:
    seed_order = candidate.get("seed_order") if isinstance(candidate.get("seed_order"), dict) else {}
    higher_id = str(seed_order.get("higher", "") or "").strip()
    lower_id = str(seed_order.get("lower", "") or "").strip()
    if higher_id not in rows_by_id or lower_id not in rows_by_id:
        raise ValueError(f"Candidate {candidate.get('pair_key', '')}: missing row for blind read")
    genre = str(metadata.get("assignment_genre") or metadata.get("genre") or "")
    selection_details = committee_anchor_selection_details(
        committee_anchor,
        source_calibration=source_calibration,
        genre=genre,
        grade_level=metadata_grade_level(metadata),
    ) + candidate_selection_detail_lines(candidate)
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
        genre=genre,
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


def should_invoke_read_b(candidate: dict, read_a: dict) -> tuple[bool, str]:
    """Phase 3a: decide whether the polish-trap auditor (Read B) should run.

    Read B is invoked when ANY of these signals is present in Read A or the
    candidate — each indicates the pair is at real risk of a polish trap that
    a second, adversarial read should audit:

      1. A concurred with the prior winner AND the pair is caution_ignored
         (the high-leverage bucket; we do not want A-only concurrence to settle
         residual-shaped pairs).
      2. A's decision_checks show interpretation_depth favoring the loser but
         proof_sufficiency favoring the winner — the classic polish-trap
         signature: "clean proof, shallow thinking".
      3. A's cautions_applied (or the candidate's escalated_cautions) include
         polished_but_shallow or formulaic_but_thin.
      4. A's decision_checks flagged rougher_but_stronger_latent=True but the
         Phase 2b override gate did not fire (e.g. A was low confidence).

    Returns (should_run, reason).
    """
    prior_winner = str((candidate.get("escalated_summary") or {}).get("winner") or "").strip()
    read_winner = str(read_a.get("winner") or "").strip()
    if not prior_winner or not read_winner:
        return False, "committee_read_b_not_invoked_incomplete_a"

    bucket = str(candidate.get("bucket") or "other")
    details = candidate.get("trigger_details") if isinstance(candidate.get("trigger_details"), dict) else {}
    escalated_cautions = set(details.get("escalated_cautions") or [])
    a_checks = normalize_committee_decision_checks(
        read_a.get("decision_checks") if isinstance(read_a.get("decision_checks"), dict) else {}
    )
    a_cautions = set(read_a.get("cautions_applied") or [])

    # (1) concur on caution_ignored
    a_concurred = read_winner == prior_winner
    if a_concurred and bucket == "caution_ignored":
        return True, "committee_read_b_a_concurred_on_caution_ignored"

    # (2) interpretation favors loser BUT proof favors winner (polish trap signature)
    winner_side = normalize_winner_side(read_a.get("winner_side"))
    loser_side = "B" if winner_side == "A" else "A" if winner_side == "B" else ""
    interp_side = vc.normalize_side(a_checks.get("interpretation_depth"))
    proof_side = vc.normalize_side(a_checks.get("proof_sufficiency"))
    if (
        winner_side
        and loser_side
        and interp_side == loser_side
        and proof_side == winner_side
    ):
        return True, "committee_read_b_interp_vs_proof_split"

    # (3) polish-like caution raised anywhere
    if (a_cautions | escalated_cautions) & POLISH_LIKE_CAUTIONS:
        return True, "committee_read_b_polish_like_caution_raised"

    # (4) rougher_but_stronger_latent=True but A did not override
    a_override, _ = read_a_override_decision(candidate, read_a)
    if bool(a_checks.get("rougher_but_stronger_latent")) and not a_override:
        return True, "committee_read_b_rougher_latent_without_override"

    return False, "committee_read_b_not_needed"


def read_b_selection_details(candidate: dict, read_a: dict) -> list[str]:
    """Adversarial prompt bits for Read B.

    Read B receives Read A and the prior pairwise decision as AUDIT TARGETS —
    not as authorities. The prompt frames B's task as answering a single
    adversarial question: is the current winner winning because of proof, or
    because it is cleaner / more formulaic?
    """
    details = candidate.get("trigger_details") if isinstance(candidate.get("trigger_details"), dict) else {}
    escalated_summary = candidate.get("escalated_summary") if isinstance(candidate.get("escalated_summary"), dict) else {}
    prior_basis = str(escalated_summary.get("decision_basis") or "").strip()
    prior_source = str(escalated_summary.get("adjudication_source") or "").strip()
    prior_cautions = sorted(details.get("escalated_cautions") or [])
    a_winner = str(read_a.get("winner") or "").strip()
    a_basis = str(read_a.get("decision_basis") or "").strip()
    a_confidence = str(read_a.get("confidence") or "").strip()
    a_checks = normalize_committee_decision_checks(
        read_a.get("decision_checks") if isinstance(read_a.get("decision_checks"), dict) else {}
    )
    a_cautions = sorted(read_a.get("cautions_applied") or [])
    return evidence_ledger_instruction_lines() + [
        "This is a Read B adversarial polish-trap audit. The prior pairwise decision and Read A are AUDIT TARGETS, not authority.",
        "Key question: Is the current winner winning because of PROOF, or because it is CLEANER / more FORMULAIC?",
        "If proof sufficiency does not survive scrutiny, swap the decision. If interpretation depth does not survive scrutiny, keep the decision.",
        "Do NOT defer to Read A or the prior. Re-read both essays and decide based on the rubric, assignment outline, committee anchors, and texts only.",
        (
            "Prior pairwise decision context (audit target, not authority): "
            f"basis={prior_basis}; source={prior_source}; cautions={prior_cautions}. "
            "The prior winner is intentionally omitted from this prompt detail; decide from the essays and ledger."
        ),
        (
            "Read A judgment (audit target): "
            f"winner={a_winner}; basis={a_basis}; confidence={a_confidence}; cautions={a_cautions}; "
            f"interpretation_depth={a_checks.get('interpretation_depth') or 'tie'}; "
            f"proof_sufficiency={a_checks.get('proof_sufficiency') or 'tie'}; "
            f"polish_trap={bool(a_checks.get('polish_trap'))}; "
            f"rougher_but_stronger_latent={bool(a_checks.get('rougher_but_stronger_latent'))}."
        ),
    ]


def run_blind_read_b(
    candidate: dict,
    read_a: dict,
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
    source_calibration: Path | dict | None = None,
) -> dict:
    seed_order = candidate.get("seed_order") if isinstance(candidate.get("seed_order"), dict) else {}
    higher_id = str(seed_order.get("higher", "") or "").strip()
    lower_id = str(seed_order.get("lower", "") or "").strip()
    if higher_id not in rows_by_id or lower_id not in rows_by_id:
        raise ValueError(f"Candidate {candidate.get('pair_key', '')}: missing row for Read B")
    genre = str(metadata.get("assignment_genre") or metadata.get("genre") or "")
    selection_details = (
        committee_anchor_selection_details(
            committee_anchor,
            source_calibration=source_calibration,
            genre=genre,
            grade_level=metadata_grade_level(metadata),
        )
        + read_b_selection_details(candidate, read_a)
    )
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
        genre=genre,
        metadata=metadata,
        selection_reasons=["committee_edge_read_b_polish_trap_audit"],
        selection_details=selection_details,
        anchor_dir=anchor_dir,
        # Orientation audit is off: the adversarial framing already reverses
        # the "whose winner is correct" test; a second orientation flip on top
        # would scramble the audit signal.
        orientation_audit=False,
        student_count=len(rows_by_id),
        response_format=COMMITTEE_RESPONSE_FORMAT,
    )
    read = normalize_committee_read(candidate, judgment)
    metadata_out = dict(read.get("model_metadata") or {})
    metadata_out["committee_read"] = "B-polish-trap-audit"
    metadata_out["adjudication_source"] = "committee_read_b"
    read["model_metadata"] = metadata_out
    return read


def read_b_from_fixture(candidate: dict, fixture_by_key: dict[str, dict]) -> dict | None:
    key = str(candidate.get("pair_key") or "").strip()
    if key not in fixture_by_key:
        return None
    read = normalize_committee_read(candidate, fixture_by_key[key])
    metadata = dict(read.get("model_metadata") or {})
    metadata["committee_read"] = "B-polish-trap-audit"
    metadata["adjudication_source"] = "committee_read_b"
    read["model_metadata"] = metadata
    return read


def row_brief(row: dict, student_count: int) -> str:
    student_id = str(row.get("student_id") or "").strip()
    seed_rank = int(num(row.get("seed_rank"), student_count) or student_count)
    level = str(row.get("_level") or row.get("adjusted_level") or row.get("level") or "").strip()
    composite = normalize_metric(row.get("_composite_score") or row.get("composite_score"))
    borda = normalize_metric(row.get("_borda_feature") or row.get("borda_percent") or row.get("borda_points"))
    support = row_support(row, student_count)
    return (
        f"{student_id}: seed_rank={seed_rank}, level={level or 'unknown'}, "
        f"composite={composite:.3f}, borda={borda:.3f}, support={support:.3f}"
    )


def group_row_brief(row: dict) -> str:
    """Minimal roster context for group reads, without score/rank anchors."""

    student_id = str(row.get("student_id") or "").strip()
    name = str(row.get("student_name") or row.get("name") or row.get("display_name") or "").strip()
    if name and name != student_id:
        return f"{student_id}: name={name}"
    return student_id


def build_group_calibration_neighborhoods(
    *,
    selected: list[dict],
    rows: list[dict],
    read_results: list[dict],
    max_groups: int,
    max_students: int,
) -> list[dict]:
    """Collect unresolved committee-read edges into small placement neighborhoods."""
    if max_groups <= 0 or max_students < 2:
        return []
    candidate_by_key = {str(candidate.get("pair_key") or ""): candidate for candidate in selected}
    rows_by_id = {str(row.get("student_id") or ""): row for row in vc.prepare_rows(rows)}
    neighborhoods: list[dict] = []
    current_ids: set[str] = set()
    current_pair_keys: list[str] = []
    current_details: list[dict] = []
    current_statuses: dict[str, str] = {}

    def emit_current() -> None:
        if not current_pair_keys or len(current_ids) < 2 or len(neighborhoods) >= max_groups:
            return
        student_count = len(rows_by_id)
        ordered_ids = sorted(
            current_ids,
            key=lambda sid: (
                int(num(rows_by_id.get(sid, {}).get("seed_rank"), student_count) or student_count),
                sid,
            ),
        )
        neighborhoods.append(
            {
                "neighborhood_id": f"group_{len(neighborhoods) + 1}",
                "student_ids": ordered_ids,
                "pair_keys": list(current_pair_keys),
                "trigger_details": copy.deepcopy(current_details),
                "read_result_statuses": dict(current_statuses),
            }
        )

    for record in read_results:
        if len(neighborhoods) >= max_groups:
            break
        if record.get("override_emitted"):
            continue
        status = str(record.get("status") or "").strip()
        if status not in UNRESOLVED_GROUP_STATUSES:
            continue
        pair_key = str(record.get("pair_key") or "").strip()
        candidate = candidate_by_key.get(pair_key)
        if not candidate:
            continue
        seed_order = candidate.get("seed_order") if isinstance(candidate.get("seed_order"), dict) else {}
        endpoints = [
            str(seed_order.get("higher") or "").strip(),
            str(seed_order.get("lower") or "").strip(),
        ]
        if len([sid for sid in endpoints if sid]) != 2 or any(sid not in rows_by_id for sid in endpoints):
            continue
        new_ids = [sid for sid in endpoints if sid not in current_ids]
        if current_pair_keys and len(current_ids) + len(new_ids) > max_students:
            emit_current()
            current_ids = set()
            current_pair_keys = []
            current_details = []
            current_statuses = {}
        if len(set(endpoints)) > max_students:
            continue
        current_ids.update(endpoints)
        current_pair_keys.append(pair_key)
        details = candidate.get("trigger_details") if isinstance(candidate.get("trigger_details"), dict) else {}
        current_details.append(
            {
                "pair_key": pair_key,
                "bucket": candidate.get("bucket", ""),
                "committee_score": candidate.get("committee_score", 0),
                "triggers": list(candidate.get("triggers") or []),
                "prior_winner": (candidate.get("escalated_summary") or {}).get("winner", ""),
                "prior_basis": (candidate.get("escalated_summary") or {}).get("decision_basis", ""),
                "read_status": status,
                "read_c_invoked": bool(record.get("read_c_invoked")),
                "cautions": details.get("escalated_cautions", []),
            }
        )
        current_statuses[pair_key] = status
    emit_current()
    return neighborhoods[:max_groups]


def packet_pair_keys(packet: dict) -> list[str]:
    keys = []
    for section in ("triggering_edges", "ambiguous_edges"):
        edges = packet.get(section) if isinstance(packet.get(section), list) else []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            pair_key = str(edge.get("pair_key") or "").strip()
            if pair_key and pair_key not in keys:
                keys.append(pair_key)
    return keys


def packet_trigger_detail(edge: dict, packet: dict, candidate_by_key: dict[str, dict]) -> dict:
    pair_key = str(edge.get("pair_key") or "").strip()
    candidate = candidate_by_key.get(pair_key, {})
    details = candidate.get("trigger_details") if isinstance(candidate.get("trigger_details"), dict) else {}
    return {
        "pair_key": pair_key,
        "bucket": candidate.get("bucket", "evidence_group_packet"),
        "committee_score": candidate.get("committee_score", packet.get("priority_score", 0)),
        "triggers": list(candidate.get("triggers") or ["evidence_group_packet"]),
        "prior_winner": (candidate.get("escalated_summary") or {}).get("winner", ""),
        "prior_basis": (candidate.get("escalated_summary") or {}).get("decision_basis", ""),
        "read_status": "evidence_group_packet_selected",
        "read_c_invoked": False,
        "cautions": details.get("escalated_cautions", []),
        "evidence_packet_id": packet.get("packet_id", ""),
        "source_neighborhood_id": packet.get("source_neighborhood_id", ""),
        "recommended_winner": edge.get("recommended_winner", ""),
        "active_winner": edge.get("active_winner", ""),
        "evidence_confidence": edge.get("confidence", ""),
        "evidence_margin": edge.get("margin", 0.0),
        "ambiguous": bool(edge.get("ambiguous")),
        "evidence_reasons": list(edge.get("reasons") or [])[:6],
    }


def build_group_calibration_neighborhoods_from_packets(
    *,
    packet_payload: dict,
    selected: list[dict],
    rows: list[dict],
    max_groups: int,
    max_students: int,
) -> list[dict]:
    if max_groups <= 0 or max_students < 2 or not packet_payload.get("enabled"):
        return []
    candidate_by_key = {str(candidate.get("pair_key") or ""): candidate for candidate in selected}
    rows_by_id = {str(row.get("student_id") or ""): row for row in vc.prepare_rows(rows)}
    raw_packets = packet_payload.get("packets") if isinstance(packet_payload.get("packets"), list) else []
    packets = [
        packet for packet in raw_packets
        if isinstance(packet, dict) and str(packet.get("selection_status") or "selected") == "selected"
    ]
    packets = sorted(
        packets,
        key=lambda packet: (
            -int(num(packet.get("priority_score"), 0) or 0),
            str(packet.get("packet_id") or ""),
            [str(sid) for sid in packet.get("student_ids", [])],
        ),
    )
    neighborhoods = []
    for packet in packets:
        if len(neighborhoods) >= max_groups:
            break
        seed_order = [str(sid).strip() for sid in packet.get("seed_order", []) if str(sid).strip()]
        if not seed_order:
            seed_order = [str(sid).strip() for sid in packet.get("student_ids", []) if str(sid).strip()]
        student_ids = [sid for sid in seed_order if sid in rows_by_id][:max_students]
        if len(student_ids) < 2:
            continue
        student_set = set(student_ids)
        edges = [
            edge for edge in (packet.get("triggering_edges", []) or []) + (packet.get("ambiguous_edges", []) or [])
            if isinstance(edge, dict)
        ]
        filtered_edges = [
            edge for edge in edges
            if set(str(sid) for sid in edge.get("pair", []) if str(sid)) <= student_set
        ]
        pair_keys = [
            key for key in packet_pair_keys({"triggering_edges": filtered_edges, "ambiguous_edges": []})
            if key
        ]
        if not pair_keys:
            # The full local order can still create support edges, but group
            # calibration needs at least one explicit edge target to audit.
            continue
        trigger_details = [
            packet_trigger_detail(edge, packet, candidate_by_key)
            for edge in sorted(filtered_edges, key=lambda edge: str(edge.get("pair_key") or ""))
        ]
        packet_context = {
            "packet_id": packet.get("packet_id", ""),
            "priority_score": packet.get("priority_score", 0),
            "recommended_read_type": packet.get("recommended_read_type", ""),
            "reason": packet.get("reason", ""),
            "source_neighborhood_id": packet.get("source_neighborhood_id", ""),
            "source_component_size": packet.get("source_component_size", 0),
            "seed_order": list(packet.get("seed_order") or []),
            "evidence_order": list(packet.get("evidence_order") or []),
            "triggering_pair_keys": [
                str(edge.get("pair_key") or "") for edge in packet.get("triggering_edges", []) if isinstance(edge, dict)
            ],
            "ambiguous_pair_keys": [
                str(edge.get("pair_key") or "") for edge in packet.get("ambiguous_edges", []) if isinstance(edge, dict)
            ],
        }
        neighborhoods.append(
            {
                "neighborhood_id": str(packet.get("packet_id") or f"evidence_group_packet_{len(neighborhoods) + 1:03d}"),
                "student_ids": student_ids,
                "pair_keys": pair_keys,
                "trigger_details": trigger_details,
                "read_result_statuses": {pair_key: "evidence_group_packet_selected" for pair_key in pair_keys},
                "evidence_packet": packet_context,
            }
        )
    return neighborhoods


def normalize_group_calibration(neighborhood: dict, payload: dict) -> dict:
    expected = [str(sid).strip() for sid in neighborhood.get("student_ids", []) if str(sid).strip()]
    expected_set = set(expected)
    seen: set[str] = set()
    ordered = []
    for raw in payload.get("ordered_student_ids", []):
        student_id = str(raw or "").strip()
        if student_id in expected_set and student_id not in seen:
            ordered.append(student_id)
            seen.add(student_id)
    missing = [sid for sid in expected if sid not in seen]
    ordered.extend(missing)
    confidence = vc.normalize_confidence(payload.get("confidence"))
    if missing:
        confidence = "low"
    notes = []
    raw_notes = payload.get("placement_notes") if isinstance(payload.get("placement_notes"), list) else []
    for note in raw_notes:
        if not isinstance(note, dict):
            continue
        student_id = str(note.get("student_id") or "").strip()
        if student_id not in expected_set:
            continue
        notes.append(
            {
                "student_id": student_id,
                "placement_band": str(note.get("placement_band") or "").strip(),
                "reason": str(note.get("reason") or "").strip(),
            }
        )
    edge_decisions = []
    unresolved_pair_keys = {str(pair_key) for pair_key in neighborhood.get("pair_keys", [])}
    raw_edges = payload.get("edge_decisions") if isinstance(payload.get("edge_decisions"), list) else []
    for edge in raw_edges:
        if not isinstance(edge, dict):
            continue
        pair_key = str(edge.get("pair_key") or "").strip()
        winner = str(edge.get("winner") or "").strip()
        if pair_key not in unresolved_pair_keys or winner not in expected_set:
            continue
        routed_cautions = edge.get("routed_cautions") if isinstance(edge.get("routed_cautions"), list) else []
        winner_moments = edge.get("winner_text_moments") if isinstance(edge.get("winner_text_moments"), list) else []
        loser_moments = edge.get("loser_text_moments") if isinstance(edge.get("loser_text_moments"), list) else []
        blocker_evidence = (
            edge.get("mechanics_blocker_evidence")
            if isinstance(edge.get("mechanics_blocker_evidence"), list)
            else []
        )
        refutation_moments = (
            edge.get("claim_refutation_text_moments")
            if isinstance(edge.get("claim_refutation_text_moments"), list)
            else []
        )
        edge_decisions.append(
            {
                "pair_key": pair_key,
                "winner": winner,
                "confidence": vc.normalize_confidence(edge.get("confidence")),
                "rationale": str(edge.get("rationale") or "").strip(),
                "polish_trap": truthy(edge.get("polish_trap")),
                "rougher_but_stronger_latent": truthy(edge.get("rougher_but_stronger_latent")),
                "mechanics_block_meaning": truthy(edge.get("mechanics_block_meaning")),
                "completion_floor_applied": truthy(edge.get("completion_floor_applied")),
                "interpretive_claim_winner": str(edge.get("interpretive_claim_winner") or "tie").strip() or "tie",
                "proof_quality_winner": str(edge.get("proof_quality_winner") or "tie").strip() or "tie",
                "textual_specificity_winner": str(edge.get("textual_specificity_winner") or "tie").strip() or "tie",
                "surface_control_winner": str(edge.get("surface_control_winner") or "tie").strip() or "tie",
                "completion_coherence_winner": str(edge.get("completion_coherence_winner") or "tie").strip() or "tie",
                "decisive_axis": str(edge.get("decisive_axis") or "tie_or_ambiguous").strip() or "tie_or_ambiguous",
                "routed_cautions": [str(caution).strip() for caution in routed_cautions if str(caution).strip()],
                "caution_honored": truthy(edge.get("caution_honored")),
                "caution_not_decisive_reason": str(edge.get("caution_not_decisive_reason") or "").strip(),
                "winner_text_moments": [str(moment).strip() for moment in winner_moments if str(moment).strip()],
                "loser_text_moments": [str(moment).strip() for moment in loser_moments if str(moment).strip()],
                "loser_interpretive_claim": str(edge.get("loser_interpretive_claim") or "").strip(),
                "winner_counterclaim": str(edge.get("winner_counterclaim") or "").strip(),
                "loser_claim_refutation": str(edge.get("loser_claim_refutation") or "").strip(),
                "claim_refutation_text_moments": [
                    str(moment).strip() for moment in refutation_moments if str(moment).strip()
                ],
                "mechanics_blocked_student": str(edge.get("mechanics_blocked_student") or "none").strip() or "none",
                "mechanics_blocker_evidence": [
                    str(moment).strip() for moment in blocker_evidence if str(moment).strip()
                ],
                "mechanics_blocker_reason": str(edge.get("mechanics_blocker_reason") or "").strip(),
            }
        )
    return {
        "neighborhood_id": neighborhood.get("neighborhood_id", ""),
        "ordered_student_ids": ordered,
        "confidence": confidence,
        "rationale": str(payload.get("rationale") or "").strip(),
        "placement_notes": notes,
        "edge_decisions": edge_decisions,
        "missing_student_ids": missing,
    }


def group_calibration_from_fixture(
    neighborhood: dict,
    fixtures: list[dict],
    index: int,
) -> dict | None:
    if not fixtures:
        return None
    neighborhood_id = str(neighborhood.get("neighborhood_id") or "")
    for fixture in fixtures:
        if str(fixture.get("neighborhood_id") or "") == neighborhood_id:
            return normalize_group_calibration(neighborhood, fixture)
    if index < len(fixtures):
        return normalize_group_calibration(neighborhood, fixtures[index])
    return None


def group_calibration_prompt(
    *,
    neighborhood: dict,
    rows_by_id: dict[str, dict],
    texts: dict[str, str],
    rubric: str,
    outline: str,
    metadata: dict,
    committee_anchor: Path,
    source_calibration: Path | dict | None = None,
) -> str:
    student_ids = [str(sid) for sid in neighborhood.get("student_ids", [])]
    rows = [rows_by_id[sid] for sid in student_ids if sid in rows_by_id]
    essay_blocks = []
    for sid in student_ids:
        row = rows_by_id.get(sid, {})
        name = str(row.get("student_name") or row.get("name") or sid)
        essay_blocks.append(f"STUDENT {sid} ({name})\n{texts.get(sid, '').strip()}")
    pair_lines = []
    for detail in neighborhood.get("trigger_details", []):
        if not isinstance(detail, dict):
            continue
        pair_lines.append(
            f"{detail.get('pair_key', '')}: prior_winner={detail.get('prior_winner', '')}; "
            f"basis={detail.get('prior_basis', '')}; status={detail.get('read_status', '')}; "
            f"triggers={detail.get('triggers', [])}; cautions={detail.get('cautions', [])}; "
            f"evidence_recommended={detail.get('recommended_winner', '')}; "
            f"evidence_confidence={detail.get('evidence_confidence', '')}; "
            f"ambiguous={detail.get('ambiguous', False)}"
        )
    packet = neighborhood.get("evidence_packet") if isinstance(neighborhood.get("evidence_packet"), dict) else {}
    packet_context = ""
    if packet:
        packet_context = "\n".join(
            [
                f"packet_id={packet.get('packet_id', '')}",
                f"recommended_read_type={packet.get('recommended_read_type', '')}",
                f"priority_score={packet.get('priority_score', '')}",
                f"reason={packet.get('reason', '')}",
                f"seed_order={packet.get('seed_order', [])}",
                f"evidence_order={packet.get('evidence_order', [])}",
                f"triggering_pair_keys={packet.get('triggering_pair_keys', [])}",
                f"ambiguous_pair_keys={packet.get('ambiguous_pair_keys', [])}",
            ]
        )
    genre = str(metadata.get("assignment_genre") or metadata.get("genre") or "")
    class_context = json.dumps(
        {
            "assignment_genre": genre,
            "grade_level": metadata.get("grade_level") or metadata.get("grade") or "",
        },
        ensure_ascii=True,
        sort_keys=True,
    )
    return "\n\n".join(
        [
            "You are doing committee-level neighborhood calibration for a writing assessment.",
            "Rank ONLY the listed students from strongest to weakest within this local neighborhood.",
            "Return every listed student_id exactly once in ordered_student_ids. Do not include any other students.",
            "Use the rubric, assignment, committee anchors, and essay texts as evidence. Cohort metrics and prior pairwise reads identify the neighborhood; they are not authority.",
            "For literary analysis, prioritize defensible interpretation, proof sufficiency, and explained textual evidence over cleaner formulaic control. Do not reward mature theme words unless they are proven by specific events.",
            "If a cleaner essay is merely organized, formulaic, or complete while a rougher essay proves stronger meaning, place the rougher essay higher. If roughness blocks meaning or the response is unfinished scaffold, keep it lower.",
            "For every unresolved pair_key listed below, return an edge_decisions item. Decide that pair directly even if your full-neighborhood order remains medium confidence. Use high confidence only when the pair winner is teacher-defensible after rereading both essays.",
            (
                "For every edge_decisions item, fill the edge ledger fields. "
                "Use student_ids or tie for interpretive_claim_winner, proof_quality_winner, textual_specificity_winner, "
                "surface_control_winner, and completion_coherence_winner. decisive_axis must name the single axis that actually decides the pair."
            ),
            (
                "For routed caution edges, copy the routed cautions into routed_cautions. "
                "Set caution_honored=true only when the caution changed or directly controlled the edge decision. "
                "If you preserve the prior/active winner despite a routed caution, set caution_honored=false, give a caution_not_decisive_reason, "
                "and cite at least two winner_text_moments plus at least one loser_text_moments from the essays."
            ),
            (
                "If you preserve the prior/active winner on a routed formulaic/thin, polished/shallow, rougher-stronger, "
                "or incomplete/scaffold caution, you must also fill loser_interpretive_claim, winner_counterclaim, "
                "loser_claim_refutation, and claim_refutation_text_moments. The refutation must directly explain why the "
                "loser-side interpretation or content claim does not beat the prior winner; 'more proof', 'more concrete events', "
                "or 'clearer evidence' alone is not enough. Label claim_refutation_text_moments with student_id prefixes so both "
                "essays are represented."
            ),
            (
                "Do not use surface_control as decisive on a routed caution edge unless mechanics_block_meaning or completion_floor_applied is true. "
                "If a complete/formulaic essay wins, explain the textual interpretation and proof quality that make it win, not just its organization."
            ),
            (
                "If mechanics_block_meaning=true, fill mechanics_blocked_student with the student_id whose meaning is blocked, "
                "mechanics_blocker_evidence with at least two concrete unreadable or meaning-breaking moments, and mechanics_blocker_reason with why "
                "the meaning is not reliably recoverable. Do not set mechanics_block_meaning=true for ordinary roughness, grammar errors, vague wording, "
                "or weaker polish when the interpretation can still be followed."
            ),
            "An edge_decisions winner may disagree with the broad ordered_student_ids only if the local pair is genuinely ambiguous; explain that tension in the edge rationale.",
            f"Class context: {class_context}",
            "Rubric:\n" + rubric.strip(),
            "Assignment outline:\n" + outline.strip(),
            "Committee anchors and external source calibration:\n"
            + "\n".join(
                committee_anchor_selection_details(
                    committee_anchor,
                    source_calibration=source_calibration,
                    genre=genre,
                    grade_level=metadata_grade_level(metadata),
                )
            ),
            "Cohort roster:\n" + "\n".join(group_row_brief(row) for row in rows),
            "Evidence group packet context:\n" + (packet_context or "No packet context supplied; this neighborhood came from unresolved committee reads."),
            "Unresolved pairwise edges under calibration:\n" + "\n".join(pair_lines),
            "Essays:\n\n" + "\n\n---\n\n".join(essay_blocks),
        ]
    )


def group_calibration_repair_prompt(
    raw_output: str,
    original_prompt: str,
    repair_reasons: list[str] | None = None,
) -> str:
    reason_text = "\n".join(f"- {reason}" for reason in (repair_reasons or ["invalid_json_response"]))
    return "\n\n".join(
        [
            "Your previous group-calibration output did not parse as the required JSON object.",
            "Repair reasons:",
            reason_text,
            "Return ONLY valid JSON. No markdown fences, no prose outside JSON.",
            "The JSON must include ordered_student_ids, confidence, rationale, and placement_notes.",
            "It must also include one edge_decisions item for every unresolved pair_key listed in the original task, including all required edge ledger fields.",
            "Original task:",
            original_prompt,
            "Previous invalid output:",
            raw_output[:4000],
        ]
    )


def run_group_calibration(
    neighborhood: dict,
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
    committee_anchor: Path,
    source_calibration: Path | dict | None = None,
) -> dict:
    group_max_output_tokens = max(int(max_output_tokens or 0), DEFAULT_GROUP_MAX_OUTPUT_TOKENS)
    prompt = group_calibration_prompt(
        neighborhood=neighborhood,
        rows_by_id=rows_by_id,
        texts=texts,
        rubric=rubric,
        outline=outline,
        metadata=metadata,
        committee_anchor=committee_anchor,
        source_calibration=source_calibration,
    )
    response = responses_create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        reasoning=reasoning,
        routing_path=routing,
        text_format=GROUP_CALIBRATION_RESPONSE_FORMAT,
        max_output_tokens=group_max_output_tokens,
    )
    content = extract_text(response)
    repair_reasons = []
    try:
        parsed = vc.parse_json(content)
    except ValueError:
        repair_reasons = ["invalid_json_response"]
        parsed = {}
    normalized = normalize_group_calibration(neighborhood, parsed)
    expected_edges = {str(pair_key) for pair_key in neighborhood.get("pair_keys", [])}
    returned_edges = {str(edge.get("pair_key") or "") for edge in normalized.get("edge_decisions", [])}
    if normalized.get("missing_student_ids"):
        repair_reasons.append(
            "ordered_student_ids omitted required student ids: "
            + ", ".join(normalized.get("missing_student_ids", []))
        )
    missing_edges = sorted(expected_edges - returned_edges)
    if missing_edges:
        repair_reasons.append(
            "edge_decisions omitted required pair_keys: " + ", ".join(missing_edges)
        )
    if repair_reasons:
        repair_response = responses_create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": group_calibration_repair_prompt(content, prompt, repair_reasons),
                }
            ],
            temperature=0.0,
            reasoning="low",
            routing_path=routing,
            text_format=GROUP_CALIBRATION_RESPONSE_FORMAT,
            max_output_tokens=group_max_output_tokens,
        )
        parsed = vc.parse_json(extract_text(repair_response))
        normalized = normalize_group_calibration(neighborhood, parsed)
    return normalized


def candidate_from_group_pair(
    left: str,
    right: str,
    rows_by_id: dict[str, dict],
    neighborhood: dict,
) -> dict:
    left_row = rows_by_id[left]
    right_row = rows_by_id[right]
    left_rank = int(num(left_row.get("seed_rank"), 999999) or 999999)
    right_rank = int(num(right_row.get("seed_rank"), 999999) or 999999)
    higher, lower = (left, right) if left_rank <= right_rank else (right, left)
    higher_rank, lower_rank = (left_rank, right_rank) if higher == left else (right_rank, left_rank)
    pair_key = pair_key_from_item({"pair": [higher, lower]})
    packet = neighborhood.get("evidence_packet") if isinstance(neighborhood.get("evidence_packet"), dict) else {}
    return {
        "pair": [higher, lower],
        "pair_key": pair_key,
        "seed_order": {
            "higher": higher,
            "lower": lower,
            "higher_rank": higher_rank,
            "lower_rank": lower_rank,
        },
        "bucket": "group_neighborhood",
        "committee_score": 0,
        "triggers": ["committee_group_neighborhood_order"],
        "trigger_details": {
            "group_neighborhood_id": neighborhood.get("neighborhood_id", ""),
            "evidence_packet_id": packet.get("packet_id", ""),
            "evidence_packet_read_type": packet.get("recommended_read_type", ""),
            "escalated_cautions": [],
        },
        "escalated_summary": {
            "winner": "",
            "loser": "",
            "winner_side": "",
            "decision": "",
            "confidence": "",
            "decision_basis": "",
            "adjudication_source": "",
        },
    }


def candidate_with_group_context(candidate: dict, neighborhood: dict) -> dict:
    item = copy.deepcopy(candidate)
    details = item.get("trigger_details") if isinstance(item.get("trigger_details"), dict) else {}
    details = dict(details)
    packet = neighborhood.get("evidence_packet") if isinstance(neighborhood.get("evidence_packet"), dict) else {}
    details.setdefault("group_neighborhood_id", neighborhood.get("neighborhood_id", ""))
    if packet:
        details["evidence_packet_id"] = packet.get("packet_id", "")
        details["evidence_packet_read_type"] = packet.get("recommended_read_type", "")
    item["trigger_details"] = details
    return item


def decision_from_group_calibration(candidate: dict, calibration: dict) -> dict | None:
    if vc.normalize_confidence(calibration.get("confidence")) != "high":
        return None
    order = [str(sid).strip() for sid in calibration.get("ordered_student_ids", []) if str(sid).strip()]
    seed_order = candidate.get("seed_order") if isinstance(candidate.get("seed_order"), dict) else {}
    higher = str(seed_order.get("higher") or "").strip()
    lower = str(seed_order.get("lower") or "").strip()
    if higher not in order or lower not in order:
        return None
    winner = higher if order.index(higher) < order.index(lower) else lower
    prior_winner = str((candidate.get("escalated_summary") or {}).get("winner") or "").strip()
    if winner == prior_winner:
        return None
    loser = lower if winner == higher else higher
    winner_side = "A" if winner == higher else "B"
    decision = "KEEP" if winner_side == "A" else "SWAP"
    details = candidate.get("trigger_details") if isinstance(candidate.get("trigger_details"), dict) else {}
    triggers = set(candidate.get("triggers") or [])
    cautions = sorted(set(details.get("escalated_cautions") or []) | {"committee_group_calibration"})
    polish_signal = bool(triggers & CAUTION_IGNORED_TRIGGERS) or bool(
        set(details.get("escalated_cautions") or []) & POLISH_LIKE_CAUTIONS
    )
    rougher_signal = bool(set(details.get("escalated_cautions") or []) & ROUGHER_STRONGER_CAUTIONS)
    return {
        "pair": [higher, lower],
        "pair_key": pair_key_from_item({"pair": [higher, lower]}),
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
        "confidence": "high",
        "adjudication_source": "committee_edge",
        "decision_basis": "content_reasoning",
        "cautions_applied": cautions,
        "criterion_notes": [],
        "decision_checks": {
            "deeper_interpretation": winner_side,
            "better_text_evidence_explanation": winner_side,
            "cleaner_or_more_formulaic": "tie",
            "rougher_but_stronger_content": winner_side if rougher_signal else "tie",
            "completion_advantage": "tie",
            "cleaner_wins_on_substance": "",
            "rougher_loses_because": "",
            "interpretation_depth": winner_side,
            "proof_sufficiency": winner_side,
            "polish_trap": polish_signal,
            "rougher_but_stronger_latent": rougher_signal,
            "alternate_theme_validity": winner_side,
            "mechanics_block_meaning": False,
            "completion_floor_applied": False,
        },
        "rationale": calibration.get("rationale", ""),
        "committee_confidence": "group_high",
        "model_metadata": {
            "adjudication_source": "committee_edge",
            "committee_read": "group-neighborhood-calibration",
            "committee_override_reason": "committee_group_calibration_override",
            "supersedes_pair_key": pair_key_from_item({"pair": [higher, lower]}),
            "phase": "3d",
        },
        "committee_edge_trace": {
            "read": "group-neighborhood-calibration",
            "override_reason": "committee_group_calibration_override",
            "triggers": sorted(triggers),
            "committee_score": candidate.get("committee_score", 0),
            "prior_winner": prior_winner,
            "neighborhood_id": calibration.get("neighborhood_id", ""),
            "ordered_student_ids": order,
            "placement_notes": calibration.get("placement_notes", []),
            "evidence_packet": {
                "packet_id": details.get("evidence_packet_id", ""),
                "recommended_read_type": details.get("evidence_packet_read_type", ""),
            },
        },
    }


def group_edge_routed_cautions(candidate: dict, edge: dict) -> list[str]:
    edge_cautions = edge.get("routed_cautions") if isinstance(edge.get("routed_cautions"), list) else []
    cautions = {str(caution).strip() for caution in edge_cautions if str(caution).strip()}
    details = candidate.get("trigger_details") if isinstance(candidate.get("trigger_details"), dict) else {}
    cautions.update(str(caution).strip() for caution in details.get("escalated_cautions", []) if str(caution).strip())
    return sorted(cautions)


def candidate_is_caution_ignored_edge(candidate: dict, edge: dict) -> bool:
    triggers = set(candidate.get("triggers") or [])
    if str(candidate.get("bucket") or "") == "caution_ignored" or bool(triggers & CAUTION_IGNORED_TRIGGERS):
        return True
    cautions = set(group_edge_routed_cautions(candidate, edge))
    return bool(cautions & (POLISH_LIKE_CAUTIONS | ROUGHER_STRONGER_CAUTIONS))


def ledger_winner_value(edge: dict, axis: str) -> str:
    return str(edge.get(f"{axis}_winner") or "tie").strip() or "tie"


def ledger_winner_matches(edge: dict, axis: str, student_id: str, *, allow_tie: bool = False) -> bool:
    value = ledger_winner_value(edge, axis)
    if value == student_id:
        return True
    return allow_tie and value in {"tie", "tie_or_ambiguous"}


def caution_reason_text(edge: dict) -> str:
    return str(edge.get("caution_not_decisive_reason") or "").strip().lower()


def caution_reason_is_generic(reason: str) -> bool:
    if not reason:
        return False
    return any(phrase in reason for phrase in GENERIC_CAUTION_REASON_PHRASES)


def caution_reason_addresses_caution(edge: dict, cautions: list[str] | set[str]) -> bool:
    reason = caution_reason_text(edge)
    for caution in cautions:
        keywords = CAUTION_REASON_KEYWORDS.get(str(caution), frozenset())
        if any(keyword in reason for keyword in keywords):
            return True
    return False


def claim_refutation_text(edge: dict, field: str) -> str:
    return str(edge.get(field) or "").strip()


def claim_refutation_is_generic(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    if len(normalized.split()) < 8:
        return True
    has_generic_phrase = any(phrase in normalized for phrase in CLAIM_REFUTATION_GENERIC_PHRASES)
    has_refutation_marker = any(marker in normalized for marker in CLAIM_REFUTATION_MARKERS)
    has_content_keyword = any(keyword in normalized for keyword in CLAIM_REFUTATION_CONTENT_KEYWORDS)
    return has_generic_phrase and not (has_refutation_marker and has_content_keyword)


def claim_refutation_mentions_both_sides(edge: dict, winner: str, loser: str) -> bool:
    raw = (
        edge.get("claim_refutation_text_moments")
        if isinstance(edge.get("claim_refutation_text_moments"), list)
        else []
    )
    moments = [str(moment).strip().lower() for moment in raw if str(moment).strip()]
    if len(moments) < 2:
        return False
    winner_lower = str(winner or "").strip().lower()
    loser_lower = str(loser or "").strip().lower()
    winner_hit = any(
        token
        and any(token in moment for moment in moments)
        for token in (winner_lower, "winner:", "prior winner:", "prior:")
    )
    loser_hit = any(
        token
        and any(token in moment for moment in moments)
        for token in (loser_lower, "loser:", "challenger:", "other essay:")
    )
    return winner_hit and loser_hit


def claim_refutation_addresses_interpretation(edge: dict) -> bool:
    combined = " ".join(
        claim_refutation_text(edge, field).lower()
        for field in ("loser_interpretive_claim", "winner_counterclaim", "loser_claim_refutation")
    )
    has_refutation_marker = any(marker in combined for marker in CLAIM_REFUTATION_MARKERS)
    has_content_keyword = any(keyword in combined for keyword in CLAIM_REFUTATION_CONTENT_KEYWORDS)
    return has_refutation_marker and has_content_keyword


def mechanics_blocker_student(edge: dict) -> str:
    value = str(edge.get("mechanics_blocked_student") or "none").strip()
    return value or "none"


def mechanics_blocker_evidence(edge: dict) -> list[str]:
    raw = edge.get("mechanics_blocker_evidence") if isinstance(edge.get("mechanics_blocker_evidence"), list) else []
    return [str(item).strip() for item in raw if str(item).strip()]


def mechanics_blocker_reason(edge: dict) -> str:
    return str(edge.get("mechanics_blocker_reason") or "").strip().lower()


def mechanics_reason_is_substantive(edge: dict) -> bool:
    reason = mechanics_blocker_reason(edge)
    if not reason:
        return False
    has_meaning_block = any(keyword in reason for keyword in MECHANICS_BLOCKING_KEYWORDS)
    surface_only = any(phrase in reason for phrase in MECHANICS_SURFACE_ONLY_PHRASES)
    if not has_meaning_block:
        return False
    # A reason can mention surface errors, but it must also explicitly connect
    # them to unrecoverable meaning, not just weaker polish or fluency.
    if surface_only and not any(
        phrase in reason
        for phrase in (
            "blocks meaning",
            "block meaning",
            "meaning is not recoverable",
            "meaning is unrecoverable",
            "cannot recover",
            "can't recover",
            "cannot follow the interpretation",
            "can't follow the interpretation",
            "not reliably recoverable",
            "unreadable",
            "incomprehensible",
        )
    ):
        return False
    return True


def reject_ledger(status: dict, reason: str) -> dict:
    status.update({"accepted": False, "reason": reason})
    return status


def mechanics_blocker_validation(candidate: dict, edge: dict, status: dict) -> dict | None:
    seed_order = candidate.get("seed_order") if isinstance(candidate.get("seed_order"), dict) else {}
    higher = str(seed_order.get("higher") or "").strip()
    lower = str(seed_order.get("lower") or "").strip()
    winner = str(edge.get("winner") or "").strip()
    loser = lower if winner == higher else higher if winner == lower else ""
    blocked_student = mechanics_blocker_student(edge)
    if blocked_student in {"", "none", "tie", "tie_or_ambiguous"}:
        return reject_ledger(status, "mechanics_blocker_missing_side")
    if loser and blocked_student != loser:
        return reject_ledger(status, "mechanics_blocker_wrong_side")
    if len(mechanics_blocker_evidence(edge)) < 2:
        return reject_ledger(status, "mechanics_blocker_missing_evidence")
    if not mechanics_blocker_reason(edge):
        return reject_ledger(status, "mechanics_blocker_reason_too_generic")
    if not mechanics_reason_is_substantive(edge):
        reason = mechanics_blocker_reason(edge)
        if any(phrase in reason for phrase in MECHANICS_SURFACE_ONLY_PHRASES):
            return reject_ledger(status, "mechanics_blocker_reason_too_generic")
        return reject_ledger(status, "mechanics_blocker_not_meaning_blocking")
    return None


def prior_preservation_claim_refutation_validation(
    candidate: dict,
    edge: dict,
    routed_cautions: list[str],
    status: dict,
) -> dict | None:
    cautions = set(routed_cautions) & INTERPRETATION_CONTENT_CAUTIONS
    if not cautions:
        return None
    # Mechanics and completion-floor blockers are already validated through
    # their side-aware blocker paths. This guard targets proof-quality laundering
    # when there is no accepted blocker.
    if truthy(edge.get("mechanics_block_meaning")) or truthy(edge.get("completion_floor_applied")):
        return None

    seed_order = candidate.get("seed_order") if isinstance(candidate.get("seed_order"), dict) else {}
    higher = str(seed_order.get("higher") or "").strip()
    lower = str(seed_order.get("lower") or "").strip()
    winner = str(edge.get("winner") or "").strip()
    loser = lower if winner == higher else higher if winner == lower else ""
    decisive_axis = str(edge.get("decisive_axis") or "").strip()

    loser_claim = claim_refutation_text(edge, "loser_interpretive_claim")
    winner_counterclaim = claim_refutation_text(edge, "winner_counterclaim")
    loser_refutation = claim_refutation_text(edge, "loser_claim_refutation")
    if not loser_claim:
        return reject_ledger(status, "missing_loser_interpretive_claim")
    if not winner_counterclaim:
        return reject_ledger(status, "missing_winner_counterclaim")
    if not loser_refutation:
        if "incomplete_or_scaffold" in cautions:
            return reject_ledger(status, "incomplete_scaffold_without_claim_refutation")
        if decisive_axis in {"proof_quality", "textual_specificity"}:
            return reject_ledger(status, "proof_quality_without_claim_refutation")
        return reject_ledger(status, "missing_loser_claim_refutation")
    if not claim_refutation_mentions_both_sides(edge, winner, loser):
        return reject_ledger(status, "claim_refutation_missing_both_sides")
    if (
        claim_refutation_is_generic(loser_claim)
        or claim_refutation_is_generic(winner_counterclaim)
        or claim_refutation_is_generic(loser_refutation)
    ):
        return reject_ledger(status, "claim_refutation_too_generic")
    if decisive_axis in {"proof_quality", "textual_specificity"} and not claim_refutation_addresses_interpretation(edge):
        return reject_ledger(status, "proof_quality_without_claim_refutation")
    if "incomplete_or_scaffold" in cautions:
        combined = " ".join(
            claim_refutation_text(edge, field).lower()
            for field in ("loser_interpretive_claim", "winner_counterclaim", "loser_claim_refutation")
        )
        scaffold_keywords = CAUTION_REASON_KEYWORDS["incomplete_or_scaffold"]
        if not any(keyword in combined for keyword in scaffold_keywords):
            return reject_ledger(status, "incomplete_scaffold_without_claim_refutation")
    return None


def prior_preservation_caution_validation(
    candidate: dict,
    edge: dict,
    routed_cautions: list[str],
    status: dict,
) -> dict | None:
    prior_winner = str((candidate.get("escalated_summary") or {}).get("winner") or "").strip()
    decisive_axis = str(edge.get("decisive_axis") or "").strip()
    mechanics_block = truthy(edge.get("mechanics_block_meaning"))
    completion_floor = truthy(edge.get("completion_floor_applied"))
    cautions = set(routed_cautions)

    reason = caution_reason_text(edge)
    if not caution_reason_addresses_caution(edge, cautions):
        if caution_reason_is_generic(reason):
            return reject_ledger(status, "caution_reason_too_generic")
        return reject_ledger(status, "caution_reason_missing_caution_reference")

    if "mechanics_impede_meaning" in cautions:
        if decisive_axis == "mechanics" and not mechanics_block:
            return reject_ledger(status, "mechanics_decisive_without_blocker")
        if decisive_axis == "mechanics" or mechanics_block:
            blocker_failure = mechanics_blocker_validation(candidate, edge, status)
            if blocker_failure:
                return blocker_failure
        if mechanics_block and not caution_reason_addresses_caution(edge, {"mechanics_impede_meaning"}):
            return reject_ledger(status, "caution_reason_missing_caution_reference")

    if "incomplete_or_scaffold" in cautions:
        if decisive_axis in {"completion_coherence", "completion_floor"} and not completion_floor:
            return reject_ledger(status, "completion_decisive_without_floor")
        if completion_floor and not caution_reason_addresses_caution(edge, {"incomplete_or_scaffold"}):
            return reject_ledger(status, "caution_reason_missing_caution_reference")

    if "formulaic_but_thin" in cautions:
        interpretation_ok = ledger_winner_matches(edge, "interpretive_claim", prior_winner, allow_tie=True)
        proof_ok = ledger_winner_matches(edge, "proof_quality", prior_winner)
        axis_ok = decisive_axis in {"interpretive_claim", "proof_quality", "textual_specificity"}
        surface_only = ledger_winner_matches(edge, "surface_control", prior_winner) and not ledger_winner_matches(
            edge, "interpretive_claim", prior_winner
        )
        if not (interpretation_ok and proof_ok and axis_ok) or surface_only:
            return reject_ledger(status, "formulaic_thin_not_substantively_defeated")

    if "polished_but_shallow" in cautions:
        if not ledger_winner_matches(edge, "interpretive_claim", prior_winner):
            return reject_ledger(status, "polished_shallow_not_substantively_defeated")

    if "rougher_but_stronger_content" in cautions:
        interpretation_ok = ledger_winner_matches(edge, "interpretive_claim", prior_winner)
        blocker_ok = mechanics_block or completion_floor
        if not (interpretation_ok or blocker_ok):
            return reject_ledger(status, "rougher_stronger_not_substantively_defeated")

    claim_refutation_failure = prior_preservation_claim_refutation_validation(
        candidate, edge, routed_cautions, status
    )
    if claim_refutation_failure:
        return claim_refutation_failure

    return None


def validate_group_edge_ledger(candidate: dict, edge: dict) -> dict:
    """Validate mini's structured per-edge ledger before group edges affect rerank."""

    pair_key = str(edge.get("pair_key") or candidate.get("pair_key") or "").strip()
    prior_winner = str((candidate.get("escalated_summary") or {}).get("winner") or "").strip()
    winner = str(edge.get("winner") or "").strip()
    routed_cautions = group_edge_routed_cautions(candidate, edge)
    caution_ignored = candidate_is_caution_ignored_edge(candidate, edge)
    status = {
        "pair_key": pair_key,
        "accepted": True,
        "reason": "edge_ledger_not_required",
        "caution_ignored": caution_ignored,
        "prior_winner": prior_winner,
        "winner": winner,
        "routed_cautions": routed_cautions,
        "decisive_axis": str(edge.get("decisive_axis") or ""),
        "caution_honored": truthy(edge.get("caution_honored")),
    }
    if not caution_ignored:
        return status

    winner_moments = edge.get("winner_text_moments") if isinstance(edge.get("winner_text_moments"), list) else []
    loser_moments = edge.get("loser_text_moments") if isinstance(edge.get("loser_text_moments"), list) else []
    decisive_axis = str(edge.get("decisive_axis") or "").strip()
    blocked = truthy(edge.get("mechanics_block_meaning")) or truthy(edge.get("completion_floor_applied"))
    if decisive_axis == "surface_control" and not blocked:
        return reject_ledger(status, "surface_control_decisive_without_blocker")
    if decisive_axis == "mechanics" and not truthy(edge.get("mechanics_block_meaning")):
        return reject_ledger(status, "mechanics_decisive_without_blocker")
    if decisive_axis == "completion_floor" and not truthy(edge.get("completion_floor_applied")):
        return reject_ledger(status, "completion_decisive_without_floor")
    if decisive_axis == "mechanics" or truthy(edge.get("mechanics_block_meaning")):
        blocker_failure = mechanics_blocker_validation(candidate, edge, status)
        if blocker_failure:
            return blocker_failure
    if (
        "incomplete_or_scaffold" in set(routed_cautions)
        and decisive_axis == "completion_coherence"
        and not truthy(edge.get("completion_floor_applied"))
    ):
        return reject_ledger(status, "completion_decisive_without_floor")
    if winner != prior_winner:
        status["reason"] = "edge_ledger_override_allowed"
        return status
    if truthy(edge.get("caution_honored")):
        return reject_ledger(status, "prior_preserved_while_claiming_caution_honored")
    if not str(edge.get("caution_not_decisive_reason") or "").strip():
        return reject_ledger(status, "missing_caution_not_decisive_reason")
    if len([moment for moment in winner_moments if str(moment).strip()]) < 2:
        return reject_ledger(status, "insufficient_winner_text_moments")
    if len([moment for moment in loser_moments if str(moment).strip()]) < 1:
        return reject_ledger(status, "missing_loser_text_moment")
    if decisive_axis in {"", "tie_or_ambiguous"}:
        return reject_ledger(status, "missing_decisive_axis")
    substantive_failure = prior_preservation_caution_validation(candidate, edge, routed_cautions, status)
    if substantive_failure:
        return substantive_failure
    status["reason"] = "prior_preservation_ledger_accepted"
    return status


def decision_from_group_edge_decision(
    candidate: dict,
    edge: dict,
    calibration: dict,
) -> dict | None:
    if vc.normalize_confidence(edge.get("confidence")) != "high":
        return None
    if truthy(edge.get("mechanics_block_meaning")) or truthy(edge.get("completion_floor_applied")):
        return None
    seed_order = candidate.get("seed_order") if isinstance(candidate.get("seed_order"), dict) else {}
    higher = str(seed_order.get("higher") or "").strip()
    lower = str(seed_order.get("lower") or "").strip()
    winner = str(edge.get("winner") or "").strip()
    if winner not in {higher, lower}:
        return None
    ledger_status = validate_group_edge_ledger(candidate, edge)
    if not ledger_status.get("accepted", False):
        return None
    prior_winner = str((candidate.get("escalated_summary") or {}).get("winner") or "").strip()
    if winner == prior_winner:
        return None
    loser = lower if winner == higher else higher
    winner_side = "A" if winner == higher else "B"
    decision = decision_from_group_calibration(
        {
            **candidate,
            "trigger_details": {
                **(candidate.get("trigger_details") if isinstance(candidate.get("trigger_details"), dict) else {}),
                "escalated_cautions": list(
                    set(
                        (
                            candidate.get("trigger_details")
                            if isinstance(candidate.get("trigger_details"), dict)
                            else {}
                        ).get("escalated_cautions", [])
                    )
                ),
            },
        },
        {
            **calibration,
            "confidence": "high",
            "ordered_student_ids": [winner, loser],
            "rationale": str(edge.get("rationale") or calibration.get("rationale") or ""),
        },
    )
    if decision is None:
        return None
    checks = decision.get("decision_checks") if isinstance(decision.get("decision_checks"), dict) else {}
    checks["polish_trap"] = truthy(edge.get("polish_trap"))
    checks["rougher_but_stronger_latent"] = truthy(edge.get("rougher_but_stronger_latent"))
    checks["mechanics_block_meaning"] = False
    checks["completion_floor_applied"] = False
    decision["decision_checks"] = checks
    decision["winner"] = winner
    decision["loser"] = loser
    decision["winner_side"] = winner_side
    decision["decision"] = "KEEP" if winner_side == "A" else "SWAP"
    decision["rationale"] = str(edge.get("rationale") or decision.get("rationale") or "")
    decision["committee_confidence"] = "group_edge_high"
    metadata = dict(decision.get("model_metadata") or {})
    metadata["committee_override_reason"] = "committee_group_edge_decision_override"
    decision["model_metadata"] = metadata
    trace = dict(decision.get("committee_edge_trace") or {})
    trace["override_reason"] = "committee_group_edge_decision_override"
    trace["edge_decision"] = {
        "pair_key": edge.get("pair_key", ""),
        "winner": winner,
        "confidence": vc.normalize_confidence(edge.get("confidence")),
        "polish_trap": truthy(edge.get("polish_trap")),
        "rougher_but_stronger_latent": truthy(edge.get("rougher_but_stronger_latent")),
        "edge_ledger_status": ledger_status,
        "decisive_axis": edge.get("decisive_axis", ""),
        "routed_cautions": group_edge_routed_cautions(candidate, edge),
    }
    decision["committee_edge_trace"] = trace
    return decision


def run_group_calibration_path(
    *,
    selected: list[dict],
    rows: list[dict],
    read_results: list[dict],
    texts_by_id: dict[str, str],
    rubric: str,
    outline: str,
    metadata: dict,
    model: str,
    routing: str,
    reasoning: str,
    max_output_tokens: int,
    committee_anchor: Path,
    live: bool,
    live_group: bool,
    fixtures: list[dict],
    max_groups: int,
    max_students: int,
    existing_decision_keys: set[str],
    source_calibration: Path | dict | None = None,
    evidence_group_packets: dict | None = None,
) -> tuple[list[dict], list[dict], dict]:
    rows_by_id = {str(row.get("student_id") or ""): row for row in vc.prepare_rows(rows)}
    packet_neighborhoods = build_group_calibration_neighborhoods_from_packets(
        packet_payload=evidence_group_packets or {},
        selected=selected,
        rows=rows,
        max_groups=max_groups,
        max_students=max_students,
    )
    if packet_neighborhoods:
        neighborhoods = packet_neighborhoods
        neighborhood_source = "evidence_group_packets"
    else:
        neighborhoods = build_group_calibration_neighborhoods(
            selected=selected,
            rows=rows,
            read_results=read_results,
            max_groups=max_groups,
            max_students=max_students,
        )
        neighborhood_source = "unresolved_read_results"
    candidate_by_key = {str(candidate.get("pair_key") or ""): candidate for candidate in selected}
    decisions: list[dict] = []
    results: list[dict] = []
    read_count = 0
    skipped_existing = 0
    for index, neighborhood in enumerate(neighborhoods):
        calibration = group_calibration_from_fixture(neighborhood, fixtures, index)
        source = "fixture" if calibration is not None else ""
        if calibration is None and live and live_group:
            progress(
                f"Group calibration {index + 1}/{max_groups} neighborhood={neighborhood.get('neighborhood_id', '')} students={len(neighborhood.get('student_ids', []))}",
                enabled=True,
            )
            calibration = run_group_calibration(
                neighborhood,
                rows_by_id,
                texts_by_id,
                rubric,
                outline,
                metadata,
                model=model,
                routing=routing,
                reasoning=reasoning,
                max_output_tokens=max_output_tokens,
                committee_anchor=committee_anchor,
                source_calibration=source_calibration,
            )
            progress(
                f"Group calibration complete neighborhood={neighborhood.get('neighborhood_id', '')} confidence={calibration.get('confidence', '')}",
                enabled=True,
            )
            source = "live"
        result = {
            "neighborhood_id": neighborhood.get("neighborhood_id", ""),
            "student_ids": neighborhood.get("student_ids", []),
            "pair_keys": neighborhood.get("pair_keys", []),
            "neighborhood_source": neighborhood_source,
            "evidence_packet": neighborhood.get("evidence_packet", {}),
            "source": source or "not_read",
            "override_pair_keys": [],
            "edge_decision_pair_keys": [],
            "edge_ledger_statuses": [],
            "support_pair_keys": [],
            "skipped_existing_decision_keys": [],
            "skipped_explicit_edge_decision_keys": [],
        }
        if calibration is None:
            result["status"] = "not_read"
            results.append(result)
            continue
        read_count += 1
        result["status"] = "read"
        result["calibration"] = calibration
        explicit_edge_keys: set[str] = set()
        for edge_decision in calibration.get("edge_decisions", []):
            pair_key = str(edge_decision.get("pair_key") or "")
            if pair_key:
                explicit_edge_keys.add(pair_key)
            if not pair_key or pair_key in existing_decision_keys:
                continue
            candidate = candidate_by_key.get(pair_key)
            if candidate is None:
                continue
            candidate = candidate_with_group_context(candidate, neighborhood)
            ledger_status = validate_group_edge_ledger(candidate, edge_decision)
            result["edge_ledger_statuses"].append(ledger_status)
            if not ledger_status.get("accepted", False):
                continue
            decision = decision_from_group_edge_decision(candidate, edge_decision, calibration)
            if decision is None:
                continue
            decisions.append(decision)
            existing_decision_keys.add(pair_key)
            result["override_pair_keys"].append(pair_key)
            result["edge_decision_pair_keys"].append(pair_key)
        ordered_ids = [
            str(sid).strip()
            for sid in calibration.get("ordered_student_ids", [])
            if str(sid).strip() in rows_by_id
        ]
        group_pair_keys = []
        for left_index, left in enumerate(ordered_ids):
            for right in ordered_ids[left_index + 1:]:
                group_pair_keys.append(pair_key_from_item({"pair": [left, right]}))
        result["group_order_pair_keys"] = group_pair_keys
        unresolved_pair_keys = {str(pair_key) for pair_key in neighborhood.get("pair_keys", [])}
        for pair_key in group_pair_keys:
            if pair_key in explicit_edge_keys:
                result["skipped_explicit_edge_decision_keys"].append(pair_key)
                continue
            if pair_key in existing_decision_keys:
                skipped_existing += 1
                result["skipped_existing_decision_keys"].append(pair_key)
                continue
            candidate = candidate_by_key.get(pair_key)
            if candidate is None:
                left, right = pair_key.split("::", 1)
                if left not in rows_by_id or right not in rows_by_id:
                    continue
                candidate = candidate_from_group_pair(left, right, rows_by_id, neighborhood)
            else:
                candidate = candidate_with_group_context(candidate, neighborhood)
            decision = decision_from_group_calibration(candidate, calibration)
            if decision is None:
                continue
            decisions.append(decision)
            existing_decision_keys.add(pair_key)
            if pair_key in unresolved_pair_keys:
                result["override_pair_keys"].append(pair_key)
            else:
                result["support_pair_keys"].append(pair_key)
        results.append(result)
    summary = {
        "enabled": bool(live or fixtures),
        "live": bool(live and live_group),
        "fixture": bool(fixtures),
        "max_groups": int(max_groups),
        "max_students": int(max_students),
        "neighborhood_source": neighborhood_source,
        "packet_neighborhood_count": len(packet_neighborhoods),
        "neighborhood_count": len(neighborhoods),
        "read_count": read_count,
        "override_count": len(decisions),
        "skipped_existing_decision_count": skipped_existing,
    }
    return decisions, results, summary


def placement_context_lines(
    candidate: dict,
    read_a: dict,
    read_b: dict | None,
    ab_reason: str,
    rows_by_id: dict[str, dict],
) -> list[str]:
    seed_order = candidate.get("seed_order") if isinstance(candidate.get("seed_order"), dict) else {}
    higher_id = str(seed_order.get("higher", "") or "").strip()
    lower_id = str(seed_order.get("lower", "") or "").strip()
    sorted_rows = sorted(
        rows_by_id.values(),
        key=lambda row: (int(num(row.get("seed_rank"), 999999) or 999999), str(row.get("student_id") or "")),
    )
    student_count = len(sorted_rows)
    rank_by_id = {str(row.get("student_id") or ""): idx for idx, row in enumerate(sorted_rows)}
    context_ids: set[str] = {higher_id, lower_id}
    for student_id in (higher_id, lower_id):
        idx = rank_by_id.get(student_id)
        if idx is None:
            continue
        for neighbor in sorted_rows[max(0, idx - 2): min(student_count, idx + 3)]:
            neighbor_id = str(neighbor.get("student_id") or "").strip()
            if neighbor_id:
                context_ids.add(neighbor_id)
    context_rows = [
        row for row in sorted_rows
        if str(row.get("student_id") or "").strip() in context_ids
    ]
    prior = candidate.get("escalated_summary") if isinstance(candidate.get("escalated_summary"), dict) else {}
    a_checks = normalize_committee_decision_checks(
        read_a.get("decision_checks") if isinstance(read_a.get("decision_checks"), dict) else {}
    )
    b_checks = normalize_committee_decision_checks(
        read_b.get("decision_checks") if read_b is not None and isinstance(read_b.get("decision_checks"), dict) else {}
    )
    lines = evidence_ledger_instruction_lines() + [
        "This is Read C placement calibration. Use cohort context to test whether the pairwise result creates a defensible top/middle/bottom placement.",
        "Do not treat seed rank, Borda, composite score, or prior judgments as authority. Use them only to identify the neighborhood and the consequence of the edge.",
        "If A/B both preserved the prior on a caution_ignored edge, explicitly ask whether they overvalued complete/formulaic proof against stronger literary interpretation.",
        f"Prior active winner={prior.get('winner', '')}; prior basis={prior.get('decision_basis', '')}; prior confidence={prior.get('confidence', '')}.",
        (
            "Read A audit target: "
            f"winner={read_a.get('winner', '')}; confidence={vc.normalize_confidence(read_a.get('confidence'))}; "
            f"interpretation_depth={a_checks.get('interpretation_depth')}; proof_sufficiency={a_checks.get('proof_sufficiency')}; "
            f"polish_trap={bool(a_checks.get('polish_trap'))}; rougher_but_stronger_latent={bool(a_checks.get('rougher_but_stronger_latent'))}; "
            f"mechanics_block_meaning={bool(a_checks.get('mechanics_block_meaning'))}; completion_floor_applied={bool(a_checks.get('completion_floor_applied'))}."
        ),
        (
            "Read B audit target: "
            f"winner={read_b.get('winner', '') if read_b else ''}; confidence={vc.normalize_confidence(read_b.get('confidence')) if read_b else ''}; "
            f"interpretation_depth={b_checks.get('interpretation_depth')}; proof_sufficiency={b_checks.get('proof_sufficiency')}; "
            f"polish_trap={bool(b_checks.get('polish_trap'))}; rougher_but_stronger_latent={bool(b_checks.get('rougher_but_stronger_latent'))}; "
            f"mechanics_block_meaning={bool(b_checks.get('mechanics_block_meaning'))}; completion_floor_applied={bool(b_checks.get('completion_floor_applied'))}; "
            f"A/B resolution={ab_reason}."
        ),
        "Placement neighborhood: " + " | ".join(row_brief(row, student_count) for row in context_rows),
        "Return the stronger essay as winner only if that winner's placement is defensible against nearby papers; if the edge should not move, keep the prior winner.",
    ]
    return [line for line in lines if line.strip()]


def should_invoke_read_c(candidate: dict, read_a: dict, read_b: dict | None, ab_reason: str) -> tuple[bool, str]:
    """Decide whether the placement-aware tiebreaker should run.

    Read C is deliberately narrower than Read B. It is for high-leverage edges
    where pairwise A/B still leaves an unstable placement: concurrence on a
    caution_ignored edge, split/weak A+B outcomes, or completion/mechanics
    blockers on a pair that can move the top pack or cross a level boundary.
    """
    if read_b is None:
        return False, "committee_read_c_not_invoked_without_read_b"
    details = candidate.get("trigger_details") if isinstance(candidate.get("trigger_details"), dict) else {}
    bucket = str(candidate.get("bucket") or "")
    high_leverage = bool(
        details.get("top10_cross")
        or details.get("level_cross")
        or details.get("top10_involved")
        or bucket == "caution_ignored"
    )
    if not high_leverage:
        return False, "committee_read_c_not_high_leverage"
    if ab_reason == "committee_read_ab_concurred" and bucket == "caution_ignored":
        return True, "committee_read_c_ab_concurred_on_caution_ignored"
    if ab_reason in {
        "committee_read_ab_split_b_confirms_prior",
        "committee_read_ab_split_no_trap",
        "committee_read_ab_weak_agreement",
    }:
        return True, "committee_read_c_unresolved_ab_split"
    if ab_reason in {
        "committee_read_b_blocked_by_mechanics_or_completion",
        "committee_read_ab_blocked_by_a_mechanics_or_completion",
    }:
        return True, "committee_read_c_completion_or_mechanics_block_on_leverage_edge"
    return False, "committee_read_c_not_needed"


def run_placement_read_c(
    candidate: dict,
    read_a: dict,
    read_b: dict,
    ab_reason: str,
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
    source_calibration: Path | dict | None = None,
) -> dict:
    seed_order = candidate.get("seed_order") if isinstance(candidate.get("seed_order"), dict) else {}
    higher_id = str(seed_order.get("higher", "") or "").strip()
    lower_id = str(seed_order.get("lower", "") or "").strip()
    if higher_id not in rows_by_id or lower_id not in rows_by_id:
        raise ValueError(f"Candidate {candidate.get('pair_key', '')}: missing row for Read C")
    genre = str(metadata.get("assignment_genre") or metadata.get("genre") or "")
    selection_details = (
        committee_anchor_selection_details(
            committee_anchor,
            source_calibration=source_calibration,
            genre=genre,
            grade_level=metadata_grade_level(metadata),
        )
        + placement_context_lines(candidate, read_a, read_b, ab_reason, rows_by_id)
    )
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
        genre=genre,
        metadata=metadata,
        selection_reasons=["committee_edge_read_c_placement_calibration"],
        selection_details=selection_details,
        anchor_dir=anchor_dir,
        orientation_audit=False,
        student_count=len(rows_by_id),
        response_format=COMMITTEE_RESPONSE_FORMAT,
    )
    read = normalize_committee_read(candidate, judgment)
    metadata_out = dict(read.get("model_metadata") or {})
    metadata_out["committee_read"] = "C-placement-calibration"
    metadata_out["adjudication_source"] = "committee_read_c"
    read["model_metadata"] = metadata_out
    return read


def read_c_from_fixture(candidate: dict, fixture_by_key: dict[str, dict]) -> dict | None:
    key = str(candidate.get("pair_key") or "").strip()
    if key not in fixture_by_key:
        return None
    read = normalize_committee_read(candidate, fixture_by_key[key])
    metadata = dict(read.get("model_metadata") or {})
    metadata["committee_read"] = "C-placement-calibration"
    metadata["adjudication_source"] = "committee_read_c"
    read["model_metadata"] = metadata
    return read


def resolve_a_b(candidate: dict, read_a: dict, read_b: dict) -> tuple[dict | None, str]:
    """Apply the Phase 3a A+B resolution rule.

    Returns (decision_read_or_None, reason). When the first element is not
    None it is the committee read (A or B) that should be emitted as the
    override edge. When None, no edge is emitted.

    Rules:
      - B blocks first: if B's decision_checks flag mechanics_block_meaning or
        completion_floor_applied, no override is emitted.
      - A and B agree on the loser → emit B override (high conf unconditional;
        medium conf only when polish_trap or rougher_but_stronger_latent is set).
        Low conf never emits even on agreement: A+B must stand on confidence.
      - A and B agree on the prior → concurrence, no edge.
      - A picked loser, B reverted to prior → split; no edge.
      - A picked prior, B picked loser → B overturns A:
          * emit B override only when B confidence is high AND B flagged
            polish_trap or rougher_but_stronger_latent.
          * Otherwise split (no trap / weak B), no edge.
    """
    prior_winner = str((candidate.get("escalated_summary") or {}).get("winner") or "").strip()
    a_winner = str(read_a.get("winner") or "").strip()
    b_winner = str(read_b.get("winner") or "").strip()
    a_checks = normalize_committee_decision_checks(
        read_a.get("decision_checks") if isinstance(read_a.get("decision_checks"), dict) else {}
    )
    b_checks = normalize_committee_decision_checks(
        read_b.get("decision_checks") if isinstance(read_b.get("decision_checks"), dict) else {}
    )
    b_conf = vc.normalize_confidence(read_b.get("confidence"))

    if b_checks.get("mechanics_block_meaning") or b_checks.get("completion_floor_applied"):
        return None, "committee_read_b_blocked_by_mechanics_or_completion"

    b_guard_read, b_guard_reason = evidence_ledger_guard_decision(candidate, read_b, read_label="B")
    if b_guard_read is not None:
        return b_guard_read, b_guard_reason
    b_source_guard_read, b_source_guard_reason = source_calibration_guard_decision(candidate, read_b, read_label="B")
    if b_source_guard_read is not None:
        return b_source_guard_read, b_source_guard_reason
    b_map_guard_read, b_map_guard_reason = evidence_map_guard_decision(candidate, read_b, read_label="B")
    if b_map_guard_read is not None:
        return b_map_guard_read, b_map_guard_reason
    if b_map_guard_reason == "evidence_map_guard_blocks_override":
        return None, b_map_guard_reason

    b_trap = bool(b_checks.get("polish_trap") or b_checks.get("rougher_but_stronger_latent"))

    a_picked_loser = bool(a_winner) and bool(prior_winner) and a_winner != prior_winner
    b_picked_loser = bool(b_winner) and bool(prior_winner) and b_winner != prior_winner

    if (
        a_picked_loser
        and b_picked_loser
        and a_winner == b_winner
        and (a_checks.get("mechanics_block_meaning") or a_checks.get("completion_floor_applied"))
    ):
        return None, "committee_read_ab_blocked_by_a_mechanics_or_completion"

    if a_picked_loser and b_picked_loser and a_winner == b_winner:
        if b_conf == "high":
            return read_b, "committee_read_ab_agree_override"
        if b_conf == "medium" and b_trap:
            return read_b, "committee_read_ab_agree_override"
        return None, "committee_read_ab_weak_agreement"

    if not a_picked_loser and not b_picked_loser:
        return None, "committee_read_ab_concurred"

    if a_picked_loser and not b_picked_loser:
        # A wanted to override, B reverts to the prior winner → no edge.
        return None, "committee_read_ab_split_b_confirms_prior"

    # A picked prior, B overturns to loser.
    if b_conf == "high" and b_trap:
        return read_b, "committee_read_b_override"
    return None, "committee_read_ab_split_no_trap"


def resolve_a_b_c(
    candidate: dict,
    read_a: dict,
    read_b: dict,
    read_c: dict,
    ab_reason: str,
) -> tuple[dict | None, str]:
    """Apply the Phase 3b placement-calibration rule.

    Read C is allowed to overturn an unresolved A/B result only when it is a
    high-confidence placement judgment, does not block its own winner on
    mechanics/completion, and gives a substantive reason for moving the edge.
    """
    prior_winner = str((candidate.get("escalated_summary") or {}).get("winner") or "").strip()
    c_winner = str(read_c.get("winner") or "").strip()
    if not prior_winner or not c_winner:
        return None, "committee_read_c_incomplete"
    if c_winner == prior_winner:
        return None, "committee_read_c_confirms_prior"
    c_conf = vc.normalize_confidence(read_c.get("confidence"))
    if c_conf != "high":
        return None, "committee_read_c_not_high_confidence"
    c_checks = normalize_committee_decision_checks(
        read_c.get("decision_checks") if isinstance(read_c.get("decision_checks"), dict) else {}
    )
    if c_checks.get("mechanics_block_meaning") or c_checks.get("completion_floor_applied"):
        return None, "committee_read_c_blocked_by_mechanics_or_completion"
    c_guard_read, c_guard_reason = evidence_ledger_guard_decision(candidate, read_c, read_label="C")
    if c_guard_read is not None:
        return c_guard_read, c_guard_reason
    c_source_guard_read, c_source_guard_reason = source_calibration_guard_decision(candidate, read_c, read_label="C")
    if c_source_guard_read is not None:
        return c_source_guard_read, c_source_guard_reason
    c_map_guard_read, c_map_guard_reason = evidence_map_guard_decision(candidate, read_c, read_label="C")
    if c_map_guard_read is not None:
        return c_map_guard_read, c_map_guard_reason
    if c_map_guard_reason == "evidence_map_guard_blocks_override":
        return None, c_map_guard_reason
    for prior_read in (read_a, read_b):
        if str(prior_read.get("winner") or "").strip() != c_winner:
            continue
        prior_checks = normalize_committee_decision_checks(
            prior_read.get("decision_checks") if isinstance(prior_read.get("decision_checks"), dict) else {}
        )
        if prior_checks.get("mechanics_block_meaning") or prior_checks.get("completion_floor_applied"):
            return None, "committee_read_c_blocked_by_prior_read_mechanics_or_completion"
    c_winner_side = normalize_winner_side(read_c.get("winner_side"))
    interpretation_favors_winner = side_favors_winner(c_checks.get("interpretation_depth"), c_winner_side)
    proof_favors_winner = side_favors_winner(c_checks.get("proof_sufficiency"), c_winner_side)
    has_substantive_basis = bool(
        c_checks.get("polish_trap")
        or c_checks.get("rougher_but_stronger_latent")
        or (interpretation_favors_winner and proof_favors_winner)
    )
    if not has_substantive_basis:
        return None, "committee_read_c_no_substantive_basis"
    return read_c, "committee_read_c_placement_override"


def decision_from_committee_read(
    candidate: dict,
    read: dict,
    reason: str,
    *,
    read_a: dict | None = None,
    read_b: dict | None = None,
    read_c: dict | None = None,
) -> dict:
    item = copy.deepcopy(read)
    metadata = item.get("model_metadata") if isinstance(item.get("model_metadata"), dict) else {}
    metadata = dict(metadata)
    # Determine which read produced the override (for metadata tagging).
    source_read_label = str(metadata.get("committee_read") or "A-blind")
    committee_read_label = source_read_label
    phase_label = "2b"
    confidence_label_prefix = "read_a"
    if read_c is not None and read is read_c:
        committee_read_label = "A+B+C"
        phase_label = "3b"
        confidence_label_prefix = "read_c"
    elif read_b is not None and read is read_b:
        committee_read_label = "A+B"
        phase_label = "3a"
        confidence_label_prefix = "read_b"
    elif read_a is not None and read_b is not None and read is read_a:
        # A's read chosen as the emit payload, but A+B both ran (should not
        # normally happen under resolve_a_b, which emits B's read; kept for
        # flexibility).
        committee_read_label = "A+B"
        phase_label = "3a"
        confidence_label_prefix = "read_a"
    metadata.update(
        {
            "adjudication_source": "committee_edge",
            "committee_read": committee_read_label,
            "committee_override_reason": reason,
            "supersedes_pair_key": candidate.get("pair_key", ""),
            "phase": phase_label,
        }
    )
    item["model_metadata"] = metadata
    item["adjudication_source"] = "committee_edge"
    item["committee_confidence"] = f"{confidence_label_prefix}_{vc.normalize_confidence(item.get('confidence'))}"
    trace = {
        "read": committee_read_label,
        "override_reason": reason,
        "triggers": list(candidate.get("triggers", [])),
        "committee_score": candidate.get("committee_score", 0),
        "prior_winner": (candidate.get("escalated_summary") or {}).get("winner", ""),
    }
    if isinstance(item.get("evidence_ledger_guard"), dict):
        trace["evidence_ledger_guard"] = item["evidence_ledger_guard"]
    if isinstance(item.get("source_calibration_guard"), dict):
        trace["source_calibration_guard"] = item["source_calibration_guard"]
    if isinstance(item.get("evidence_map_guard"), dict):
        trace["evidence_map_guard"] = item["evidence_map_guard"]
    if read_a is not None:
        a_checks = normalize_committee_decision_checks(
            read_a.get("decision_checks") if isinstance(read_a.get("decision_checks"), dict) else {}
        )
        trace["read_a"] = {
            "winner": read_a.get("winner", ""),
            "confidence": vc.normalize_confidence(read_a.get("confidence")),
            "polish_trap": bool(a_checks.get("polish_trap")),
            "rougher_but_stronger_latent": bool(a_checks.get("rougher_but_stronger_latent")),
        }
    if read_b is not None:
        b_checks = normalize_committee_decision_checks(
            read_b.get("decision_checks") if isinstance(read_b.get("decision_checks"), dict) else {}
        )
        trace["read_b"] = {
            "winner": read_b.get("winner", ""),
            "confidence": vc.normalize_confidence(read_b.get("confidence")),
            "polish_trap": bool(b_checks.get("polish_trap")),
            "rougher_but_stronger_latent": bool(b_checks.get("rougher_but_stronger_latent")),
        }
    if read_c is not None:
        c_checks = normalize_committee_decision_checks(
            read_c.get("decision_checks") if isinstance(read_c.get("decision_checks"), dict) else {}
        )
        trace["read_c"] = {
            "winner": read_c.get("winner", ""),
            "confidence": vc.normalize_confidence(read_c.get("confidence")),
            "polish_trap": bool(c_checks.get("polish_trap")),
            "rougher_but_stronger_latent": bool(c_checks.get("rougher_but_stronger_latent")),
            "interpretation_depth": c_checks.get("interpretation_depth", ""),
            "proof_sufficiency": c_checks.get("proof_sufficiency", ""),
        }
    item["committee_edge_trace"] = trace
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
    max_read_b: int | None,
    max_read_c: int | None,
    live: bool,
    live_read_b: bool,
    live_read_c: bool,
    fixture_by_key: dict[str, dict],
    read_b_fixture: dict[str, dict] | None = None,
    read_c_fixture: dict[str, dict] | None = None,
    source_calibration: Path | dict | None = None,
) -> tuple[list[dict], list[dict], dict]:
    """Run the committee read path.

    Phase 2b shipped this as single-read (A-only). Phase 3a extends it to
    multi-read with an optional polish-trap auditor (Read B). Selection of
    read order now uses `committee_read_priority` so residual-shaped pairs
    are read first regardless of the upstream bucket ordering.

    Behavior:
      - Always sorts `selected` by `committee_read_priority` before reading.
      - Runs Read A via `fixture_by_key` (if present) or via the live judge
        when `live=True`. If neither produces a read, records `not_read`.
      - If `should_invoke_read_b` fires, runs Read B from fixture when provided
        or live when `live=True` and `live_read_b=True`; then applies
        `resolve_a_b` to decide whether to emit an override.
      - If A/B remains unresolved on a high-leverage placement edge, runs
        Read C from fixture or live when enabled and applies
        `resolve_a_b_c`.
      - Otherwise falls back to Phase 2b A-only override gate.
    """
    rows_by_id = {row["student_id"]: row for row in vc.prepare_rows(rows)}
    read_results: list[dict] = []
    decisions: list[dict] = []
    read_cap = max(0, int(max_reads))
    read_b_cap = read_cap if max_read_b is None else max(0, int(max_read_b))
    read_c_cap = read_cap if max_read_c is None else max(0, int(max_read_c))
    read_a_attempt_count = 0
    read_a_count = 0
    read_b_count = 0
    read_c_count = 0
    read_b_skipped_cap = 0
    read_c_skipped_cap = 0
    b_fixture = read_b_fixture or {}
    c_fixture = read_c_fixture or {}
    # Phase 3a: read order is set by per-read priority, not the selection order.
    ordered_selected = sorted(selected, key=committee_read_priority)
    for candidate in ordered_selected:
        read_tier = committee_read_priority(candidate)[0]
        record = {
            "pair_key": candidate.get("pair_key", ""),
            "bucket": candidate.get("bucket", ""),
            "committee_score": candidate.get("committee_score", 0),
            "read_priority_tier": read_tier,
            "status": "",
            "override_emitted": False,
            "read_b_invoked": False,
            "read_c_invoked": False,
        }
        if read_cap and read_a_attempt_count >= read_cap:
            record["status"] = "max_reads_exceeded"
            read_results.append(record)
            continue
        read = read_from_fixture(candidate, fixture_by_key)
        if read is not None:
            read_a_attempt_count += 1
        elif live:
            read_a_attempt_count += 1
            progress(
                f"Read A {read_a_attempt_count}/{read_cap or len(ordered_selected)} pair={candidate.get('pair_key', '')}",
                enabled=True,
            )
            try:
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
                    source_calibration=source_calibration,
                )
            except Exception as exc:
                record["status"] = "read_a_error"
                record["error"] = str(exc)
                progress(
                    f"Read A error pair={candidate.get('pair_key', '')}: {str(exc)[:240]}",
                    enabled=True,
                )
                read_results.append(record)
                continue
            progress(
                f"Read A complete pair={candidate.get('pair_key', '')} winner={read.get('winner', '')} confidence={read.get('confidence', '')}",
                enabled=True,
            )
        if read is None:
            record["status"] = "not_read"
            read_results.append(record)
            continue
        read_a_count += 1
        should_override_a, reason_a = read_a_override_decision(candidate, read)
        record.update(
            {
                "read": read,
                "read_winner": read.get("winner", ""),
                "prior_winner": (candidate.get("escalated_summary") or {}).get("winner", ""),
                "read_a_override_candidate": bool(should_override_a),
                "read_a_override_reason": reason_a,
            }
        )
        ledger_guard_read, ledger_guard_reason = evidence_ledger_guard_decision(candidate, read, read_label="A")
        record["evidence_ledger_guard_reason"] = ledger_guard_reason
        record["evidence_ledger_guard_emitted"] = bool(ledger_guard_read)
        if ledger_guard_read is not None:
            record["status"] = ledger_guard_reason
            record["override_emitted"] = True
            record["ledger_guard_read"] = ledger_guard_read
            decisions.append(
                decision_from_committee_read(
                    candidate,
                    ledger_guard_read,
                    ledger_guard_reason,
                    read_a=read,
                )
            )
            read_results.append(record)
            continue

        source_guard_read, source_guard_reason = source_calibration_guard_decision(candidate, read, read_label="A")
        record["source_calibration_guard_reason"] = source_guard_reason
        record["source_calibration_guard_emitted"] = bool(source_guard_read)
        if source_guard_read is not None:
            record["status"] = source_guard_reason
            record["override_emitted"] = True
            record["source_calibration_guard_read"] = source_guard_read
            decisions.append(
                decision_from_committee_read(
                    candidate,
                    source_guard_read,
                    source_guard_reason,
                    read_a=read,
                )
            )
            read_results.append(record)
            continue

        evidence_map_guard_read, evidence_map_guard_reason = evidence_map_guard_decision(candidate, read, read_label="A")
        record["evidence_map_guard_reason"] = evidence_map_guard_reason
        record["evidence_map_guard_emitted"] = bool(evidence_map_guard_read)
        record["evidence_map_guard_blocked_override"] = evidence_map_guard_reason == "evidence_map_guard_blocks_override"
        if evidence_map_guard_read is not None:
            record["status"] = evidence_map_guard_reason
            record["override_emitted"] = True
            record["evidence_map_guard_read"] = evidence_map_guard_read
            decisions.append(
                decision_from_committee_read(
                    candidate,
                    evidence_map_guard_read,
                    evidence_map_guard_reason,
                    read_a=read,
                )
            )
            read_results.append(record)
            continue
        if evidence_map_guard_reason == "evidence_map_guard_blocks_override":
            record["status"] = evidence_map_guard_reason
            record["override_emitted"] = False
            read_results.append(record)
            continue

        # Decide whether Read B should audit this pair.
        should_run_b, b_invocation_reason = should_invoke_read_b(candidate, read)
        record["read_b_invocation_reason"] = b_invocation_reason
        read_b = None
        if should_run_b and b_fixture:
            read_b = read_b_from_fixture(candidate, b_fixture)
            if read_b is None:
                record["read_b_status"] = "fixture_missing"
        elif should_run_b and live and live_read_b:
            if read_b_cap and read_b_count >= read_b_cap:
                read_b_skipped_cap += 1
                record["read_b_status"] = "max_read_b_exceeded"
            else:
                progress(
                    f"Read B {read_b_count + 1}/{read_b_cap or read_cap or len(ordered_selected)} pair={candidate.get('pair_key', '')} reason={b_invocation_reason}",
                    enabled=True,
                )
                try:
                    read_b = run_blind_read_b(
                        candidate,
                        read,
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
                        source_calibration=source_calibration,
                    )
                    progress(
                        f"Read B complete pair={candidate.get('pair_key', '')} winner={read_b.get('winner', '')} confidence={read_b.get('confidence', '')}",
                        enabled=True,
                    )
                except Exception as exc:
                    record["read_b_status"] = "read_b_error"
                    record["read_b_error"] = str(exc)
                    progress(
                        f"Read B error pair={candidate.get('pair_key', '')}: {str(exc)[:240]}",
                        enabled=True,
                    )
        elif should_run_b:
            record["read_b_status"] = "not_available"

        if read_b is not None:
            read_b_count += 1
            record["read_b_invoked"] = True
            record["read_b"] = read_b
            record["read_b_winner"] = read_b.get("winner", "")
            decision_read, ab_reason = resolve_a_b(candidate, read, read_b)
            record["status"] = ab_reason
            if "evidence_map_guard" in ab_reason:
                record["evidence_map_guard_reason"] = ab_reason
                record["evidence_map_guard_emitted"] = decision_read is not None
                record["evidence_map_guard_blocked_override"] = ab_reason == "evidence_map_guard_blocks_override"

            read_c = None
            should_run_c, c_invocation_reason = should_invoke_read_c(candidate, read, read_b, ab_reason)
            record["read_c_invocation_reason"] = c_invocation_reason
            if decision_read is None and should_run_c and c_fixture:
                read_c = read_c_from_fixture(candidate, c_fixture)
                if read_c is None:
                    record["read_c_status"] = "fixture_missing"
            elif decision_read is None and should_run_c and live and live_read_c:
                if read_c_cap and read_c_count >= read_c_cap:
                    read_c_skipped_cap += 1
                    record["read_c_status"] = "max_read_c_exceeded"
                else:
                    progress(
                        f"Read C {read_c_count + 1}/{read_c_cap or read_cap or len(ordered_selected)} pair={candidate.get('pair_key', '')} reason={c_invocation_reason}",
                        enabled=True,
                    )
                    try:
                        read_c = run_placement_read_c(
                            candidate,
                            read,
                            read_b,
                            ab_reason,
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
                            source_calibration=source_calibration,
                        )
                        progress(
                            f"Read C complete pair={candidate.get('pair_key', '')} winner={read_c.get('winner', '')} confidence={read_c.get('confidence', '')}",
                            enabled=True,
                        )
                    except Exception as exc:
                        record["read_c_status"] = "read_c_error"
                        record["read_c_error"] = str(exc)
                        progress(
                            f"Read C error pair={candidate.get('pair_key', '')}: {str(exc)[:240]}",
                            enabled=True,
                        )
            elif decision_read is None and should_run_c:
                record["read_c_status"] = "not_available"

            if read_c is not None:
                read_c_count += 1
                record["read_c_invoked"] = True
                record["read_c"] = read_c
                record["read_c_winner"] = read_c.get("winner", "")
                c_decision_read, c_reason = resolve_a_b_c(candidate, read, read_b, read_c, ab_reason)
                record["status"] = c_reason
                if "evidence_map_guard" in c_reason:
                    record["evidence_map_guard_reason"] = c_reason
                    record["evidence_map_guard_emitted"] = c_decision_read is not None
                    record["evidence_map_guard_blocked_override"] = c_reason == "evidence_map_guard_blocks_override"
                decision_read = c_decision_read
                ab_reason = c_reason

            record["override_emitted"] = decision_read is not None
            if decision_read is not None:
                decisions.append(
                    decision_from_committee_read(
                        candidate,
                        decision_read,
                        ab_reason,
                        read_a=read,
                        read_b=read_b,
                        read_c=read_c,
                    )
                )
            read_results.append(record)
            continue

        # Read B was not invoked (condition did not fire, or no fixture entry
        # available): fall back to Phase 2b A-only override gate.
        record["status"] = reason_a
        record["override_emitted"] = bool(should_override_a)
        if should_override_a:
            decisions.append(decision_from_committee_read(candidate, read, reason_a))
        read_results.append(record)
    return decisions, read_results, {
        "enabled": bool(live or fixture_by_key or b_fixture or c_fixture),
        "live": bool(live),
        "fixture": bool(fixture_by_key),
        "read_b_fixture": bool(b_fixture),
        "read_c_fixture": bool(c_fixture),
        "read_b_live": bool(live and live_read_b),
        "read_c_live": bool(live and live_read_c),
        "max_reads": read_cap,
        "max_read_b": read_b_cap,
        "max_read_c": read_c_cap,
        "read_attempt_count": read_a_attempt_count,
        "read_count": read_a_count,
        "read_b_count": read_b_count,
        "read_c_count": read_c_count,
        "override_count": len(decisions),
        "skipped_max_reads": sum(1 for item in read_results if item.get("status") == "max_reads_exceeded"),
        "skipped_max_read_b": read_b_skipped_cap,
        "skipped_max_read_c": read_c_skipped_cap,
        "read_a_error_count": sum(1 for item in read_results if item.get("status") == "read_a_error"),
        "read_b_error_count": sum(1 for item in read_results if item.get("read_b_status") == "read_b_error"),
        "read_c_error_count": sum(1 for item in read_results if item.get("read_c_status") == "read_c_error"),
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


COMMITTEE_CYCLE_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def committee_decision_edge(decision: dict) -> tuple[str, str] | None:
    winner = str(decision.get("winner") or "").strip()
    pair = decision.get("pair") if isinstance(decision.get("pair"), list) else []
    pair_ids = [str(student_id).strip() for student_id in pair if str(student_id).strip()]
    loser = str(decision.get("loser") or "").strip()
    if not loser and winner and winner in pair_ids and len(pair_ids) == 2:
        loser = pair_ids[1] if pair_ids[0] == winner else pair_ids[0]
    if not winner or not loser or winner == loser:
        return None
    return winner, loser


def committee_decision_strength(decision: dict) -> tuple[int, int, int, str]:
    confidence = COMMITTEE_CYCLE_CONFIDENCE_RANK.get(vc.normalize_confidence(decision.get("confidence")), -1)
    committee_confidence = str(decision.get("committee_confidence") or "").strip().lower()
    if committee_confidence.endswith("high"):
        committee_rank = 2
    elif committee_confidence.endswith("medium"):
        committee_rank = 1
    elif committee_confidence.endswith("low"):
        committee_rank = 0
    else:
        committee_rank = -1
    metadata = decision.get("model_metadata") if isinstance(decision.get("model_metadata"), dict) else {}
    trace = decision.get("committee_edge_trace") if isinstance(decision.get("committee_edge_trace"), dict) else {}
    read = str(metadata.get("committee_read") or trace.get("read") or "").strip()
    read_rank = {
        "group-neighborhood-calibration": 3,
        "C-placement-calibration": 2,
        "C-placement-calibration-guard": 2,
        "B-polish-trap-audit": 1,
        "A-blind": 0,
    }.get(read, 0)
    return confidence, committee_rank, read_rank, str(pair_key_from_item(decision) or decision.get("pair_key") or "")


def find_committee_override_cycle(decisions: list[dict]) -> list[dict]:
    graph: dict[str, list[tuple[str, dict]]] = {}
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        edge = committee_decision_edge(decision)
        if edge is None:
            continue
        winner, loser = edge
        graph.setdefault(winner, []).append((loser, decision))
    for winner in graph:
        graph[winner].sort(key=lambda item: str(pair_key_from_item(item[1]) or item[1].get("pair_key") or ""))

    visited: set[str] = set()

    def dfs(node: str, path_nodes: list[str], path_decisions: list[dict]) -> list[dict]:
        for loser, decision in graph.get(node, []):
            if loser in path_nodes:
                start = path_nodes.index(loser)
                return path_decisions[start:] + [decision]
            if loser in visited:
                continue
            cycle = dfs(loser, path_nodes + [loser], path_decisions + [decision])
            if cycle:
                return cycle
        visited.add(node)
        return []

    for node in sorted(graph):
        if node in visited:
            continue
        cycle = dfs(node, [node], [])
        if cycle:
            return cycle
    return []


def resolve_committee_override_cycles(decisions: list[dict]) -> tuple[list[dict], dict]:
    """Suppress the weakest emitted committee edge until overrides are acyclic."""

    remaining = [decision for decision in decisions if isinstance(decision, dict)]
    suppressed: list[dict] = []
    while True:
        cycle = find_committee_override_cycle(remaining)
        if not cycle:
            break
        weakest = min(
            cycle,
            key=lambda decision: (
                committee_decision_strength(decision),
                str(pair_key_from_item(decision) or decision.get("pair_key") or ""),
            ),
        )
        weakest_key = str(pair_key_from_item(weakest) or weakest.get("pair_key") or "")
        cycle_keys = [str(pair_key_from_item(decision) or decision.get("pair_key") or "") for decision in cycle]
        edge = committee_decision_edge(weakest) or ("", "")
        suppressed.append(
            {
                "pair_key": weakest_key,
                "winner": edge[0],
                "loser": edge[1],
                "confidence": vc.normalize_confidence(weakest.get("confidence")),
                "committee_confidence": str(weakest.get("committee_confidence") or ""),
                "cycle_pair_keys": cycle_keys,
                "reason": "committee_override_cycle",
            }
        )
        removed = False
        next_remaining: list[dict] = []
        for decision in remaining:
            if not removed and decision is weakest:
                removed = True
                continue
            next_remaining.append(decision)
        remaining = next_remaining
    return remaining, {
        "evaluated_count": len([decision for decision in decisions if isinstance(decision, dict)]),
        "cycles_detected": len(suppressed),
        "suppressed_count": len(suppressed),
        "suppressed": suppressed,
    }


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
        "source_calibration": str(args.source_calibration),
        "evidence_map": str(args.evidence_map),
        "evidence_group_packets": str(args.evidence_group_packets) if args.evidence_group_packets else "",
        "evidence_neighborhood_output": str(args.evidence_neighborhood_output),
        "evidence_group_packets_output": str(args.evidence_group_packets_output),
        "blind_read_fixture": str(args.blind_read_fixture) if args.blind_read_fixture else "",
        "read_b_fixture": str(args.read_b_fixture) if args.read_b_fixture else "",
        "read_c_fixture": str(args.read_c_fixture) if args.read_c_fixture else "",
        "group_calibration_fixture": str(args.group_calibration_fixture) if args.group_calibration_fixture else "",
        "live_trace": str(args.live_trace_output),
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
    parser.add_argument(
        "--read-b-fixture",
        type=Path,
        default=None,
        help=(
            "Optional offline Read-B (polish-trap auditor) fixture keyed by pair_key. "
            "Phase 3a multi-read: when provided, eligible candidates are audited by "
            "Read B and A+B resolution rules decide whether to emit an override."
        ),
    )
    parser.add_argument(
        "--read-c-fixture",
        type=Path,
        default=None,
        help=(
            "Optional offline Read-C placement-calibration fixture keyed by pair_key. "
            "Read C runs only for unresolved high-leverage A/B outcomes."
        ),
    )
    parser.add_argument(
        "--group-calibration-fixture",
        type=Path,
        default=None,
        help=(
            "Optional offline group-neighborhood calibration fixture. This runs after unresolved "
            "A/B/C reads and can emit committee_edge overrides from a high-confidence local order."
        ),
    )
    parser.add_argument("--live", action="store_true", help="Run live committee adjudication for selected candidates.")
    parser.add_argument("--max-reads", type=int, default=DEFAULT_MAX_READS, help="Maximum selected candidates to read in live/fixture mode.")
    parser.add_argument(
        "--max-read-b",
        type=int,
        default=None,
        help="Maximum live/fixture Read-B audits. Defaults to --max-reads; 0 means unlimited.",
    )
    parser.add_argument(
        "--no-live-read-b",
        action="store_true",
        help="Disable live Read-B audits even when --live is set; fixture Read-B still works.",
    )
    parser.add_argument(
        "--max-read-c",
        type=int,
        default=None,
        help="Maximum live/fixture Read-C placement audits. Defaults to --max-reads; 0 means unlimited.",
    )
    parser.add_argument(
        "--no-live-read-c",
        action="store_true",
        help="Disable live Read-C placement audits even when --live is set; fixture Read-C still works.",
    )
    parser.add_argument(
        "--max-group-calibrations",
        type=int,
        default=DEFAULT_MAX_GROUP_CALIBRATIONS,
        help="Maximum unresolved neighborhoods to calibrate after A/B/C reads.",
    )
    parser.add_argument(
        "--max-group-students",
        type=int,
        default=DEFAULT_MAX_GROUP_STUDENTS,
        help="Maximum students per group-neighborhood calibration.",
    )
    parser.add_argument(
        "--no-live-group-calibration",
        action="store_true",
        help="Disable live group-neighborhood calibration even when --live is set; fixture calibration still works.",
    )
    parser.add_argument("--rubric", type=Path, default=Path(DEFAULT_RUBRIC))
    parser.add_argument("--outline", type=Path, default=Path(DEFAULT_OUTLINE))
    parser.add_argument("--routing", type=Path, default=Path(DEFAULT_ROUTING))
    parser.add_argument("--committee-anchor", type=Path, default=Path(DEFAULT_COMMITTEE_ANCHOR))
    parser.add_argument(
        "--source-calibration",
        type=Path,
        default=Path(DEFAULT_SOURCE_CALIBRATION_PATH),
        help=(
            "Copyright-safe external source calibration manifest. Used only by routed "
            "committee reads; default broad pipeline remains model-free at this seam."
        ),
    )
    parser.add_argument(
        "--evidence-map",
        type=Path,
        default=Path(DEFAULT_EVIDENCE_MAP),
        help=(
            "Optional deterministic evidence-map artifact. When present, selected "
            "committee candidates include an offline claim/evidence/commentary signal; "
            "default behavior remains model-free and passthrough when no decisions exist."
        ),
    )
    parser.add_argument(
        "--evidence-group-packets",
        type=Path,
        default=None,
        help=(
            "Optional prebuilt evidence_group_calibration_packets.json. When omitted, "
            "the resolver uses the packet artifact it builds in this run."
        ),
    )
    parser.add_argument("--model", default="", help="Override literary committee model")
    parser.add_argument("--reasoning", default="", help="Override literary committee reasoning")
    parser.add_argument("--max-output-tokens", type=int, default=0, help="Override literary committee max output tokens")
    parser.add_argument("--candidates-output", type=Path, default=Path(DEFAULT_CANDIDATES_OUT))
    parser.add_argument("--decisions-output", type=Path, default=Path(DEFAULT_DECISIONS_OUT))
    parser.add_argument("--report-output", type=Path, default=Path(DEFAULT_REPORT_OUT))
    parser.add_argument("--merged-output", type=Path, default=Path(DEFAULT_MERGED_OUT))
    parser.add_argument("--evidence-neighborhood-output", type=Path, default=Path(DEFAULT_EVIDENCE_NEIGHBORHOOD_OUT))
    parser.add_argument("--evidence-group-packets-output", type=Path, default=Path(DEFAULT_EVIDENCE_GROUP_PACKETS_OUT))
    parser.add_argument("--max-evidence-packet-students", type=int, default=DEFAULT_MAX_PACKET_STUDENTS)
    parser.add_argument("--max-evidence-group-packets", type=int, default=DEFAULT_MAX_GROUP_PACKETS)
    parser.add_argument("--live-trace-output", type=Path, default=None)
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
    if args.live_trace_output is None:
        args.live_trace_output = args.decisions_output.with_name(Path(DEFAULT_LIVE_TRACE_OUT).name)
    if args.evidence_map == Path(DEFAULT_EVIDENCE_MAP) and args.escalated != Path(DEFAULT_ESCALATED):
        args.evidence_map = args.escalated.with_name("evidence_map.json")
    if (
        args.evidence_neighborhood_output == Path(DEFAULT_EVIDENCE_NEIGHBORHOOD_OUT)
        and args.escalated != Path(DEFAULT_ESCALATED)
    ):
        args.evidence_neighborhood_output = args.escalated.with_name("evidence_neighborhood_report.json")
    if (
        args.evidence_group_packets_output == Path(DEFAULT_EVIDENCE_GROUP_PACKETS_OUT)
        and args.escalated != Path(DEFAULT_ESCALATED)
    ):
        args.evidence_group_packets_output = args.escalated.with_name("evidence_group_calibration_packets.json")
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
        evidence_maps_by_id = load_evidence_maps(args.evidence_map)
        input_evidence_group_packets = load_evidence_group_packets(args.evidence_group_packets)
        manual_decisions = load_decisions(args.decisions)
        blind_read_fixture = load_blind_read_fixture(args.blind_read_fixture)
        read_b_fixture = load_blind_read_fixture(args.read_b_fixture)
        read_c_fixture = load_blind_read_fixture(args.read_c_fixture)
        group_calibration_fixture = load_group_calibration_fixture(args.group_calibration_fixture)
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
        evidence_maps_by_id=evidence_maps_by_id,
    )
    selected, skipped, budget = select_within_budget(candidates, config=config)
    merged_candidates = selected + skipped
    evidence_neighborhood_report = build_evidence_neighborhood_report(
        maps_by_id=evidence_maps_by_id,
        candidates=selected,
        rows=rows,
        generated_at=generated_at,
        source_paths={
            "evidence_map": str(args.evidence_map),
            "committee_candidates": str(args.candidates_output),
            "scores": str(args.scores),
        },
    )
    evidence_group_packets = build_evidence_group_calibration_packets(
        neighborhood_report=evidence_neighborhood_report,
        maps_by_id=evidence_maps_by_id,
        rows=rows,
        generated_at=generated_at,
        source_paths={
            "evidence_map": str(args.evidence_map),
            "evidence_neighborhood_report": str(args.evidence_neighborhood_output),
            "committee_candidates": str(args.candidates_output),
            "scores": str(args.scores),
        },
        max_packet_students=args.max_evidence_packet_students,
        max_packets=args.max_evidence_group_packets,
    )
    active_evidence_group_packets = input_evidence_group_packets or evidence_group_packets
    read_a_decisions = []
    read_a_results = []
    read_a_summary = {
        "enabled": False,
        "live": False,
        "fixture": False,
        "read_b_fixture": False,
        "read_c_fixture": False,
        "read_b_live": False,
        "read_c_live": False,
        "max_reads": int(args.max_reads),
        "max_read_b": int(args.max_read_b if args.max_read_b is not None else args.max_reads),
        "max_read_c": int(args.max_read_c if args.max_read_c is not None else args.max_reads),
        "read_attempt_count": 0,
        "read_count": 0,
        "read_b_count": 0,
        "read_c_count": 0,
        "override_count": 0,
        "skipped_max_reads": 0,
        "skipped_max_read_b": 0,
        "skipped_max_read_c": 0,
        "read_a_error_count": 0,
        "read_b_error_count": 0,
        "read_c_error_count": 0,
    }
    group_decisions: list[dict] = []
    group_results: list[dict] = []
    group_summary = {
        "enabled": False,
        "live": False,
        "fixture": False,
        "max_groups": int(args.max_group_calibrations),
        "max_students": int(args.max_group_students),
        "neighborhood_source": "",
        "packet_neighborhood_count": 0,
        "neighborhood_count": 0,
        "read_count": 0,
        "override_count": 0,
        "skipped_existing_decision_count": 0,
    }
    read_path_requested = bool(args.live or blind_read_fixture or read_b_fixture or read_c_fixture)
    group_path_requested = bool(args.live or group_calibration_fixture)
    if read_path_requested or group_path_requested:
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
            if read_path_requested:
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
                    source_calibration=args.source_calibration,
                    max_reads=args.max_reads,
                    max_read_b=args.max_read_b,
                    max_read_c=args.max_read_c,
                    live=bool(args.live),
                    live_read_b=not bool(args.no_live_read_b),
                    live_read_c=not bool(args.no_live_read_c),
                    fixture_by_key=blind_read_fixture,
                    read_b_fixture=read_b_fixture,
                    read_c_fixture=read_c_fixture,
                )
            if group_path_requested:
                existing_keys = {
                    pair_key_from_item(decision)
                    for decision in (manual_decisions + read_a_decisions)
                    if pair_key_from_item(decision)
                }
                group_decisions, group_results, group_summary = run_group_calibration_path(
                    selected=selected,
                    rows=rows,
                    read_results=read_a_results,
                    texts_by_id=texts_by_id,
                    rubric=rubric,
                    outline=outline,
                    metadata=class_metadata,
                    model=model,
                    routing=str(args.routing),
                    reasoning=str(reasoning),
                    max_output_tokens=max_output_tokens,
                    committee_anchor=args.committee_anchor,
                    source_calibration=args.source_calibration,
                    live=bool(args.live),
                    live_group=not bool(args.no_live_group_calibration),
                    fixtures=group_calibration_fixture,
                    max_groups=args.max_group_calibrations,
                    max_students=args.max_group_students,
                    existing_decision_keys=existing_keys,
                    evidence_group_packets=active_evidence_group_packets,
                )
        except Exception as exc:
            report = {
                "generated_at": generated_at,
                "phase": 2,
                "passthrough": True,
                "source_paths": source_paths,
                "error": str(exc),
                "read_a": read_a_summary,
                "group_calibration": group_summary,
            }
            write_json(args.report_output, report)
            write_json(
                args.live_trace_output,
                {
                    "generated_at": generated_at,
                    "phase": "3e",
                    "passthrough": True,
                    "source_paths": source_paths,
                    "enabled": bool(read_path_requested or group_path_requested),
                    "error": str(exc),
                    "read_a": read_a_summary,
                    "group_calibration": group_summary,
                    "ledger_guard": {"evaluated_count": 0, "override_count": 0, "statuses": {}},
                    "source_calibration_guard": {"evaluated_count": 0, "override_count": 0, "statuses": {}},
                    "evidence_map_guard": {"evaluated_count": 0, "override_count": 0, "blocked_override_count": 0, "statuses": {}},
                    "read_results": read_a_results,
                    "group_calibration_results": group_results,
                    "decision_pair_keys": [],
                },
            )
            return 1
    raw_decisions = manual_decisions + read_a_decisions + group_decisions
    decisions, cycle_resolution = resolve_committee_override_cycles(raw_decisions)
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
        "read_b": {
            "enabled": bool(read_a_summary.get("read_b_live") or read_a_summary.get("read_b_fixture")),
            "live": bool(read_a_summary.get("read_b_live")),
            "fixture": bool(read_a_summary.get("read_b_fixture")),
            "max_reads": int(read_a_summary.get("max_read_b", 0) or 0),
            "read_count": int(read_a_summary.get("read_b_count", 0) or 0),
            "skipped_max_reads": int(read_a_summary.get("skipped_max_read_b", 0) or 0),
        },
        "read_c": {
            "enabled": bool(read_a_summary.get("read_c_live") or read_a_summary.get("read_c_fixture")),
            "live": bool(read_a_summary.get("read_c_live")),
            "fixture": bool(read_a_summary.get("read_c_fixture")),
            "max_reads": int(read_a_summary.get("max_read_c", 0) or 0),
            "read_count": int(read_a_summary.get("read_c_count", 0) or 0),
            "skipped_max_reads": int(read_a_summary.get("skipped_max_read_c", 0) or 0),
        },
        "read_a_results": read_a_results,
        "group_calibration": group_summary,
        "group_calibration_results": group_results,
        "cycle_resolution": cycle_resolution,
    }
    ledger_guard_statuses = Counter(
        str(record.get("evidence_ledger_guard_reason") or "not_evaluated")
        for record in read_a_results
        if isinstance(record, dict)
    )
    source_guard_statuses = Counter(
        str(record.get("source_calibration_guard_reason") or "not_evaluated")
        for record in read_a_results
        if isinstance(record, dict)
    )
    evidence_map_guard_statuses = Counter(
        str(record.get("evidence_map_guard_reason") or "not_evaluated")
        for record in read_a_results
        if isinstance(record, dict)
    )
    live_trace_payload = {
        "generated_at": generated_at,
        "phase": "3e",
        "passthrough": passthrough,
        "source_paths": source_paths,
        "enabled": bool(read_a_summary.get("enabled") or group_summary.get("enabled")),
        "read_a": read_a_summary,
        "read_b": decisions_payload["read_b"],
        "read_c": decisions_payload["read_c"],
        "group_calibration": group_summary,
        "ledger_guard": {
            "evaluated_count": sum(1 for record in read_a_results if isinstance(record, dict) and "evidence_ledger_guard_reason" in record),
            "override_count": sum(1 for record in read_a_results if isinstance(record, dict) and record.get("evidence_ledger_guard_emitted")),
            "statuses": dict(sorted(ledger_guard_statuses.items())),
        },
        "source_calibration_guard": {
            "evaluated_count": sum(1 for record in read_a_results if isinstance(record, dict) and "source_calibration_guard_reason" in record),
            "override_count": sum(1 for record in read_a_results if isinstance(record, dict) and record.get("source_calibration_guard_emitted")),
            "statuses": dict(sorted(source_guard_statuses.items())),
        },
        "evidence_map_guard": {
            "evaluated_count": sum(1 for record in read_a_results if isinstance(record, dict) and "evidence_map_guard_reason" in record),
            "override_count": sum(1 for record in read_a_results if isinstance(record, dict) and record.get("evidence_map_guard_emitted")),
            "blocked_override_count": sum(1 for record in read_a_results if isinstance(record, dict) and record.get("evidence_map_guard_blocked_override")),
            "statuses": dict(sorted(evidence_map_guard_statuses.items())),
        },
        "read_results": read_a_results,
        "group_calibration_results": group_results,
        "decision_pair_keys": [decision.get("pair_key", "") for decision in normalized_decisions],
        "cycle_resolution": cycle_resolution,
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
        "read_b": decisions_payload["read_b"],
        "read_c": decisions_payload["read_c"],
        "ledger_guard": live_trace_payload["ledger_guard"],
        "source_calibration_guard": live_trace_payload["source_calibration_guard"],
        "evidence_map_guard": live_trace_payload["evidence_map_guard"],
        "group_calibration": group_summary,
        "cycle_resolution": cycle_resolution,
        "phase2_ready": True,
    }
    write_json(args.candidates_output, candidate_payload)
    write_json(args.decisions_output, decisions_payload)
    write_json(args.live_trace_output, live_trace_payload)
    write_json(args.report_output, report_payload)
    write_json(args.evidence_neighborhood_output, evidence_neighborhood_report)
    write_json(args.evidence_group_packets_output, evidence_group_packets)
    write_json(args.merged_output, merged_payload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
