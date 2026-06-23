#!/usr/bin/env python3
"""Rubric-centered evidence and instructional summaries for teacher review.

This module is intentionally deterministic. It does not replace the assessor
passes; it packages their outputs into a defensible teacher-facing contract:
each score is presented as a claim tied to a rubric criterion, cited evidence,
counter-evidence, and uncertainty.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path


GENERIC_CRITERIA = [
    {
        "id": "task_alignment",
        "name": "Task Alignment",
        "canonical_dimension": "task_alignment",
        "weight": 0.25,
    },
    {
        "id": "content_reasoning",
        "name": "Content and Reasoning",
        "canonical_dimension": "ideas_analysis",
        "weight": 0.35,
    },
    {
        "id": "organization",
        "name": "Organization",
        "canonical_dimension": "organization",
        "weight": 0.2,
    },
    {
        "id": "language_control",
        "name": "Language Control",
        "canonical_dimension": "language_control",
        "weight": 0.2,
    },
]


DIMENSION_KEYWORDS = {
    "task_alignment": ("prompt", "theme", "claim", "answer", "assignment", "because", "shows"),
    "ideas_analysis": (
        "because",
        "shows",
        "means",
        "theme",
        "character",
        "evidence",
        "quote",
        "example",
        "this shows",
        "this means",
    ),
    "organization": ("first", "second", "finally", "conclusion", "topic", "paragraph", "also", "however"),
    "language_control": ("sentence", "word", "grammar", "spelling", "punctuation", "clear", "varied"),
    "criterion_other": ("because", "example", "evidence", "paragraph", "sentence", "shows"),
}


INSTRUCTION_TAGS = {
    "evidence_explanation": {
        "label": "Explain evidence after quoting or summarizing it",
        "lesson": "Mini-lesson: model a claim-evidence-explain paragraph and require one 'this shows' sentence after each example.",
    },
    "organization": {
        "label": "Strengthen paragraph order and topic/conclusion sentences",
        "lesson": "Mini-lesson: reorder one sample paragraph set and revise topic/conclusion sentences for flow.",
    },
    "language_control": {
        "label": "Run a focused conventions pass before submitting",
        "lesson": "Mini-lesson: edit three sentences for boundaries, punctuation, and precise word choice before revising the full draft.",
    },
    "task_alignment": {
        "label": "Answer the exact prompt with a stable claim",
        "lesson": "Mini-lesson: underline the prompt verbs, draft a one-sentence answer, then test every paragraph against it.",
    },
    "boundary_case": {
        "label": "Clarify level-boundary decisions with anchor papers",
        "lesson": "Calibration: compare boundary papers to teacher-scored anchors before finalizing marks.",
    },
    "high_disagreement": {
        "label": "Resolve split evidence through side-by-side review",
        "lesson": "Review: read disagreement pairs side by side and record which criterion actually decides the edge.",
    },
}


def canonical_hash(payload: str) -> str:
    return hashlib.sha256(str(payload or "").encode("utf-8")).hexdigest()


def sentences(text: str) -> list[str]:
    chunks = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text or "") if part.strip()]
    return chunks if chunks else ([text.strip()] if str(text or "").strip() else [])


def snippet(text: str, limit: int = 220) -> str:
    clean = " ".join(str(text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "..."


def _criteria(normalized_rubric: dict | None) -> list[dict]:
    items = (normalized_rubric or {}).get("criteria", []) if isinstance(normalized_rubric, dict) else []
    out = []
    for idx, item in enumerate(items if isinstance(items, list) else [], start=1):
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "id": str(item.get("id") or f"criterion_{idx}"),
                "name": str(item.get("name") or item.get("canonical_label") or f"Criterion {idx}"),
                "canonical_dimension": str(item.get("canonical_dimension") or "criterion_other"),
                "weight": float(item.get("weight", 0.0) or 0.0),
                "descriptor_summary": str(item.get("descriptor_summary", "") or ""),
            }
        )
    return out or list(GENERIC_CRITERIA)


def _keywords_for(criterion: dict) -> tuple[str, ...]:
    dim = str(criterion.get("canonical_dimension", "") or "criterion_other")
    name = str(criterion.get("name", "") or "").lower()
    tokens = list(DIMENSION_KEYWORDS.get(dim, DIMENSION_KEYWORDS["criterion_other"]))
    if "organization" in name or "structure" in name:
        tokens.extend(DIMENSION_KEYWORDS["organization"])
    if "language" in name or "convention" in name or "grammar" in name:
        tokens.extend(DIMENSION_KEYWORDS["language_control"])
    if "content" in name or "idea" in name or "analysis" in name:
        tokens.extend(DIMENSION_KEYWORDS["ideas_analysis"])
    return tuple(dict.fromkeys(tokens))


def _score_sentence(sentence: str, keywords: tuple[str, ...]) -> tuple[int, int]:
    low = sentence.lower()
    hits = sum(1 for keyword in keywords if keyword in low)
    return hits, len(sentence)


def select_evidence(text: str, keywords: tuple[str, ...], *, limit: int = 2) -> list[dict]:
    ranked = sorted(sentences(text), key=lambda item: _score_sentence(item, keywords), reverse=True)
    evidence = []
    for item in ranked[:limit]:
        quote = snippet(item)
        if not quote:
            continue
        evidence.append({"quote": quote, "hash": canonical_hash(quote)[:16], "source": "student_text"})
    return evidence


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _level_from_percent(percent: float) -> str:
    if percent >= 80:
        return "4"
    if percent >= 70:
        return "3"
    if percent >= 60:
        return "2"
    return "1"


def _counter_evidence(row: dict, criterion: dict, evidence: list[dict], flags: list[str]) -> tuple[list[str], list[str]]:
    counters = []
    tags = []
    dim = str(criterion.get("canonical_dimension", "") or "")
    conv = _num(row.get("conventions_mistake_rate_percent"), 0.0)
    rubric = _num(row.get("rubric_after_penalty_percent") or row.get("rubric_mean_percent"), 0.0)
    if not evidence:
        counters.append("No directly cited sentence was available for this criterion.")
        tags.append("evidence_explanation")
    if dim in {"ideas_analysis", "task_alignment"} and rubric < 70:
        counters.append("The draft needs clearer explanation of how evidence proves the claim.")
        tags.append("evidence_explanation")
    if dim == "organization" and rubric < 75:
        counters.append("Paragraph flow or topic/conclusion control may limit the criterion score.")
        tags.append("organization")
    if dim == "language_control" and conv >= 6:
        counters.append(f"Conventions signal is elevated at {conv:.1f}% mistake rate.")
        tags.append("language_control")
    if "boundary_case" in flags:
        counters.append("This paper is near a level boundary and should be compared with anchors.")
        tags.append("boundary_case")
    if "high_disagreement" in flags:
        counters.append("Pairwise evidence is split, so a teacher side-by-side read is warranted.")
        tags.append("high_disagreement")
    return counters, sorted(set(tags))


def _confidence(flags: list[str], evidence: list[dict], row: dict) -> dict:
    score = 0.86
    reasons = []
    if not evidence:
        score -= 0.18
        reasons.append("missing criterion citation")
    if "high_disagreement" in flags:
        score -= 0.18
        reasons.append("split pairwise evidence")
    if "boundary_case" in flags:
        score -= 0.12
        reasons.append("near level boundary")
    if "low_confidence_rerank_move" in flags:
        score -= 0.1
        reasons.append("low-confidence movement")
    conv = _num(row.get("conventions_mistake_rate_percent"), 0.0)
    if conv >= 10:
        score -= 0.08
        reasons.append("high conventions signal")
    score = max(0.0, min(1.0, score))
    label = "high"
    if score < 0.58:
        label = "teacher_read_required"
    elif score < 0.75:
        label = "medium"
    return {"score": round(score, 3), "label": label, "reasons": reasons}


def build_rubric_claims(
    row: dict,
    text: str,
    normalized_rubric: dict | None,
    uncertainty_flags: list[str] | None = None,
    uncertainty_reasons: list[str] | None = None,
) -> list[dict]:
    flags = [str(item) for item in (uncertainty_flags or []) if str(item)]
    reasons = [str(item) for item in (uncertainty_reasons or []) if str(item)]
    percent = _num(row.get("rubric_after_penalty_percent") or row.get("rubric_mean_percent"), 0.0)
    level = str(row.get("adjusted_level") or row.get("base_level") or _level_from_percent(percent))
    claims = []
    for criterion in _criteria(normalized_rubric):
        keywords = _keywords_for(criterion)
        evidence = select_evidence(text, keywords)
        counters, tags = _counter_evidence(row, criterion, evidence, flags)
        confidence = _confidence(flags, evidence, row)
        combined_reasons = list(dict.fromkeys([*(confidence.get("reasons", []) or []), *reasons]))
        claims.append(
            {
                "criterion_id": criterion["id"],
                "criterion_name": criterion["name"],
                "canonical_dimension": criterion["canonical_dimension"],
                "weight": criterion.get("weight", 0.0),
                "claim": f"Current evidence supports Level {level} / {round(percent)}% for {criterion['name']}.",
                "machine_percent": round(percent, 2),
                "machine_level": level,
                "evidence": evidence,
                "counter_evidence": counters,
                "uncertainty": {
                    **confidence,
                    "flags": flags,
                    "reasons": combined_reasons,
                },
                "instruction_tags": tags,
            }
        )
    return claims


def build_instructional_summary(students: list[dict]) -> dict:
    counts: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    for student in students:
        sid = str(student.get("student_id", "") or "")
        for claim in student.get("rubric_claims", []) or []:
            for tag in claim.get("instruction_tags", []) or []:
                counts[tag] = counts.get(tag, 0) + 1
                examples.setdefault(tag, [])
                if sid and len(examples[tag]) < 5:
                    examples[tag].append(sid)
        for flag in student.get("uncertainty_flags", []) or []:
            tag = str(flag)
            if tag in INSTRUCTION_TAGS:
                counts[tag] = counts.get(tag, 0) + 1
                examples.setdefault(tag, [])
                if sid and len(examples[tag]) < 5:
                    examples[tag].append(sid)
    misconceptions = []
    for tag, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        info = INSTRUCTION_TAGS.get(tag, {"label": tag.replace("_", " "), "lesson": "Review the tagged essays and record a teacher decision."})
        misconceptions.append(
            {
                "tag": tag,
                "label": info["label"],
                "count": count,
                "student_ids": examples.get(tag, []),
                "mini_lesson": info["lesson"],
            }
        )
    return {
        "misconceptions": misconceptions,
        "mini_lessons": [item["mini_lesson"] for item in misconceptions[:4]],
        "teacher_message": "Use these clusters to turn grading into the next writing lesson.",
    }


def scan_pii_text(text: str) -> dict:
    return {
        "email_count": len(re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text or "")),
        "phone_like_count": len(re.findall(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b", text or "")),
        "long_id_count": len(re.findall(r"\b\d{10,}\b", text or "")),
    }


def build_data_posture(root: Path) -> dict:
    root = Path(root)
    paths = {
        "inputs_submissions": root / "inputs" / "submissions",
        "processing_text": root / "processing" / "normalized_text",
        "outputs": root / "outputs",
        "projects": root / "projects",
    }
    counts = {}
    pii_counts = {"email_count": 0, "phone_like_count": 0, "long_id_count": 0}
    for name, path in paths.items():
        files = [item for item in path.rglob("*") if item.is_file()] if path.exists() else []
        counts[name] = len(files)
        for file_path in files:
            if file_path.suffix.lower() not in {".txt", ".md", ".json", ".csv"}:
                continue
            try:
                scan = scan_pii_text(file_path.read_text(encoding="utf-8", errors="ignore")[:200000])
            except OSError:
                continue
            for key, value in scan.items():
                pii_counts[key] += int(value)
    return {
        "status": "local_private_workspace",
        "teacher_message": "Student work is stored only in local/private project data for this workspace. Use project delete/export controls for lifecycle cleanup.",
        "file_counts": counts,
        "pii_scan": pii_counts,
        "retention_controls": {
            "project_delete_available": True,
            "browser_draft_clear_available": True,
            "aggregate_learning_finalized_only": True,
        },
    }
