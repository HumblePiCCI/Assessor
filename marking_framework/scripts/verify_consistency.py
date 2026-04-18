#!/usr/bin/env python3
import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.assessor_utils import load_file_text, resolve_input_path
    from scripts.assessor_context import load_class_metadata, normalize_genre
    from scripts.global_rerank import run_global_rerank
    from scripts.llm_assessors_core import json_from_text
    from scripts.levels import normalize_level
    from scripts.openai_client import extract_text, responses_create
    from scripts.draft_quality import analyze_draft_quality
except ImportError:  # pragma: no cover - Support running as script without package context
    from assessor_utils import load_file_text, resolve_input_path  # pragma: no cover
    from assessor_context import load_class_metadata, normalize_genre  # pragma: no cover
    from global_rerank import run_global_rerank  # pragma: no cover
    from llm_assessors_core import json_from_text  # pragma: no cover
    from levels import normalize_level  # pragma: no cover
    from openai_client import extract_text, responses_create  # pragma: no cover
    from draft_quality import analyze_draft_quality  # pragma: no cover


RESPONSE_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "winner_side": {"type": "string", "enum": ["A", "B"]},
            "decision": {"type": "string", "enum": ["KEEP", "SWAP"]},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "rationale": {"type": "string"},
            "criterion_notes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "criterion": {"type": "string"},
                        "stronger": {"type": "string", "enum": ["A", "B", "tie"]},
                        "reason": {"type": "string"},
                    },
                    "required": ["criterion", "stronger", "reason"],
                    "additionalProperties": False,
                },
            },
            "decision_basis": {
                "type": "string",
                "enum": [
                    "task_alignment",
                    "content_reasoning",
                    "evidence_development",
                    "genre_requirements",
                    "organization",
                    "language_control",
                    "completion",
                    "balanced",
                ],
            },
            "cautions_applied": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "rougher_but_stronger_content",
                        "formulaic_but_thin",
                        "polished_but_shallow",
                        "mechanics_impede_meaning",
                        "off_task",
                        "incomplete_or_scaffold",
                        "genre_requirement_decisive",
                    ],
                },
            },
            "decision_checks": {
                "type": "object",
                "properties": {
                    "deeper_interpretation": {"type": "string", "enum": ["A", "B", "tie"]},
                    "better_text_evidence_explanation": {"type": "string", "enum": ["A", "B", "tie"]},
                    "cleaner_or_more_formulaic": {"type": "string", "enum": ["A", "B", "tie"]},
                    "rougher_but_stronger_content": {"type": "string", "enum": ["A", "B", "none"]},
                    "completion_advantage": {"type": "string", "enum": ["A", "B", "tie"]},
                    "cleaner_wins_on_substance": {"type": "string"},
                    "rougher_loses_because": {"type": "string"},
                },
                "required": [
                    "deeper_interpretation",
                    "better_text_evidence_explanation",
                    "cleaner_or_more_formulaic",
                    "rougher_but_stronger_content",
                    "completion_advantage",
                    "cleaner_wins_on_substance",
                    "rougher_loses_because",
                ],
                "additionalProperties": False,
            },
        },
        "required": ["winner_side", "decision", "confidence", "rationale", "criterion_notes", "decision_basis", "cautions_applied", "decision_checks"],
        "additionalProperties": False,
    },
}

DEFAULT_BAND_SEAM_REPORT = "outputs/band_seam_report.json"
DEFAULT_EXPANSION_REPORT = "outputs/post_seam_pair_expansion.json"
DEFAULT_PAIRWISE_ANCHOR_DIR = Path(__file__).resolve().parents[1] / "inputs" / "pairwise_anchors"
DECISION_BASIS_VALUES = {
    "task_alignment",
    "content_reasoning",
    "evidence_development",
    "genre_requirements",
    "organization",
    "language_control",
    "completion",
    "balanced",
}
CAUTION_VALUES = {
    "rougher_but_stronger_content",
    "formulaic_but_thin",
    "polished_but_shallow",
    "mechanics_impede_meaning",
    "off_task",
    "incomplete_or_scaffold",
    "genre_requirement_decisive",
}
LEVEL_SORT = {"1": 1, "2": 2, "3": 3, "4": 4, "4+": 5}

GENRE_PRIORITY_RULES = {
    "literary_analysis": {
        "label": "literary analysis",
        "criteria": [
            "Task alignment and interpretive claim about the text",
            "Depth of literary reasoning about theme, character, choices, consequences, or craft",
            "Sustained explanation of a relationship, conflict, pattern, or mechanism of change when it reveals literary meaning",
            "Specific text evidence and explanation of how it proves the interpretation",
            "Distinction between analysis and plot summary",
            "Organization and coherence as support for the analysis",
            "Language control and conventions only after meaning, evidence, and explanation",
        ],
        "cautions": [
            "A rougher essay with a clearer interpretation, better evidence explanation, or more task-specific meaning should beat a cleaner formulaic essay with thin insight.",
            "Do not let a five-paragraph shape, tidy topic sentences, length, or surface coherence outrank stronger literary thinking.",
            "Do not require both essays to use the same theme wording. A defensible theme about trauma, healing, identity, trust, accountability, consequences, or support can win when it is better developed.",
            "A sustained analysis of one important relationship, conflict, or mechanism can beat a broader list of events that repeats a simple theme.",
            "Plot summary is not analysis unless the student explains how the events support the claim.",
            "An unfinished scaffold, outline, or fragmentary draft should not beat a complete essay unless the complete essay is off-task or meaning is not recoverable.",
        ],
    },
    "argumentative": {
        "label": "argumentative writing",
        "criteria": [
            "Clear, arguable claim that answers the prompt",
            "Relevant reasons and evidence, including credibility or specificity where expected",
            "Reasoning that explains why the evidence supports the claim",
            "Counterargument engagement when the assignment calls for it",
            "Audience awareness, organization, and transitions",
            "Language control and conventions after claim, evidence, and reasoning",
        ],
        "cautions": [
            "Do not reward persuasive polish or confident tone over weak reasons or unsupported claims.",
            "A less polished argument with stronger reasons and evidence can outrank a smoother but emptier argument.",
        ],
    },
    "informational_report": {
        "label": "informational writing",
        "criteria": [
            "Accuracy and relevance of information",
            "Completeness and sufficiency for the assigned topic",
            "Explanation, examples, and source integration where expected",
            "Logical organization, headings, or sections when useful",
            "Objective tone and vocabulary suited to the audience",
            "Language control and conventions after accuracy and sufficiency",
        ],
        "cautions": [
            "Do not reward fluent filler over accurate, relevant information.",
            "A polished report with thin, vague, or inaccurate content should lose to a rougher but more informative response.",
        ],
    },
    "informative_letter": {
        "label": "informative letter",
        "criteria": [
            "Clear purpose and useful context for the recipient",
            "Relevant and sufficient information, examples, or explanations",
            "Audience-appropriate tone and letter format",
            "Organization that helps the recipient understand the information",
            "Language control and conventions after purpose and information quality",
        ],
        "cautions": [
            "Do not reward letter polish over missing or weak information.",
            "Tone and format matter, but they should not outrank the assignment's purpose and content.",
        ],
    },
    "summary_report": {
        "label": "summary writing",
        "criteria": [
            "Accurate capture of the main idea and essential supporting points",
            "Concise selection rather than dumping every detail",
            "Paraphrase and synthesis in the student's own words",
            "No major distortions, invented details, or copied/extraction-heavy passages",
            "Organization and language control after accuracy, concision, and synthesis",
        ],
        "cautions": [
            "Do not reward length, copied detail, or source-like fluency over accurate concise synthesis.",
            "A shorter summary can outrank a longer one when it selects the essential ideas more accurately.",
        ],
    },
    "instructions": {
        "label": "procedural writing",
        "criteria": [
            "Procedural completeness: materials, setup, conditions, and all essential steps",
            "Executable sequence and clarity",
            "Precision, measurements, cautions, and safety details where needed",
            "Audience usability",
            "Language control and conventions after executability and precision",
        ],
        "cautions": [
            "Do not reward smooth prose if the procedure cannot actually be followed.",
            "Missing key steps, safety details, or measurements can be decisive even when the writing sounds polished.",
        ],
    },
    "narrative": {
        "label": "narrative writing",
        "criteria": [
            "Development of events, character, setting, and conflict",
            "Purposeful detail, voice, and reflection",
            "Sequencing, pacing, and coherence",
            "Control of the narrative point or meaning",
            "Language control and conventions after narrative development and effect",
        ],
        "cautions": [
            "Do not require essay-like thesis structure in a narrative.",
            "A mechanically rough narrative with stronger development, voice, and meaning can outrank a cleaner but flat story.",
        ],
    },
    "news_report": {
        "label": "news report",
        "criteria": [
            "Accurate who/what/when/where/why lead",
            "Objective reporting tone",
            "Relevant facts, quotations, and source attribution",
            "Inverted-pyramid or news-appropriate structure",
            "Language control and conventions after journalistic accuracy and objectivity",
        ],
        "cautions": [
            "Do not reward dramatic or persuasive style over factual, objective reporting.",
            "A cleaner article with missing core facts should lose to a rougher article that reports the event accurately.",
        ],
    },
    "book_review": {
        "label": "book review",
        "criteria": [
            "Clear judgment or recommendation",
            "Specific support from the book",
            "Audience awareness about what another reader needs to know",
            "Balance of summary, evaluation, and response",
            "Organization and language control after judgment and support",
        ],
        "cautions": [
            "Do not reward pure plot summary over supported evaluation.",
            "A rougher review with a clearer judgment and better text support can outrank a polished summary.",
        ],
    },
    "speech": {
        "label": "speech",
        "criteria": [
            "Clear purpose or claim for the audience",
            "Rhetorical effectiveness, examples, and appeals",
            "Audience engagement and tone",
            "Speech structure: opening, development, and closing",
            "Language control and conventions after purpose and rhetorical effect",
        ],
        "cautions": [
            "Do not reward essay-like polish over audience impact and rhetorical purpose.",
            "A speech must work for listeners, not only as a tidy paragraph sequence.",
        ],
    },
    "portfolio": {
        "label": "writing portfolio",
        "criteria": [
            "Sustained quality across included pieces",
            "Range of writing skills, forms, and purposes",
            "Sufficiency of evidence for the overall judgment",
            "Strength of the strongest pieces balanced against serious weak spots",
            "Language control after the portfolio evidence as a whole",
        ],
        "cautions": [
            "Do not let one polished piece hide thin or incomplete portfolio evidence.",
            "Judge the body of work, not a single best excerpt.",
        ],
    },
}


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


def clamp01(value, default=0.0) -> float:
    return max(0.0, min(1.0, num(value, default)))


def load_texts(text_dir: Path) -> dict[str, str]:
    texts = {}
    if not text_dir.exists():
        return texts
    for path in sorted(text_dir.glob("*.txt")):
        texts[path.stem.strip()] = path.read_text(encoding="utf-8", errors="ignore")
    return texts


def normalize_confidence(value) -> str:
    token = str(value or "").strip().lower()
    if token == "high":
        return "high"
    if token in {"med", "medium"}:
        return "medium"
    return "low"


def normalize_decision(value) -> str:
    token = str(value or "").strip().upper()
    return "SWAP" if token == "SWAP" else "KEEP"


def load_pairwise_metadata(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        payload = load_class_metadata(path)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_json(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_pairwise_genre(metadata: dict | None) -> str:
    metadata = metadata if isinstance(metadata, dict) else {}
    raw = (
        metadata.get("genre")
        or metadata.get("assignment_genre")
        or metadata.get("genre_form")
        or metadata.get("assessment_unit")
    )
    return str(normalize_genre(raw) or "").strip().lower()


def pairwise_genre_rules(genre: str) -> dict:
    normalized = normalize_genre(genre) or ""
    if normalized == "research_report":
        normalized = "informational_report"
    if normalized == "persuasive_response":
        normalized = "argumentative"
    return GENRE_PRIORITY_RULES.get(
        normalized,
        {
            "label": normalized.replace("_", " ") if normalized else "the assigned writing type",
            "criteria": [
                "Task alignment and fulfillment of the assignment purpose",
                "Quality, specificity, and development of ideas",
                "Evidence, examples, details, or support required by the task",
                "Genre control and audience awareness",
                "Organization and coherence",
                "Language control and conventions after purpose, ideas, support, and genre requirements",
            ],
            "cautions": [
                "Use the rubric and assignment, not generic essay polish.",
                "Do not let length, neat structure, or surface fluency outrank stronger task-specific content.",
                "Conventions are decisive only when errors block meaning or when the content quality is otherwise close.",
            ],
        },
    )


def metadata_grade_label(metadata: dict | None) -> str:
    metadata = metadata if isinstance(metadata, dict) else {}
    for key in ("grade_level", "grade_numeric_equivalent", "grade_numeric", "grade"):
        value = str(metadata.get(key, "") or "").strip()
        if value:
            return f"Grade {value}"
    return "the assigned grade level"


def format_numbered(items: list[str]) -> str:
    return "\n".join(f"{idx}. {item}" for idx, item in enumerate(items, start=1))


def canonical_anchor_genre(genre: str) -> str:
    normalized = normalize_genre(genre) or ""
    if normalized == "research_report":
        return "informational_report"
    if normalized == "persuasive_response":
        return "argumentative"
    return normalized or "generic"


def load_pairwise_anchor_payload(genre: str, anchor_dir: str | Path | None = None) -> dict:
    base_dir = Path(anchor_dir) if anchor_dir else DEFAULT_PAIRWISE_ANCHOR_DIR
    normalized = canonical_anchor_genre(genre)
    candidates = [base_dir / f"{normalized}.json"]
    if normalized != "generic":
        candidates.append(base_dir / "generic.json")
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def format_pairwise_anchor_block(genre: str, anchor_dir: str | Path | None = None) -> str:
    payload = load_pairwise_anchor_payload(genre, anchor_dir)
    if not payload:
        return ""
    lines = ["Pairwise calibration anchors:"]
    anchors = payload.get("anchors", [])
    for item in anchors if isinstance(anchors, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "") or "").strip()
        decision_rule = str(item.get("decision_rule", "") or "").strip()
        if title and decision_rule:
            lines.append(f"- {title}: {decision_rule}")
        elif decision_rule:
            lines.append(f"- {decision_rule}")
    caution_checks = payload.get("caution_checks", [])
    if isinstance(caution_checks, list) and caution_checks:
        lines.append("Before choosing a winner, explicitly check:")
        for item in caution_checks:
            text = str(item or "").strip()
            if text:
                lines.append(f"- {text}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def genre_specific_pairwise_guidance(genre: str, metadata: dict | None = None, anchor_dir: str | Path | None = None) -> str:
    metadata = metadata if isinstance(metadata, dict) else {}
    rules = pairwise_genre_rules(genre)
    lines = [
        f"Pairwise priority frame for {metadata_grade_label(metadata)} {rules['label']}:",
        format_numbered(rules["criteria"]),
        "Meaning-before-polish guardrails:",
        *[f"- {item}" for item in rules["cautions"]],
        "- Do not use aggregate rank, Borda, rubric percent, level, or seed order as evidence; the pairwise read is blind because upstream signals can be wrong.",
        "- Use organization and conventions as tie-breakers unless they materially affect meaning, task completion, accuracy, or genre function.",
    ]
    if str(metadata.get("generated_by", "") or "").strip().lower() == "bootstrap" and genre:
        lines.append(
            "This is a cold-start classroom cohort. Be conservative about structure-only wins; prefer essays with clearer task-specific meaning, evidence, and explanation."
        )
    anchor_block = format_pairwise_anchor_block(genre, anchor_dir)
    if anchor_block:
        lines.extend(["", anchor_block])
    return "\n".join(lines).strip()


def effective_window(requested_window: int, metadata: dict | None = None) -> int:
    metadata = metadata if isinstance(metadata, dict) else {}
    requested = max(1, int(requested_window))
    genre = resolve_pairwise_genre(metadata)
    if str(metadata.get("generated_by", "") or "").strip().lower() == "bootstrap" and genre == "literary_analysis":
        return max(requested, 4)
    return requested


def seed_percentile(seed_rank: int, student_count: int) -> float:
    if student_count <= 1:
        return 1.0
    return max(0.0, min(1.0, 1.0 - ((int(seed_rank) - 1) / max(student_count - 1, 1))))


def comparison_reach(row: dict, requested_window: int, student_count: int, metadata: dict | None = None) -> int:
    base = effective_window(requested_window, metadata)
    metadata = metadata if isinstance(metadata, dict) else {}
    genre = resolve_pairwise_genre(metadata)
    if str(metadata.get("generated_by", "") or "").strip().lower() != "bootstrap" or genre != "literary_analysis":
        return base
    seed_pct = seed_percentile(int(row.get("seed_rank", 1) or 1), student_count)
    borda_pct = clamp01(row.get("borda_percent"), seed_pct)
    composite_pct = clamp01(row.get("composite_score"), seed_pct)
    divergence = max(abs(seed_pct - borda_pct), abs(seed_pct - composite_pct))
    extra = 0
    if divergence >= 0.6:
        extra = 6
    elif divergence >= 0.4:
        extra = 4
    elif divergence >= 0.25:
        extra = 2
    return min(max(1, student_count - 1), base + extra)


def rank_divergence(row: dict, student_count: int) -> float:
    seed_pct = seed_percentile(int(row.get("seed_rank", 1) or 1), student_count)
    borda_pct = clamp01(row.get("borda_percent"), seed_pct)
    composite_pct = clamp01(row.get("composite_score"), seed_pct)
    return max(abs(seed_pct - borda_pct), abs(seed_pct - composite_pct))


def ids_from_band_seam_report(report: dict) -> set[str]:
    ids = set()
    for item in report.get("applied", []) if isinstance(report.get("applied"), list) else []:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("student_id", "") or "").strip()
        if sid:
            ids.add(sid)
    return ids


def ids_from_band_seam_pairwise_requests(report: dict) -> list[tuple[str, str, str]]:
    requested = []
    for item in report.get("pairwise_checks_needed", []) if isinstance(report.get("pairwise_checks_needed"), list) else []:
        if not isinstance(item, dict):
            continue
        higher = str(item.get("higher_candidate", "") or "").strip()
        lower = str(item.get("lower_candidate", "") or "").strip()
        if higher and lower and higher != lower:
            requested.append((higher, lower, str(item.get("reason", "") or "").strip()))
    return requested


def band_seam_mover_ids(rows: list[dict], band_seam_report: dict | None = None) -> set[str]:
    row_ids = {str(row.get("student_id", "") or "").strip() for row in rows}
    movers = ids_from_band_seam_report(band_seam_report or {}) & row_ids
    for row in rows:
        sid = str(row.get("student_id", "") or "").strip()
        if not sid:
            continue
        pre_level = normalize_level(row.get("pre_band_adjudication_level"))
        adjusted_level = normalize_level(row.get("adjusted_level") or row.get("base_level"))
        if pre_level and adjusted_level and pre_level != adjusted_level:
            movers.add(sid)
    return movers


def aggregate_divergence_mover_ids(rows: list[dict], *, divergence_threshold: float = 0.35) -> set[str]:
    count = max(1, len(rows))
    movers = set()
    for row in rows:
        sid = str(row.get("student_id", "") or "").strip()
        if sid and rank_divergence(row, count) >= float(divergence_threshold):
            movers.add(sid)
    return movers


def has_top_pack_claim(row: dict, *, top_pack_size: int, student_count: int) -> bool:
    if top_pack_size <= 0:
        return False
    top_cutoff = seed_percentile(min(top_pack_size, student_count), student_count)
    seed_pct = seed_percentile(int(row.get("seed_rank", 1) or 1), student_count)
    aggregate_peak = max(seed_pct, clamp01(row.get("borda_percent"), seed_pct), clamp01(row.get("composite_score"), seed_pct))
    return aggregate_peak >= max(0.0, top_cutoff - 0.05)


def post_seam_mover_ids(rows: list[dict], band_seam_report: dict | None = None, *, divergence_threshold: float = 0.35) -> set[str]:
    return band_seam_mover_ids(rows, band_seam_report) | aggregate_divergence_mover_ids(rows, divergence_threshold=divergence_threshold)


def add_pair_spec(specs: dict[tuple[str, str], dict], rows_by_id: dict[str, dict], left_id: str, right_id: str, reason: str, *, detail: str = ""):
    left_id = str(left_id or "").strip()
    right_id = str(right_id or "").strip()
    if not left_id or not right_id or left_id == right_id or left_id not in rows_by_id or right_id not in rows_by_id:
        return
    left = rows_by_id[left_id]
    right = rows_by_id[right_id]
    higher, lower = sorted(
        [left, right],
        key=lambda row: (int(row.get("seed_rank", 0) or 0), str(row.get("student_id", "")).lower()),
    )
    key = tuple(sorted((left_id, right_id)))
    item = specs.setdefault(
        key,
        {
            "higher": higher,
            "lower": lower,
            "selection_reasons": [],
            "selection_details": [],
        },
    )
    if reason and reason not in item["selection_reasons"]:
        item["selection_reasons"].append(reason)
    if detail and detail not in item["selection_details"]:
        item["selection_details"].append(detail)


def cross_band_support_score(row: dict, student_count: int) -> float:
    seed_pct = seed_percentile(int(row.get("seed_rank", 1) or 1), student_count)
    return max(
        seed_pct,
        clamp01(row.get("borda_percent"), seed_pct),
        clamp01(row.get("composite_score"), seed_pct),
    )


def uncertainty_challenger_score(row: dict, student_count: int) -> float:
    seed_pct = seed_percentile(int(row.get("seed_rank", 1) or 1), student_count)
    support_peak = max(
        seed_pct,
        clamp01(row.get("borda_percent"), seed_pct),
        clamp01(row.get("composite_score"), seed_pct),
    )
    flags = {item.strip() for item in str(row.get("flags", "") or "").split(";") if item.strip()}
    score = 0.0
    score += min(num(row.get("rank_sd"), 0.0) / 3.0, 1.0)
    score += min(num(row.get("rubric_sd_points"), 0.0) / 8.0, 1.0)
    score += max(0.0, support_peak - seed_pct)
    if "rank_sd" in flags:
        score += 0.5
    if "rubric_sd" in flags:
        score += 0.2
    if "severe_collapse_rescue" in flags or "boundary_calibration" in flags:
        score += 0.3
    if "band_seam_ambiguous" in flags:
        score += 0.3
    return score


def add_uncertainty_challenger_specs(
    specs: dict[tuple[str, str], dict],
    rows: list[dict],
    rows_by_id: dict[str, dict],
    *,
    challenger_count: int,
    anchor_count: int,
    top_pack_size: int,
):
    challenger_count = max(0, int(challenger_count))
    anchor_count = max(0, int(anchor_count))
    if not challenger_count or not anchor_count:
        return
    student_count = max(1, len(rows))
    top_cutoff = max(0, int(top_pack_size))
    challengers = sorted(
        [
            row
            for row in rows
            if int(row.get("seed_rank", 999999) or 999999) > top_cutoff
            and uncertainty_challenger_score(row, student_count) > 0.0
        ],
        key=lambda row: (
            -uncertainty_challenger_score(row, student_count),
            int(row.get("seed_rank", 999999) or 999999),
            str(row.get("student_id", "")).lower(),
        ),
    )[:challenger_count]
    anchors = sorted(
        rows,
        key=lambda row: (
            int(row.get("seed_rank", 999999) or 999999),
            str(row.get("student_id", "")).lower(),
        ),
    )[:anchor_count]
    for challenger in challengers:
        for anchor in anchors:
            if challenger["student_id"] == anchor["student_id"]:
                continue
            add_pair_spec(
                specs,
                rows_by_id,
                challenger["student_id"],
                anchor["student_id"],
                "uncertainty_challenger",
                detail=(
                    f"{challenger['student_id']} has high rank/rubric disagreement and is checked "
                    f"against top-{anchor_count} post-seam anchors"
                ),
            )


def add_cross_band_challenger_specs(
    specs: dict[tuple[str, str], dict],
    rows: list[dict],
    rows_by_id: dict[str, dict],
    *,
    challenger_count: int,
    anchor_count: int,
):
    challenger_count = max(0, int(challenger_count))
    anchor_count = max(0, int(anchor_count))
    if not challenger_count or not anchor_count:
        return
    by_level: dict[str, list[dict]] = {}
    for row in rows:
        level = normalize_level(row.get("level") or row.get("adjusted_level") or row.get("base_level"))
        if level in LEVEL_SORT:
            by_level.setdefault(level, []).append(row)
    ordered_levels = sorted(by_level, key=lambda level: LEVEL_SORT[level])
    student_count = max(1, len(rows))
    for lower_level, upper_level in zip(ordered_levels, ordered_levels[1:]):
        lower_rows = by_level.get(lower_level, [])
        upper_rows = by_level.get(upper_level, [])
        if not lower_rows or not upper_rows:
            continue
        challengers = sorted(
            lower_rows,
            key=lambda row: (
                -cross_band_support_score(row, student_count),
                int(row.get("seed_rank", 999999) or 999999),
                str(row.get("student_id", "")).lower(),
            ),
        )[:challenger_count]
        anchors = sorted(
            upper_rows,
            key=lambda row: (
                int(row.get("seed_rank", 999999) or 999999),
                str(row.get("student_id", "")).lower(),
            ),
        )[:anchor_count]
        for challenger in challengers:
            for anchor in anchors:
                add_pair_spec(
                    specs,
                    rows_by_id,
                    challenger["student_id"],
                    anchor["student_id"],
                    "cross_band_challenger",
                    detail=(
                        f"top lower-band challenger from Level {lower_level} checked against "
                        f"upper-band Level {upper_level} anchor after band-seam adjudication"
                    ),
                )


def build_prompt(
    rubric: str,
    outline: str,
    higher: dict,
    lower: dict,
    higher_text: str,
    lower_text: str,
    *,
    genre: str = "",
    metadata: dict | None = None,
    selection_reasons: list[str] | None = None,
    selection_details: list[str] | None = None,
    anchor_dir: str | Path | None = None,
    orientation_context: str = "",
) -> str:
    extra_guidance = genre_specific_pairwise_guidance(genre, metadata, anchor_dir)
    guidance_block = f"\nAdditional ranking guidance:\n{extra_guidance}\n" if extra_guidance else ""
    reason_text = ", ".join(selection_reasons or []) or "seed_window"
    details = "\n".join(f"- {detail}" for detail in (selection_details or []) if detail)
    details_block = f"\nSelection details:\n{details}\n" if details else ""
    orientation_block = f"\nOrientation audit context:\n{orientation_context.strip()}\n" if str(orientation_context or "").strip() else ""
    output_contract = """Judgment process:
1. Compare the essays using the priority frame above, in order.
2. Name which essay is stronger for each major criterion. Use "tie" when there is no meaningful difference.
3. Complete decision_checks before deciding. For literary analysis, "deeper_interpretation" and "better_text_evidence_explanation" are the core checks; "cleaner_or_more_formulaic" is not a winning check by itself.
4. Choose winner_side first: A if Essay A is stronger, B if Essay B is stronger. Ignore current seed order when choosing winner_side.
5. Set decision only after winner_side: KEEP when winner_side is A; SWAP when winner_side is B.
6. If one essay is cleaner or more formulaic but the other has stronger task-specific content, reasoning, evidence, or genre fulfillment, do not choose the cleaner essay for polish alone.
7. If you choose the cleaner or more formulaic essay over a rougher essay, cleaner_wins_on_substance must identify the specific stronger interpretation/evidence explanation. Do not cite focus, structure, clarity, length, or grammar alone.
8. If you choose against a rougher essay with possible stronger interpretation, rougher_loses_because must explain why its interpretation or evidence explanation is actually weaker, not just less polished.
9. If you choose the rougher essay, confirm that its deeper or alternate interpretation is sustained through recoverable textual evidence and explanation, not just mature theme vocabulary.
10. For literary analysis, five-paragraph form, paragraph count, complete essay shape, clearer thesis wording, or smoother transitions are not decisive unless the other response is incomplete/scaffolded or meaning is not recoverable.
11. For literary analysis, a complete essay with a clear claim, multiple specific text events, and repeated explanation can beat a rougher essay whose theme sounds more sophisticated but is less consistently proven.
12. If conventions or organization drive the result, explain whether they merely polish the writing or actually affect meaning, accuracy, completion, or usability.
13. Confidence calibration:
   - Use high when the same essay is clearly stronger on task alignment plus content/reasoning or evidence/development, even if the other essay is cleaner or more formulaic.
   - Use medium when the important criteria are genuinely mixed or the advantage is modest.
   - Use low only when the comparison is ambiguous or both essays are similarly flawed.
   - Do not downgrade a clear content/evidence winner from high to medium just because it has more surface errors.
   - In a literary-analysis rougher-vs-cleaner conflict, use high only if the winner clearly wins both deeper_interpretation and better_text_evidence_explanation.
12. Use cautions_applied only for cautions that materially affected this judgment. Use an empty array when none of the caution labels is genuinely needed."""
    return f"""You are collecting pairwise ranking evidence for a global reranker.

Rubric:
{rubric}

Assignment Outline:
{outline}
{guidance_block}

Pair identity only:
- Essay A: {higher['student_id']}
- Essay B: {lower['student_id']}

This comparison is blind to preliminary ranks, bands, rubric percents, Borda support, and composite scores. Those upstream signals may explain why the pair was selected, but they are not evidence for which essay is stronger.

Why this pair is being checked:
{reason_text}
{details_block}
{orientation_block}

{output_contract}

Essay A: {higher['student_id']}
{higher_text}

Essay B: {lower['student_id']}
{lower_text}

Decide which essay should rank higher for this assignment.

Allowed values:
- winner_side: A when Essay A is stronger; B when Essay B is stronger.
- decision: KEEP when Essay A should stay above Essay B; SWAP when Essay B should move above Essay A.
- confidence: low, medium, high.
- criterion_notes[].stronger: A, B, tie.
- decision_basis: task_alignment, content_reasoning, evidence_development, genre_requirements, organization, language_control, completion, balanced.
- cautions_applied: rougher_but_stronger_content, formulaic_but_thin, polished_but_shallow, mechanics_impede_meaning, off_task, incomplete_or_scaffold, genre_requirement_decisive. Use [] if no caution materially affected the decision.
- decision_checks.deeper_interpretation: A, B, tie.
- decision_checks.better_text_evidence_explanation: A, B, tie.
- decision_checks.cleaner_or_more_formulaic: A, B, tie.
- decision_checks.rougher_but_stronger_content: A, B, none.
- decision_checks.completion_advantage: A, B, tie.

Return ONLY valid JSON in this shape:
{{
  "winner_side": "A",
  "decision": "KEEP",
  "confidence": "high",
  "rationale": "short justification that names the decisive task-specific reason, not just polish or seed order",
  "criterion_notes": [
    {{"criterion": "task alignment", "stronger": "A", "reason": "brief note"}},
    {{"criterion": "content/reasoning", "stronger": "B", "reason": "brief note"}},
    {{"criterion": "evidence/development", "stronger": "tie", "reason": "brief note"}},
    {{"criterion": "organization/language", "stronger": "A", "reason": "brief note"}}
  ],
  "decision_basis": "content_reasoning",
  "cautions_applied": [],
  "decision_checks": {{
    "deeper_interpretation": "A",
    "better_text_evidence_explanation": "A",
    "cleaner_or_more_formulaic": "B",
    "rougher_but_stronger_content": "none",
    "completion_advantage": "tie",
    "cleaner_wins_on_substance": "If the cleaner essay wins, name its stronger interpretation/evidence explanation here; otherwise explain that polish did not decide.",
    "rougher_loses_because": "If the rougher essay loses, explain the substantive weakness here; otherwise explain that roughness did not decide."
  }}
}}
"""


def parse_json(text: str) -> dict:
    try:
        payload = json_from_text(text)
    except ValueError as exc:
        raise ValueError("Invalid JSON response") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid JSON response")
    return payload


def build_repair_prompt(raw_text: str, original_prompt: str = "", repair_reasons: list[str] | None = None) -> str:
    original_block = ""
    if str(original_prompt or "").strip():
        original_block = f"""
Original adjudication prompt, including the essays and rubric:
{original_prompt}
"""
    reasons = [str(reason or "").strip() for reason in (repair_reasons or []) if str(reason or "").strip()]
    reason_block = ""
    if reasons:
        reason_block = "\nRepair triggers:\n" + "\n".join(f"- {reason}" for reason in reasons) + "\n"
    return f"""The prior response was supposed to be JSON but was malformed.

Repair the response by re-reading the original adjudication prompt when it is provided. Do not say the essays are missing when the original prompt includes them.
{reason_block}

Allowed values:
- winner_side: A when Essay A is stronger; B when Essay B is stronger.
- decision: KEEP or SWAP.
- confidence: low, medium, high.
- criterion_notes[].stronger: A, B, tie.
- decision_basis: task_alignment, content_reasoning, evidence_development, genre_requirements, organization, language_control, completion, balanced.
- cautions_applied: rougher_but_stronger_content, formulaic_but_thin, polished_but_shallow, mechanics_impede_meaning, off_task, incomplete_or_scaffold, genre_requirement_decisive. Use [] if no caution materially affected the decision.
- decision_checks.deeper_interpretation: A, B, tie.
- decision_checks.better_text_evidence_explanation: A, B, tie.
- decision_checks.cleaner_or_more_formulaic: A, B, tie.
- decision_checks.rougher_but_stronger_content: A, B, none.
- decision_checks.completion_advantage: A, B, tie.

Return ONLY valid JSON in this shape:
{{
  "winner_side": "A",
  "decision": "KEEP",
  "confidence": "medium",
  "rationale": "short justification",
  "criterion_notes": [
    {{"criterion": "task alignment", "stronger": "A", "reason": "brief note"}},
    {{"criterion": "content/reasoning", "stronger": "B", "reason": "brief note"}},
    {{"criterion": "evidence/development", "stronger": "tie", "reason": "brief note"}},
    {{"criterion": "organization/language", "stronger": "A", "reason": "brief note"}}
  ],
  "decision_basis": "balanced",
  "cautions_applied": [],
  "decision_checks": {{
    "deeper_interpretation": "tie",
    "better_text_evidence_explanation": "tie",
    "cleaner_or_more_formulaic": "tie",
    "rougher_but_stronger_content": "none",
    "completion_advantage": "tie",
    "cleaner_wins_on_substance": "brief note",
    "rougher_loses_because": "brief note"
  }}
}}

{original_block}
Malformed response:
{raw_text}
"""


def normalize_stronger(value) -> str:
    token = str(value or "").strip().upper()
    if token in {"A", "B"}:
        return token
    return "tie"


def normalize_criterion_notes(value) -> list[dict]:
    notes = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        criterion = str(item.get("criterion", "") or "").strip()
        reason = str(item.get("reason", "") or "").strip()
        if not criterion and not reason:
            continue
        notes.append(
            {
                "criterion": criterion or "unspecified",
                "stronger": normalize_stronger(item.get("stronger")),
                "reason": reason,
            }
        )
    return notes


def normalize_decision_basis(value) -> str:
    token = str(value or "").strip().lower()
    return token if token in DECISION_BASIS_VALUES else "balanced"


def normalize_cautions(value) -> list[str]:
    cautions = []
    for item in value if isinstance(value, list) else []:
        token = str(item or "").strip().lower()
        if token in CAUTION_VALUES and token not in cautions:
            cautions.append(token)
    return cautions


def normalize_side(value, *, allow_none: bool = False) -> str:
    token = str(value or "").strip().upper()
    if allow_none and not token:
        return "none"
    if token in {"A", "B"}:
        return token
    if allow_none and token == "NONE":
        return "none"
    return "tie"


def normalize_winner_side(value) -> str:
    token = str(value or "").strip().upper()
    return token if token in {"A", "B"} else ""


def decision_from_winner_side(value) -> str:
    side = normalize_winner_side(value)
    if side == "A":
        return "KEEP"
    if side == "B":
        return "SWAP"
    return ""


def winner_side_from_decision(value) -> str:
    return "B" if normalize_decision(value) == "SWAP" else "A"


def normalize_decision_checks(value) -> dict:
    payload = value if isinstance(value, dict) else {}
    return {
        "deeper_interpretation": normalize_side(payload.get("deeper_interpretation")),
        "better_text_evidence_explanation": normalize_side(payload.get("better_text_evidence_explanation")),
        "cleaner_or_more_formulaic": normalize_side(payload.get("cleaner_or_more_formulaic")),
        "rougher_but_stronger_content": normalize_side(payload.get("rougher_but_stronger_content"), allow_none=True),
        "completion_advantage": normalize_side(payload.get("completion_advantage")),
        "cleaner_wins_on_substance": str(payload.get("cleaner_wins_on_substance", "") or "").strip(),
        "rougher_loses_because": str(payload.get("rougher_loses_because", "") or "").strip(),
    }


def parsed_judgment_repair_reasons(parsed: dict) -> list[str]:
    reasons = []
    if not normalize_winner_side(parsed.get("winner_side")):
        reasons.append("missing_or_invalid_winner_side")
    if normalize_decision(parsed.get("decision")) not in {"KEEP", "SWAP"}:
        reasons.append("missing_or_invalid_decision")
    if normalize_confidence(parsed.get("confidence")) not in {"low", "medium", "high"}:
        reasons.append("missing_or_invalid_confidence")
    if normalize_decision_basis(parsed.get("decision_basis")) not in DECISION_BASIS_VALUES:
        reasons.append("missing_or_invalid_decision_basis")
    if len(normalize_criterion_notes(parsed.get("criterion_notes"))) < 3:
        reasons.append("missing_or_sparse_criterion_notes")
    checks = parsed.get("decision_checks") if isinstance(parsed.get("decision_checks"), dict) else {}
    for key in (
        "deeper_interpretation",
        "better_text_evidence_explanation",
        "cleaner_or_more_formulaic",
        "rougher_but_stronger_content",
        "completion_advantage",
    ):
        if not str(checks.get(key, "") or "").strip():
            reasons.append(f"missing_decision_check:{key}")
    rationale = str(parsed.get("rationale") or parsed.get("reason") or "").strip().lower()
    if (
        "cannot reliably evaluate" in rationale
        or "not provided" in rationale
        or ("missing" in rationale and "essay" in rationale)
    ):
        reasons.append("rationale_says_essay_content_missing")
    return reasons


def side_for_student(higher: dict, lower: dict, student_id: str) -> str:
    if student_id == higher["student_id"]:
        return "A"
    if student_id == lower["student_id"]:
        return "B"
    return ""


def student_for_side(higher: dict, lower: dict, side: str) -> str:
    token = normalize_side(side)
    if token == "A":
        return higher["student_id"]
    if token == "B":
        return lower["student_id"]
    return ""


def confidence_downgrade_for_selfcheck(
    higher: dict,
    lower: dict,
    *,
    genre: str,
    decision: str,
    confidence: str,
    decision_basis: str,
    decision_checks: dict,
) -> tuple[str, list[str]]:
    notes = []
    normalized_genre = resolve_pairwise_genre({"assignment_genre": genre}) or normalize_genre(genre) or ""
    if normalized_genre != "literary_analysis" or normalize_confidence(confidence) != "high":
        return confidence, notes
    winner = pair_winner_from_decision(higher, lower, decision)
    winner_side = side_for_student(higher, lower, winner)
    deeper = decision_checks.get("deeper_interpretation", "tie")
    evidence = decision_checks.get("better_text_evidence_explanation", "tie")
    cleaner = decision_checks.get("cleaner_or_more_formulaic", "tie")
    rougher_stronger = decision_checks.get("rougher_but_stronger_content", "none")
    if deeper not in {winner_side, "tie"} or evidence not in {winner_side, "tie"}:
        notes.append("high_confidence_downgraded_literary_core_checks_mixed")
    if cleaner == winner_side and (deeper != winner_side or evidence != winner_side):
        notes.append("high_confidence_downgraded_cleaner_winner_without_core_sweep")
    if rougher_stronger in {"A", "B"} and rougher_stronger != winner_side:
        notes.append("high_confidence_downgraded_selfcheck_prefers_loser")
    if decision_basis in {"organization", "language_control"}:
        notes.append("high_confidence_downgraded_surface_basis")
    if notes:
        return "medium", notes
    return confidence, notes


def pair_winner_from_decision(higher: dict, lower: dict, decision: str) -> str:
    return lower["student_id"] if normalize_decision(decision) == "SWAP" else higher["student_id"]


def pair_loser_from_decision(higher: dict, lower: dict, decision: str) -> str:
    return higher["student_id"] if normalize_decision(decision) == "SWAP" else lower["student_id"]


def pair_seed_features(row: dict) -> dict:
    return {
        "student_id": row["student_id"],
        "seed_rank": int(row["seed_rank"]),
        "level": row["level"],
        "rubric_after_penalty_percent": round(float(row["rubric_after_penalty_percent"]), 6),
        "composite_score": round(float(row["composite_score"]), 6),
        "borda_percent": round(float(row["borda_percent"]), 6),
    }


def judge_pair(
    rubric: str,
    outline: str,
    higher: dict,
    lower: dict,
    higher_text: str,
    lower_text: str,
    *,
    model: str,
    routing: str,
    reasoning: str,
    max_output_tokens: int,
    genre: str = "",
    metadata: dict | None = None,
    selection_reasons: list[str] | None = None,
    selection_details: list[str] | None = None,
    anchor_dir: str | Path | None = None,
    orientation_context: str = "",
    response_format: dict | None = None,
) -> dict:
    prompt = build_prompt(
        rubric,
        outline,
        higher,
        lower,
        higher_text,
        lower_text,
        genre=genre,
        metadata=metadata,
        selection_reasons=selection_reasons,
        selection_details=selection_details,
        anchor_dir=anchor_dir,
        orientation_context=orientation_context,
    )
    response = responses_create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        reasoning=reasoning,
        routing_path=routing,
        text_format=response_format or RESPONSE_FORMAT,
        max_output_tokens=max_output_tokens,
    )
    content = extract_text(response)
    repair_used = False
    repair_reasons = []
    try:
        parsed = parse_json(content)
        repair_reasons = parsed_judgment_repair_reasons(parsed)
        if repair_reasons:
            raise ValueError("Incomplete JSON response")
    except ValueError:
        repair_used = True
        if not repair_reasons:
            repair_reasons = ["invalid_json_response"]
        repair_response = responses_create(
            model=model,
            messages=[{"role": "user", "content": build_repair_prompt(content, prompt, repair_reasons)}],
            temperature=0.0,
            reasoning="low",
            routing_path=routing,
            text_format=response_format or RESPONSE_FORMAT,
            max_output_tokens=max_output_tokens,
        )
        content = extract_text(repair_response)
        parsed = parse_json(content)
        repair_reasons.extend(reason for reason in parsed_judgment_repair_reasons(parsed) if reason not in repair_reasons)
        response = repair_response
    parsed_decision = normalize_decision(parsed.get("decision"))
    winner_side = normalize_winner_side(parsed.get("winner_side"))
    decision = decision_from_winner_side(winner_side) or parsed_decision
    decision_notes = []
    if winner_side:
        expected_decision = decision_from_winner_side(winner_side)
        if expected_decision != parsed_decision:
            decision_notes.append("decision_overridden_by_winner_side")
    else:
        winner_side = winner_side_from_decision(parsed_decision)
        decision_notes.append("winner_side_missing_fallback_to_decision")
    confidence = normalize_confidence(parsed.get("confidence"))
    rationale = str(parsed.get("rationale") or parsed.get("reason") or "").strip()
    criterion_notes = normalize_criterion_notes(parsed.get("criterion_notes"))
    decision_basis = normalize_decision_basis(parsed.get("decision_basis"))
    cautions_applied = normalize_cautions(parsed.get("cautions_applied"))
    decision_checks = normalize_decision_checks(parsed.get("decision_checks"))
    parsed_checks = parsed.get("decision_checks") if isinstance(parsed.get("decision_checks"), dict) else {}
    for key in (
        "interpretation_depth",
        "proof_sufficiency",
        "polish_trap",
        "rougher_but_stronger_latent",
        "alternate_theme_validity",
        "mechanics_block_meaning",
        "completion_floor_applied",
    ):
        if key in parsed_checks:
            decision_checks[key] = parsed_checks.get(key)
    confidence, selfcheck_notes = confidence_downgrade_for_selfcheck(
        higher,
        lower,
        genre=genre,
        decision=decision,
        confidence=confidence,
        decision_basis=decision_basis,
        decision_checks=decision_checks,
    )
    selfcheck_notes = decision_notes + selfcheck_notes
    return {
        "pair": [higher["student_id"], lower["student_id"]],
        "seed_order": {
            "higher": higher["student_id"],
            "lower": lower["student_id"],
            "higher_rank": int(higher["seed_rank"]),
            "lower_rank": int(lower["seed_rank"]),
        },
        "seed_features": {
            "higher": pair_seed_features(higher),
            "lower": pair_seed_features(lower),
        },
        "selection_reasons": list(selection_reasons or []),
        "selection_details": list(selection_details or []),
        "winner_side": winner_side,
        "decision": decision,
        "winner": pair_winner_from_decision(higher, lower, decision),
        "loser": pair_loser_from_decision(higher, lower, decision),
        "confidence": confidence,
        "rationale": rationale,
        "criterion_notes": criterion_notes,
        "decision_basis": decision_basis,
        "cautions_applied": cautions_applied,
        "decision_checks": decision_checks,
        "model_metadata": {
            "requested_model": model,
            "response_model": response.get("model") or model,
            "routing_path": routing,
            "repair_used": repair_used,
            "repair_reasons": repair_reasons,
            "selfcheck_notes": selfcheck_notes,
            "reasoning": reasoning,
            "temperature": 0.0,
            "cached": bool(response.get("cached", False)),
            "usage": response.get("usage", {}),
        },
    }


ORIENTATION_AUDIT_REASONS = {
    "large_mover_neighborhood",
    "band_seam_requested",
}
ORIENTATION_AUDIT_DIVERGENCE_THRESHOLD = 0.35
ORIENTATION_CONFIDENCE_WEIGHTS = {"low": 0.5, "medium": 1.0, "high": 2.0}


def should_orientation_audit_pair(
    genre: str,
    selection_reasons: list[str] | None,
    higher: dict | None = None,
    lower: dict | None = None,
    *,
    student_count: int = 0,
) -> bool:
    normalized_genre = resolve_pairwise_genre({"assignment_genre": genre}) or normalize_genre(genre) or ""
    if normalized_genre != "literary_analysis":
        return False
    reasons = {str(item or "").strip() for item in (selection_reasons or [])}
    if reasons & ORIENTATION_AUDIT_REASONS:
        return True
    count = max(int(student_count or 0), int(num((higher or {}).get("seed_rank"), 0)), int(num((lower or {}).get("seed_rank"), 0)), 1)
    return any(
        rank_divergence(row, count) >= ORIENTATION_AUDIT_DIVERGENCE_THRESHOLD
        for row in (higher or {}, lower or {})
        if isinstance(row, dict)
    )


def compact_judgment_for_orientation_audit(judgment: dict) -> dict:
    checks = judgment.get("decision_checks") if isinstance(judgment.get("decision_checks"), dict) else {}
    return {
        "pair": list(judgment.get("pair", [])),
        "winner": judgment.get("winner", ""),
        "winner_side": judgment.get("winner_side", ""),
        "decision": judgment.get("decision", ""),
        "confidence": judgment.get("confidence", ""),
        "decision_basis": judgment.get("decision_basis", ""),
        "cautions_applied": list(judgment.get("cautions_applied", [])),
        "decision_checks": {
            "deeper_interpretation": checks.get("deeper_interpretation", ""),
            "better_text_evidence_explanation": checks.get("better_text_evidence_explanation", ""),
            "cleaner_or_more_formulaic": checks.get("cleaner_or_more_formulaic", ""),
            "rougher_but_stronger_content": checks.get("rougher_but_stronger_content", ""),
            "completion_advantage": checks.get("completion_advantage", ""),
        },
        "rationale": str(judgment.get("rationale", "") or "")[:700],
    }


def attach_orientation_audit(judgment: dict, audit: dict) -> dict:
    metadata = judgment.setdefault("model_metadata", {})
    metadata["orientation_audit"] = audit
    return judgment


def side_for_pair_member(judgment: dict, student_id: str) -> str:
    pair = judgment.get("pair") if isinstance(judgment.get("pair"), list) else []
    if len(pair) >= 1 and student_id == pair[0]:
        return "A"
    if len(pair) >= 2 and student_id == pair[1]:
        return "B"
    return ""


def student_for_pair_side(judgment: dict, side: str) -> str:
    pair = judgment.get("pair") if isinstance(judgment.get("pair"), list) else []
    token = normalize_winner_side(side)
    if token == "A" and len(pair) >= 1:
        return str(pair[0])
    if token == "B" and len(pair) >= 2:
        return str(pair[1])
    return ""


def remap_side_for_original(value, judgment: dict, higher: dict, lower: dict, *, allow_none: bool = False) -> str:
    token = normalize_side(value, allow_none=allow_none)
    if token in {"tie", "none"}:
        return token
    student_id = student_for_pair_side(judgment, token)
    return side_for_student(higher, lower, student_id) or ("none" if allow_none else "tie")


def reorient_judgment_to_original(judgment: dict, higher: dict, lower: dict) -> dict:
    winner = str(judgment.get("winner", "") or "")
    if winner not in {higher["student_id"], lower["student_id"]}:
        return judgment
    loser = lower["student_id"] if winner == higher["student_id"] else higher["student_id"]
    winner_side = side_for_student(higher, lower, winner)
    reoriented = dict(judgment)
    reoriented["pair"] = [higher["student_id"], lower["student_id"]]
    reoriented["seed_order"] = {
        "higher": higher["student_id"],
        "lower": lower["student_id"],
        "higher_rank": int(higher["seed_rank"]),
        "lower_rank": int(lower["seed_rank"]),
    }
    reoriented["seed_features"] = {
        "higher": pair_seed_features(higher),
        "lower": pair_seed_features(lower),
    }
    reoriented["winner_side"] = winner_side
    reoriented["decision"] = decision_from_winner_side(winner_side)
    reoriented["winner"] = winner
    reoriented["loser"] = loser
    notes = []
    for note in judgment.get("criterion_notes", []) if isinstance(judgment.get("criterion_notes"), list) else []:
        item = dict(note) if isinstance(note, dict) else {}
        item["stronger"] = remap_side_for_original(item.get("stronger"), judgment, higher, lower)
        notes.append(item)
    reoriented["criterion_notes"] = notes
    checks = normalize_decision_checks(judgment.get("decision_checks"))
    reoriented["decision_checks"] = {
        "deeper_interpretation": remap_side_for_original(checks.get("deeper_interpretation"), judgment, higher, lower),
        "better_text_evidence_explanation": remap_side_for_original(checks.get("better_text_evidence_explanation"), judgment, higher, lower),
        "cleaner_or_more_formulaic": remap_side_for_original(checks.get("cleaner_or_more_formulaic"), judgment, higher, lower),
        "rougher_but_stronger_content": remap_side_for_original(checks.get("rougher_but_stronger_content"), judgment, higher, lower, allow_none=True),
        "completion_advantage": remap_side_for_original(checks.get("completion_advantage"), judgment, higher, lower),
        "cleaner_wins_on_substance": checks.get("cleaner_wins_on_substance", ""),
        "rougher_loses_because": checks.get("rougher_loses_because", ""),
    }
    if judgment.get("pair") != reoriented["pair"]:
        reoriented["rationale"] = (
            f"Orientation-audited swapped read selected {winner}. "
            f"Raw swapped rationale: {str(judgment.get('rationale', '') or '')}"
        )
    return reoriented


def completion_floor_winner_from_judgment(judgment: dict) -> str:
    cautions = set(normalize_cautions(judgment.get("cautions_applied")))
    if "incomplete_or_scaffold" not in cautions:
        return ""
    checks = normalize_decision_checks(judgment.get("decision_checks"))
    return student_for_pair_side(judgment, checks.get("completion_advantage"))


def primary_self_declares_orientation_risk(genre: str, judgment: dict) -> bool:
    normalized_genre = resolve_pairwise_genre({"assignment_genre": genre}) or normalize_genre(genre) or ""
    if normalized_genre != "literary_analysis":
        return False
    if normalize_confidence(judgment.get("confidence")) == "high":
        return False
    cautions = set(normalize_cautions(judgment.get("cautions_applied")))
    return bool(cautions & {"rougher_but_stronger_content", "mechanics_impede_meaning", "polished_but_shallow", "formulaic_but_thin"})


def positive_support_divergence(row: dict, student_count: int) -> float:
    seed_pct = seed_percentile(int(row.get("seed_rank", 1) or 1), student_count)
    borda_pct = clamp01(row.get("borda_percent"), seed_pct)
    composite_pct = clamp01(row.get("composite_score"), seed_pct)
    return max(borda_pct - seed_pct, composite_pct - seed_pct, 0.0)


def choose_orientation_conflict_judgment(
    primary: dict,
    reverse: dict,
    higher: dict,
    lower: dict,
    *,
    student_count: int,
    higher_text: str = "",
    lower_text: str = "",
) -> tuple[dict, str]:
    higher_draft = analyze_draft_quality(higher_text)
    lower_draft = analyze_draft_quality(lower_text)
    if higher_draft.get("hard_floor_incomplete") and not lower_draft.get("hard_floor_incomplete"):
        for judgment in (primary, reverse):
            if judgment.get("winner") == lower["student_id"]:
                return judgment, "resolved_by_deterministic_completion_floor"
        return primary, "primary_retained_deterministic_completion_floor_unmatched"
    if lower_draft.get("hard_floor_incomplete") and not higher_draft.get("hard_floor_incomplete"):
        for judgment in (primary, reverse):
            if judgment.get("winner") == higher["student_id"]:
                return judgment, "resolved_by_deterministic_completion_floor"
        return primary, "primary_retained_deterministic_completion_floor_unmatched"

    completion_candidates = [
        sid
        for sid in (completion_floor_winner_from_judgment(primary), completion_floor_winner_from_judgment(reverse))
        if sid in {higher["student_id"], lower["student_id"]}
    ]
    if completion_candidates:
        counts = Counter(completion_candidates)
        winner = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        for judgment in (primary, reverse):
            if judgment.get("winner") == winner:
                return judgment, "resolved_by_completion_floor"
        return primary, "primary_retained_completion_floor_unmatched"

    count = max(int(student_count or 0), int(higher.get("seed_rank", 0) or 0), int(lower.get("seed_rank", 0) or 0), 1)
    positive_divergences = {
        higher["student_id"]: positive_support_divergence(higher, count),
        lower["student_id"]: positive_support_divergence(lower, count),
    }
    movers = [sid for sid, divergence in positive_divergences.items() if divergence >= ORIENTATION_AUDIT_DIVERGENCE_THRESHOLD]
    if len(movers) == 1:
        mover = movers[0]
        for judgment in (primary, reverse):
            if judgment.get("winner") == mover:
                return judgment, "resolved_by_large_mover_cross_evidence"

    primary_weight = ORIENTATION_CONFIDENCE_WEIGHTS.get(normalize_confidence(primary.get("confidence")), 0.5)
    reverse_weight = ORIENTATION_CONFIDENCE_WEIGHTS.get(normalize_confidence(reverse.get("confidence")), 0.5)
    if abs(primary_weight - reverse_weight) >= 1.0:
        if reverse_weight > primary_weight:
            return reverse, "resolved_by_higher_confidence_swapped_read"
        return primary, "resolved_by_higher_confidence_primary_read"

    return primary, "primary_retained_after_unresolved_orientation_conflict"


def judge_pair_with_orientation_audit(
    rubric: str,
    outline: str,
    higher: dict,
    lower: dict,
    higher_text: str,
    lower_text: str,
    *,
    model: str,
    routing: str,
    reasoning: str,
    max_output_tokens: int,
    genre: str = "",
    metadata: dict | None = None,
    selection_reasons: list[str] | None = None,
    selection_details: list[str] | None = None,
    anchor_dir: str | Path | None = None,
    orientation_audit: bool = True,
    student_count: int = 0,
    response_format: dict | None = None,
) -> dict:
    primary = judge_pair(
        rubric,
        outline,
        higher,
        lower,
        higher_text,
        lower_text,
        model=model,
        routing=routing,
        reasoning=reasoning,
        max_output_tokens=max_output_tokens,
        genre=genre,
        metadata=metadata,
        selection_reasons=selection_reasons,
        selection_details=selection_details,
        anchor_dir=anchor_dir,
        response_format=response_format,
    )
    audit_needed = should_orientation_audit_pair(genre, selection_reasons, higher, lower, student_count=student_count) or primary_self_declares_orientation_risk(genre, primary)
    if not orientation_audit or not audit_needed:
        return primary

    reverse_reasons = list(selection_reasons or [])
    if "orientation_audit_swapped_read" not in reverse_reasons:
        reverse_reasons.append("orientation_audit_swapped_read")
    reverse_details = list(selection_details or []) + [
        "Swapped read for orientation-bias detection; Essay A/B positions are arbitrary.",
    ]
    reverse = judge_pair(
        rubric,
        outline,
        lower,
        higher,
        lower_text,
        higher_text,
        model=model,
        routing=routing,
        reasoning=reasoning,
        max_output_tokens=max_output_tokens,
        genre=genre,
        metadata=metadata,
        selection_reasons=reverse_reasons,
        selection_details=reverse_details,
        anchor_dir=anchor_dir,
        response_format=response_format,
    )
    if primary.get("winner") == reverse.get("winner"):
        return attach_orientation_audit(
            primary,
            {
                "status": "agreement",
                "primary": compact_judgment_for_orientation_audit(primary),
                "swapped": compact_judgment_for_orientation_audit(reverse),
            },
        )

    chosen, status = choose_orientation_conflict_judgment(
        primary,
        reverse,
        higher,
        lower,
        student_count=student_count,
        higher_text=higher_text,
        lower_text=lower_text,
    )
    resolved = reorient_judgment_to_original(chosen, higher, lower)
    return attach_orientation_audit(
        resolved,
        {
            "status": status,
            "primary": compact_judgment_for_orientation_audit(primary),
            "swapped": compact_judgment_for_orientation_audit(reverse),
            "resolver": compact_judgment_for_orientation_audit(resolved),
        },
    )


def rank_key(rows: list[dict]) -> str:
    if not rows:
        return ""
    for key in ("seed_rank", "consensus_rank", "final_rank", "consistency_rank"):
        if key in rows[0]:
            return key
    return ""


def prepare_rows(rows: list[dict]) -> list[dict]:
    seed_key = rank_key(rows)
    ordered = sorted(
        [dict(row) for row in rows if str(row.get("student_id", "")).strip()],
        key=lambda row: (
            int(num(row.get(seed_key), 0.0) or 0.0),
            str(row.get("student_id", "")).lower(),
        ),
    )
    prepared = []
    for idx, row in enumerate(ordered, start=1):
        prepared.append(
            {
                "student_id": str(row.get("student_id", "")).strip(),
                "seed_rank": int(num(row.get("seed_rank") or row.get(seed_key), idx) or idx),
                "adjusted_level": row.get("adjusted_level", ""),
                "base_level": row.get("base_level", ""),
                "level": normalize_level(row.get("adjusted_level") or row.get("base_level")) or "",
                "rubric_after_penalty_percent": num(
                    row.get("rubric_after_penalty_percent"),
                    num(row.get("rubric_mean_percent"), 0.0),
                ),
                "borda_percent": clamp01(row.get("borda_percent"), 0.0),
                "composite_score": num(row.get("composite_score"), 0.0),
                "rank_sd": num(row.get("rank_sd"), 0.0),
                "rubric_sd_points": num(row.get("rubric_sd_points"), 0.0),
                "flags": str(row.get("flags", "") or ""),
                "source": dict(row),
            }
        )
    return prepared


def select_pair_specs(
    rows: list[dict],
    window: int,
    metadata: dict | None = None,
    *,
    top_pack_size: int = 0,
    large_mover_window: int = 0,
    band_seam_report: dict | None = None,
    large_mover_divergence: float = 0.35,
    cross_band_challenger_count: int = 0,
    cross_band_anchor_count: int = 0,
    uncertainty_challenger_count: int = 0,
    uncertainty_anchor_count: int = 0,
) -> list[dict]:
    ordered = list(rows)
    specs = {}
    rows_by_id = {row["student_id"]: row for row in ordered}
    width = max(1, int(window))
    count = len(ordered)
    reach = {
        row["student_id"]: comparison_reach(row, width, count, metadata)
        for row in ordered
    }
    for idx, higher in enumerate(ordered):
        for lower_idx in range(idx + 1, len(ordered)):
            lower = ordered[lower_idx]
            gap = lower_idx - idx
            if gap > max(reach.get(higher["student_id"], width), reach.get(lower["student_id"], width)):
                continue
            reason = "seed_window" if gap <= width else "aggregate_divergence_reach"
            add_pair_spec(
                specs,
                rows_by_id,
                higher["student_id"],
                lower["student_id"],
                reason,
                detail=f"seed rank gap {gap}; reach {max(reach.get(higher['student_id'], width), reach.get(lower['student_id'], width))}",
            )

    top_count = min(max(0, int(top_pack_size)), count)
    for idx, higher in enumerate(ordered[:top_count]):
        for lower in ordered[idx + 1 : top_count]:
            add_pair_spec(
                specs,
                rows_by_id,
                higher["student_id"],
                lower["student_id"],
                "top_pack",
                detail=f"both essays are in the top {top_count} seed positions after band-seam adjudication",
            )

    seam_movers = band_seam_mover_ids(ordered, band_seam_report or {})
    aggregate_movers = aggregate_divergence_mover_ids(ordered, divergence_threshold=large_mover_divergence)
    movers = seam_movers | aggregate_movers
    top_pack_movers = {
        sid
        for sid in movers
        if sid in seam_movers
        or has_top_pack_claim(rows_by_id.get(sid, {}), top_pack_size=top_count, student_count=count)
    }
    mover_window = max(0, int(large_mover_window))
    index_by_id = {row["student_id"]: idx for idx, row in enumerate(ordered)}
    top_ids = [row["student_id"] for row in ordered[:top_count]]
    for mover_id in sorted(top_pack_movers, key=lambda sid: index_by_id.get(sid, count)):
        mover_idx = index_by_id.get(mover_id)
        if mover_idx is None:
            continue
        for top_id in top_ids:
            if top_id != mover_id:
                add_pair_spec(
                    specs,
                    rows_by_id,
                    mover_id,
                    top_id,
                    "large_mover_top_pack",
                    detail=f"{mover_id} is a post-seam or aggregate-divergence mover checked against the top pack",
                )
    for mover_id in sorted(movers, key=lambda sid: index_by_id.get(sid, count)):
        mover_idx = index_by_id.get(mover_id)
        if mover_idx is None:
            continue
        if mover_window:
            start = max(0, mover_idx - mover_window)
            stop = min(count, mover_idx + mover_window + 1)
            for other in ordered[start:stop]:
                if other["student_id"] != mover_id:
                    add_pair_spec(
                        specs,
                        rows_by_id,
                        mover_id,
                        other["student_id"],
                        "large_mover_neighborhood",
                        detail=f"{mover_id} is checked within +/-{mover_window} seed positions",
                    )

    for higher_id, lower_id, reason in ids_from_band_seam_pairwise_requests(band_seam_report or {}):
        add_pair_spec(
            specs,
            rows_by_id,
            higher_id,
            lower_id,
            "band_seam_requested",
            detail=reason or "band seam adjudicator requested this direct comparison",
        )

    add_cross_band_challenger_specs(
        specs,
        ordered,
        rows_by_id,
        challenger_count=cross_band_challenger_count,
        anchor_count=cross_band_anchor_count,
    )
    add_uncertainty_challenger_specs(
        specs,
        ordered,
        rows_by_id,
        challenger_count=uncertainty_challenger_count,
        anchor_count=uncertainty_anchor_count,
        top_pack_size=top_count,
    )

    return list(specs.values())


def select_pairs(rows: list[dict], window: int, metadata: dict | None = None) -> list[tuple[dict, dict]]:
    return [(item["higher"], item["lower"]) for item in select_pair_specs(rows, window, metadata)]


def collect_judgments(
    rows: list[dict],
    texts: dict[str, str],
    rubric: str,
    outline: str,
    *,
    model: str,
    routing: str,
    reasoning: str,
    max_output_tokens: int,
    window: int,
    metadata: dict | None = None,
    top_pack_size: int = 0,
    large_mover_window: int = 0,
    band_seam_report: dict | None = None,
    large_mover_divergence: float = 0.35,
    cross_band_challenger_count: int = 0,
    cross_band_anchor_count: int = 0,
    uncertainty_challenger_count: int = 0,
    uncertainty_anchor_count: int = 0,
    anchor_dir: str | Path | None = None,
    orientation_audit: bool = True,
    replicates: int = 1,
) -> list[dict]:
    judgments = []
    genre = resolve_pairwise_genre(metadata)
    pair_specs = select_pair_specs(
        rows,
        window,
        metadata,
        top_pack_size=top_pack_size,
        large_mover_window=large_mover_window,
        band_seam_report=band_seam_report,
        large_mover_divergence=large_mover_divergence,
        cross_band_challenger_count=cross_band_challenger_count,
        cross_band_anchor_count=cross_band_anchor_count,
        uncertainty_challenger_count=uncertainty_challenger_count,
        uncertainty_anchor_count=uncertainty_anchor_count,
    )
    for spec in pair_specs:
        higher = spec["higher"]
        lower = spec["lower"]
        for replicate_idx in range(max(1, int(replicates))):
            details = list(spec.get("selection_details", []))
            if replicates > 1:
                details.append(f"Independent replicate {replicate_idx + 1} of {replicates}; re-read the essays from scratch.")
            judgment = judge_pair_with_orientation_audit(
                rubric,
                outline,
                higher,
                lower,
                texts.get(higher["student_id"], ""),
                texts.get(lower["student_id"], ""),
                model=model,
                routing=routing,
                reasoning=reasoning,
                max_output_tokens=max_output_tokens,
                genre=genre,
                metadata=metadata,
                selection_reasons=spec.get("selection_reasons", []),
                selection_details=details,
                anchor_dir=anchor_dir,
                orientation_audit=orientation_audit,
                student_count=len(rows),
            )
            judgments.append(judgment)
    return judgments


def summarize_pair_reasons(judgments: list[dict]) -> dict:
    counts = Counter()
    for judgment in judgments:
        for reason in judgment.get("selection_reasons", []) if isinstance(judgment.get("selection_reasons"), list) else []:
            counts[str(reason)] += 1
    return dict(sorted(counts.items()))


def write_expansion_report(
    path: Path,
    rows: list[dict],
    judgments: list[dict],
    *,
    top_pack_size: int,
    large_mover_window: int,
    band_seam_report_path: str,
    large_mover_divergence: float,
    cross_band_challenger_count: int,
    cross_band_anchor_count: int,
    uncertainty_challenger_count: int,
    uncertainty_anchor_count: int,
    band_seam_report: dict,
):
    path.parent.mkdir(parents=True, exist_ok=True)
    seam_movers = band_seam_mover_ids(rows, band_seam_report)
    aggregate_movers = aggregate_divergence_mover_ids(rows, divergence_threshold=large_mover_divergence)
    mover_ids = post_seam_mover_ids(rows, band_seam_report, divergence_threshold=large_mover_divergence)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "top_pack_size": int(top_pack_size),
        "large_mover_window": int(large_mover_window),
        "large_mover_divergence": float(large_mover_divergence),
        "cross_band_challenger_count": int(cross_band_challenger_count),
        "cross_band_anchor_count": int(cross_band_anchor_count),
        "uncertainty_challenger_count": int(uncertainty_challenger_count),
        "uncertainty_anchor_count": int(uncertainty_anchor_count),
        "band_seam_report": band_seam_report_path,
        "band_seam_movers": sorted(seam_movers),
        "aggregate_divergence_movers": sorted(aggregate_movers),
        "post_seam_movers": sorted(mover_ids),
        "comparison_count": len(judgments),
        "reason_counts": summarize_pair_reasons(judgments),
        "pairs": [
            {
                "pair": list(judgment.get("pair", [])),
                "seed_order": dict(judgment.get("seed_order", {})),
                "selection_reasons": list(judgment.get("selection_reasons", [])),
                "selection_details": list(judgment.get("selection_details", [])),
            }
            for judgment in judgments
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def write_judgment_payload(
    path: Path,
    rows: list[dict],
    judgments: list[dict],
    *,
    model: str,
    routing: str,
    window: int,
    source_scores: str,
    top_pack_size: int = 0,
    large_mover_window: int = 0,
    band_seam_report: str = "",
    cross_band_challenger_count: int = 0,
    cross_band_anchor_count: int = 0,
    uncertainty_challenger_count: int = 0,
    uncertainty_anchor_count: int = 0,
    orientation_audit: bool = True,
    replicates: int = 1,
):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_scores": source_scores,
        "model": model,
        "routing": routing,
        "comparison_window": int(window),
        "post_seam_expansion": {
            "top_pack_size": int(top_pack_size),
            "large_mover_window": int(large_mover_window),
            "band_seam_report": band_seam_report,
            "cross_band_challenger_count": int(cross_band_challenger_count),
            "cross_band_anchor_count": int(cross_band_anchor_count),
            "uncertainty_challenger_count": int(uncertainty_challenger_count),
            "uncertainty_anchor_count": int(uncertainty_anchor_count),
            "orientation_audit": bool(orientation_audit),
            "replicates": int(max(1, replicates)),
            "reason_counts": summarize_pair_reasons(judgments),
        },
        "seed_student_count": len(rows),
        "checks": judgments,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect pairwise evidence for global ranking consistency.")
    parser.add_argument("--scores", default="outputs/consensus_scores.csv", help="Seed ranking CSV")
    parser.add_argument("--texts", default="processing/normalized_text", help="Essay text dir")
    parser.add_argument("--rubric", default="inputs/rubric.md", help="Rubric file")
    parser.add_argument("--outline", default="inputs/assignment_outline.md", help="Assignment outline file")
    parser.add_argument("--class-metadata", default="inputs/class_metadata.json", help="Class metadata JSON")
    parser.add_argument("--routing", default="config/llm_routing.json", help="Routing config")
    parser.add_argument("--model", default="gpt-5.4-mini", help="Model for pairwise checks")
    parser.add_argument("--reasoning", default="low", help="Reasoning effort for pairwise checks")
    parser.add_argument("--window", type=int, default=2, help="How many lower-seeded neighbors to compare against each essay")
    parser.add_argument("--top-pack-size", type=int, default=6, help="Fully compare the top N seeds after band-seam adjudication")
    parser.add_argument("--large-mover-window", type=int, default=5, help="Neighborhood radius for post-seam and aggregate-divergence movers")
    parser.add_argument("--large-mover-divergence", type=float, default=0.35, help="Seed-vs-aggregate divergence threshold for large-mover expansion")
    parser.add_argument("--cross-band-challenger-count", type=int, default=8, help="Top lower-band challengers to compare against upper-band anchors after band seam")
    parser.add_argument("--cross-band-anchor-count", type=int, default=6, help="Upper-band anchors per adjacent level boundary for challenger comparisons")
    parser.add_argument("--uncertainty-challenger-count", type=int, default=12, help="High-disagreement non-top-pack papers to compare against post-seam anchors")
    parser.add_argument("--uncertainty-anchor-count", type=int, default=10, help="Top post-seam anchors used for uncertainty-challenger comparisons")
    parser.add_argument("--band-seam-report", default=DEFAULT_BAND_SEAM_REPORT, help="Band seam report used for post-seam pair expansion")
    parser.add_argument("--expansion-report", default=DEFAULT_EXPANSION_REPORT, help="Pair expansion audit artifact JSON")
    parser.add_argument("--disable-post-seam-expansion", action="store_true", help="Disable top-pack and large-mover pair expansion")
    parser.add_argument("--anchor-dir", default=str(DEFAULT_PAIRWISE_ANCHOR_DIR), help="Directory of genre-specific pairwise calibration anchor JSON files")
    parser.add_argument("--disable-orientation-audit", action="store_true", help="Disable swapped-read orientation auditing for high-risk literary-analysis pairs")
    parser.add_argument("--replicates", type=int, default=1, help="Independent judgments per selected pair")
    parser.add_argument("--max-output-tokens", type=int, default=900, help="Max model output tokens")
    parser.add_argument("--output", default="outputs/consistency_checks.json", help="Output JSON")
    parser.add_argument("--apply", action="store_true", help="Compatibility mode: collect evidence, then run the global reranker")
    parser.add_argument("--rerank-output", default="outputs/final_order.csv", help="Final reranked CSV output")
    parser.add_argument("--matrix-output", default="outputs/pairwise_matrix.json", help="Pairwise matrix JSON output")
    parser.add_argument("--scores-output", default="outputs/rerank_scores.csv", help="Rerank score CSV output")
    parser.add_argument("--report-output", default="outputs/consistency_report.json", help="Consistency report JSON output")
    parser.add_argument("--legacy-output", default="outputs/consistency_adjusted.csv", help="Compatibility CSV output")
    parser.add_argument("--config", default="config/marking_config.json", help="Marking config JSON")
    parser.add_argument("--local-prior", default="outputs/local_teacher_prior.json", help="Local teacher prior JSON")
    args = parser.parse_args()

    scores_path = Path(args.scores)
    if not scores_path.exists():
        print(f"Missing scores file: {scores_path}")
        return 1
    seed_rows = prepare_rows(load_rows(scores_path))
    if not seed_rows:
        print("No scores to verify.")
        return 1

    texts = load_texts(Path(args.texts))
    rubric_path = resolve_input_path(Path(args.rubric), "rubric")
    outline_path = resolve_input_path(Path(args.outline), "assignment_outline")
    metadata = load_pairwise_metadata(Path(args.class_metadata))
    rubric = load_file_text(rubric_path)
    outline = load_file_text(outline_path)
    expansion_enabled = not args.disable_post_seam_expansion
    band_seam_report_path = Path(args.band_seam_report)
    if args.band_seam_report == DEFAULT_BAND_SEAM_REPORT and scores_path.parent.name != "outputs":
        band_seam_report_path = scores_path.parent / "band_seam_report.json"
    band_seam_report = load_json(band_seam_report_path) if expansion_enabled else {}
    top_pack_size = max(0, int(args.top_pack_size)) if expansion_enabled else 0
    large_mover_window = max(0, int(args.large_mover_window)) if expansion_enabled else 0
    cross_band_challenger_count = max(0, int(args.cross_band_challenger_count)) if expansion_enabled else 0
    cross_band_anchor_count = max(0, int(args.cross_band_anchor_count)) if expansion_enabled else 0
    uncertainty_challenger_count = max(0, int(args.uncertainty_challenger_count)) if expansion_enabled else 0
    uncertainty_anchor_count = max(0, int(args.uncertainty_anchor_count)) if expansion_enabled else 0

    judgments = collect_judgments(
        seed_rows,
        texts,
        rubric,
        outline,
        model=args.model,
        routing=args.routing,
        reasoning=args.reasoning,
        max_output_tokens=max(64, int(args.max_output_tokens)),
        window=max(1, int(args.window)),
        metadata=metadata,
        top_pack_size=top_pack_size,
        large_mover_window=large_mover_window,
        band_seam_report=band_seam_report,
        large_mover_divergence=max(0.0, float(args.large_mover_divergence)),
        cross_band_challenger_count=cross_band_challenger_count,
        cross_band_anchor_count=cross_band_anchor_count,
        uncertainty_challenger_count=uncertainty_challenger_count,
        uncertainty_anchor_count=uncertainty_anchor_count,
        anchor_dir=args.anchor_dir,
        orientation_audit=not args.disable_orientation_audit,
        replicates=max(1, int(args.replicates)),
    )
    out_path = Path(args.output)
    expansion_report_path = Path(args.expansion_report)
    if args.expansion_report == DEFAULT_EXPANSION_REPORT and out_path.parent.name != "outputs":
        expansion_report_path = out_path.parent / "post_seam_pair_expansion.json"
    write_judgment_payload(
        out_path,
        seed_rows,
        judgments,
        model=args.model,
        routing=args.routing,
        window=effective_window(max(1, int(args.window)), metadata),
        source_scores=str(scores_path),
        top_pack_size=top_pack_size,
        large_mover_window=large_mover_window,
        band_seam_report=str(band_seam_report_path) if expansion_enabled else "",
        cross_band_challenger_count=cross_band_challenger_count,
        cross_band_anchor_count=cross_band_anchor_count,
        uncertainty_challenger_count=uncertainty_challenger_count,
        uncertainty_anchor_count=uncertainty_anchor_count,
        orientation_audit=not args.disable_orientation_audit,
        replicates=max(1, int(args.replicates)),
    )
    if expansion_enabled:
        write_expansion_report(
            expansion_report_path,
            seed_rows,
            judgments,
            top_pack_size=top_pack_size,
            large_mover_window=large_mover_window,
            band_seam_report_path=str(band_seam_report_path),
            large_mover_divergence=max(0.0, float(args.large_mover_divergence)),
            cross_band_challenger_count=cross_band_challenger_count,
            cross_band_anchor_count=cross_band_anchor_count,
            uncertainty_challenger_count=uncertainty_challenger_count,
            uncertainty_anchor_count=uncertainty_anchor_count,
            band_seam_report=band_seam_report,
        )
    print(f"Pairwise judgments saved to {out_path}")

    if args.apply:
        run_global_rerank(
            scores_path=scores_path,
            judgments_path=out_path,
            config_path=Path(args.config),
            local_prior_path=Path(args.local_prior),
            final_order_path=Path(args.rerank_output),
            matrix_output_path=Path(args.matrix_output),
            score_output_path=Path(args.scores_output),
            report_output_path=Path(args.report_output),
            legacy_output_path=Path(args.legacy_output),
            iterations=300,
            learning_rate=0.18,
            regularization=0.75,
            low_confidence_max_displacement=1,
            medium_confidence_max_displacement=3,
            high_confidence_max_displacement=999999,
            max_cross_level_gap=1,
            max_cross_rubric_gap=2.0,
            min_crossing_margin=1.5,
            hard_evidence_margin=1.5,
        )
        print(f"Global rerank saved to {args.rerank_output}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
