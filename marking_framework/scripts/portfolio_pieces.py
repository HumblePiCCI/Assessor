#!/usr/bin/env python3
import json
import math
import re
from pathlib import Path
from statistics import median

try:
    from scripts.levels import normalize_level
except ImportError:  # pragma: no cover - Running as a script
    from levels import normalize_level  # pragma: no cover


LEVEL_RANGES = {
    "1": (50.0, 59.0),
    "2": (60.0, 69.0),
    "3": (70.0, 79.0),
    "4": (80.0, 89.0),
    "4+": (90.0, 100.0),
}


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(value)))


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", str(text or ""))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = _mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / len(values))


def _truncate(text: str, max_chars: int) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if max_chars and len(compact) > max_chars:
        return compact[:max_chars].rstrip() + "..."
    return compact


def _extract_title(chunk: str, piece_index: int) -> str:
    lines = [line.strip() for line in str(chunk or "").splitlines() if line.strip()]
    if not lines:
        return f"Piece {piece_index}"
    first = lines[0]
    word_count = len(_words(first))
    if word_count <= 14:
        return first
    compact = _truncate(first, 48)
    return compact or f"Piece {piece_index}"


def split_portfolio_pieces(text: str) -> list[dict]:
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", str(text or "")) if chunk.strip()]
    if not chunks:
        return []
    pieces = []
    for idx, chunk in enumerate(chunks, start=1):
        pieces.append(
            {
                "piece_id": f"p{idx:02d}",
                "title": _extract_title(chunk, idx),
                "text": chunk,
                "word_count": len(_words(chunk)),
                "summary": _truncate(chunk, 180),
            }
        )
    return pieces


def summarize_portfolio_pieces(pieces: list[dict], max_chars: int) -> str:
    if not pieces:
        return ""
    item_budget = max(60, int(max_chars / max(1, min(len(pieces), 6))))
    parts = []
    for piece in pieces[:6]:
        title = piece.get("title") or piece.get("piece_id") or "Piece"
        summary = _truncate(piece.get("text", ""), item_budget)
        parts.append(f"{title}: {summary}")
    return _truncate(" | ".join(parts), max_chars)


def _piece_band(score: float) -> str:
    level = normalize_level(score)
    return level or "1"


def _band_count(scores: list[float], threshold: float) -> int:
    return sum(1 for score in scores if float(score) >= threshold)


def _lower_half_mean(scores: list[float]) -> float:
    if not scores:
        return 0.0
    ordered = sorted(float(score) for score in scores)
    return _mean(ordered[: max(1, math.ceil(len(ordered) / 2.0))])


def _upper_half_mean(scores: list[float]) -> float:
    if not scores:
        return 0.0
    ordered = sorted(float(score) for score in scores)
    return _mean(ordered[len(ordered) // 2 :])


def _portfolio_level_from_scores(scores: list[float], raw_score: float) -> str:
    if not scores:
        return "1"
    count = len(scores)
    med = median(scores)
    lower = _lower_half_mean(scores)
    support_4 = _band_count(scores, 80.0)
    support_3 = _band_count(scores, 70.0)
    support_2 = _band_count(scores, 60.0)
    if raw_score >= 90.0 and support_4 == count:
        return "4+"
    if (
        raw_score >= 82.0
        or (support_4 >= max(2, math.ceil(count * 0.40)) and med >= 76.0 and lower >= 72.0)
    ):
        return "4"
    if raw_score >= 72.0 or (support_3 >= max(2, math.ceil(count * 0.60)) and med >= 70.0 and lower >= 64.0):
        return "3"
    if raw_score >= 62.0 or support_2 >= max(1, math.ceil(count * 0.50)):
        return "2"
    return "1"


def _score_anchor_for_level(level: str) -> float:
    low, high = LEVEL_RANGES.get(level, LEVEL_RANGES["1"])
    return round((low + high) / 2.0, 2)


def _robust_portfolio_score(scores: list[float]) -> tuple[float, dict]:
    if not scores:
        return 0.0, {"median": 0.0, "lower_half_mean": 0.0, "upper_half_mean": 0.0, "stdev": 0.0}
    med = float(median(scores))
    lower = float(_lower_half_mean(scores))
    upper = float(_upper_half_mean(scores))
    deviation = float(_stdev(scores))
    raw = (0.45 * med) + (0.35 * lower) + (0.20 * upper)
    if deviation > 10.0:
        raw -= min(6.0, (deviation - 10.0) * 0.40)
    elif deviation < 5.0 and len(scores) >= 4:
        raw += 0.75
    return _clamp(raw), {
        "median": round(med, 2),
        "lower_half_mean": round(lower, 2),
        "upper_half_mean": round(upper, 2),
        "stdev": round(deviation, 2),
    }


def _clamp_score_to_level(score: float, level: str) -> float:
    low, high = LEVEL_RANGES.get(level, LEVEL_RANGES["1"])
    return round(_clamp(score, low, high), 2)


def _aggregate_numeric(values: list[float]) -> float:
    score, _stats = _robust_portfolio_score(values)
    level = _portfolio_level_from_scores(values, score)
    return _clamp_score_to_level(score, level)


def _aggregate_criteria(piece_items: list[dict]) -> dict[str, float]:
    by_criterion: dict[str, list[float]] = {}
    for item in piece_items:
        for criterion_id, score in (item.get("criteria_points") or {}).items():
            if isinstance(score, (int, float)):
                by_criterion.setdefault(str(criterion_id), []).append(float(score))
    aggregated = {}
    for criterion_id, scores in by_criterion.items():
        aggregated[criterion_id] = round(_aggregate_numeric(scores), 2)
    return aggregated


def _portfolio_note(level: str, piece_scores: list[float], titles: list[str]) -> str:
    label = {
        "1": "Overall working below the expected standard across the portfolio.",
        "2": "Overall working towards the expected standard across the portfolio.",
        "3": "Overall working at the expected standard across the portfolio.",
        "4": "Overall working at greater depth across the portfolio.",
        "4+": "Overall working at exceptional depth across the portfolio.",
    }.get(level, "Overall portfolio judgment unavailable.")
    counts: dict[str, int] = {}
    for score in piece_scores:
        counts[_piece_band(score)] = counts.get(_piece_band(score), 0) + 1
    profile = ", ".join(f"{count} piece(s) at level {lvl}" for lvl, count in sorted(counts.items()))
    title_preview = ", ".join(title for title in titles[:4] if title)
    parts = [label]
    if profile:
        parts.append(f"Piece profile: {profile}.")
    if title_preview:
        parts.append(f"Pieces: {title_preview}.")
    return " ".join(parts).strip()


def aggregate_portfolio_piece_assessments(
    student_id: str,
    pieces: list[dict],
    piece_items: list[dict],
    assessor_id: str | None = None,
) -> tuple[dict, dict]:
    scores = [float(item.get("rubric_total_points", 0.0) or 0.0) for item in piece_items]
    raw_score, stats = _robust_portfolio_score(scores)
    overall_level = _portfolio_level_from_scores(scores, raw_score)
    overall_score = _clamp_score_to_level(raw_score, overall_level)
    criteria_points = _aggregate_criteria(piece_items)
    titles = [str(piece.get("title", "")) for piece in pieces]
    note = _portfolio_note(overall_level, scores, titles)

    piece_rows = []
    for piece, item in zip(pieces, piece_items):
        piece_score = float(item.get("rubric_total_points", 0.0) or 0.0)
        piece_rows.append(
            {
                "piece_id": piece.get("piece_id"),
                "title": piece.get("title"),
                "word_count": piece.get("word_count"),
                "rubric_total_points": round(piece_score, 2),
                "level": _piece_band(piece_score),
                "notes": item.get("notes", ""),
            }
        )

    aggregate_item = {
        "student_id": student_id,
        "rubric_total_points": overall_score,
        "criteria_points": criteria_points,
        "criteria_evidence": [],
        "notes": note,
        "portfolio_overall_level": overall_level,
        "portfolio_piece_count": len(piece_rows),
        "portfolio_piece_scores": piece_rows,
        "portfolio_aggregation": {
            "assessor_id": assessor_id,
            "raw_score": round(raw_score, 2),
            "overall_level": overall_level,
            "piece_score_stats": stats,
        },
    }
    report = {
        "student_id": student_id,
        "assessor_id": assessor_id,
        "piece_count": len(piece_rows),
        "overall_score": overall_score,
        "overall_level": overall_level,
        "piece_score_stats": stats,
        "pieces": piece_rows,
    }
    return aggregate_item, report


def write_report(path: Path, report: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
