#!/usr/bin/env python3
"""Copyright-safe source calibration helpers.

The source pack stores links, score-scale metadata, and distilled teacher
calibration rules from public exemplar sources. It intentionally does not store
full student responses or long source quotations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from scripts.assessor_context import normalize_genre
except ImportError:  # pragma: no cover - Support running as a standalone script
    from assessor_context import normalize_genre  # type: ignore  # pragma: no cover


DEFAULT_SOURCE_CALIBRATION = (
    Path(__file__).resolve().parents[1]
    / "inputs"
    / "calibration_sources"
    / "writing_assessment_sources.json"
)

DISALLOWED_CONTENT_KEYS = {
    "student_response",
    "student_responses",
    "sample_text",
    "sample_texts",
    "essay_text",
    "essay_texts",
    "full_response",
    "full_responses",
    "verbatim_response",
    "verbatim_responses",
}


def load_source_calibration(path: str | Path | None = None) -> dict:
    """Load the source-calibration manifest, returning {} when unavailable."""

    source_path = Path(path) if path else DEFAULT_SOURCE_CALIBRATION
    if not source_path.exists():
        return {}
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_grade_level(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        text = str(value).strip().lower().replace("grade", "").strip()
        try:
            return int(text)
        except (TypeError, ValueError):
            return None


def canonical_genre(value: str | None) -> str:
    return normalize_genre(value or "") or "generic"


def source_genres(source: dict) -> set[str]:
    raw = source.get("genres") if isinstance(source.get("genres"), list) else []
    writing_types = source.get("writing_types") if isinstance(source.get("writing_types"), list) else []
    return {canonical_genre(str(item)) for item in [*raw, *writing_types] if str(item or "").strip()}


def source_grades(source: dict) -> list[int]:
    grades = []
    for item in source.get("grades", []) if isinstance(source.get("grades"), list) else []:
        parsed = parse_grade_level(item)
        if parsed is not None:
            grades.append(parsed)
    return sorted(set(grades))


def grade_distance(source: dict, grade_level: int | None) -> int:
    if grade_level is None:
        return 0
    grades = source_grades(source)
    if not grades:
        return 99
    return min(abs(grade_level - grade) for grade in grades)


def source_matches_genre(source: dict, genre: str) -> bool:
    normalized = canonical_genre(genre)
    genres = source_genres(source)
    if not genres:
        return False
    if normalized in genres:
        return True
    if normalized == "literary_analysis" and "text_based_response" in genres:
        return True
    if normalized in {"informational_report", "summary_report"} and "explanatory" in genres:
        return True
    if normalized == "argumentative" and "opinion_argument" in genres:
        return True
    return "all_writing" in genres


def utility_rank(source: dict) -> int:
    raw = str(source.get("utility") or "").strip().lower()
    return {
        "core": 0,
        "strong": 1,
        "supplemental": 2,
        "stretch": 3,
        "watchlist": 4,
    }.get(raw, 5)


def selected_sources(
    payload: dict,
    *,
    genre: str = "",
    grade_level: int | None = None,
    max_sources: int = 8,
) -> list[dict]:
    """Select the most relevant sources for a prompt context."""

    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    normalized_genre = canonical_genre(genre)
    scored = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        genre_match = source_matches_genre(source, normalized_genre)
        # Keep strong cross-grade/cross-genre sources available, but rank exact
        # genre and nearby-grade anchors first.
        score = (
            0 if genre_match else 2,
            grade_distance(source, grade_level),
            utility_rank(source),
            str(source.get("id") or ""),
        )
        scored.append((score, source))
    return [source for _, source in sorted(scored, key=lambda item: item[0])[: max(0, int(max_sources))]]


def selected_rules(
    payload: dict,
    *,
    genre: str = "",
    grade_level: int | None = None,
    max_sources: int = 8,
    max_rules: int = 18,
) -> list[dict]:
    """Return distilled rules from the selected source set."""

    rules: list[dict] = []
    normalized_genre = canonical_genre(genre)
    for source in selected_sources(payload, genre=normalized_genre, grade_level=grade_level, max_sources=max_sources):
        source_id = str(source.get("id") or "").strip()
        for raw in source.get("calibration_rules", []) if isinstance(source.get("calibration_rules"), list) else []:
            if not isinstance(raw, dict):
                continue
            applies_to = {
                canonical_genre(str(item))
                for item in raw.get("applies_to", [])
                if str(item or "").strip()
            } if isinstance(raw.get("applies_to"), list) else set()
            if applies_to and normalized_genre not in applies_to and "all_writing" not in applies_to:
                continue
            text = str(raw.get("rule") or "").strip()
            if not text:
                continue
            rules.append(
                {
                    "source_id": source_id,
                    "id": str(raw.get("id") or "").strip(),
                    "priority": str(raw.get("priority") or "").strip() or "medium",
                    "rule": text,
                }
            )
            if len(rules) >= max(0, int(max_rules)):
                return rules
    return rules


def format_source_calibration_lines(
    payload: dict,
    *,
    genre: str = "",
    grade_level: int | None = None,
    max_sources: int = 8,
    max_rules: int = 18,
) -> list[str]:
    """Format source calibration as compact prompt details."""

    if not payload:
        return []
    sources = selected_sources(payload, genre=genre, grade_level=grade_level, max_sources=max_sources)
    rules = selected_rules(
        payload,
        genre=genre,
        grade_level=grade_level,
        max_sources=max_sources,
        max_rules=max_rules,
    )
    if not sources and not rules:
        return []
    source_labels = [
        f"{source.get('id', '')} ({source.get('provider', '')}; {source.get('scale', {}).get('label', '')})"
        for source in sources
        if str(source.get("id") or "").strip()
    ]
    lines = [
        (
            "External teacher-scored calibration sources are active. Use only the distilled calibration rules; "
            "do not quote, reproduce, or infer any full source essay text."
        )
    ]
    if source_labels:
        lines.append("Selected calibration source families: " + "; ".join(source_labels))
    if rules:
        lines.append("Source-derived calibration rules:")
        for rule in rules:
            prefix = f"{rule['source_id']}:{rule['id']}" if rule.get("id") else str(rule.get("source_id") or "")
            lines.append(f"{prefix}: {rule['rule']}")
    global_rules = payload.get("global_anchor_rules") if isinstance(payload.get("global_anchor_rules"), list) else []
    if global_rules:
        lines.append("Global source-pack guardrails:")
        for raw in global_rules[:6]:
            text = str(raw.get("rule") if isinstance(raw, dict) else raw).strip()
            if text:
                lines.append(text)
    return [line for line in lines if line.strip()]


def _walk_content_keys(value: Any, path: str = "") -> list[str]:
    errors = []
    if isinstance(value, dict):
        for key, child in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            if str(key) in DISALLOWED_CONTENT_KEYS:
                errors.append(f"disallowed raw-content key: {next_path}")
            errors.extend(_walk_content_keys(child, next_path))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            errors.extend(_walk_content_keys(child, f"{path}[{idx}]"))
    return errors


def validate_source_calibration(payload: dict) -> list[str]:
    """Return manifest validation errors."""

    errors: list[str] = []
    if not isinstance(payload, dict) or not payload:
        return ["manifest is empty or not an object"]
    if not isinstance(payload.get("sources"), list) or not payload["sources"]:
        errors.append("sources must be a non-empty list")
    for idx, source in enumerate(payload.get("sources", [])):
        if not isinstance(source, dict):
            errors.append(f"sources[{idx}] must be an object")
            continue
        for key in ("id", "name", "provider", "url", "genres", "scale", "calibration_rules", "rights_note"):
            if key not in source:
                errors.append(f"{source.get('id', f'sources[{idx}]')}: missing {key}")
        if not str(source.get("url") or "").startswith("http"):
            errors.append(f"{source.get('id', f'sources[{idx}]')}: url must be http(s)")
        if not isinstance(source.get("calibration_rules"), list) or not source.get("calibration_rules"):
            errors.append(f"{source.get('id', f'sources[{idx}]')}: calibration_rules must be non-empty")
    errors.extend(_walk_content_keys(payload))
    return errors

