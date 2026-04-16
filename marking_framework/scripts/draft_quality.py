#!/usr/bin/env python3
import re


SCAFFOLD_HEADING_RE = re.compile(
    r"^\s*(?P<label>"
    r"thesis|claim|reason|reasoning|evidence|proof|explanation|analysis|topic sentence|"
    r"concluding sentence|cite/?detail|detail|sum-?up the argument|reflect on the theme|"
    r"reflect|closing reflection|commentary"
    r")(?:\s+\d+)?\s*:\s*(?P<body>.*)$",
    re.IGNORECASE,
)

INCOMPLETE_NOTE_TOKENS = (
    "incomplete",
    "fragmentary",
    "placeholder",
    "graphic organizer",
    "sentence starter",
    "unfinished",
    "partially completed",
    "underdeveloped structure",
)

TRAILING_SENTENCE_PUNCTUATION = (".", "!", "?", '"', "'", "”", "’", "…")


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", str(text or "")))


def _ends_with_terminal_punctuation(text: str) -> bool:
    stripped = str(text or "").strip()
    return bool(stripped) and stripped.endswith(TRAILING_SENTENCE_PUNCTUATION)


def analyze_draft_quality(text: str, notes: str = "") -> dict:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    placeholder_lines = []
    blank_placeholder_lines = []
    partial_placeholder_lines = []
    unfinished_placeholder_clauses = []

    for line in lines:
        match = SCAFFOLD_HEADING_RE.match(line)
        if not match:
            continue
        placeholder_lines.append(line)
        tail = str(match.group("body") or "").strip()
        tail_words = _word_count(tail)
        if not tail:
            blank_placeholder_lines.append(line)
        elif tail_words <= 6:
            partial_placeholder_lines.append(line)
        if tail and tail_words <= 8 and not _ends_with_terminal_punctuation(tail):
            unfinished_placeholder_clauses.append(line)

    note_text = str(notes or "").strip().lower()
    note_incomplete = any(token in note_text for token in INCOMPLETE_NOTE_TOKENS)
    last_line = lines[-1] if lines else ""
    abrupt_placeholder_ending = bool(last_line and SCAFFOLD_HEADING_RE.match(last_line))

    penalty = 0.0
    penalty += 3.0 * len(placeholder_lines)
    penalty += 5.0 * len(blank_placeholder_lines)
    penalty += 3.0 * len(partial_placeholder_lines)
    penalty += 4.0 * len(unfinished_placeholder_clauses)
    if len(placeholder_lines) >= 3:
        penalty += 6.0
    if note_incomplete:
        penalty += 4.0
    if abrupt_placeholder_ending:
        penalty += 6.0
    hard_floor_incomplete = (
        len(placeholder_lines) >= 3
        and (
            bool(blank_placeholder_lines)
            or bool(unfinished_placeholder_clauses)
            or abrupt_placeholder_ending
        )
    )
    if hard_floor_incomplete:
        penalty = max(penalty, 34.0)
    penalty = min(40.0, penalty)

    reasons = []
    if placeholder_lines:
        reasons.append(f"scaffold headings present ({len(placeholder_lines)})")
    if blank_placeholder_lines:
        reasons.append(f"blank scaffold prompts ({len(blank_placeholder_lines)})")
    if partial_placeholder_lines:
        reasons.append(f"unfinished scaffold responses ({len(partial_placeholder_lines)})")
    if unfinished_placeholder_clauses:
        reasons.append(f"broken scaffold clauses ({len(unfinished_placeholder_clauses)})")
    if note_incomplete:
        reasons.append("assessor notes already describe the draft as incomplete/fragmentary")
    if abrupt_placeholder_ending:
        reasons.append("response ends on an unfinished scaffold prompt")
    if hard_floor_incomplete:
        reasons.append("incomplete scaffold draft triggers completion-integrity floor")

    if penalty >= 16.0:
        severity = "high"
    elif penalty >= 8.0:
        severity = "medium"
    elif penalty > 0.0:
        severity = "low"
    else:
        severity = "none"

    return {
        "penalty_points": round(penalty, 2),
        "severity": severity,
        "placeholder_line_count": len(placeholder_lines),
        "blank_placeholder_count": len(blank_placeholder_lines),
        "partial_placeholder_count": len(partial_placeholder_lines),
        "unfinished_placeholder_clause_count": len(unfinished_placeholder_clauses),
        "note_incomplete": note_incomplete,
        "abrupt_placeholder_ending": abrupt_placeholder_ending,
        "hard_floor_incomplete": hard_floor_incomplete,
        "reasons": reasons,
        "placeholder_lines": placeholder_lines[:8],
    }


def apply_draft_penalty(item: dict, text: str, notes: str = "") -> tuple[dict, dict]:
    signals = analyze_draft_quality(text, notes)
    penalty = float(signals.get("penalty_points", 0.0) or 0.0)
    if penalty <= 0.0:
        return item, signals

    updated = dict(item or {})
    original_total = float(updated.get("rubric_total_points", 0.0) or 0.0)
    updated_total = max(0.0, original_total - penalty)
    updated["rubric_total_points"] = round(updated_total, 2)

    criteria = updated.get("criteria_points")
    if isinstance(criteria, dict) and criteria:
        shifted = {}
        for key, value in criteria.items():
            try:
                shifted[key] = round(max(0.0, float(value) - penalty), 2)
            except (TypeError, ValueError):
                shifted[key] = value
        updated["criteria_points"] = shifted

    warning = "incomplete_scaffold_draft"
    warnings = updated.get("warnings")
    if isinstance(warnings, list):
        if warning not in warnings:
            warnings.append(warning)
    else:
        updated["warnings"] = [warning]

    note_suffix = (
        f"Deterministic draft-completion penalty applied ({penalty:.2f}) due to "
        + ", ".join(signals.get("reasons", [])[:3])
        + "."
    )
    note_text = str(updated.get("notes", "") or "").strip()
    updated["notes"] = f"{note_text} | {note_suffix}" if note_text else note_suffix
    updated["draft_completion_penalty_points"] = round(penalty, 2)
    updated["draft_completion_severity"] = signals.get("severity", "none")
    updated["draft_completion_floor_applied"] = bool(signals.get("hard_floor_incomplete"))
    return updated, signals
