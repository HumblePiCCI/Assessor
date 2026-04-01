#!/usr/bin/env python3
import copy
import json
import re
from pathlib import Path

try:
    from scripts.aggregate_helpers import get_level_band, get_level_bands
except ImportError:  # pragma: no cover - Running as a script
    from aggregate_helpers import get_level_band, get_level_bands  # pragma: no cover


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clean_text(value: str | None) -> str:
    return " ".join(str(value or "").lower().split())


def parse_portfolio_note_signal(note: str | None) -> dict | None:
    text = _clean_text(note)
    if not text:
        return None

    reasons = []
    estimate = None

    if re.search(r"\b(wts|working towards)\b", text):
        if re.search(r"low[- ]expected|low[- ]exs|boundary|near expected|towards/low|towards / low", text):
            estimate = 2.3
            reasons.append("working_towards_boundary")
        else:
            estimate = 2.0
            reasons.append("working_towards")
    elif re.search(r"\bworking at(?: the)? expected standard\b|\bexpected standard\b|\bexs\b", text):
        if re.search(r"greater depth|above expected|toward(?:s)? greater depth|near greater depth|at/near greater depth", text):
            estimate = 3.55
            reasons.append("expected_plus_strengths")
        else:
            estimate = 3.0
            reasons.append("expected_standard")
    elif re.search(r"greater depth|above expected|toward(?:s)? greater depth|near greater depth|at/near greater depth|greater-depth control", text):
        estimate = 3.6
        reasons.append("greater_depth")

    if estimate is None:
        positives = 0
        negatives = 0
        positive_markers = (
            "strong range",
            "generally effective",
            "effective execution",
            "clear understanding",
            "solid execution",
            "confident",
            "sophisticated",
            "coherent",
            "above expected",
        )
        negative_markers = (
            "frequent spelling errors",
            "inconsistent punctuation",
            "reduces clarity",
            "working towards",
            "not secure",
            "uneven",
            "inconsistent across pieces",
            "low expected",
        )
        positives = sum(1 for marker in positive_markers if marker in text)
        negatives = sum(1 for marker in negative_markers if marker in text)
        if positives or negatives:
            estimate = max(2.0, min(3.6, 3.0 + (0.18 * positives) - (0.2 * negatives)))
            reasons.append("sentiment_fallback")

    if estimate is None:
        return None

    return {
        "estimate": round(float(estimate), 2),
        "reasons": reasons,
    }


def signal_from_portfolio_fields(score: dict | None) -> dict | None:
    if not isinstance(score, dict):
        return None
    level = str(score.get("portfolio_overall_level", "") or "").strip()
    if not level:
        aggregation = score.get("portfolio_aggregation") or {}
        level = str(aggregation.get("overall_level", "") or "").strip()
    mapping = {
        "1": 1.0,
        "2": 2.0,
        "3": 3.0,
        "4": 3.6,
        "4+": 4.2,
    }
    estimate = mapping.get(level)
    if estimate is None:
        return None
    return {
        "estimate": round(float(estimate), 2),
        "reasons": ["portfolio_piece_aggregation"],
    }


def _score_range_for_estimate(estimate: float) -> dict:
    value = float(estimate)
    if value >= 3.45:
        return {"canonical_level": "4", "min_score": 80.0, "max_score": 89.0, "anchor_score": 84.0}
    if value >= 3.05:
        return {"canonical_level": "4", "min_score": 74.0, "max_score": 84.0, "anchor_score": 79.0}
    if value >= 2.55:
        return {"canonical_level": "3", "min_score": 70.0, "max_score": 79.0, "anchor_score": 74.0}
    if value >= 2.2:
        return {"canonical_level": "3", "min_score": 64.0, "max_score": 74.0, "anchor_score": 69.0}
    if value < 1.75:
        return {"canonical_level": "1", "min_score": 50.0, "max_score": 59.0, "anchor_score": 54.0}
    return {"canonical_level": "2", "min_score": 60.0, "max_score": 69.0, "anchor_score": 64.0}


def _student_summary(votes: list[dict]) -> dict:
    if not votes:
        return {}
    estimates = [float(vote["estimate"]) for vote in votes]
    mean_estimate = sum(estimates) / len(estimates)
    score_range = _score_range_for_estimate(mean_estimate)
    return {
        "note_votes": len(votes),
        "note_estimate_mean": round(mean_estimate, 2),
        "note_canonical_level": score_range["canonical_level"],
        "note_anchor_score": score_range["anchor_score"],
    }


def apply_portfolio_mode(pass1: list[dict], config: dict, scope: dict | None = None) -> tuple[list[dict], dict]:
    portfolio_cfg = (config or {}).get("portfolio_mode", {}) if isinstance(config, dict) else {}
    scope = scope or {}
    if not portfolio_cfg.get("enabled", False) or not scope.get("is_portfolio"):
        return pass1, {"enabled": False, "applied": 0, "student_summaries": {}, "assessor_adjustments": []}

    updated = copy.deepcopy(pass1)
    clamp_threshold = _num(portfolio_cfg.get("note_clamp_threshold"), 4.0)
    adjustments = []
    notes_by_student: dict[str, list[dict]] = {}

    for assessor in updated:
        assessor_id = str(assessor.get("assessor_id", "")).strip()
        for score in assessor.get("scores", []):
            student_id = str(score.get("student_id", "")).strip()
            signal = signal_from_portfolio_fields(score) or parse_portfolio_note_signal(score.get("notes"))
            if signal is None:
                continue
            score_range = _score_range_for_estimate(signal["estimate"])
            notes_by_student.setdefault(student_id, []).append(signal)
            original_total = score.get("rubric_total_points")
            if original_total is None:
                criteria = score.get("criteria_points", {})
                original_total = sum(v for v in criteria.values() if isinstance(v, (int, float)))
            total = _num(original_total, 0.0)
            clamped = max(score_range["min_score"], min(score_range["max_score"], total))
            if abs(clamped - total) >= clamp_threshold:
                score["rubric_total_points"] = round(clamped, 2)
                score["portfolio_note_estimate"] = signal["estimate"]
                score["portfolio_note_level"] = score_range["canonical_level"]
                score["portfolio_note_adjusted"] = True
                adjustments.append(
                    {
                        "assessor_id": assessor_id,
                        "student_id": student_id,
                        "from_score": round(total, 2),
                        "to_score": round(clamped, 2),
                        "note_estimate": signal["estimate"],
                        "note_level": score_range["canonical_level"],
                        "reasons": signal["reasons"],
                    }
                )
            else:
                score["portfolio_note_estimate"] = signal["estimate"]
                score["portfolio_note_level"] = score_range["canonical_level"]
                score["portfolio_note_adjusted"] = False

    student_summaries = {student_id: _student_summary(votes) for student_id, votes in notes_by_student.items()}
    report = {
        "enabled": True,
        "applied": len(adjustments),
        "assessor_adjustments": adjustments,
        "student_summaries": student_summaries,
        "scope": {
            "grade_level": scope.get("grade_level"),
            "genre": scope.get("genre"),
            "assessment_unit": scope.get("assessment_unit"),
        },
    }
    return updated, report


def write_report(path: Path, report: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
