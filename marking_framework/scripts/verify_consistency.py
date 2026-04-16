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
except ImportError:  # pragma: no cover - Support running as script without package context
    from assessor_utils import load_file_text, resolve_input_path  # pragma: no cover
    from assessor_context import load_class_metadata, normalize_genre  # pragma: no cover
    from global_rerank import run_global_rerank  # pragma: no cover
    from llm_assessors_core import json_from_text  # pragma: no cover
    from levels import normalize_level  # pragma: no cover
    from openai_client import extract_text, responses_create  # pragma: no cover


RESPONSE_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
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
        },
        "required": ["decision", "confidence", "rationale", "criterion_notes", "decision_basis", "cautions_applied"],
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

GENRE_PRIORITY_RULES = {
    "literary_analysis": {
        "label": "literary analysis",
        "criteria": [
            "Task alignment and interpretive claim about the text",
            "Depth of literary reasoning about theme, character, choices, consequences, or craft",
            "Specific text evidence and explanation of how it proves the interpretation",
            "Distinction between analysis and plot summary",
            "Organization and coherence as support for the analysis",
            "Language control and conventions only after meaning, evidence, and explanation",
        ],
        "cautions": [
            "A rougher essay with a clearer interpretation, better evidence explanation, or more task-specific meaning should beat a cleaner formulaic essay with thin insight.",
            "Do not let a five-paragraph shape, tidy topic sentences, length, or surface coherence outrank stronger literary thinking.",
            "Plot summary is not analysis unless the student explains how the events support the claim.",
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
        "- Do not use aggregate rank, Borda, rubric percent, or seed order as the reason for the decision; those are context only.",
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
) -> str:
    extra_guidance = genre_specific_pairwise_guidance(genre, metadata, anchor_dir)
    guidance_block = f"\nAdditional ranking guidance:\n{extra_guidance}\n" if extra_guidance else ""
    reason_text = ", ".join(selection_reasons or []) or "seed_window"
    details = "\n".join(f"- {detail}" for detail in (selection_details or []) if detail)
    details_block = f"\nSelection details:\n{details}\n" if details else ""
    output_contract = """Judgment process:
1. Compare the essays using the priority frame above, in order.
2. Name which essay is stronger for each major criterion. Use "tie" when there is no meaningful difference.
3. Decide KEEP only if Essay A should remain above Essay B. Decide SWAP only if Essay B should move above Essay A.
4. If one essay is cleaner or more formulaic but the other has stronger task-specific content, reasoning, evidence, or genre fulfillment, do not choose the cleaner essay for polish alone.
5. If conventions or organization drive the result, explain whether they merely polish the writing or actually affect meaning, accuracy, completion, or usability.
6. Confidence calibration:
   - Use high when the same essay is clearly stronger on task alignment plus content/reasoning or evidence/development, even if the other essay is cleaner or more formulaic.
   - Use medium when the important criteria are genuinely mixed or the advantage is modest.
   - Use low only when the comparison is ambiguous or both essays are similarly flawed.
   - Do not downgrade a clear content/evidence winner from high to medium just because it has more surface errors.
7. Use cautions_applied only for cautions that materially affected this judgment. Use an empty array when none of the caution labels is genuinely needed."""
    return f"""You are collecting pairwise ranking evidence for a global reranker.

Rubric:
{rubric}

Assignment Outline:
{outline}
{guidance_block}

Current seed order:
- Higher seed essay: {higher['student_id']} (seed rank {higher['seed_rank']}, level {higher['level'] or 'unknown'}, rubric {higher['rubric_after_penalty_percent']:.2f}%, Borda {clamp01(higher.get('borda_percent'), 0.0):.4f}, composite {num(higher.get('composite_score'), 0.0):.4f})
- Lower seed essay: {lower['student_id']} (seed rank {lower['seed_rank']}, level {lower['level'] or 'unknown'}, rubric {lower['rubric_after_penalty_percent']:.2f}%, Borda {clamp01(lower.get('borda_percent'), 0.0):.4f}, composite {num(lower.get('composite_score'), 0.0):.4f})

Why this pair is being checked:
{reason_text}
{details_block}

{output_contract}

Essay A (currently seeded above Essay B): {higher['student_id']}
{higher_text}

Essay B (currently seeded below Essay A): {lower['student_id']}
{lower_text}

Decide whether the seed order should stay as-is or flip for the final ranking.

Allowed values:
- decision: KEEP when Essay A should stay above Essay B; SWAP when Essay B should move above Essay A.
- confidence: low, medium, high.
- criterion_notes[].stronger: A, B, tie.
- decision_basis: task_alignment, content_reasoning, evidence_development, genre_requirements, organization, language_control, completion, balanced.
- cautions_applied: rougher_but_stronger_content, formulaic_but_thin, polished_but_shallow, mechanics_impede_meaning, off_task, incomplete_or_scaffold, genre_requirement_decisive. Use [] if no caution materially affected the decision.

Return ONLY valid JSON in this shape:
{{
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
  "cautions_applied": []
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


def build_repair_prompt(raw_text: str) -> str:
    return f"""The prior response was supposed to be JSON but was malformed.

Allowed values:
- decision: KEEP or SWAP.
- confidence: low, medium, high.
- criterion_notes[].stronger: A, B, tie.
- decision_basis: task_alignment, content_reasoning, evidence_development, genre_requirements, organization, language_control, completion, balanced.
- cautions_applied: rougher_but_stronger_content, formulaic_but_thin, polished_but_shallow, mechanics_impede_meaning, off_task, incomplete_or_scaffold, genre_requirement_decisive. Use [] if no caution materially affected the decision.

Return ONLY valid JSON in this shape:
{{
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
  "cautions_applied": []
}}

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
    )
    response = responses_create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        reasoning=reasoning,
        routing_path=routing,
        text_format=RESPONSE_FORMAT,
        max_output_tokens=max_output_tokens,
    )
    content = extract_text(response)
    repair_used = False
    try:
        parsed = parse_json(content)
    except ValueError:
        repair_used = True
        repair_response = responses_create(
            model=model,
            messages=[{"role": "user", "content": build_repair_prompt(content)}],
            temperature=0.0,
            reasoning="low",
            routing_path=routing,
            text_format=RESPONSE_FORMAT,
            max_output_tokens=max_output_tokens,
        )
        content = extract_text(repair_response)
        parsed = parse_json(content)
        response = repair_response
    decision = normalize_decision(parsed.get("decision"))
    confidence = normalize_confidence(parsed.get("confidence"))
    rationale = str(parsed.get("rationale") or parsed.get("reason") or "").strip()
    criterion_notes = normalize_criterion_notes(parsed.get("criterion_notes"))
    decision_basis = normalize_decision_basis(parsed.get("decision_basis"))
    cautions_applied = normalize_cautions(parsed.get("cautions_applied"))
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
        "decision": decision,
        "winner": pair_winner_from_decision(higher, lower, decision),
        "loser": pair_loser_from_decision(higher, lower, decision),
        "confidence": confidence,
        "rationale": rationale,
        "criterion_notes": criterion_notes,
        "decision_basis": decision_basis,
        "cautions_applied": cautions_applied,
        "model_metadata": {
            "requested_model": model,
            "response_model": response.get("model") or model,
            "routing_path": routing,
            "repair_used": repair_used,
            "reasoning": reasoning,
            "temperature": 0.0,
            "cached": bool(response.get("cached", False)),
            "usage": response.get("usage", {}),
        },
    }


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
    anchor_dir: str | Path | None = None,
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
    )
    for spec in pair_specs:
        higher = spec["higher"]
        lower = spec["lower"]
        judgment = judge_pair(
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
            selection_details=spec.get("selection_details", []),
            anchor_dir=anchor_dir,
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
    parser.add_argument("--band-seam-report", default=DEFAULT_BAND_SEAM_REPORT, help="Band seam report used for post-seam pair expansion")
    parser.add_argument("--expansion-report", default=DEFAULT_EXPANSION_REPORT, help="Pair expansion audit artifact JSON")
    parser.add_argument("--disable-post-seam-expansion", action="store_true", help="Disable top-pack and large-mover pair expansion")
    parser.add_argument("--anchor-dir", default=str(DEFAULT_PAIRWISE_ANCHOR_DIR), help="Directory of genre-specific pairwise calibration anchor JSON files")
    parser.add_argument("--max-output-tokens", type=int, default=600, help="Max model output tokens")
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
        anchor_dir=args.anchor_dir,
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
