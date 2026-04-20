#!/usr/bin/env python3
"""Deterministic claim/evidence/commentary maps for writing cohorts.

This is an offline seam. It does not grade by itself and it does not call a
model. The goal is to create a stable, text-derived evidence ledger that later
committee reads and guards can compare against model-authored rationales.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.draft_quality import analyze_draft_quality
    from scripts.literary_surface_features import compute_surface_features
except ImportError:  # pragma: no cover - Support running as a standalone script.
    from draft_quality import analyze_draft_quality  # type: ignore  # pragma: no cover
    from literary_surface_features import compute_surface_features  # type: ignore  # pragma: no cover


DEFAULT_TEXTS = "processing/normalized_text"
DEFAULT_CLASS_METADATA = "inputs/class_metadata.json"
DEFAULT_OUTPUT = "outputs/evidence_map.json"
DEFAULT_PAIR_SIGNALS_OUTPUT = "outputs/evidence_map_pair_signals.json"
DEFAULT_SCORES = "outputs/consensus_scores.csv"
DEFAULT_NEIGHBORHOOD_OUTPUT = "outputs/evidence_neighborhood_report.json"
MEDIUM_HIGH_CONFIDENCE = frozenset({"medium", "high"})

WORD_RE = re.compile(r"[A-Za-z0-9']+")
SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?")
PARAGRAPH_RE = re.compile(r"\n\s*\n+")
QUOTE_RE = re.compile(r"[\"“”]")

COMMENTARY_MARKERS = (
    "because",
    "this shows",
    "this suggests",
    "this reveals",
    "this proves",
    "this demonstrates",
    "which shows",
    "which suggests",
    "which means",
    "meaning that",
    "reveals that",
    "shows that",
    "suggests that",
    "demonstrates that",
    "illustrates that",
    "symbolizes",
    "represents",
    "teaches",
    "learns",
    "changes",
    "realizes",
    "matters",
    "important because",
    "as a result",
    "therefore",
    "would make",
    "may be",
    "i imagine",
    "i feel",
    "desire",
)
COMMENTARY_RE = re.compile(
    r"\b("
    + "|".join(re.escape(marker) for marker in COMMENTARY_MARKERS)
    + r")\b",
    re.IGNORECASE,
)
CLAIM_RE = re.compile(
    r"\b("
    r"theme|message|lesson|claim|argument|shows that|reveals that|proves that|"
    r"demonstrates that|because|important|matters|learns|changes|consequence|"
    r"accountability|trust|support|identity|self[- ]?worth|healing|trauma|"
    r"leadership|second chance|belonging|responsibility"
    r")\b",
    re.IGNORECASE,
)
PLOT_RE = re.compile(
    r"\b("
    r"then|after|before|when|next|later|early in|in chapter|at the start|"
    r"at the end|one day|first|second|third|finally|went|got|stole|ran|"
    r"joined|punched|called|said|told|gave|made|caught|happened"
    r")\b",
    re.IGNORECASE,
)
FORMULA_RE = re.compile(
    r"\b(first|second|third|another|also|finally|in conclusion|to conclude|overall)\b",
    re.IGNORECASE,
)

THEME_CONCEPTS = {
    "accountability": ("accountability", "responsibility", "take responsibility", "consequence", "choices"),
    "belonging": ("belong", "fit in", "alone", "team", "friends"),
    "change": ("change", "grow", "mature", "better person", "turn", "improve"),
    "confidence": ("confidence", "self worth", "self-worth", "ashamed", "proud"),
    "consequences": ("consequence", "punishment", "legal trouble", "suspended", "expelled"),
    "fear": ("fear", "afraid", "scared", "run from", "running from"),
    "healing": ("heal", "healing", "recover", "support", "love"),
    "identity": ("identity", "self worth", "self-worth", "name", "somebody", "known as"),
    "leadership": ("leader", "leadership", "leading"),
    "mentorship": ("mentor", "guidance", "second chance", "chance", "support"),
    "poverty": ("poor", "poverty", "money", "wealth", "neighborhood"),
    "resilience": ("resilience", "keep going", "try hardest", "through hard times"),
    "second_chances": ("second chance", "chance to change", "make it right", "opportunity"),
    "shame": ("shame", "ashamed", "embarrassed", "laughed"),
    "trauma": ("trauma", "traumatic", "gun", "gunshot", "shoot", "ptsd", "drunk"),
    "trust": ("trust", "rebuild", "safe", "rely", "bond"),
}
HIGH_VALUE_CONCEPTS = {
    "belonging",
    "confidence",
    "fear",
    "healing",
    "identity",
    "mentorship",
    "resilience",
    "second_chances",
    "shame",
    "trauma",
    "trust",
}
TEXT_MOMENT_PATTERNS = {
    "bullying_or_fight": r"\b(brandon|bully|bullied|chicken|fight|punch|cafeteria|suspended)\b",
    "coach_consequence": r"\b(coach|brody|extra laps|cab|taxi|punish|practice|uniform|jersey)\b",
    "family_or_mother": r"\b(mom|mother|medical school|nurse|family)\b",
    "father_gun_trauma": r"\b(father|dad|gun|gunshot|shoot|shot|drunk)\b",
    "mr_charles": r"\b(mr\.?\s*charles|store|sunflower|storage room)\b",
    "shoe_theft": r"\b(shoe|shoes|silver|stole|steal|stealing|shoplift|sports store)\b",
    "team_or_track": r"\b(track|team|defenders|race|running|runner|sprinter|lu)\b",
    "team_dinner_or_secret": r"\b(dinner|secret|newbie|newbies|bond|trust each other)\b",
    "world_records": r"\b(world record|guinness|records)\b",
}
TEXT_MOMENT_RE = {
    key: re.compile(pattern, re.IGNORECASE) for key, pattern in TEXT_MOMENT_PATTERNS.items()
}


@dataclass(frozen=True)
class EvidenceUnit:
    sentence_index: int
    paragraph_index: int
    text: str
    role: str
    text_moments: list[str]
    literary_concepts: list[str]
    commentary_markers: list[str]
    has_quote: bool
    is_claim: bool
    is_text_evidence: bool
    is_commentary: bool
    is_integrated_analysis: bool
    is_plot_summary: bool
    claim_link_strength: float

    def to_dict(self) -> dict:
        return asdict(self)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_optional_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def words(text: str) -> list[str]:
    return WORD_RE.findall(text or "")


def split_paragraphs(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    return [part.strip() for part in PARAGRAPH_RE.split(raw) if part.strip()] or [raw]


def split_sentences(text: str) -> list[str]:
    return [match.group(0).strip() for match in SENTENCE_RE.finditer(text or "") if match.group(0).strip()]


def _snippet(text: str, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    return compact if len(compact) <= limit else compact[: limit - 3].rstrip() + "..."


def extract_literary_concepts(sentence: str) -> list[str]:
    lowered = str(sentence or "").lower()
    found = []
    for concept, tokens in THEME_CONCEPTS.items():
        if any(re.search(r"(?<![A-Za-z0-9'])" + re.escape(token) + r"(?![A-Za-z0-9'])", lowered) for token in tokens):
            found.append(concept)
    return sorted(set(found))


def extract_text_moments(sentence: str) -> list[str]:
    found = [key for key, pattern in TEXT_MOMENT_RE.items() if pattern.search(sentence or "")]
    if QUOTE_RE.search(sentence or ""):
        found.append("quoted_or_paraphrased_text")
    return sorted(set(found))


def extract_commentary_markers(sentence: str) -> list[str]:
    markers = [match.group(0).lower() for match in COMMENTARY_RE.finditer(sentence or "")]
    return sorted(set(markers))


def classify_role(
    *,
    sentence: str,
    sentence_index: int,
    paragraph_index: int,
    text_moments: list[str],
    concepts: list[str],
    commentary_markers: list[str],
) -> tuple[str, bool, bool, bool, bool, bool, float]:
    stripped = str(sentence or "").strip()
    has_claim = bool(CLAIM_RE.search(stripped)) or (sentence_index <= 2 and bool(concepts))
    has_text_evidence = bool(text_moments)
    has_commentary = bool(commentary_markers) or (bool(concepts) and bool(text_moments) and "because" in stripped.lower())
    has_plot = bool(PLOT_RE.search(stripped)) or (has_text_evidence and not has_commentary)
    is_integrated = bool(has_text_evidence and has_commentary)
    is_plot_summary = bool(has_plot and has_text_evidence and not has_commentary)
    if is_integrated:
        role = "integrated_analysis"
    elif has_commentary:
        role = "commentary"
    elif has_text_evidence:
        role = "text_evidence"
    elif has_claim:
        role = "claim"
    else:
        role = "general"
    claim_link_strength = 0.0
    if has_claim:
        claim_link_strength += 0.45
    if concepts:
        claim_link_strength += min(0.35, 0.10 * len(concepts))
    if is_integrated:
        claim_link_strength += 0.35
    elif has_commentary:
        claim_link_strength += 0.20
    return (
        role,
        has_claim,
        has_text_evidence,
        has_commentary,
        is_integrated,
        is_plot_summary,
        round(min(1.0, claim_link_strength), 6),
    )


def extract_evidence_units(text: str) -> list[EvidenceUnit]:
    units: list[EvidenceUnit] = []
    sentence_index = 0
    for paragraph_index, paragraph in enumerate(split_paragraphs(text), start=1):
        for sentence in split_sentences(paragraph):
            sentence_index += 1
            text_moments = extract_text_moments(sentence)
            concepts = extract_literary_concepts(sentence)
            commentary_markers = extract_commentary_markers(sentence)
            (
                role,
                is_claim,
                is_text_evidence,
                is_commentary,
                is_integrated,
                is_plot_summary,
                claim_link_strength,
            ) = classify_role(
                sentence=sentence,
                sentence_index=sentence_index,
                paragraph_index=paragraph_index,
                text_moments=text_moments,
                concepts=concepts,
                commentary_markers=commentary_markers,
            )
            units.append(
                EvidenceUnit(
                    sentence_index=sentence_index,
                    paragraph_index=paragraph_index,
                    text=_snippet(sentence),
                    role=role,
                    text_moments=text_moments,
                    literary_concepts=concepts,
                    commentary_markers=commentary_markers,
                    has_quote=bool(QUOTE_RE.search(sentence)),
                    is_claim=is_claim,
                    is_text_evidence=is_text_evidence,
                    is_commentary=is_commentary,
                    is_integrated_analysis=is_integrated,
                    is_plot_summary=is_plot_summary,
                    claim_link_strength=claim_link_strength,
                )
            )
    return units


def _concept_repetition_penalty(concept_counter: Counter, concept_unit_count: int) -> float:
    if concept_unit_count <= 2 or not concept_counter:
        return 0.0
    most_common = concept_counter.most_common(1)[0][1]
    dominance = most_common / max(1, concept_unit_count)
    if dominance <= 0.58:
        return 0.0
    return round((dominance - 0.58) * 4.0, 6)


def _focus_score(unit_count: int, claim_count: int, concept_counter: Counter, paragraph_count: int) -> float:
    if unit_count <= 0:
        return 0.0
    distinct = len(concept_counter)
    concept_units = sum(concept_counter.values())
    if concept_units == 0:
        return 0.0
    dominance = concept_counter.most_common(1)[0][1] / max(1, concept_units)
    balance = 1.0 - min(1.0, abs(dominance - 0.45))
    breadth = min(1.0, distinct / 4.0)
    structure = 1.0 if 2 <= paragraph_count <= 6 else 0.65
    claim_control = min(1.0, claim_count / 3.0)
    return round((balance * 0.35) + (breadth * 0.30) + (structure * 0.20) + (claim_control * 0.15), 6)


GENERIC_COMMENTARY_FRAME_RE = re.compile(
    r"\b(this (?:detail|shows?|suggests?|reveals?|proves?)|"
    r"this shows that|this suggests that|this proves that)\b",
    re.IGNORECASE,
)


def _generic_commentary_penalty(text: str) -> tuple[int, float]:
    count = len(GENERIC_COMMENTARY_FRAME_RE.findall(text or ""))
    if count <= 2:
        return count, 0.0
    return count, round(min(3.5, (count - 2) * 0.75), 6)


def _adjacent_explanation_count(units: list[EvidenceUnit]) -> int:
    count = 0
    previous: EvidenceUnit | None = None
    for unit in units:
        if (
            previous is not None
            and unit.paragraph_index == previous.paragraph_index
            and previous.is_text_evidence
            and not previous.is_commentary
            and unit.is_commentary
        ):
            count += 1
        previous = unit
    return count


def score_evidence_map(text: str, units: list[EvidenceUnit], *, genre: str = "") -> dict:
    surface = compute_surface_features(text)
    draft_quality = analyze_draft_quality(text)
    unit_dicts = [unit.to_dict() for unit in units]
    concept_counter = Counter(
        concept for unit in units for concept in unit.literary_concepts
    )
    moment_counter = Counter(moment for unit in units for moment in unit.text_moments)
    claim_count = sum(1 for unit in units if unit.is_claim)
    commentary_count = sum(1 for unit in units if unit.is_commentary)
    text_evidence_count = sum(1 for unit in units if unit.is_text_evidence)
    integrated_count = sum(1 for unit in units if unit.is_integrated_analysis)
    adjacent_explanation_count = _adjacent_explanation_count(units)
    explained_moment_count = integrated_count + adjacent_explanation_count
    plot_summary_count = sum(1 for unit in units if unit.is_plot_summary)
    quote_count = sum(1 for unit in units if unit.has_quote)
    quote_without_commentary_count = sum(1 for unit in units if unit.has_quote and not unit.is_commentary)
    high_value_concept_count = sum(count for concept, count in concept_counter.items() if concept in HIGH_VALUE_CONCEPTS)
    distinct_high_value_concept_count = sum(1 for concept in concept_counter if concept in HIGH_VALUE_CONCEPTS)
    thematic_commentary_count = sum(
        1
        for unit in units
        if (unit.is_claim or unit.is_commentary)
        and bool(set(unit.literary_concepts) & HIGH_VALUE_CONCEPTS)
    )
    thematic_depth_score = min(float(thematic_commentary_count), float(distinct_high_value_concept_count + 3))
    concept_integrated_count = sum(
        1
        for unit in units
        if unit.is_integrated_analysis and bool(set(unit.literary_concepts) & HIGH_VALUE_CONCEPTS)
    )
    concept_repetition_penalty = _concept_repetition_penalty(concept_counter, sum(concept_counter.values()))
    focus_score = _focus_score(len(units), claim_count, concept_counter, surface.paragraph_count)
    commentary_to_event_ratio = round(commentary_count / max(1, text_evidence_count), 6)
    explanation_density = round(explained_moment_count / max(1, len(units)), 6)
    word_count = surface.word_count
    length_penalty = 0.0
    if word_count < 120:
        length_penalty += 1.25
    if word_count > 700 and commentary_to_event_ratio < 0.45:
        length_penalty += 1.25
    if word_count > 900:
        length_penalty += 0.75
    formulaic_penalty = min(2.0, surface.formulaic_topic_sentence_count * 0.35)
    plot_penalty = min(6.0, plot_summary_count * 0.50)
    generic_commentary_frame_count, generic_commentary_penalty = _generic_commentary_penalty(text)
    thin_evidence_penalty = 0.0
    if text_evidence_count >= 8 and commentary_to_event_ratio < 0.35:
        thin_evidence_penalty = min(2.5, (0.35 - commentary_to_event_ratio) * 8.0)
    overclaim_penalty = max(0.0, (claim_count - 10) * 0.45)
    if claim_count > commentary_count + integrated_count + 4:
        overclaim_penalty += min(3.0, (claim_count - commentary_count - integrated_count - 4) * 0.25)
    unsupported_theme_penalty = max(
        0.0,
        thematic_depth_score - (commentary_count + integrated_count + adjacent_explanation_count),
    ) * 1.50
    rambling_evidence_penalty = 0.0
    if len(units) > 40 and plot_summary_count > 25:
        rambling_evidence_penalty = min(4.0, ((len(units) - 40) * 0.15) + ((plot_summary_count - 25) * 0.12))
    completion_penalty = 100.0 if draft_quality.get("hard_floor_incomplete") else 0.0
    score = (
        min(4, claim_count) * 0.55
        + min(8, commentary_count) * 0.85
        + min(8, text_evidence_count) * 0.30
        + min(6, integrated_count) * 1.25
        + min(5, adjacent_explanation_count) * 0.75
        + thematic_depth_score * 1.45
        + min(4, concept_integrated_count) * 0.60
        + min(8, len(moment_counter)) * 0.45
        + min(7, len(concept_counter)) * 0.65
        + min(5, distinct_high_value_concept_count) * 1.50
        + min(6, high_value_concept_count) * 0.18
        + focus_score * 2.10
        + explanation_density * 2.50
        + min(0.75, quote_count * 0.10)
        - plot_penalty
        - formulaic_penalty
        - generic_commentary_penalty
        - thin_evidence_penalty
        - overclaim_penalty
        - unsupported_theme_penalty
        - rambling_evidence_penalty
        - concept_repetition_penalty * 1.35
        - quote_without_commentary_count * 1.00
        - length_penalty
        - completion_penalty
    )
    score = round(score, 6)
    if completion_penalty:
        band_signal = "completion_floor"
    elif score >= 15:
        band_signal = "strong_substantive_analysis"
    elif score >= 11:
        band_signal = "solid_analysis"
    elif score >= 7:
        band_signal = "developing_analysis"
    elif score >= 3.5:
        band_signal = "thin_or_summary_heavy"
    else:
        band_signal = "minimal_or_incomplete"
    strongest_units = sorted(
        [
            unit
            for unit in unit_dicts
            if unit.get("is_integrated_analysis") or unit.get("claim_link_strength", 0.0) >= 0.7
        ],
        key=lambda item: (
            -float(item.get("claim_link_strength", 0.0) or 0.0),
            -len(item.get("text_moments") or []),
            int(item.get("sentence_index", 999999) or 999999),
        ),
    )[:5]
    return {
        "genre": genre,
        "word_count": word_count,
        "sentence_count": len(units),
        "paragraph_count": surface.paragraph_count,
        "claim_count": claim_count,
        "text_evidence_unit_count": text_evidence_count,
        "commentary_unit_count": commentary_count,
        "integrated_analysis_count": integrated_count,
        "adjacent_explanation_count": adjacent_explanation_count,
        "explained_moment_count": explained_moment_count,
        "plot_summary_unit_count": plot_summary_count,
        "quotation_count": quote_count,
        "quote_without_commentary_count": quote_without_commentary_count,
        "distinct_text_moment_count": len(moment_counter),
        "text_moments": dict(sorted(moment_counter.items())),
        "distinct_literary_concept_count": len(concept_counter),
        "literary_concepts": dict(sorted(concept_counter.items())),
        "high_value_concept_count": high_value_concept_count,
        "distinct_high_value_concept_count": distinct_high_value_concept_count,
        "thematic_commentary_count": thematic_commentary_count,
        "thematic_depth_score": thematic_depth_score,
        "concept_integrated_count": concept_integrated_count,
        "commentary_to_event_ratio": commentary_to_event_ratio,
        "explanation_density": explanation_density,
        "focus_score": focus_score,
        "concept_repetition_penalty": concept_repetition_penalty,
        "generic_commentary_frame_count": generic_commentary_frame_count,
        "generic_commentary_penalty": generic_commentary_penalty,
        "thin_evidence_penalty": round(thin_evidence_penalty, 6),
        "overclaim_penalty": round(overclaim_penalty, 6),
        "unsupported_theme_penalty": round(unsupported_theme_penalty, 6),
        "rambling_evidence_penalty": round(rambling_evidence_penalty, 6),
        "formulaic_topic_sentence_count": surface.formulaic_topic_sentence_count,
        "draft_quality": draft_quality,
        "completion_floor_applied": bool(draft_quality.get("hard_floor_incomplete")),
        "evidence_map_score": score,
        "band_signal": band_signal,
        "strongest_units": strongest_units,
    }


def build_student_evidence_map(student_id: str, text: str, *, genre: str = "") -> dict:
    units = extract_evidence_units(text)
    summary = score_evidence_map(text, units, genre=genre)
    return {
        "student_id": student_id,
        "summary": summary,
        "units": [unit.to_dict() for unit in units],
    }


def build_evidence_maps(texts_by_id: dict[str, str], *, genre: str = "") -> dict[str, dict]:
    return {
        student_id: build_student_evidence_map(student_id, text, genre=genre)
        for student_id, text in sorted(texts_by_id.items())
    }


def evidence_map_summary(map_item: dict) -> dict:
    summary = map_item.get("summary") if isinstance(map_item.get("summary"), dict) else {}
    keys = (
        "evidence_map_score",
        "band_signal",
        "word_count",
        "claim_count",
        "text_evidence_unit_count",
        "commentary_unit_count",
        "integrated_analysis_count",
        "adjacent_explanation_count",
        "explained_moment_count",
        "plot_summary_unit_count",
        "distinct_text_moment_count",
        "distinct_literary_concept_count",
        "high_value_concept_count",
        "distinct_high_value_concept_count",
        "thematic_commentary_count",
        "thematic_depth_score",
        "concept_integrated_count",
        "commentary_to_event_ratio",
        "explanation_density",
        "focus_score",
        "concept_repetition_penalty",
        "generic_commentary_frame_count",
        "generic_commentary_penalty",
        "thin_evidence_penalty",
        "overclaim_penalty",
        "unsupported_theme_penalty",
        "rambling_evidence_penalty",
        "formulaic_topic_sentence_count",
        "completion_floor_applied",
    )
    return {key: summary.get(key) for key in keys if key in summary}


def _reason_delta(label: str, left_value: float, right_value: float, left_id: str, right_id: str, threshold: float) -> list[str]:
    delta = round(left_value - right_value, 6)
    if abs(delta) < threshold:
        return []
    favored = left_id if delta > 0 else right_id
    return [f"{favored} higher {label} ({abs(delta):.2f})"]


def compare_evidence_maps(
    left_id: str,
    right_id: str,
    maps_by_id: dict[str, dict],
    *,
    margin_threshold: float = 0.75,
) -> dict:
    left = evidence_map_summary(maps_by_id.get(left_id, {}))
    right = evidence_map_summary(maps_by_id.get(right_id, {}))
    left_score = float(left.get("evidence_map_score") or 0.0)
    right_score = float(right.get("evidence_map_score") or 0.0)
    left_floor = bool(left.get("completion_floor_applied"))
    right_floor = bool(right.get("completion_floor_applied"))
    if left_floor and not right_floor:
        recommended = right_id
        margin = 100.0
    elif right_floor and not left_floor:
        recommended = left_id
        margin = 100.0
    else:
        margin = round(abs(left_score - right_score), 6)
        if margin < margin_threshold:
            recommended = "tie"
        else:
            recommended = left_id if left_score > right_score else right_id
    reasons: list[str] = []
    if left_floor or right_floor:
        reasons.append("completion floor detected")
    reasons.extend(
        _reason_delta(
            "integrated analysis",
            float(left.get("integrated_analysis_count") or 0.0),
            float(right.get("integrated_analysis_count") or 0.0),
            left_id,
            right_id,
            1.0,
        )
    )
    reasons.extend(
        _reason_delta(
            "commentary units",
            float(left.get("commentary_unit_count") or 0.0),
            float(right.get("commentary_unit_count") or 0.0),
            left_id,
            right_id,
            2.0,
        )
    )
    reasons.extend(
        _reason_delta(
            "literary concept breadth",
            float(left.get("distinct_literary_concept_count") or 0.0),
            float(right.get("distinct_literary_concept_count") or 0.0),
            left_id,
            right_id,
            2.0,
        )
    )
    reasons.extend(
        _reason_delta(
            "focus score",
            float(left.get("focus_score") or 0.0),
            float(right.get("focus_score") or 0.0),
            left_id,
            right_id,
            0.25,
        )
    )
    reasons.extend(
        _reason_delta(
            "plot-summary load",
            float(right.get("plot_summary_unit_count") or 0.0),
            float(left.get("plot_summary_unit_count") or 0.0),
            left_id,
            right_id,
            2.0,
        )
    )
    return {
        "pair": [left_id, right_id],
        "pair_key": "::".join(sorted((left_id, right_id))),
        "recommended_winner": recommended,
        "margin": margin,
        "scores": {left_id: left_score, right_id: right_score},
        "summaries": {left_id: left, right_id: right},
        "reasons": reasons[:6],
        "confidence": "high" if margin >= 2.0 or margin == 100.0 else "medium" if margin >= margin_threshold else "low",
    }


def read_texts(root: Path) -> dict[str, str]:
    texts = {}
    if not root.exists():
        return texts
    for path in sorted(root.glob("*.txt")):
        student_id = path.stem
        texts[student_id] = path.read_text(encoding="utf-8", errors="ignore")
    return texts


def candidate_pairs(payload: dict) -> list[tuple[str, str]]:
    pairs = []
    for section in ("candidates", "skipped"):
        raw_items = payload.get(section)
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            pair = item.get("pair")
            if isinstance(pair, list) and len(pair) == 2:
                left, right = str(pair[0]).strip(), str(pair[1]).strip()
                if left and right:
                    pairs.append((left, right))
    return sorted(set(pairs), key=lambda pair: "::".join(sorted(pair)))


def build_pair_signals(maps_by_id: dict[str, dict], pairs: list[tuple[str, str]]) -> list[dict]:
    signals = []
    for left, right in pairs:
        if left not in maps_by_id or right not in maps_by_id:
            continue
        signals.append(compare_evidence_maps(left, right, maps_by_id))
    return signals


def load_score_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def selected_candidate_items(payload: dict) -> list[dict]:
    raw_items = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
    return [item for item in raw_items if isinstance(item, dict)]


def student_rank_map(rows: list[dict]) -> dict[str, int]:
    ranks = {}
    for index, row in enumerate(rows, start=1):
        student_id = str(row.get("student_id") or "").strip()
        if not student_id:
            continue
        raw_rank = row.get("seed_rank") or row.get("consensus_rank") or row.get("final_rank") or index
        try:
            rank = int(float(raw_rank))
        except (TypeError, ValueError):
            rank = index
        ranks[student_id] = rank
    return ranks


def candidate_active_winner(candidate: dict) -> str:
    summary = candidate.get("escalated_summary") if isinstance(candidate.get("escalated_summary"), dict) else {}
    winner = str(summary.get("winner") or "").strip()
    if winner:
        return winner
    signal = candidate.get("evidence_map_pair_signal")
    if not isinstance(signal, dict):
        details = candidate.get("trigger_details") if isinstance(candidate.get("trigger_details"), dict) else {}
        signal = details.get("evidence_map_pair_signal")
    if isinstance(signal, dict):
        return str(signal.get("active_winner") or "").strip()
    return ""


def candidate_evidence_signal(candidate: dict, maps_by_id: dict[str, dict]) -> dict:
    signal = candidate.get("evidence_map_pair_signal")
    if not isinstance(signal, dict):
        details = candidate.get("trigger_details") if isinstance(candidate.get("trigger_details"), dict) else {}
        signal = details.get("evidence_map_pair_signal")
    if isinstance(signal, dict) and signal:
        return signal
    pair = candidate.get("pair") if isinstance(candidate.get("pair"), list) else []
    if len(pair) != 2:
        return {}
    left, right = str(pair[0]).strip(), str(pair[1]).strip()
    if left in maps_by_id and right in maps_by_id:
        signal = compare_evidence_maps(left, right, maps_by_id)
        active_winner = candidate_active_winner({**candidate, "evidence_map_pair_signal": signal})
        signal["active_winner"] = active_winner
        signal["contradicts_active_winner"] = bool(
            signal.get("recommended_winner") not in {"", "tie", active_winner}
        )
        return signal
    return {}


def evidence_edge_record(candidate: dict, maps_by_id: dict[str, dict]) -> dict | None:
    pair = candidate.get("pair") if isinstance(candidate.get("pair"), list) else []
    signal = candidate_evidence_signal(candidate, maps_by_id)
    signal_pair = signal.get("pair") if isinstance(signal.get("pair"), list) else []
    if len(pair) != 2 and len(signal_pair) == 2:
        pair = signal_pair
    if len(pair) != 2 or not signal:
        return None
    left, right = str(pair[0]).strip(), str(pair[1]).strip()
    if not left or not right:
        return None
    confidence = str(signal.get("confidence") or "").strip().lower()
    recommended = str(signal.get("recommended_winner") or "").strip()
    active_winner = str(signal.get("active_winner") or candidate_active_winner(candidate)).strip()
    contradictory = bool(recommended not in {"", "tie", active_winner})
    ambiguous = bool(recommended in {"", "tie"} or confidence not in MEDIUM_HIGH_CONFIDENCE)
    return {
        "pair": [left, right],
        "pair_key": "::".join(sorted((left, right))),
        "recommended_winner": recommended or "tie",
        "active_winner": active_winner,
        "confidence": confidence or "low",
        "margin": signal.get("margin", 0.0),
        "contradicts_active_winner": contradictory,
        "ambiguous": ambiguous,
        "scores": signal.get("scores", {}),
        "reasons": list(signal.get("reasons") or [])[:6],
    }


def focused_neighborhood_edges(edge_records: list[dict]) -> list[dict]:
    contradictions = [
        edge for edge in edge_records
        if edge.get("contradicts_active_winner")
        and not edge.get("ambiguous")
        and edge.get("confidence") in MEDIUM_HIGH_CONFIDENCE
    ]
    contradiction_nodes = {sid for edge in contradictions for sid in edge.get("pair", [])}
    focused = {edge["pair_key"]: edge for edge in contradictions}
    for edge in edge_records:
        if edge.get("pair_key") in focused:
            continue
        pair_nodes = set(edge.get("pair", []))
        if edge.get("ambiguous") and pair_nodes & contradiction_nodes:
            focused[edge["pair_key"]] = edge
    return sorted(focused.values(), key=lambda edge: edge["pair_key"])


def connected_components_from_edges(edges: list[dict]) -> list[list[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        pair = edge.get("pair") if isinstance(edge.get("pair"), list) else []
        if len(pair) != 2:
            continue
        left, right = str(pair[0]), str(pair[1])
        graph[left].add(right)
        graph[right].add(left)
    components = []
    seen: set[str] = set()
    for start in sorted(graph):
        if start in seen:
            continue
        queue = deque([start])
        seen.add(start)
        component = []
        while queue:
            node = queue.popleft()
            component.append(node)
            for neighbor in sorted(graph[node]):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        components.append(sorted(component))
    return components


def evidence_score_for(student_id: str, maps_by_id: dict[str, dict]) -> float:
    summary = evidence_map_summary(maps_by_id.get(student_id, {}))
    try:
        return float(summary.get("evidence_map_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def evidence_local_order(
    student_ids: list[str],
    edge_records: list[dict],
    maps_by_id: dict[str, dict],
    ranks: dict[str, int],
) -> list[str]:
    wins = Counter()
    losses = Counter()
    student_set = set(student_ids)
    for edge in edge_records:
        if edge.get("ambiguous") or edge.get("confidence") not in MEDIUM_HIGH_CONFIDENCE:
            continue
        winner = str(edge.get("recommended_winner") or "").strip()
        pair = [str(sid) for sid in edge.get("pair", [])]
        if winner not in student_set or len(pair) != 2:
            continue
        loser = pair[1] if pair[0] == winner else pair[0]
        if loser not in student_set:
            continue
        wins[winner] += 1
        losses[loser] += 1
    return sorted(
        student_ids,
        key=lambda sid: (
            -(wins[sid] - losses[sid]),
            -evidence_score_for(sid, maps_by_id),
            ranks.get(sid, 999999),
            sid,
        ),
    )


def has_evidence_cycle(student_ids: list[str], edge_records: list[dict]) -> bool:
    graph: dict[str, set[str]] = defaultdict(set)
    student_set = set(student_ids)
    for edge in edge_records:
        if edge.get("ambiguous") or edge.get("confidence") not in MEDIUM_HIGH_CONFIDENCE:
            continue
        winner = str(edge.get("recommended_winner") or "")
        pair = [str(sid) for sid in edge.get("pair", [])]
        if winner not in student_set or len(pair) != 2:
            continue
        loser = pair[1] if pair[0] == winner else pair[0]
        if loser in student_set:
            graph[winner].add(loser)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for neighbor in graph.get(node, set()):
            if visit(neighbor):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(student_id) for student_id in student_ids)


def classify_evidence_neighborhood(
    student_ids: list[str],
    component_edges: list[dict],
) -> tuple[str, str]:
    strong_edges = [
        edge for edge in component_edges
        if not edge.get("ambiguous") and edge.get("confidence") in MEDIUM_HIGH_CONFIDENCE
    ]
    contradictory_edges = [edge for edge in strong_edges if edge.get("contradicts_active_winner")]
    ambiguous_edges = [edge for edge in component_edges if edge.get("ambiguous")]
    if not strong_edges:
        return "insufficient_signal", "no medium/high evidence-map edges in component"
    if len(student_ids) == 2 and len(contradictory_edges) == 1 and not ambiguous_edges:
        return "pair_guard_only", "isolated strong evidence-map contradiction"
    if len(student_ids) >= 3:
        return "needs_group_calibration", "connected component has three or more students"
    if contradictory_edges and ambiguous_edges:
        return "needs_group_calibration", "component mixes strong contradiction with ambiguous internal edge"
    if has_evidence_cycle(student_ids, component_edges):
        return "needs_group_calibration", "directed evidence-map edges form a local cycle"
    return "insufficient_signal", "component has evidence but no actionable contradiction pattern"


def build_evidence_neighborhood_report(
    *,
    maps_by_id: dict[str, dict],
    candidates: list[dict],
    rows: list[dict],
    generated_at: str | None = None,
    source_paths: dict | None = None,
) -> dict:
    generated_at = generated_at or now_iso()
    source_paths = source_paths or {}
    if not maps_by_id:
        return {
            "generated_at": generated_at,
            "phase": "offline_evidence_neighborhood_v1",
            "enabled": False,
            "reason": "evidence_map_missing",
            "source_paths": source_paths,
            "counts": {
                "candidate_edges": len(candidates),
                "evidence_edges": 0,
                "contradicting_edges": 0,
                "ambiguous_edges": 0,
                "neighborhoods": 0,
            },
            "neighborhoods": [],
        }
    ranks = student_rank_map(rows)
    edge_records = [
        edge for edge in (evidence_edge_record(candidate, maps_by_id) for candidate in candidates)
        if edge is not None
    ]
    focused_edges = focused_neighborhood_edges(edge_records)
    components = connected_components_from_edges(focused_edges)
    neighborhoods = []
    for index, student_ids in enumerate(components, start=1):
        student_set = set(student_ids)
        component_edges = [
            edge for edge in edge_records
            if set(edge.get("pair", [])) <= student_set
            and (
                edge.get("pair_key") in {focused.get("pair_key") for focused in focused_edges}
                or (not edge.get("ambiguous") and edge.get("confidence") in MEDIUM_HIGH_CONFIDENCE)
            )
        ]
        component_edges = sorted(component_edges, key=lambda edge: edge["pair_key"])
        contradicting_edges = [
            edge for edge in component_edges
            if edge.get("contradicts_active_winner")
            and not edge.get("ambiguous")
            and edge.get("confidence") in MEDIUM_HIGH_CONFIDENCE
        ]
        ambiguous_edges = [edge for edge in component_edges if edge.get("ambiguous")]
        strong_edges = [
            edge for edge in component_edges
            if not edge.get("ambiguous") and edge.get("confidence") in MEDIUM_HIGH_CONFIDENCE
        ]
        action, reason = classify_evidence_neighborhood(student_ids, component_edges)
        seed_order = sorted(student_ids, key=lambda sid: (ranks.get(sid, 999999), sid))
        neighborhoods.append(
            {
                "neighborhood_id": f"evidence_neighborhood_{index}",
                "student_ids": seed_order,
                "seed_order": seed_order,
                "evidence_order": evidence_local_order(student_ids, component_edges, maps_by_id, ranks),
                "contradicting_edges": contradicting_edges,
                "ambiguous_edges": ambiguous_edges,
                "confidence_density": round(len(strong_edges) / max(1, len(strong_edges) + len(ambiguous_edges)), 6),
                "has_cycle": has_evidence_cycle(student_ids, component_edges),
                "recommended_next_action": action,
                "reason": reason,
            }
        )
    return {
        "generated_at": generated_at,
        "phase": "offline_evidence_neighborhood_v1",
        "enabled": True,
        "source_paths": source_paths,
        "counts": {
            "candidate_edges": len(candidates),
            "evidence_edges": len([edge for edge in edge_records if edge.get("confidence") in MEDIUM_HIGH_CONFIDENCE and not edge.get("ambiguous")]),
            "contradicting_edges": len([edge for edge in edge_records if edge.get("contradicts_active_winner") and not edge.get("ambiguous")]),
            "ambiguous_edges": len([edge for edge in edge_records if edge.get("ambiguous")]),
            "neighborhoods": len(neighborhoods),
        },
        "neighborhoods": neighborhoods,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build deterministic evidence maps for student writing.")
    parser.add_argument("--texts", type=Path, default=Path(DEFAULT_TEXTS))
    parser.add_argument("--class-metadata", type=Path, default=Path(DEFAULT_CLASS_METADATA))
    parser.add_argument("--output", type=Path, default=Path(DEFAULT_OUTPUT))
    parser.add_argument(
        "--candidates",
        type=Path,
        default=None,
        help="Optional committee_edge_candidates.json for pair-level evidence-map signals.",
    )
    parser.add_argument(
        "--pair-signals-output",
        type=Path,
        default=Path(DEFAULT_PAIR_SIGNALS_OUTPUT),
        help="Output path used when --candidates is provided.",
    )
    parser.add_argument("--scores", type=Path, default=Path(DEFAULT_SCORES))
    parser.add_argument(
        "--committee-candidates",
        type=Path,
        default=None,
        help="Optional committee_edge_candidates.json for offline evidence-neighborhood report.",
    )
    parser.add_argument(
        "--neighborhood-output",
        type=Path,
        default=Path(DEFAULT_NEIGHBORHOOD_OUTPUT),
        help="Output path used when --committee-candidates is provided.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    metadata = load_optional_json(args.class_metadata)
    genre = str(metadata.get("assignment_genre") or metadata.get("genre") or "").strip()
    texts_by_id = read_texts(args.texts)
    maps_by_id = build_evidence_maps(texts_by_id, genre=genre)
    generated_at = now_iso()
    payload = {
        "generated_at": generated_at,
        "phase": "offline_evidence_map_v1",
        "source_paths": {
            "texts": str(args.texts),
            "class_metadata": str(args.class_metadata),
        },
        "genre": genre,
        "student_count": len(maps_by_id),
        "students": maps_by_id,
    }
    write_json(args.output, payload)
    if args.candidates is not None:
        candidate_payload = load_optional_json(args.candidates)
        pairs = candidate_pairs(candidate_payload)
        signals = build_pair_signals(maps_by_id, pairs)
        write_json(
            args.pair_signals_output,
            {
                "generated_at": generated_at,
                "phase": "offline_evidence_map_pair_signals_v1",
                "source_paths": {
                    "evidence_map": str(args.output),
                    "candidates": str(args.candidates),
                },
                "pair_count": len(signals),
                "pair_signals": signals,
            },
        )
    if args.committee_candidates is not None:
        candidate_payload = load_optional_json(args.committee_candidates)
        rows = load_score_rows(args.scores)
        report = build_evidence_neighborhood_report(
            maps_by_id=maps_by_id,
            candidates=selected_candidate_items(candidate_payload),
            rows=rows,
            generated_at=generated_at,
            source_paths={
                "evidence_map": str(args.output),
                "committee_candidates": str(args.committee_candidates),
                "scores": str(args.scores),
            },
        )
        write_json(args.neighborhood_output, report)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
