#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.assessor_context import (
    build_grade_context, choose_preferred_genre, format_exemplars, genre_specificity, infer_genre_from_text, load_class_metadata, load_exemplars,
    load_grade_profiles, normalize_genre, resolve_exemplar_selection, select_grade_level,
)
from scripts.rubric_criteria import (
    contract_criteria_ids,
    contract_criteria_prompt,
    contract_prompt,
    criteria_ids,
    criteria_prompt,
    evidence_requirements,
    load_rubric_criteria,
)
from scripts.assessor_utils import extract_docx_text, load_file_text, normalize_ranking_ids, resolve_input_path, summarize_text
from scripts.rubric_contract import load_json as load_rubric_json, runtime_rubric_context
from scripts.draft_quality import analyze_draft_quality, apply_draft_penalty
from scripts.llm_assessors_core import (
    build_pass1_prompt, build_pass1_repair_prompt, build_pass2_prompt, ensure_dir, json_from_text, load_json, load_routing,
    load_texts, looks_like_prompt_echo, parse_pass1_item, pass1_text_format, preflight_costs,
)
from scripts.fallback_assessor import deterministic_pass1_item
from scripts.calibration_gate import calibration_gate_error
from scripts.calibration_contract import build_run_scope
from scripts.pass1_guard import stabilize_pass1_item
from scripts.pass1_reconcile import guard_parameters, reconcile_pass1_item, strip_internal_fields
from scripts.pass2_contract import build_pass2_repair_prompt, normalize_full_ranking, pass2_text_format
from scripts.portfolio_pieces import (
    aggregate_portfolio_piece_assessments,
    split_portfolio_pieces,
    summarize_portfolio_for_ranking,
    summarize_portfolio_pieces,
    write_report as write_portfolio_piece_report,
)
try:
    from scripts.openai_client import responses_create, extract_text, extract_usage
except ImportError:  # pragma: no cover - Support running as a script without package context
    from openai_client import responses_create, extract_text, extract_usage  # pragma: no cover
def reset_assessor_outputs(path: Path):
    for file in path.glob("assessor_*"):
        if file.is_file():
            file.unlink()
def write_text_atomic(path: Path, content: str):
    tmp = path.with_suffix(path.suffix + ".tmp"); tmp.write_text(content, encoding="utf-8"); tmp.replace(path)
def ranking_from_scores(scores: dict, known_ids: list) -> list:
    ranked = [(sid, float(scores.get(sid, 0.0) or 0.0)) for sid in known_ids]
    ranked.sort(key=lambda item: (-item[1], item[0].lower()))
    return [sid for sid, _ in ranked]


def is_portfolio_scope(metadata: dict, genre: str | None) -> bool:
    assessment_unit = str((metadata or {}).get("assessment_unit", "") or "").strip().lower()
    genre_form = str((metadata or {}).get("genre_form", "") or "").strip().lower()
    return str(genre or "").strip().lower() == "portfolio" or assessment_unit == "portfolio" or "portfolio" in genre_form


def build_portfolio_piece_prompt(
    role_name: str,
    rubric: str,
    outline: str,
    student_id: str,
    piece: dict,
    total_pieces: int,
    grade_context: str = "",
    exemplars: str = "",
    criteria_block: str = "",
    evidence_reqs: dict | None = None,
    notes_word_limit: int | None = None,
) -> str:
    piece_context = (
        "PORTFOLIO PIECE CONTEXT:\n"
        f"- This is piece {piece.get('piece_id')} of {total_pieces} from one student's writing portfolio.\n"
        f"- Piece title: {piece.get('title', 'Untitled piece')}\n"
        "- Score this piece on its own quality using the rubric and grade expectations.\n"
        "- Do not assign a whole-portfolio judgment from this piece alone.\n"
    )
    merged_grade_context = f"{grade_context}\n\n{piece_context}".strip() if grade_context else piece_context
    return build_pass1_prompt(
        role_name,
        rubric,
        outline,
        f"{student_id}::{piece.get('piece_id')}",
        str(piece.get("text", "") or ""),
        merged_grade_context,
        exemplars,
        criteria_block,
        evidence_reqs,
        notes_word_limit=notes_word_limit,
    )


def _prefers_compact_structured_output(model: str) -> bool:
    token = str(model or "").strip().lower()
    return token.startswith("gpt-5.4-mini") or token.startswith("gpt-5.4-nano")


def _structured_reasoning(model: str, configured: str) -> str:
    if _prefers_compact_structured_output(model):
        return "low"
    return str(configured or "medium")


def _pass1_notes_word_limit(model: str, *, piece_mode: bool) -> int | None:
    if not _prefers_compact_structured_output(model):
        return None
    return 10 if piece_mode else 18


def _response_incomplete_hint(response: dict | None) -> str:
    if not isinstance(response, dict):
        return ""
    if str(response.get("status") or "").strip().lower() != "incomplete":
        return ""
    details = response.get("incomplete_details")
    reason = str((details or {}).get("reason") or "").strip().lower() if isinstance(details, dict) else ""
    if reason == "max_output_tokens":
        return "Your previous response hit max_output_tokens before finishing. Retry with much shorter JSON."
    if reason:
        return f"Your previous response was incomplete ({reason}). Retry with much shorter JSON."
    return "Your previous response was incomplete. Retry with much shorter JSON."


def guard_bias_for_exemplar_scope(match_quality: str | None, score_delta: float, level_gap: int, anchor_blend: float) -> tuple[float, int, float]:
    quality = str(match_quality or "").strip().lower()
    if quality == "exact_scope":
        return float(score_delta), int(level_gap), float(anchor_blend)
    if quality in {"band_fallback", "genre_library", "genre_library_fallback"}:
        return max(float(score_delta), 8.0), max(int(level_gap), 2), min(float(anchor_blend), 0.12)
    if quality in {"cross_band", "root_library", "missing"}:
        return max(float(score_delta), 12.0), max(int(level_gap), 2), 0.0
    return float(score_delta), int(level_gap), float(anchor_blend)


def resolve_pass1_contract(criteria_cfg: dict, genre: str | None, routing_require_evidence: bool) -> dict:
    if not criteria_cfg:
        return {
            "criteria_block": "",
            "required_ids": [],
            "require_evidence": bool(routing_require_evidence),
            "reqs": {},
        }
    criteria_block = contract_criteria_prompt(criteria_cfg, genre)
    guidance_block = contract_prompt(criteria_cfg, genre)
    if guidance_block:
        criteria_block = f"{criteria_block}\n\n{guidance_block}".strip() if criteria_block else guidance_block
    required_ids = contract_criteria_ids(criteria_cfg, genre)
    reqs = evidence_requirements(criteria_cfg, genre)
    require_evidence = bool(routing_require_evidence or reqs.get("force_require_evidence", False))
    if reqs and require_evidence:
        reqs = dict(reqs)
        strict_evidence_contract = bool(reqs.get("preserve_validation", False) or reqs.get("hard_fail_on_evidence_errors", False))
        if not strict_evidence_contract:
            reqs["quote_validation"] = False
            reqs["rationale_min_words"] = 0
    else:
        reqs = {}
    return {
        "criteria_block": criteria_block,
        "required_ids": required_ids,
        "require_evidence": require_evidence,
        "reqs": reqs,
    }


def _truncate_compact(text: str, max_chars: int) -> str:
    compact = " ".join(str(text or "").split())
    if max_chars and len(compact) > max_chars:
        return compact[:max_chars].rstrip() + "..."
    return compact


def build_scope_grounding_context(scope_grounding: dict | None) -> str:
    payload = scope_grounding if isinstance(scope_grounding, dict) else {}
    if not payload.get("accepted", False):
        return ""
    prompt = str(payload.get("retrieval_prompt", "") or "").strip()
    suggested_scope = payload.get("suggested_scope", {}) if isinstance(payload.get("suggested_scope", {}), dict) else {}
    scope_bits = []
    for key in ("grade_band", "genre", "rubric_family"):
        value = str(suggested_scope.get(key, "") or "").strip()
        if value:
            scope_bits.append(f"{key}={value}")
    scope_line = f"Suggested nearest grounded scope: {', '.join(scope_bits)}." if scope_bits else ""
    parts = [
        "GROUNDING CONTEXT:",
        scope_line,
        prompt,
        "Use this only to stabilize expectations for similar cohorts. The rubric contract still governs the score.",
    ]
    return "\n".join(part for part in parts if part).strip()


def _rank_positions(order: list[str]) -> dict[str, int]:
    return {sid: idx for idx, sid in enumerate(order, start=1)}


def build_committee_consensus_report(
    pass1_scores_by_assessor: dict[str, dict],
    pass2_rankings_by_assessor: dict[str, list[str]],
    known_ids: list[str],
    scope_grounding: dict | None,
) -> dict:
    per_student = {}
    for sid in known_ids:
        pass1_scores = [
            float(scores.get(sid, 0.0) or 0.0)
            for scores in pass1_scores_by_assessor.values()
            if sid in scores
        ]
        rank_positions = []
        for ranking in pass2_rankings_by_assessor.values():
            positions = _rank_positions(ranking)
            if sid in positions:
                rank_positions.append(float(positions[sid]))
        pass1_mean = _mean_numeric(pass1_scores)
        pass1_variance = _mean_numeric([(value - pass1_mean) ** 2 for value in pass1_scores]) if pass1_scores else 0.0
        rank_mean = _mean_numeric(rank_positions)
        rank_variance = _mean_numeric([(value - rank_mean) ** 2 for value in rank_positions]) if rank_positions else 0.0
        per_student[sid] = {
            "rubric_mean": round(pass1_mean, 6),
            "rubric_sd": round(pass1_variance ** 0.5, 6),
            "rank_mean": round(rank_mean, 6),
            "rank_sd": round(rank_variance ** 0.5, 6),
            "committee_size_pass1": len(pass1_scores),
            "committee_size_pass2": len(rank_positions),
        }
    mean_rubric_sd = _mean_numeric([item["rubric_sd"] for item in per_student.values()])
    mean_rank_sd = _mean_numeric([item["rank_sd"] for item in per_student.values()])
    payload = scope_grounding if isinstance(scope_grounding, dict) else {}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "existing_multi_assessor_panel",
        "activated": bool(payload.get("committee_mode_recommended", False)),
        "fallback_used": not bool(payload.get("committee_mode_recommended", False)),
        "fallback_reason": "" if payload.get("committee_mode_recommended", False) else "committee_not_requested",
        "scope_grounding": {
            "accepted": bool(payload.get("accepted", False)),
            "familiarity_label": str(payload.get("familiarity_label", "") or ""),
            "committee_mode_recommended": bool(payload.get("committee_mode_recommended", False)),
        },
        "summary": {
            "student_count": len(known_ids),
            "mean_rubric_sd": round(mean_rubric_sd, 6),
            "mean_rank_sd": round(mean_rank_sd, 6),
        },
        "students": per_student,
    }


def _criterion_scores_from_item(item: dict) -> dict[str, float]:
    scores = {}
    for key, value in (item.get("criteria_points") or {}).items():
        if isinstance(value, (int, float)):
            scores[str(key)] = float(value)
    for entry in item.get("criteria_evidence") or []:
        if not isinstance(entry, dict):
            continue
        cid = str(entry.get("criterion_id") or "").strip()
        score = entry.get("score")
        if cid and isinstance(score, (int, float)):
            scores[cid] = float(score)
    return scores


def _is_fallback_deterministic_note(note: str | None) -> bool:
    return str(note or "").strip().lower().startswith("fallback deterministic score")


def _mean_numeric(values: list[float]) -> float:
    return (sum(values) / len(values)) if values else 0.0


def _word_count(text: str | None) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", str(text or "")))


def _resolve_consensus_pass2_item(student_id: str, assessor_items: dict, genre: str | None) -> dict:
    direct_item = assessor_items.get(student_id)
    if isinstance(direct_item, dict) and direct_item.get("student_id"):
        return direct_item
    collected = []
    for items_by_assessor in assessor_items.values():
        if not isinstance(items_by_assessor, dict):
            continue
        item = items_by_assessor.get(student_id)
        if isinstance(item, dict) and item.get("student_id"):
            collected.append(item)
    if not collected:
        return {}
    normalized_genre = str(genre or "").strip().lower()
    if normalized_genre not in {"summary_report", "argumentative", "instructions"}:
        preferred = [item for item in collected if not _is_fallback_deterministic_note(item.get("notes"))]
        return dict(preferred[0] if preferred else collected[0])

    preferred = [item for item in collected if not _is_fallback_deterministic_note(item.get("notes"))]
    selected = preferred or collected
    criteria_by_id: dict[str, list[float]] = {}
    rubric_scores = []
    notes = []
    for item in selected:
        score = item.get("rubric_total_points")
        if isinstance(score, (int, float)):
            rubric_scores.append(float(score))
        for cid, value in _criterion_scores_from_item(item).items():
            criteria_by_id.setdefault(cid, []).append(float(value))
        note_text = " ".join(str(item.get("notes", "") or "").split())
        if note_text and note_text not in notes:
            notes.append(note_text)
    consensus = dict(selected[0])
    if rubric_scores:
        consensus["rubric_total_points"] = round(_mean_numeric(rubric_scores), 2)
    if criteria_by_id:
        consensus["criteria_points"] = {
            cid: round(_mean_numeric(values), 2)
            for cid, values in sorted(criteria_by_id.items())
            if values
        }
    if notes:
        consensus["notes"] = " ".join(notes[:2])
    return consensus


def _summary_signal_bonus_penalty(note_text: str, word_count: int, median_word_count: float) -> float:
    lowered = str(note_text or "").lower()
    penalty = 0.0
    bonus = 0.0
    if (
        "clear ending summary paragraph" in lowered
        or "final paragraph functions as a reasonable summary" in lowered
        or "solid summary" in lowered
    ):
        bonus += 6.0
    if "reasonable summary" in lowered:
        bonus += 2.0
    if "personal opinion" in lowered or "opinion-based" in lowered:
        penalty += 18.0
    if "food list" in lowered:
        penalty += 4.0
    if "repeats the same information again" in lowered or "padded by duplication" in lowered:
        penalty += 6.0
    elif "repeats information" in lowered or "repeats points" in lowered or "repeats the main idea" in lowered:
        penalty += 4.0
    if "copied/extraction-heavy" in lowered or "closely mirrored from the source" in lowered:
        penalty += 6.0
    elif (
        "source-like/copying" in lowered
        or "source-like wording" in lowered
        or "source-like sentences" in lowered
        or "closely match source wording" in lowered
        or "near-copied" in lowered
        or "copied or very closely mirrored" in lowered
        or "copied source sentences" in lowered
    ):
        penalty += 5.0
    elif "source-like" in lowered or "copied" in lowered:
        penalty += 4.0
    if "far too detailed" in lowered or "overly long" in lowered or "too long for a summary" in lowered:
        penalty += 5.0
    elif "not concise" in lowered:
        penalty += 4.0
    length_penalty = 0.0
    if median_word_count > 0 and word_count > median_word_count:
        length_penalty = min(10.0, (word_count - median_word_count) * 0.14)
    return bonus - penalty - length_penalty


def _literary_analysis_signal_bonus_penalty(note_text: str) -> float:
    lowered = str(note_text or "").lower()
    bonus = 0.0
    penalty = 0.0
    if (
        "clear thesis" in lowered
        or "focused thesis" in lowered
        or "clear central idea" in lowered
        or "coherent theme" in lowered
    ):
        bonus += 5.0
    if (
        "relevant evidence" in lowered
        or "specific evidence" in lowered
        or "textual evidence" in lowered
        or "multiple relevant examples" in lowered
    ):
        bonus += 5.0
    if (
        "insightful analysis" in lowered
        or "strong analysis" in lowered
        or "developed analysis" in lowered
        or "clear analysis" in lowered
    ):
        bonus += 6.0
    if "organized" in lowered or "cohesive" in lowered or "clear structure" in lowered:
        bonus += 2.5

    if (
        "repetitive" in lowered
        or "underdeveloped" in lowered
        or "thin evidence" in lowered
        or "weaker support" in lowered
        or "weak support" in lowered
    ):
        penalty += 5.0
    if (
        "vague" in lowered
        or "unsupported" in lowered
        or "inaccurate" in lowered
        or "factual vagueness" in lowered
    ):
        penalty += 4.0
    if (
        "fragmentary" in lowered
        or "incomplete" in lowered
        or "placeholder" in lowered
        or "unfinished" in lowered
    ):
        penalty += 12.0
    if "grammar" in lowered or "conventions" in lowered:
        penalty += 1.5
    return bonus - penalty


def build_literary_analysis_seed_order(
    known_ids: list[str],
    texts: dict[str, str],
    assessor_items: dict[str, dict],
) -> list[str] | None:
    if not known_ids:
        return None
    ranking_payload = {}
    for sid in known_ids:
        item = _resolve_consensus_pass2_item(sid, assessor_items, "literary_analysis")
        if not item:
            continue
        criteria_points = _criterion_scores_from_item(item)
        thesis = float(criteria_points.get("LA1", criteria_points.get("AR1", criteria_points.get("K1", 0.0))) or 0.0)
        evidence = float(criteria_points.get("LA2", criteria_points.get("AR2", criteria_points.get("T1", 0.0))) or 0.0)
        analysis = float(criteria_points.get("LA3", criteria_points.get("AR3", criteria_points.get("T2", 0.0))) or 0.0)
        organization = float(criteria_points.get("C1", 0.0) or 0.0)
        expression = float(criteria_points.get("C3", criteria_points.get("C2", 0.0)) or 0.0)
        weighted_components = []
        total_weight = 0.0
        for value, weight in (
            (thesis, 0.18),
            (evidence, 0.24),
            (analysis, 0.28),
            (organization, 0.15),
            (expression, 0.15),
        ):
            if value > 0:
                weighted_components.append(weight * value)
                total_weight += weight
        rubric_score = float(item.get("rubric_total_points", 0.0) or 0.0)
        base_signal = (sum(weighted_components) / total_weight) if total_weight > 0 else rubric_score
        note_text = str(item.get("notes", "") or "")
        draft_quality = analyze_draft_quality(texts.get(sid, ""), note_text)
        note_signal = _literary_analysis_signal_bonus_penalty(note_text)
        completion_bucket = 0 if draft_quality.get("hard_floor_incomplete") else 1
        completion_floor_penalty = 18.0 if draft_quality.get("hard_floor_incomplete") else 0.0
        final_signal = round(
            (0.68 * base_signal)
            + (0.32 * rubric_score)
            + note_signal
            - draft_quality["penalty_points"]
            - completion_floor_penalty,
            4,
        )
        ranking_payload[sid] = {
            "completion_bucket": completion_bucket,
            "signal": final_signal,
            "analysis": analysis,
            "evidence": evidence,
            "rubric_score": rubric_score,
        }
    if len(ranking_payload) != len(known_ids):
        return None
    index_lookup = {sid: idx for idx, sid in enumerate(known_ids)}
    ordered = sorted(
        known_ids,
        key=lambda sid: (
            int(ranking_payload[sid]["completion_bucket"]),
            float(ranking_payload[sid]["signal"]),
            float(ranking_payload[sid]["analysis"]),
            float(ranking_payload[sid]["evidence"]),
            float(ranking_payload[sid]["rubric_score"]),
            -index_lookup[sid],
        ),
        reverse=True,
    )
    return ordered


def build_literary_analysis_report_ranking_summary(
    item: dict,
    fallback_summary: str,
    text: str,
    max_chars: int = 280,
) -> str:
    if not isinstance(item, dict):
        return _truncate_compact(fallback_summary, max_chars)
    score = float(item.get("rubric_total_points", 0.0) or 0.0)
    criteria_points = _criterion_scores_from_item(item)
    thesis = float(criteria_points.get("LA1", criteria_points.get("AR1", criteria_points.get("K1", 0.0))) or 0.0)
    evidence = float(criteria_points.get("LA2", criteria_points.get("AR2", criteria_points.get("T1", 0.0))) or 0.0)
    analysis = float(criteria_points.get("LA3", criteria_points.get("AR3", criteria_points.get("T2", 0.0))) or 0.0)
    organization = float(criteria_points.get("C1", 0.0) or 0.0)
    expression = float(criteria_points.get("C3", criteria_points.get("C2", 0.0)) or 0.0)
    parts = [f"Literary analysis score {score:.2f}."]
    metrics = []
    for label, value in (
        ("thesis", thesis),
        ("evidence", evidence),
        ("analysis", analysis),
        ("organization", organization),
        ("expression", expression),
    ):
        if value > 0:
            metrics.append(f"{label} {value:.0f}")
    if metrics:
        parts.append("Criteria: " + "; ".join(metrics) + ".")
    strengths = []
    cautions = []
    if thesis >= 80:
        strengths.append("clear thematic thesis")
    elif thesis and thesis < 68:
        cautions.append("theme focus is weak")
    if evidence >= 80:
        strengths.append("specific textual support")
    elif evidence and evidence < 68:
        cautions.append("text support is thin")
    if analysis >= 80:
        strengths.append("developed literary analysis")
    elif analysis and analysis < 68:
        cautions.append("analysis stays basic")
    draft_quality = analyze_draft_quality(text, str(item.get("notes", "") or fallback_summary))
    if draft_quality["penalty_points"] > 0:
        cautions.append("response is unfinished and still contains scaffold/organizer residue")
    if draft_quality.get("hard_floor_incomplete"):
        cautions.append("completion-integrity floor applied because the draft is visibly unfinished")
    if strengths:
        parts.append("Strengths: " + ", ".join(dict.fromkeys(strengths)) + ".")
    if cautions:
        parts.append("Cautions: " + ", ".join(dict.fromkeys(cautions)) + ".")
    note = _truncate_compact(str(item.get("notes", "") or fallback_summary), 140)
    if note:
        parts.append(note)
    return _truncate_compact(" ".join(parts), max_chars)


def build_summary_seed_order(
    known_ids: list[str],
    texts: dict[str, str],
    assessor_items: dict[str, dict],
) -> list[str] | None:
    if not known_ids:
        return None
    word_counts = {sid: _word_count(texts.get(sid, "")) for sid in known_ids}
    nonzero_counts = sorted(count for count in word_counts.values() if count > 0)
    median_word_count = float(nonzero_counts[len(nonzero_counts) // 2]) if nonzero_counts else 0.0
    scores = {}
    for sid in known_ids:
        item = _resolve_consensus_pass2_item(sid, assessor_items, "summary_report")
        if not item:
            continue
        criteria_points = _criterion_scores_from_item(item)
        sr1 = float(criteria_points.get("SR1", 0.0) or 0.0)
        sr2 = float(criteria_points.get("SR2", 0.0) or 0.0)
        sr3 = float(criteria_points.get("SR3", 0.0) or 0.0)
        c1 = float(criteria_points.get("C1", 0.0) or 0.0)
        c2 = float(criteria_points.get("C2", 0.0) or 0.0)
        base_signal = (0.20 * sr1) + (0.30 * sr2) + (0.30 * sr3) + (0.10 * c1) + (0.10 * c2)
        note_signal = _summary_signal_bonus_penalty(
            str(item.get("notes", "") or ""),
            word_counts.get(sid, 0),
            median_word_count,
        )
        scores[sid] = round(base_signal + note_signal, 4)
    if len(scores) != len(known_ids):
        return None
    return ranking_from_scores(scores, known_ids)


def build_summary_report_ranking_summary(item: dict, fallback_summary: str, max_chars: int = 280) -> str:
    if not isinstance(item, dict):
        return _truncate_compact(fallback_summary, max_chars)
    score = float(item.get("rubric_total_points", 0.0) or 0.0)
    criteria_points = _criterion_scores_from_item(item)
    sr1 = float(criteria_points.get("SR1", 0.0) or 0.0)
    sr2 = float(criteria_points.get("SR2", 0.0) or 0.0)
    sr3 = float(criteria_points.get("SR3", 0.0) or 0.0)
    c1 = float(criteria_points.get("C1", 0.0) or 0.0)
    c2 = float(criteria_points.get("C2", 0.0) or 0.0)
    parts = [f"Summary writing score {score:.2f}."]
    metrics = []
    for label, value in (
        ("main-idea capture", sr1),
        ("concision", sr2),
        ("paraphrase", sr3),
        ("organization", c1),
        ("conventions", c2),
    ):
        if value > 0:
            metrics.append(f"{label} {value:.0f}")
    if metrics:
        parts.append("Criteria: " + "; ".join(metrics) + ".")
    strengths = []
    cautions = []
    if sr1 >= 80:
        strengths.append("accurate main ideas")
    elif sr1 and sr1 < 68:
        cautions.append("missing or inaccurate key points")
    if sr2 >= 80:
        strengths.append("concise information selection")
    elif sr2 and sr2 < 70:
        cautions.append("too much source detail")
    if sr3 >= 80:
        strengths.append("clear paraphrase and synthesis")
    elif sr3 and sr3 < 70:
        cautions.append("too close to source phrasing")
    note_text = str(item.get("notes", "") or fallback_summary)
    lowered_note = note_text.lower()
    if "personal opinion" in lowered_note or "unsupported conclusion" in lowered_note or "irrelevant personal" in lowered_note:
        cautions.append("drifts into personal opinion")
    if "copied" in lowered_note or "source-like" in lowered_note or "verbatim" in lowered_note or "extraction" in lowered_note:
        cautions.append("heavy source lifting")
    if "decent summary" in lowered_note or "clear summary" in lowered_note or "effective summary" in lowered_note:
        strengths.append("clear summary focus")
    if strengths:
        parts.append("Strengths: " + ", ".join(strengths) + ".")
    if cautions:
        parts.append("Cautions: " + ", ".join(cautions) + ".")
    note = _truncate_compact(note_text, 140)
    if note:
        parts.append(note)
    return _truncate_compact(" ".join(parts), max_chars)


def _instructions_signal_bonus_penalty(note_text: str) -> float:
    lowered = str(note_text or "").lower()
    bonus = 0.0
    penalty = 0.0
    if (
        "complete procedure" in lowered
        or "complete set of steps" in lowered
        or "usable procedure" in lowered
        or "thorough procedure" in lowered
        or "can be followed accurately" in lowered
    ):
        bonus += 6.0
    if (
        "clear sequence" in lowered
        or "logical sequence" in lowered
        or "easy to follow" in lowered
        or "steps are clearly ordered" in lowered
    ):
        bonus += 5.0
    if (
        "precise measurements" in lowered
        or "accurate measurements" in lowered
        or "safety details" in lowered
        or "appropriate cautions" in lowered
        or "safety-conscious" in lowered
    ):
        bonus += 5.0

    if (
        "missing materials" in lowered
        or "missing equipment" in lowered
        or "missing setup" in lowered
        or "missing steps" in lowered
        or "omits key steps" in lowered
        or "incomplete procedure" in lowered
    ):
        penalty += 8.0
    if (
        "unclear sequence" in lowered
        or "sequence is confusing" in lowered
        or "hard to follow" in lowered
        or "order of steps is unclear" in lowered
        or "steps are out of order" in lowered
    ):
        penalty += 7.0
    if (
        "missing safety" in lowered
        or "omits safety" in lowered
        or "unsafe" in lowered
        or "imprecise measurements" in lowered
        or "vague directions" in lowered
        or "lacks precision" in lowered
    ):
        penalty += 7.0
    if "generic explanation" in lowered or "sounds more like a report" in lowered:
        penalty += 3.0
    return bonus - penalty


def build_instructions_seed_order(known_ids: list[str], assessor_items: dict[str, dict]) -> list[str] | None:
    if not known_ids:
        return None
    scores = {}
    for sid in known_ids:
        item = _resolve_consensus_pass2_item(sid, assessor_items, "instructions")
        if not item:
            continue
        criteria_points = _criterion_scores_from_item(item)
        weighted_components = []
        total_weight = 0.0
        for cid, weight in (
            ("IN1", 0.34),
            ("IN2", 0.28),
            ("IN3", 0.23),
            ("C2", 0.08),
            ("C3", 0.07),
        ):
            value = criteria_points.get(cid)
            if isinstance(value, (int, float)):
                weighted_components.append(weight * float(value))
                total_weight += weight
        rubric_score = float(item.get("rubric_total_points", 0.0) or 0.0)
        base_signal = (sum(weighted_components) / total_weight) if total_weight > 0 else rubric_score
        note_signal = _instructions_signal_bonus_penalty(str(item.get("notes", "") or ""))
        scores[sid] = round((0.76 * base_signal) + (0.24 * rubric_score) + note_signal, 4)
    if len(scores) != len(known_ids):
        return None
    return ranking_from_scores(scores, known_ids)


def build_instructions_report_ranking_summary(item: dict, fallback_summary: str, max_chars: int = 280) -> str:
    if not isinstance(item, dict):
        return _truncate_compact(fallback_summary, max_chars)
    score = float(item.get("rubric_total_points", 0.0) or 0.0)
    criteria_points = _criterion_scores_from_item(item)
    in1 = float(criteria_points.get("IN1", 0.0) or 0.0)
    in2 = float(criteria_points.get("IN2", 0.0) or 0.0)
    in3 = float(criteria_points.get("IN3", 0.0) or 0.0)
    c2 = float(criteria_points.get("C2", 0.0) or 0.0)
    c3 = float(criteria_points.get("C3", 0.0) or 0.0)
    parts = [f"Instructions score {score:.2f}."]
    metrics = []
    for label, value in (
        ("completeness", in1),
        ("sequence", in2),
        ("precision/safety", in3),
        ("conventions", c2),
        ("clarity", c3),
    ):
        if value > 0:
            metrics.append(f"{label} {value:.0f}")
    if metrics:
        parts.append("Criteria: " + "; ".join(metrics) + ".")
    strengths = []
    cautions = []
    if in1 >= 80:
        strengths.append("complete usable procedure")
    elif in1 and in1 < 68:
        cautions.append("missing needed steps or materials")
    if in2 >= 80:
        strengths.append("clear executable sequence")
    elif in2 and in2 < 68:
        cautions.append("sequence is hard to follow")
    if in3 >= 80:
        strengths.append("precise directions and safety control")
    elif in3 and in3 < 68:
        cautions.append("precision or safety details are weak")
    note_text = str(item.get("notes", "") or fallback_summary)
    lowered_note = note_text.lower()
    if "complete procedure" in lowered_note or "easy to follow" in lowered_note:
        strengths.append("procedure can be followed accurately")
    if "missing safety" in lowered_note or "omits safety" in lowered_note or "unsafe" in lowered_note:
        cautions.append("important safety details are missing")
    if "missing materials" in lowered_note or "missing setup" in lowered_note or "missing steps" in lowered_note:
        cautions.append("key procedural setup is omitted")
    if strengths:
        parts.append("Strengths: " + ", ".join(dict.fromkeys(strengths)) + ".")
    if cautions:
        parts.append("Cautions: " + ", ".join(dict.fromkeys(cautions)) + ".")
    note = _truncate_compact(note_text, 140)
    if note:
        parts.append(note)
    return _truncate_compact(" ".join(parts), max_chars)


def _argumentative_signal_bonus_penalty(note_text: str) -> float:
    lowered = str(note_text or "").lower()
    bonus = 0.0
    penalty = 0.0
    if (
        "clear claim" in lowered
        or "strong claim" in lowered
        or "arguable claim" in lowered
        or "focused argument" in lowered
    ):
        bonus += 5.0
    if (
        "well-supported" in lowered
        or "effective evidence" in lowered
        or "strong evidence" in lowered
        or "relevant evidence" in lowered
        or "credible evidence" in lowered
    ):
        bonus += 6.0
    if (
        "addresses counterargument" in lowered
        or "engages counterargument" in lowered
        or "acknowledges opposition" in lowered
        or "responds to opposing views" in lowered
    ):
        bonus += 4.0
    if "convincing" in lowered or "persuasive" in lowered or "strong reasoning" in lowered:
        bonus += 4.0
    if "effective organization" in lowered or "logical progression" in lowered:
        bonus += 2.5

    if (
        "unclear claim" in lowered
        or "weak claim" in lowered
        or "claim is vague" in lowered
        or "lacks a clear claim" in lowered
    ):
        penalty += 7.0
    if (
        "limited evidence" in lowered
        or "thin evidence" in lowered
        or "unsupported" in lowered
        or "underdeveloped evidence" in lowered
        or "few specifics" in lowered
    ):
        penalty += 8.0
    if (
        "ignores counterargument" in lowered
        or "no counterargument" in lowered
        or "one-sided" in lowered
        or "does not address opposing views" in lowered
    ):
        penalty += 4.5
    if (
        "repetitive" in lowered
        or "formulaic" in lowered
        or "list-like" in lowered
        or "loosely connected reasons" in lowered
    ):
        penalty += 3.5
    if "off-topic" in lowered or "drifts" in lowered or "summary of the topic" in lowered:
        penalty += 4.0
    return bonus - penalty


def build_argumentative_seed_order(known_ids: list[str], assessor_items: dict[str, dict]) -> list[str] | None:
    if not known_ids:
        return None
    scores = {}
    for sid in known_ids:
        item = _resolve_consensus_pass2_item(sid, assessor_items, "argumentative")
        if not item:
            continue
        criteria_points = _criterion_scores_from_item(item)
        weighted_components = []
        total_weight = 0.0
        for cid, weight in (
            ("AR1", 0.26),
            ("AR2", 0.30),
            ("AR3", 0.18),
            ("C1", 0.10),
            ("C3", 0.08),
            ("T1", 0.08),
        ):
            value = criteria_points.get(cid)
            if isinstance(value, (int, float)):
                weighted_components.append(weight * float(value))
                total_weight += weight
        rubric_score = float(item.get("rubric_total_points", 0.0) or 0.0)
        base_signal = (sum(weighted_components) / total_weight) if total_weight > 0 else rubric_score
        note_signal = _argumentative_signal_bonus_penalty(str(item.get("notes", "") or ""))
        scores[sid] = round((0.72 * base_signal) + (0.28 * rubric_score) + note_signal, 4)
    if len(scores) != len(known_ids):
        return None
    return ranking_from_scores(scores, known_ids)


def build_argumentative_report_ranking_summary(item: dict, fallback_summary: str, max_chars: int = 280) -> str:
    if not isinstance(item, dict):
        return _truncate_compact(fallback_summary, max_chars)
    score = float(item.get("rubric_total_points", 0.0) or 0.0)
    criteria_points = _criterion_scores_from_item(item)
    ar1 = float(criteria_points.get("AR1", 0.0) or 0.0)
    ar2 = float(criteria_points.get("AR2", 0.0) or 0.0)
    ar3 = float(criteria_points.get("AR3", 0.0) or 0.0)
    c1 = float(criteria_points.get("C1", 0.0) or 0.0)
    c3 = float(criteria_points.get("C3", 0.0) or 0.0)
    parts = [f"Argument score {score:.2f}."]
    metrics = []
    for label, value in (
        ("claim", ar1),
        ("evidence", ar2),
        ("counterargument", ar3),
        ("organization", c1),
        ("sentence craft", c3),
    ):
        if value > 0:
            metrics.append(f"{label} {value:.0f}")
    if metrics:
        parts.append("Criteria: " + "; ".join(metrics) + ".")
    strengths = []
    cautions = []
    if ar1 >= 80:
        strengths.append("clear arguable claim")
    elif ar1 and ar1 < 68:
        cautions.append("claim control is weak")
    if ar2 >= 80:
        strengths.append("well-supported reasoning")
    elif ar2 and ar2 < 68:
        cautions.append("evidence is thin or generic")
    if ar3 >= 78:
        strengths.append("engages opposition")
    elif ar3 and ar3 < 62:
        cautions.append("counterargument handling is limited")
    if c1 >= 78:
        strengths.append("logical progression")
    elif c1 and c1 < 64:
        cautions.append("organization is loose")
    note_text = str(item.get("notes", "") or fallback_summary)
    lowered_note = note_text.lower()
    if "convincing" in lowered_note or "persuasive" in lowered_note:
        strengths.append("convincing overall case")
    if "one-sided" in lowered_note or "unsupported" in lowered_note:
        cautions.append("argument remains one-sided or unsupported")
    if "formulaic" in lowered_note or "repetitive" in lowered_note:
        cautions.append("repetition weakens force")
    if strengths:
        parts.append("Strengths: " + ", ".join(dict.fromkeys(strengths)) + ".")
    if cautions:
        parts.append("Cautions: " + ", ".join(dict.fromkeys(cautions)) + ".")
    note = _truncate_compact(note_text, 140)
    if note:
        parts.append(note)
    return _truncate_compact(" ".join(parts), max_chars)


def argumentative_seed_mode(metadata: dict, genre: str | None, portfolio_scope: bool) -> str:
    if portfolio_scope or str(genre or "").strip().lower() != "argumentative":
        return ""
    cohort_shape = str((metadata or {}).get("cohort_shape") or (metadata or {}).get("cohort_coherence") or "").strip().lower()
    source_family = str((metadata or {}).get("source_family") or "").strip().lower()
    if "same_rubric_family_cross_topic" in cohort_shape and "thoughtful" in source_family:
        return "cross_topic"
    if ("same_prompt" in cohort_shape or bool((metadata or {}).get("prompt_shared", False))) and (
        "naep" in source_family or "thoughtful" in source_family
    ):
        return "single_prompt"
    return ""


def use_argumentative_seed_order(metadata: dict, genre: str | None, portfolio_scope: bool) -> bool:
    return bool(argumentative_seed_mode(metadata, genre, portfolio_scope))


def use_instructions_seed_order(metadata: dict, genre: str | None, portfolio_scope: bool) -> bool:
    if portfolio_scope:
        return False
    normalized_genre = str(genre or "").strip().lower()
    cohort_shape = str((metadata or {}).get("cohort_shape") or (metadata or {}).get("cohort_coherence") or "").strip().lower()
    source_family = str((metadata or {}).get("source_family") or "").strip().lower()
    assignment_context = " ".join(
        str((metadata or {}).get(key) or "")
        for key in ("assignment_name", "assignment_genre", "genre_form", "assessment_unit")
    ).lower()
    is_instructional = normalized_genre == "instructions" or (
        normalized_genre == "informational_report" and ("instruction" in assignment_context or "procedur" in assignment_context)
    )
    return is_instructional and "same_prompt" in cohort_shape and "thoughtful" in source_family


def build_pass2_ranking_contract(genre: str | None, portfolio_scope: bool, metadata: dict | None = None) -> str:
    if portfolio_scope:
        return (
            "RANKING CONTRACT:\n"
            "- Student summaries already reflect piece-level portfolio scoring.\n"
            "- Compare the overall portfolio judgment, piece profile, and strongest pieces rather than isolated excerpts.\n"
            "- A portfolio with stronger piece distribution and stronger top pieces should outrank a flatter lower portfolio."
        )
    if str(genre or "").strip().lower() == "summary_report":
        return (
            "RANKING CONTRACT:\n"
            "- Rank these as summaries, not generic informational responses.\n"
            "- Accurate main-idea capture, concision, and paraphrase should outweigh raw length or copied source detail.\n"
            "- A concise accurate paraphrase should outrank a longer extraction-heavy response."
        )
    if use_instructions_seed_order(metadata or {}, genre, portfolio_scope):
        return (
            "RANKING CONTRACT:\n"
            "- Rank these as executable instructions, not generic informational prose.\n"
            "- Complete usable setup, clear sequencing, and precise safety-aware directions should outweigh surface fluency alone.\n"
            "- A procedure that can actually be followed accurately should outrank a polished but incomplete response."
        )
    arg_seed_mode = argumentative_seed_mode(metadata or {}, genre, portfolio_scope)
    if arg_seed_mode == "cross_topic":
        return (
            "RANKING CONTRACT:\n"
            "- Rank these as argumentative responses across different topics, not by topic excitement or surface polish alone.\n"
            "- Stronger claim control, evidence quality, reasoning, and counterargument handling should outweigh sheer length or rhetorical flourish.\n"
            "- A clearer better-supported argument should outrank a longer or more dramatic but thinner response."
        )
    if arg_seed_mode == "single_prompt":
        return (
            "RANKING CONTRACT:\n"
            "- Rank these as responses to the same persuasive/argument prompt.\n"
            "- Stronger claim control, evidence quality, reasoning, and counterargument handling should outweigh surface polish or length alone.\n"
            "- A more convincing, better-supported response should outrank a longer but thinner or less controlled response."
        )
    return ""


def use_summary_seed_order(metadata: dict, genre: str | None, portfolio_scope: bool) -> bool:
    if portfolio_scope or str(genre or "").strip().lower() != "summary_report":
        return False
    cohort_shape = str((metadata or {}).get("cohort_shape") or (metadata or {}).get("cohort_coherence") or "").strip().lower()
    return "same_prompt" in cohort_shape


def use_literary_analysis_seed_order(
    metadata: dict,
    genre: str | None,
    portfolio_scope: bool,
    texts: dict[str, str],
    assessor_items: dict[str, dict],
) -> bool:
    if portfolio_scope or str(genre or "").strip().lower() != "literary_analysis":
        return False
    for sid, text in texts.items():
        item = _resolve_consensus_pass2_item(sid, assessor_items, "literary_analysis")
        draft_quality = analyze_draft_quality(text, str(item.get("notes", "") or ""))
        if draft_quality["penalty_points"] >= 8.0:
            return True
    generated_by = str((metadata or {}).get("generated_by") or "").strip().lower()
    return generated_by == "bootstrap"


def build_pass2_student_summaries(
    known_ids: list[str],
    raw_summaries: dict[str, str],
    source_texts: dict[str, str],
    assessor_items: dict[str, dict],
    genre: str | None,
    portfolio_scope: bool,
    max_chars: int,
    metadata: dict | None = None,
) -> list[dict]:
    entries = []
    normalized_genre = str(genre or "").strip().lower()
    argumentative_seed_mode_active = use_argumentative_seed_order(metadata or {}, genre, portfolio_scope)
    instructions_seed_mode = use_instructions_seed_order(metadata or {}, genre, portfolio_scope)
    literary_seed_mode = use_literary_analysis_seed_order(metadata or {}, genre, portfolio_scope, source_texts, assessor_items)
    for sid in known_ids:
        raw_summary = raw_summaries.get(sid, "")
        item = _resolve_consensus_pass2_item(sid, assessor_items, genre)
        if portfolio_scope:
            summary = summarize_portfolio_for_ranking(item, max_chars=max_chars)
        elif normalized_genre == "summary_report":
            summary = build_summary_report_ranking_summary(item, raw_summary, max_chars=max_chars)
        elif instructions_seed_mode:
            summary = build_instructions_report_ranking_summary(item, raw_summary, max_chars=max_chars)
        elif normalized_genre == "argumentative" and argumentative_seed_mode_active:
            summary = build_argumentative_report_ranking_summary(item, raw_summary, max_chars=max_chars)
        elif normalized_genre == "literary_analysis" and literary_seed_mode:
            summary = build_literary_analysis_report_ranking_summary(item, raw_summary, source_texts.get(sid, ""), max_chars=max_chars)
        else:
            summary = raw_summary
        entries.append({"student_id": sid, "summary": summary or _truncate_compact(raw_summary, max_chars)})
    return entries


def unanimous_portfolio_seed_order(pass1_scores_by_assessor: dict[str, dict], known_ids: list[str]) -> list[str] | None:
    orders = []
    for assessor in sorted(pass1_scores_by_assessor):
        scores = pass1_scores_by_assessor.get(assessor, {})
        if not isinstance(scores, dict) or not scores:
            continue
        orders.append(ranking_from_scores(scores, known_ids))
    if not orders:
        return None
    first = orders[0]
    if all(order == first for order in orders[1:]):
        return list(first)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LLM assessors for Pass 1 and Pass 2")
    parser.add_argument("--texts", default="processing/normalized_text", help="Normalized text directory")
    parser.add_argument("--rubric", default="inputs/rubric.md", help="Rubric file (md or txt)")
    parser.add_argument("--outline", default="inputs/assignment_outline.md", help="Assignment outline file")
    parser.add_argument("--routing", default="config/llm_routing.json", help="LLM routing config")
    parser.add_argument("--pass1-out", default="assessments/pass1_individual", help="Pass 1 output dir")
    parser.add_argument("--pass2-out", default="assessments/pass2_comparative", help="Pass 2 output dir")
    parser.add_argument("--max-summary-chars", type=int, default=800, help="Max chars for summaries in pass2")
    parser.add_argument("--assessors", default="A,B,C", help="Comma-separated assessor IDs")
    parser.add_argument("--cost-limits", default="config/cost_limits.json", help="Cost limits config")
    parser.add_argument("--pricing", default="config/pricing.json", help="Pricing config")
    parser.add_argument("--ignore-cost-limits", action="store_true", help="Skip cost limit checks")
    parser.add_argument("--grade-level", type=int, default=None, help="Grade level for expectations")
    parser.add_argument("--grade-profiles", default="config/grade_level_profiles.json", help="Grade profiles config")
    parser.add_argument("--class-metadata", default="inputs/class_metadata.json", help="Class metadata JSON")
    parser.add_argument("--exemplars", default="inputs/exemplars", help="Exemplars directory")
    parser.add_argument("--genre", default=None, help="Assignment genre for exemplar selection")
    parser.add_argument("--rubric-criteria", default="config/rubric_criteria.json", help="Rubric criteria JSON")
    parser.add_argument("--normalized-rubric", default="outputs/normalized_rubric.json", help="Normalized rubric contract JSON")
    parser.add_argument("--rubric-manifest", default="outputs/rubric_manifest.json", help="Rubric manifest JSON")
    parser.add_argument("--rubric-verification", default="outputs/rubric_verification.json", help="Rubric verification JSON")
    parser.add_argument("--portfolio-piece-report", default="outputs/portfolio_piece_report.json", help="Portfolio piece scoring report JSON")
    parser.add_argument("--scope-grounding", default="outputs/scope_grounding.json", help="Scope grounding JSON")
    parser.add_argument("--committee-report", default="outputs/committee_consensus_report.json", help="Committee consensus report JSON")
    parser.add_argument("--fallback", choices=["none", "deterministic"], default="deterministic", help="Fallback strategy when model output is invalid")
    parser.add_argument("--require-model-usage", action="store_true", help="Fail if no model outputs are accepted")
    args = parser.parse_args()
    routing = load_routing(Path(args.routing))
    mode = os.environ.get("LLM_MODE") or routing.get("mode", "openai")
    if mode != "codex_local" and not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. Aborting.")
        return 1
    pass1_model = routing["tasks"]["pass1_assessor"]["model"]
    pass1_reasoning = _structured_reasoning(pass1_model, routing["tasks"]["pass1_assessor"].get("reasoning", "medium"))
    pass1_temp = routing["tasks"]["pass1_assessor"].get("temperature", 0.2)
    pass1_max_tokens = routing["tasks"]["pass1_assessor"].get("max_output_tokens")
    pass2_model = routing["tasks"]["pass2_ranker"]["model"]
    pass2_reasoning = _structured_reasoning(pass2_model, routing["tasks"]["pass2_ranker"].get("reasoning", "medium"))
    pass2_temp = routing["tasks"]["pass2_ranker"].get("temperature", 0.2)
    pass2_max_tokens = routing["tasks"]["pass2_ranker"].get("max_output_tokens")
    guard_cfg = routing.get("pass1_guard", {})
    guard_enabled = bool(guard_cfg.get("enabled", False))
    guard_max_score_delta = float(guard_cfg.get("max_score_delta", 8.0) or 8.0)
    guard_max_level_gap = int(guard_cfg.get("max_level_gap", 1) or 1)
    guard_anchor_blend = float(guard_cfg.get("anchor_blend", 0.0) or 0.0)
    min_model_coverage = float(routing.get("quality_gates", {}).get("min_model_coverage", 0.0) or 0.0)
    texts = load_texts(Path(args.texts))
    rubric_path = resolve_input_path(Path(args.rubric), "rubric")
    outline_path = resolve_input_path(Path(args.outline), "assignment_outline")
    rubric_context = runtime_rubric_context(
        rubric_path,
        normalized_path=Path(args.normalized_rubric),
        verification_path=Path(args.rubric_verification),
    )
    rubric = rubric_context["rubric_text"]
    outline = load_file_text(outline_path)
    if not rubric.strip():
        print(f"Rubric text is empty. Check file at {rubric_path}.")
        return 1
    metadata = load_class_metadata(Path(args.class_metadata))
    profiles = load_grade_profiles(Path(args.grade_profiles))
    grade_level = select_grade_level(args.grade_level, metadata)
    grade_context = build_grade_context(grade_level, profiles)
    normalized_rubric = rubric_context.get("normalized_rubric", {}) if isinstance(rubric_context.get("normalized_rubric", {}), dict) else {}
    rubric_manifest = load_rubric_json(Path(args.rubric_manifest))
    explicit_genre = normalize_genre(args.genre)
    rubric_genre = normalize_genre(normalized_rubric.get("genre"))
    metadata_genre = normalize_genre(
        metadata.get("genre")
        or metadata.get("assignment_genre")
        or metadata.get("genre_form")
        or metadata.get("assessment_unit")
    )
    inferred_genre = None
    if not explicit_genre and not rubric_genre and genre_specificity(metadata_genre) < 4:
        inferred_genre = infer_genre_from_text(rubric_context.get("raw_text", rubric), outline)
    genre = explicit_genre or rubric_genre or choose_preferred_genre(metadata_genre, inferred_genre)
    if not genre:
        genre = normalize_genre(inferred_genre)
    portfolio_scope = is_portfolio_scope(metadata, genre)
    portfolio_pieces_by_student = {
        student_id: split_portfolio_pieces(text)
        for student_id, text in texts.items()
    } if portfolio_scope else {}
    base_exemplars = Path(args.exemplars)
    exemplars_dir = base_exemplars
    exemplar_selection = {
        "path": base_exemplars,
        "requested_band": None,
        "requested_genre": genre,
        "selected_band": None,
        "selected_genre": None,
        "match_quality": "custom",
    }
    if str(args.exemplars) == "inputs/exemplars":
        exemplar_selection = resolve_exemplar_selection(base_exemplars, grade_level, genre)
        exemplars_dir = exemplar_selection["path"]
    exemplars = load_exemplars(exemplars_dir)
    exemplar_block = format_exemplars(exemplars)
    criteria_cfg = load_rubric_criteria(Path(args.rubric_criteria))
    contract = resolve_pass1_contract(
        criteria_cfg,
        genre,
        bool(routing.get("tasks", {}).get("pass1_assessor", {}).get("require_evidence", False)),
    )
    criteria_block = contract["criteria_block"]
    required_ids = contract["required_ids"]
    piece_criteria_block = criteria_prompt(criteria_cfg, None) if criteria_cfg else ""
    piece_required_ids = criteria_ids(criteria_cfg, None) if criteria_cfg else []
    reqs = contract["reqs"]
    require_evidence = contract["require_evidence"]
    assessors = [a.strip() for a in args.assessors.split(",") if a.strip()]
    scope_grounding = load_json(Path(args.scope_grounding))
    run_scope = build_run_scope(
        metadata=metadata | {"grade_level": grade_level, "genre": genre},
        routing=routing,
        rubric_path=rubric_path,
        rubric_manifest=rubric_manifest,
    )
    grounding_context = build_scope_grounding_context(scope_grounding)
    if grounding_context:
        grade_context = f"{grade_context}\n\n{grounding_context}".strip() if grade_context else grounding_context
    gate_error = calibration_gate_error(
        routing,
        assessors,
        run_scope,
        context={
            "routing_path": args.routing,
            "rubric_path": rubric_path,
            "calibration_set_path": "config/calibration_set.json",
            "exemplars_path": args.exemplars,
        },
    )
    if gate_error:
        print(gate_error)
        return 1
    ensure_dir(Path(args.pass1_out))
    ensure_dir(Path(args.pass2_out))
    reset_assessor_outputs(Path(args.pass1_out))
    reset_assessor_outputs(Path(args.pass2_out))
    usage_log = Path("outputs/usage_log.jsonl")
    usage_log.parent.mkdir(parents=True, exist_ok=True)
    failure_log = Path("logs/llm_failures.jsonl")
    failure_log.parent.mkdir(parents=True, exist_ok=True)
    pass1_preflight_texts = texts
    if portfolio_scope:
        pass1_preflight_texts = {}
        for student_id, pieces in portfolio_pieces_by_student.items():
            if len(pieces) > 1:
                for piece in pieces:
                    pass1_preflight_texts[f"{student_id}::{piece.get('piece_id')}"] = str(piece.get("text", "") or "")
            else:
                pass1_preflight_texts[student_id] = texts.get(student_id, "")
    summaries = []
    raw_summary_map = {}
    for sid, text in texts.items():
        pieces = portfolio_pieces_by_student.get(sid, []) if portfolio_scope else []
        if len(pieces) > 1:
            summary = summarize_portfolio_pieces(pieces, args.max_summary_chars)
        else:
            summary = summarize_text(text, args.max_summary_chars)
        raw_summary_map[sid] = summary
        summaries.append({"student_id": sid, "summary": summary})
    if mode != "codex_local" and not args.ignore_cost_limits:
        pricing = load_json(Path(args.pricing))
        limits = load_json(Path(args.cost_limits))
        preflight = preflight_costs(
            pass1_preflight_texts,
            rubric,
            outline,
            summaries,
            routing,
            pricing,
            limits,
            grade_context,
            exemplar_block,
            student_count_override=len(texts),
        )
        if not preflight.get("ok"):
            print(f"Cost preflight failed: {preflight.get('reason')}")
            if limits.get("abort_on_limit", True):
                return 1
        else:
            per_student_max = limits.get("per_student_max_usd", None)
            per_job_max = limits.get("per_job_max_usd", None)
            alert_at = limits.get("alert_at_percent", 80)
            per_student_cost = preflight.get("per_student_cost", 0.0)
            total_cost = preflight.get("total_cost", 0.0)
            print(f"Estimated cost: ${total_cost:.2f} total (~${per_student_cost:.2f}/student)")
            if per_student_max and per_student_cost > per_student_max:
                msg = f"Estimated per-student cost ${per_student_cost:.2f} exceeds limit ${per_student_max:.2f}"
                print(msg)
                if limits.get("abort_on_limit", True):
                    return 1
            if per_job_max and total_cost > per_job_max:
                msg = f"Estimated total cost ${total_cost:.2f} exceeds job limit ${per_job_max:.2f}"
                print(msg)
                if limits.get("abort_on_limit", True):
                    return 1
            if per_job_max and total_cost > (per_job_max * (alert_at / 100.0)):
                print(f"Warning: estimated total cost ${total_cost:.2f} is above {alert_at}% of job limit ${per_job_max:.2f}")
    pass1_scores_by_assessor = {}
    pass1_items_by_assessor = {}
    model_successes = 0
    model_attempts = 0
    portfolio_piece_report = {"enabled": bool(portfolio_scope), "students": {}}
    min_piece_success_ratio = 0.6
    for assessor in assessors:
        scores = []
        for student_id, text in texts.items():
            pieces = portfolio_pieces_by_student.get(student_id, []) if portfolio_scope else []
            use_piece_mode = len(pieces) > 1
            model_attempts += 1
            if use_piece_mode:
                piece_items = []
                piece_successes = 0
                for piece in pieces:
                    piece_key = f"{student_id}::{piece.get('piece_id')}"
                    piece_text = str(piece.get("text", "") or "")
                    anchor_piece_item = deterministic_pass1_item(piece_key, piece_text, assessor, piece_required_ids, exemplars)
                    piece_notes_word_limit = _pass1_notes_word_limit(pass1_model, piece_mode=True)
                    base_prompt = build_portfolio_piece_prompt(
                        assessor,
                        rubric,
                        outline,
                        student_id,
                        piece,
                        len(pieces),
                        grade_context,
                        exemplar_block,
                        piece_criteria_block,
                        reqs,
                        notes_word_limit=piece_notes_word_limit,
                    )
                    prompt = base_prompt
                    piece_item = None
                    for attempt in range(3):
                        response = None
                        try:
                            response = responses_create(
                                model=pass1_model,
                                messages=[{"role": "user", "content": prompt}],
                                temperature=pass1_temp,
                                reasoning=pass1_reasoning,
                                routing_path=args.routing,
                                text_format=pass1_text_format(require_evidence),
                                max_output_tokens=pass1_max_tokens,
                            )
                            content = extract_text(response)
                            usage = extract_usage(response)
                            with usage_log.open("a", encoding="utf-8") as f:
                                f.write(
                                    json.dumps(
                                        {
                                            "task": "pass1_piece",
                                            "assessor": assessor,
                                            "student_id": student_id,
                                            "piece_id": piece.get("piece_id"),
                                            "usage": usage,
                                            "model": pass1_model,
                                        }
                                    ) + "\n"
                                )
                        except Exception as exc:
                            content = f"[model_error] {exc}"
                        try:
                            if mode == "codex_local" and looks_like_prompt_echo(content, piece_key):
                                raise ValueError("Model returned prompt echo instead of scored JSON.")
                            piece_item = parse_pass1_item(content, piece_key, piece_required_ids, reqs, piece_text, strict=False)
                            if str(piece_item.get("student_id", "")).strip() != piece_key:
                                raise ValueError("Pass1 response student_id mismatch.")
                            score = piece_item.get("rubric_total_points")
                            if not isinstance(score, (int, float)):
                                raise ValueError("Pass1 response missing numeric rubric_total_points.")
                            piece_item = strip_internal_fields(reconcile_pass1_item(piece_item, piece_required_ids))
                            piece_successes += 1
                            break
                        except ValueError as exc:
                            failure = {
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "task": "pass1_piece",
                                "assessor": assessor,
                                "student_id": student_id,
                                "piece_id": piece.get("piece_id"),
                                "attempt": attempt + 1,
                                "mode": mode,
                                "error": str(exc),
                                "response_preview": content[:2000],
                            }
                            with failure_log.open("a", encoding="utf-8") as f:
                                f.write(json.dumps(failure) + "\n")
                            prompt = build_pass1_repair_prompt(
                                piece_key,
                                content,
                                bool(piece_required_ids),
                                context_prompt=base_prompt,
                                error_hint=_response_incomplete_hint(response),
                                notes_word_limit=piece_notes_word_limit,
                            )
                    if piece_item is None:
                        if args.fallback == "deterministic":
                            piece_item = anchor_piece_item
                        else:
                            raise ValueError(f"Pass1 portfolio piece response invalid after retry. See {failure_log}.")
                    piece_item, _draft_quality = apply_draft_penalty(
                        piece_item,
                        piece_text,
                        str(piece_item.get("notes", "") or ""),
                    )
                    piece_items.append(piece_item)
                item, aggregation = aggregate_portfolio_piece_assessments(student_id, pieces, piece_items, assessor)
                scores.append(item)
                student_entry = portfolio_piece_report["students"].setdefault(
                    student_id,
                    {
                        "piece_count": len(pieces),
                        "pieces": [
                            {
                                "piece_id": piece.get("piece_id"),
                                "title": piece.get("title"),
                                "word_count": piece.get("word_count"),
                            }
                            for piece in pieces
                        ],
                        "assessors": {},
                    },
                )
                student_entry["assessors"][assessor] = aggregation
                if piece_successes > 0 and (piece_successes / max(1, len(pieces))) >= min_piece_success_ratio:
                    model_successes += 1
                continue

            anchor_item = deterministic_pass1_item(student_id, text, assessor, required_ids, exemplars)
            pass1_notes_word_limit = _pass1_notes_word_limit(pass1_model, piece_mode=False)
            prompt = build_pass1_prompt(
                assessor,
                rubric,
                outline,
                student_id,
                text,
                grade_context,
                exemplar_block,
                criteria_block,
                reqs,
                notes_word_limit=pass1_notes_word_limit,
            )
            base_prompt = prompt
            item = None
            item_used_model = False
            for attempt in range(3):
                response = None
                try:
                    response = responses_create(
                        model=pass1_model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=pass1_temp,
                        reasoning=pass1_reasoning,
                        routing_path=args.routing,
                        text_format=pass1_text_format(require_evidence),
                        max_output_tokens=pass1_max_tokens,
                    )
                    content = extract_text(response)
                    usage = extract_usage(response)
                    with usage_log.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"task": "pass1", "assessor": assessor, "student_id": student_id, "usage": usage, "model": pass1_model}) + "\n")
                except Exception as exc:
                    content = f"[model_error] {exc}"
                try:
                    if mode == "codex_local" and looks_like_prompt_echo(content, student_id):
                        raise ValueError("Model returned prompt echo instead of scored JSON.")
                    item = parse_pass1_item(content, student_id, required_ids, reqs, text, strict=False)
                    if str(item.get("student_id", "")).strip() != student_id:
                        raise ValueError("Pass1 response student_id mismatch.")
                    score = item.get("rubric_total_points")
                    if not isinstance(score, (int, float)):
                        raise ValueError("Pass1 response missing numeric rubric_total_points.")
                    item = reconcile_pass1_item(item, required_ids)
                    if guard_enabled:
                        scope_delta, scope_gap, scope_blend = guard_bias_for_exemplar_scope(
                            exemplar_selection.get("match_quality"),
                            guard_max_score_delta,
                            guard_max_level_gap,
                            guard_anchor_blend,
                        )
                        dyn_delta, dyn_gap, dyn_blend = guard_parameters(
                            item, scope_delta, scope_gap, scope_blend
                        )
                        item = stabilize_pass1_item(item, anchor_item, dyn_delta, dyn_gap, dyn_blend)
                    item = strip_internal_fields(item)
                    item_used_model = True
                    break
                except ValueError as exc:
                    failure = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "task": "pass1",
                        "assessor": assessor,
                        "student_id": student_id,
                        "attempt": attempt + 1,
                        "mode": mode,
                        "error": str(exc),
                        "response_preview": content[:2000],
                    }
                    with failure_log.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(failure) + "\n")
                    prompt = build_pass1_repair_prompt(
                        student_id,
                        content,
                        bool(required_ids),
                        context_prompt=base_prompt,
                        error_hint=_response_incomplete_hint(response),
                        notes_word_limit=pass1_notes_word_limit,
                    )
            if item is None:
                if args.fallback == "deterministic":
                    item = anchor_item
                else:
                    raise ValueError(f"Pass1 response invalid after retry. See {failure_log}.")
            item, _draft_quality = apply_draft_penalty(
                item,
                text,
                str(item.get("notes", "") or ""),
            )
            if item_used_model:
                model_successes += 1
            scores.append(item)
        pass1_scores_by_assessor[assessor] = {
            s["student_id"]: float(s.get("rubric_total_points", 0.0) or 0.0) for s in scores
        }
        pass1_items_by_assessor[assessor] = {
            s["student_id"]: s for s in scores
        }
        pass1_payload = {
            "assessor_id": f"assessor_{assessor}",
            "role": "llm_assessor",
            "rubric_points_possible": None,
            "scores": scores,
        }
        out_path = Path(args.pass1_out) / f"assessor_{assessor}.json"
        write_text_atomic(out_path, json.dumps(pass1_payload, indent=2))
    if portfolio_scope:
        write_portfolio_piece_report(Path(args.portfolio_piece_report), portfolio_piece_report)
    known_ids = list(texts.keys())
    portfolio_seed_order = unanimous_portfolio_seed_order(pass1_scores_by_assessor, known_ids) if portfolio_scope else None
    summary_seed_order = build_summary_seed_order(known_ids, texts, pass1_items_by_assessor) if use_summary_seed_order(metadata, genre, portfolio_scope) else None
    instructions_seed_order = build_instructions_seed_order(known_ids, pass1_items_by_assessor) if use_instructions_seed_order(metadata, genre, portfolio_scope) else None
    argumentative_seed_order = build_argumentative_seed_order(known_ids, pass1_items_by_assessor) if use_argumentative_seed_order(metadata, genre, portfolio_scope) else None
    literary_seed_order = build_literary_analysis_seed_order(known_ids, texts, pass1_items_by_assessor) if use_literary_analysis_seed_order(metadata, genre, portfolio_scope, texts, pass1_items_by_assessor) else None
    pass2_rankings_by_assessor = {}
    for assessor in assessors:
        score_order = ranking_from_scores(pass1_scores_by_assessor.get(assessor, {}), known_ids)
        ranking_contract = build_pass2_ranking_contract(genre, portfolio_scope, metadata)
        summary_item_source = pass1_items_by_assessor if (summary_seed_order or instructions_seed_order or argumentative_seed_order) else pass1_items_by_assessor.get(assessor, {})
        student_summaries = build_pass2_student_summaries(
            known_ids,
            raw_summary_map,
            texts,
            summary_item_source,
            genre,
            portfolio_scope,
            args.max_summary_chars,
            metadata,
        )
        prompt = build_pass2_prompt(
            assessor,
            rubric,
            outline,
            student_summaries,
            grade_context + ("\n\n" + ranking_contract if ranking_contract else ""),
        )
        error = ""
        try:
            model_attempts += 1
            response = responses_create(
                model=pass2_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=pass2_temp,
                reasoning=pass2_reasoning,
                routing_path=args.routing,
                text_format=pass2_text_format(),
                max_output_tokens=pass2_max_tokens,
            )
            content = extract_text(response)
            usage = extract_usage(response)
            with usage_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"task": "pass2", "assessor": assessor, "usage": usage, "model": pass2_model}) + "\n")
            try:
                lines, missing = normalize_full_ranking(content, known_ids)
                if not missing:
                    model_successes += 1
            except ValueError as exc:
                lines = []
                missing = known_ids
                error = str(exc)
        except Exception as exc:
            content = f"[model_error] {exc}"
            lines = []
            missing = known_ids
            error = str(exc)
        if error or missing:
            repair_prompt = build_pass2_repair_prompt(known_ids, content, missing)
            try:
                response = responses_create(
                    model=pass2_model,
                    messages=[{"role": "user", "content": repair_prompt}],
                    temperature=0.0,
                    reasoning=pass2_reasoning,
                    routing_path=args.routing,
                    text_format=pass2_text_format(),
                    max_output_tokens=pass2_max_tokens,
                )
                repair_content = extract_text(response)
                try:
                    lines, missing = normalize_full_ranking(repair_content, known_ids)
                    error = ""
                    if not missing:
                        model_successes += 1
                except ValueError as exc:
                    error = str(exc)
                    lines = list(score_order)
                    missing = []
            except Exception as exc:
                repair_content = f"[model_error] {exc}"
                error = str(exc)
                lines = list(score_order)
                missing = []
            if missing:
                for sid in score_order:
                    if sid not in missing:
                        continue
                    lines.append(sid)
            if error or missing:
                failure = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "task": "pass2",
                    "assessor": assessor,
                    "mode": mode,
                    "error": error or f"Missing ids after retry: {missing}",
                    "response_preview": content[:2000],
                    "response_repair_preview": repair_content[:2000],
                }
                with failure_log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(failure) + "\n")
        if not lines:
            lines = list(score_order)
        if portfolio_seed_order:
            lines = list(portfolio_seed_order)
        elif summary_seed_order:
            lines = list(summary_seed_order)
        elif instructions_seed_order:
            lines = list(instructions_seed_order)
        elif argumentative_seed_order:
            lines = list(argumentative_seed_order)
        elif literary_seed_order:
            lines = list(literary_seed_order)
        pass2_rankings_by_assessor[assessor] = list(lines)
        out_path = Path(args.pass2_out) / f"assessor_{assessor}.txt"
        write_text_atomic(out_path, "\n".join(lines))
    committee_report = build_committee_consensus_report(
        pass1_scores_by_assessor,
        pass2_rankings_by_assessor,
        known_ids,
        scope_grounding,
    )
    committee_report_path = Path(args.committee_report)
    committee_report_path.parent.mkdir(parents=True, exist_ok=True)
    committee_report_path.write_text(json.dumps(committee_report, indent=2), encoding="utf-8")
    if mode == "openai":
        print(f"Model coverage: {model_successes}/{model_attempts} successful structured outputs.")
        coverage = (model_successes / model_attempts) if model_attempts else 0.0
        if min_model_coverage > 0 and coverage < min_model_coverage:
            print(f"Model coverage {coverage:.2%} below gate {min_model_coverage:.2%}. Failing run.")
            return 1
        if args.require_model_usage and model_successes == 0:
            print("No model outputs were accepted; failing because --require-model-usage is set.")
            return 1
    print("LLM assessor runs completed.")
    return 0
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
