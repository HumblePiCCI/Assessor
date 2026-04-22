#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.assessor_context import infer_genre_from_text, normalize_genre
    from scripts.calibration_contract import canonical_json_hash, file_sha256, normalize_scope_input
    from scripts.document_extract import clean_text, extract_document_text, resolve_document_path
    from scripts.rubric_criteria import criteria_for_genre, load_rubric_criteria
except ImportError:  # pragma: no cover - Support running as a script
    from assessor_context import infer_genre_from_text, normalize_genre  # pragma: no cover
    from calibration_contract import canonical_json_hash, file_sha256, normalize_scope_input  # pragma: no cover
    from document_extract import clean_text, extract_document_text, resolve_document_path  # pragma: no cover
    from rubric_criteria import criteria_for_genre, load_rubric_criteria  # pragma: no cover


RUBRIC_SCHEMA_VERSION = 1
RUBRIC_ARTIFACTS = {
    "normalized_rubric": "outputs/normalized_rubric.json",
    "rubric_manifest": "outputs/rubric_manifest.json",
    "rubric_validation_report": "outputs/rubric_validation_report.json",
    "rubric_verification": "outputs/rubric_verification.json",
}
LOW_CONFIDENCE_THRESHOLD = 0.56
HIGH_CONFIDENCE_THRESHOLD = 0.8
SUPPORTED_SUFFIXES = {".md", ".txt", ".json", ".csv", ".docx", ".pdf", ".rtf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".webp", ".gif", ".bmp"}
GENRE_OPTIONS = {
    "argumentative",
    "informational",
    "literary_analysis",
    "narrative",
    "persuasive",
    "poetry",
    "reflective",
}
CANONICAL_DIMENSIONS = (
    (
        "ideas_analysis",
        "Ideas and Analysis",
        (
            "idea",
            "analysis",
            "thinking",
            "insight",
            "interpretation",
            "theme",
            "understanding",
            "meaning",
            "content",
            "knowledge",
        ),
    ),
    (
        "organization",
        "Organization",
        (
            "organization",
            "structure",
            "paragraph",
            "coherence",
            "flow",
            "transition",
            "sequencing",
            "introduction",
            "conclusion",
        ),
    ),
    (
        "evidence_support",
        "Evidence and Support",
        (
            "evidence",
            "support",
            "quotation",
            "quote",
            "example",
            "detail",
            "proof",
            "reference",
            "citation",
        ),
    ),
    (
        "style_voice",
        "Style and Voice",
        (
            "voice",
            "style",
            "eloquence",
            "word choice",
            "diction",
            "tone",
            "audience",
            "concision",
            "clarity",
        ),
    ),
    (
        "conventions",
        "Conventions",
        (
            "grammar",
            "convention",
            "mechanic",
            "punctuation",
            "spelling",
            "sentence",
            "syntax",
            "usage",
            "editing",
        ),
    ),
)
LEVEL_DEFAULTS = [
    {"label": "1", "band_min": 0.0, "band_max": 59.99},
    {"label": "2", "band_min": 60.0, "band_max": 69.99},
    {"label": "3", "band_min": 70.0, "band_max": 79.99},
    {"label": "4", "band_min": 80.0, "band_max": 100.0},
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_payload(payload):
    if isinstance(payload, dict):
        return {
            key: _stable_payload(value)
            for key, value in payload.items()
            if key not in {"generated_at", "confirmed_at", "updated_at"}
        }
    if isinstance(payload, list):
        return [_stable_payload(item) for item in payload]
    return payload


def stable_contract_hash(payload) -> str:
    return canonical_json_hash(_stable_payload(payload))


def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def resolve_rubric_path(path: Path) -> Path:
    return resolve_document_path(path)


def _line_tokens(text: str) -> list[str]:
    return [line.strip() for line in clean_text(text).splitlines() if line.strip()]


def _is_level_line(line: str) -> bool:
    low = line.lower()
    return bool(re.search(r"\blevel\s*[1-4]\+?\b", low)) or bool(re.search(r"\b[1-4]\+?\s*[-:–]\s*", low))


def _is_weight_line(line: str) -> bool:
    return bool(re.search(r"(?i)\b\d{1,3}\s*(%|pts?|points?)\b", line))


def _canonical_dimension(text: str) -> tuple[str, str]:
    low = text.lower()
    best = ("criterion_other", "Other")
    best_hits = 0
    for cid, label, keywords in CANONICAL_DIMENSIONS:
        hits = sum(1 for token in keywords if token in low)
        if hits > best_hits:
            best = (cid, label)
            best_hits = hits
    return best


def _criterion_from_line(line: str, index: int) -> dict | None:
    raw = re.sub(r"^[\-\*\u2022\d\.\)\(]+", "", line).strip(" :-\t")
    if len(raw) < 3:
        return None
    if _is_level_line(raw):
        return None
    if re.match(r"(?i)^(comments?|notes?|scoring|descriptors?)$", raw):
        return None
    weight = None
    weight_match = re.search(r"(?i)\b(\d{1,3}(?:\.\d+)?)\s*(%|pts?|points?)\b", raw)
    if weight_match:
        weight = float(weight_match.group(1))
        raw = raw[: weight_match.start()].strip(" :-\t")
    cid, canonical_label = _canonical_dimension(raw)
    label = raw or canonical_label
    return {
        "id": f"criterion_{index}",
        "name": label,
        "canonical_dimension": cid,
        "canonical_label": canonical_label,
        "weight": weight,
        "descriptor_summary": "",
        "evidence_expectations": [],
        "raw_line": line,
    }


def _criteria_from_text(text: str, criteria_cfg: dict, genre: str | None) -> tuple[list[dict], list[str]]:
    warnings = []
    lines = _line_tokens(text)
    criteria = []
    seen = set()
    for line in lines:
        if not (_is_weight_line(line) or any(token in line.lower() for token in ("ideas", "organization", "evidence", "voice", "style", "grammar", "conventions", "analysis"))):
            continue
        item = _criterion_from_line(line, len(criteria) + 1)
        if not item:
            continue
        token = re.sub(r"[^a-z0-9]+", "", item["name"].lower())
        if not token or token in seen:
            continue
        seen.add(token)
        criteria.append(item)
    if criteria:
        return _normalize_weights(criteria), warnings

    # Fall back to the canonical scaffold when the uploaded rubric is sparse.
    scaffold = criteria_for_genre(criteria_cfg, genre) if criteria_cfg else []
    for idx, item in enumerate(scaffold[:6], start=1):
        criteria.append(
            {
                "id": str(item.get("id") or f"criterion_{idx}"),
                "name": str(item.get("name") or f"Criterion {idx}"),
                "canonical_dimension": _canonical_dimension(str(item.get("description") or item.get("name") or ""))[0],
                "canonical_label": _canonical_dimension(str(item.get("description") or item.get("name") or ""))[1],
                "weight": None,
                "descriptor_summary": str(item.get("description") or ""),
                "evidence_expectations": [],
                "raw_line": "",
            }
        )
    if criteria:
        warnings.append("criteria_inferred_from_canonical_scaffold")
        return _normalize_weights(criteria), warnings
    for idx, (_cid, label, _keywords) in enumerate(CANONICAL_DIMENSIONS[:4], start=1):
        criteria.append(
            {
                "id": f"criterion_{idx}",
                "name": label,
                "canonical_dimension": _cid,
                "canonical_label": label,
                "weight": None,
                "descriptor_summary": "",
                "evidence_expectations": [],
                "raw_line": "",
            }
        )
    if criteria:
        warnings.append("criteria_inferred_from_default_dimensions")
        return _normalize_weights(criteria), warnings
    warnings.append("criteria_parse_empty")
    return [], warnings


def _normalize_weights(criteria: list[dict]) -> list[dict]:
    weighted = [item for item in criteria if isinstance(item.get("weight"), (int, float)) and float(item["weight"]) > 0]
    if weighted:
        total = sum(float(item["weight"]) for item in weighted)
        for item in criteria:
            if item in weighted:
                item["weight"] = round(float(item["weight"]) / total, 6)
            else:
                item["weight"] = 0.0
        zero_count = sum(1 for item in criteria if not item["weight"])
        if zero_count:
            remainder = round(sum(item["weight"] for item in criteria), 6)
            if remainder < 1.0:
                share = round((1.0 - remainder) / zero_count, 6)
                for item in criteria:
                    if not item["weight"]:
                        item["weight"] = share
        return criteria
    if not criteria:
        return criteria
    equal = round(1.0 / len(criteria), 6)
    for item in criteria:
        item["weight"] = equal
    return criteria


def _levels_from_text(text: str) -> tuple[list[dict], list[str]]:
    warnings = []
    levels = []
    seen = set()
    for line in _line_tokens(text):
        match = re.search(
            r"(?i)(?:level\s*)?([1-4]\+?)\b.*?(?:(\d{1,3}(?:\.\d+)?)\s*[-–]\s*(\d{1,3}(?:\.\d+)?))?",
            line,
        )
        if not match:
            continue
        label = match.group(1)
        if label in seen:
            continue
        seen.add(label)
        band_min = float(match.group(2)) if match.group(2) is not None else None
        band_max = float(match.group(3)) if match.group(3) is not None else None
        descriptor = line.strip()
        levels.append(
            {
                "label": str(label),
                "band_min": band_min,
                "band_max": band_max,
                "descriptor": descriptor,
            }
        )
    if not levels:
        warnings.append("level_descriptors_not_explicit")
        return [dict(item) for item in LEVEL_DEFAULTS], warnings
    levels.sort(key=lambda item: float(re.sub(r"[^0-9.]", "", str(item["label"])) or 0.0))
    # Fill in missing band ranges with the Ontario defaults.
    default_lookup = {item["label"]: item for item in LEVEL_DEFAULTS}
    for item in levels:
        default = default_lookup.get(str(item["label"]))
        if default is None:
            continue
        if item["band_min"] is None:
            item["band_min"] = default["band_min"]
        if item["band_max"] is None:
            item["band_max"] = default["band_max"]
    return levels, warnings


def _evidence_requirements(text: str, criteria_cfg: dict) -> dict:
    requirements = {}
    cfg = criteria_cfg.get("evidence_requirements", {}) if isinstance(criteria_cfg, dict) else {}
    if isinstance(cfg, dict):
        requirements.update(cfg)
    low = text.lower()
    requirements["requires_textual_evidence"] = any(token in low for token in ("quote", "quotation", "evidence", "support", "citation"))
    requirements["requires_analysis"] = any(token in low for token in ("analysis", "explain", "this shows", "interpret"))
    return requirements


def _summary_lines(criteria: list[dict], levels: list[dict], genre: str, evidence: dict) -> list[str]:
    lines = []
    if criteria:
        lines.append(f"We think your rubric has {len(criteria)} criteria.")
        weighted = [item for item in criteria if isinstance(item.get('weight'), (int, float))]
        if weighted:
            top = sorted(weighted, key=lambda item: float(item.get("weight", 0.0)), reverse=True)[:2]
            top_text = ", ".join(f"{item['name']} ({round(float(item['weight']) * 100):d}%)" for item in top)
            lines.append(f"We think the strongest weighting is on {top_text}.")
    if levels:
        ordered = ", ".join(
            f"Level {item['label']}={int(float(item['band_min']))}-{int(float(item['band_max']))}"
            for item in levels
            if item.get("band_min") is not None and item.get("band_max") is not None
        )
        if ordered:
            lines.append(f"We think the level mapping is {ordered}.")
    if genre:
        lines.append(f"We think this is closest to a {genre.replace('_', ' ')} rubric.")
    if evidence.get("requires_textual_evidence"):
        lines.append("We think the rubric expects explicit evidence or quotation support.")
    if evidence.get("requires_analysis"):
        lines.append("We think the rubric expects explanation or analysis, not just summary.")
    return lines


def _confidence_score(text: str, criteria: list[dict], levels: list[dict], extraction: dict, criteria_warnings: list[str], level_warnings: list[str]) -> tuple[float, str, list[str]]:
    score = 0.0
    signals = []
    if text:
        score += 0.25
        signals.append("text_extracted")
    if criteria:
        score += 0.25
        signals.append("criteria_detected")
    if levels:
        score += 0.2
        signals.append("levels_detected")
    if len(levels) >= 4:
        score += 0.1
        signals.append("full_level_scale")
    if not extraction.get("warnings"):
        score += 0.1
        signals.append("clean_extraction")
    if not criteria_warnings and not level_warnings:
        score += 0.1
        signals.append("low_warning_count")
    if score >= HIGH_CONFIDENCE_THRESHOLD:
        return round(score, 6), "high", signals
    if score >= LOW_CONFIDENCE_THRESHOLD:
        return round(score, 6), "medium", signals
    return round(score, 6), "low", signals


def _normalized_rubric(
    rubric_path: Path,
    *,
    outline_text: str = "",
    criteria_config_path: Path | None = None,
    teacher_edits: dict | None = None,
) -> tuple[dict, dict, dict, dict]:
    rubric_path = resolve_rubric_path(rubric_path)
    if not rubric_path.exists():
        raise FileNotFoundError(f"Rubric file not found: {rubric_path}")
    criteria_cfg = load_rubric_criteria(criteria_config_path) if criteria_config_path else {}
    raw_text, extraction = extract_document_text(rubric_path)
    genre = normalize_genre(infer_genre_from_text(raw_text, outline_text))
    criteria, criteria_warnings = _criteria_from_text(raw_text, criteria_cfg, genre)
    levels, level_warnings = _levels_from_text(raw_text)
    evidence = _evidence_requirements(raw_text, criteria_cfg)
    confidence_score, confidence_status, signals = _confidence_score(raw_text, criteria, levels, extraction, criteria_warnings, level_warnings)
    normalized = {
        "schema_version": RUBRIC_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "source": {
            "path": str(rubric_path),
            "filename": rubric_path.name,
            "sha256": file_sha256(rubric_path),
            "format": extraction.get("source_format", "unknown"),
        },
        "genre": genre,
        "rubric_family": "",
        "criteria": criteria,
        "scale": {
            "levels": levels,
            "level_count": len(levels),
            "score_bands_explicit": not bool(level_warnings),
        },
        "evidence_requirements": evidence,
        "plain_language_summary": _summary_lines(criteria, levels, genre, evidence),
        "raw_text": raw_text,
        "raw_text_excerpt": raw_text[:4000],
    }
    normalized["rubric_family"] = rubric_family_id(normalized)
    if teacher_edits:
        normalized = apply_teacher_edits(normalized, teacher_edits)
    validation = build_validation_report(normalized, extraction, criteria_warnings, level_warnings, confidence_score, confidence_status, signals)
    verification = build_verification(normalized, validation, teacher_edits=teacher_edits)
    manifest = build_rubric_manifest(normalized, validation, verification)
    return normalized, manifest, validation, verification


def rubric_family_id(normalized: dict) -> str:
    criteria_names = [re.sub(r"[^a-z0-9]+", "_", str(item.get("canonical_dimension") or item.get("name") or "").strip().lower()).strip("_") for item in normalized.get("criteria", [])]
    criteria_names = [item for item in criteria_names if item]
    genre = str(normalized.get("genre", "") or "general")
    level_count = int(((normalized.get("scale", {}) or {}).get("level_count", 0) or 0))
    token = "__".join([genre or "general", str(level_count or 0), "-".join(criteria_names[:4]) or "generic"])
    digest = canonical_json_hash(
        {
            "genre": genre,
            "criteria": criteria_names,
            "levels": [item.get("label") for item in ((normalized.get("scale", {}) or {}).get("levels", []) or [])],
        }
    )
    base = re.sub(r"[^a-z0-9_]+", "_", token.lower()).strip("_")
    return f"{base}_{digest[:8]}"


def build_validation_report(
    normalized: dict,
    extraction: dict,
    criteria_warnings: list[str],
    level_warnings: list[str],
    confidence_score: float,
    confidence_status: str,
    signals: list[str],
) -> dict:
    errors = []
    warnings = list(dict.fromkeys(list(extraction.get("warnings", [])) + list(criteria_warnings) + list(level_warnings)))
    if not normalized.get("raw_text"):
        errors.append("rubric_text_empty")
    if not normalized.get("criteria"):
        errors.append("criteria_missing")
    if not ((normalized.get("scale", {}) or {}).get("levels")):
        errors.append("level_scale_missing")
    proceed_mode = "auto"
    requires_confirmation = False
    if errors or confidence_status == "low":
        proceed_mode = "block"
        requires_confirmation = True
    elif confidence_status == "medium":
        proceed_mode = "warn"
    return {
        "schema_version": RUBRIC_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "source_format": normalized.get("source", {}).get("format", "unknown"),
        "confidence": {
            "score": confidence_score,
            "status": confidence_status,
            "signals": signals,
        },
        "coverage": {
            "criteria_count": len(normalized.get("criteria", [])),
            "level_count": int(((normalized.get("scale", {}) or {}).get("level_count", 0) or 0)),
            "genre_detected": bool(normalized.get("genre")),
            "weight_sum": round(sum(float(item.get("weight", 0.0) or 0.0) for item in normalized.get("criteria", [])), 6),
        },
        "parse_checks": {
            "errors": errors,
            "warnings": warnings,
        },
        "proceed_mode": proceed_mode,
        "requires_confirmation": requires_confirmation,
    }


def _sanitize_edit_list(items) -> list[dict]:
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(dict(item))
    return out


def apply_teacher_edits(normalized: dict, teacher_edits: dict | None) -> dict:
    payload = json.loads(json.dumps(normalized))
    edits = dict(teacher_edits or {})
    genre = normalize_genre(edits.get("genre"))
    if genre:
        payload["genre"] = genre
    rubric_family = str(edits.get("rubric_family", "") or "").strip()
    if rubric_family:
        payload["rubric_family"] = re.sub(r"[^a-z0-9_]+", "_", rubric_family.lower()).strip("_")
    criteria = _sanitize_edit_list(edits.get("criteria"))
    if criteria:
        merged = []
        for index, item in enumerate(criteria, start=1):
            name = str(item.get("name", "") or "").strip()
            if not name:
                continue
            cid, label = _canonical_dimension(name)
            weight = item.get("weight")
            try:
                weight = float(weight) if weight not in ("", None) else None
            except (TypeError, ValueError):
                weight = None
            merged.append(
                {
                    "id": str(item.get("id") or f"criterion_{index}"),
                    "name": name,
                    "canonical_dimension": str(item.get("canonical_dimension") or cid),
                    "canonical_label": str(item.get("canonical_label") or label),
                    "weight": weight,
                    "descriptor_summary": str(item.get("descriptor_summary", "") or ""),
                    "evidence_expectations": list(item.get("evidence_expectations", []) or []),
                    "raw_line": str(item.get("raw_line", "") or ""),
                }
            )
        payload["criteria"] = _normalize_weights(merged)
    levels = _sanitize_edit_list(edits.get("levels"))
    if levels:
        merged_levels = []
        for item in levels:
            label = str(item.get("label", "") or "").strip()
            if not label:
                continue
            try:
                band_min = float(item.get("band_min")) if item.get("band_min") not in ("", None) else None
            except (TypeError, ValueError):
                band_min = None
            try:
                band_max = float(item.get("band_max")) if item.get("band_max") not in ("", None) else None
            except (TypeError, ValueError):
                band_max = None
            merged_levels.append(
                {
                    "label": label,
                    "band_min": band_min,
                    "band_max": band_max,
                    "descriptor": str(item.get("descriptor", "") or ""),
                }
            )
        merged_levels.sort(key=lambda item: float(re.sub(r"[^0-9.]", "", item["label"]) or 0.0))
        payload["scale"]["levels"] = merged_levels
        payload["scale"]["level_count"] = len(merged_levels)
        payload["scale"]["score_bands_explicit"] = True
    notes = str(edits.get("teacher_notes", "") or "").strip()
    if notes:
        payload["teacher_notes"] = notes
    if not payload.get("rubric_family"):
        payload["rubric_family"] = rubric_family_id(payload)
    return payload


def build_verification(normalized: dict, validation: dict, *, teacher_edits: dict | None = None, action: str | None = None) -> dict:
    confidence_status = str(((validation.get("confidence", {}) or {}).get("status", "") or "low")).lower()
    edits = dict(teacher_edits or {})
    status = "auto_confirmed"
    if validation.get("requires_confirmation"):
        status = "needs_confirmation"
    elif confidence_status == "medium":
        status = "warning"
    if action in {"confirm", "confirmed"}:
        status = "confirmed"
    elif action in {"edit", "edited"} or edits:
        status = "edited"
    elif action == "reject":
        status = "rejected"
    return {
        "schema_version": RUBRIC_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "status": status,
        "required_confirmation": bool(validation.get("requires_confirmation", False)) and status not in {"confirmed", "edited"},
        "teacher_edits": edits,
        "warnings": list((validation.get("parse_checks", {}) or {}).get("warnings", []) or []),
        "errors": list((validation.get("parse_checks", {}) or {}).get("errors", []) or []),
        "summary": list(normalized.get("plain_language_summary", []) or []),
        "editable_projection": {
            "genre": normalized.get("genre", ""),
            "rubric_family": normalized.get("rubric_family", ""),
            "criteria": [
                {
                    "id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "weight": item.get("weight", ""),
                    "canonical_dimension": item.get("canonical_dimension", ""),
                    "descriptor_summary": item.get("descriptor_summary", ""),
                }
                for item in normalized.get("criteria", [])
            ],
            "levels": [
                {
                    "label": item.get("label", ""),
                    "band_min": item.get("band_min"),
                    "band_max": item.get("band_max"),
                    "descriptor": item.get("descriptor", ""),
                }
                for item in ((normalized.get("scale", {}) or {}).get("levels", []) or [])
            ],
        },
    }


def build_rubric_manifest(normalized: dict, validation: dict, verification: dict) -> dict:
    manifest = {
        "schema_version": RUBRIC_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "source": dict(normalized.get("source", {})),
        "genre": normalized.get("genre", ""),
        "rubric_family": normalized.get("rubric_family", ""),
        "verification_status": verification.get("status", ""),
        "requires_confirmation": bool(verification.get("required_confirmation", False)),
        "proceed_mode": validation.get("proceed_mode", "block"),
        "confidence_status": ((validation.get("confidence", {}) or {}).get("status", "") or ""),
        "confidence_score": ((validation.get("confidence", {}) or {}).get("score", 0.0) or 0.0),
        "criteria_count": len(normalized.get("criteria", [])),
        "level_count": int(((normalized.get("scale", {}) or {}).get("level_count", 0) or 0)),
        "weight_sum": round(sum(float(item.get("weight", 0.0) or 0.0) for item in normalized.get("criteria", [])), 6),
        "hashes": {},
    }
    manifest["hashes"]["normalized_rubric_sha256"] = stable_contract_hash(normalized)
    manifest["hashes"]["rubric_validation_report_sha256"] = stable_contract_hash(validation)
    manifest["hashes"]["rubric_verification_sha256"] = stable_contract_hash(verification)
    manifest["manifest_hash"] = stable_contract_hash(manifest)
    return manifest


def build_rubric_artifacts(
    rubric_path: Path,
    *,
    outline_path: Path | None = None,
    criteria_config_path: Path | None = None,
    existing_verification: dict | None = None,
    teacher_edits: dict | None = None,
    action: str | None = None,
) -> dict:
    rubric_path = resolve_rubric_path(rubric_path)
    outline_text = ""
    if outline_path is not None and resolve_rubric_path(outline_path).exists():
        outline_text, _outline_meta = extract_document_text(resolve_rubric_path(outline_path))
    merged_edits = {}
    existing_status = ""
    if isinstance(existing_verification, dict) and existing_verification:
        merged_edits.update(existing_verification.get("teacher_edits", {}) if isinstance(existing_verification.get("teacher_edits", {}), dict) else {})
        existing_status = str(existing_verification.get("status", "") or "")
    if teacher_edits:
        merged_edits.update(dict(teacher_edits))
    normalized, manifest, validation, verification = _normalized_rubric(
        rubric_path,
        outline_text=outline_text,
        criteria_config_path=criteria_config_path,
        teacher_edits=merged_edits or None,
    )
    if existing_status in {"confirmed", "edited"} and not action:
        action = "edit" if merged_edits else "confirm"
    verification = build_verification(normalized, validation, teacher_edits=merged_edits or None, action=action)
    manifest = build_rubric_manifest(normalized, validation, verification)
    return {
        "normalized_rubric": normalized,
        "rubric_manifest": manifest,
        "rubric_validation_report": validation,
        "rubric_verification": verification,
    }


def write_rubric_artifacts(output_dir: Path, artifacts: dict) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for key, rel_path in RUBRIC_ARTIFACTS.items():
        payload = artifacts.get(key, {})
        path = output_dir / Path(rel_path).name if output_dir.name == "outputs" else output_dir / rel_path
        write_json(path, payload if isinstance(payload, dict) else {})
        written[key] = path
    return written


def load_rubric_artifacts(root: Path) -> dict:
    payload = {}
    for key, rel_path in RUBRIC_ARTIFACTS.items():
        payload[key] = load_json(root / rel_path)
    return payload


def rubric_contract_summary(artifacts: dict) -> dict:
    manifest = artifacts.get("rubric_manifest", {}) if isinstance(artifacts.get("rubric_manifest", {}), dict) else {}
    verification = artifacts.get("rubric_verification", {}) if isinstance(artifacts.get("rubric_verification", {}), dict) else {}
    validation = artifacts.get("rubric_validation_report", {}) if isinstance(artifacts.get("rubric_validation_report", {}), dict) else {}
    return {
        "rubric_family": str(manifest.get("rubric_family", "") or ""),
        "verification_status": str(verification.get("status", "") or ""),
        "requires_confirmation": bool(verification.get("required_confirmation", False)),
        "proceed_mode": str(validation.get("proceed_mode", "") or manifest.get("proceed_mode", "") or ""),
        "confidence_status": str((validation.get("confidence", {}) or {}).get("status", "") or manifest.get("confidence_status", "") or ""),
        "confidence_score": float((validation.get("confidence", {}) or {}).get("score", manifest.get("confidence_score", 0.0)) or 0.0),
        "manifest_hash": str(manifest.get("manifest_hash", "") or ""),
        "source_sha256": str((manifest.get("source", {}) or {}).get("sha256", "") or ""),
        "normalized_sha256": str(((manifest.get("hashes", {}) or {}).get("normalized_rubric_sha256", "") or "")),
        "verification_sha256": str(((manifest.get("hashes", {}) or {}).get("rubric_verification_sha256", "") or "")),
    }


def prompt_text_from_normalized(normalized: dict, *, include_raw_text: bool = True) -> str:
    lines = [
        "VERIFIED RUBRIC CONTRACT",
        f"- Genre: {normalized.get('genre', '') or 'unknown'}",
        f"- Rubric family: {normalized.get('rubric_family', '') or 'unknown'}",
        "- Criteria:",
    ]
    for item in normalized.get("criteria", []) or []:
        weight = item.get("weight")
        weight_label = ""
        if isinstance(weight, (int, float)):
            weight_label = f" ({round(float(weight) * 100):d}%)"
        summary = str(item.get("descriptor_summary", "") or "").strip()
        lines.append(f"  - {item.get('name', 'Criterion')}{weight_label}: {summary or item.get('canonical_label', '')}")
    levels = ((normalized.get("scale", {}) or {}).get("levels", []) or [])
    if levels:
        lines.append("- Level expectations:")
        for item in levels:
            band_min = item.get("band_min")
            band_max = item.get("band_max")
            if band_min is None or band_max is None:
                band = f"Level {item.get('label', '')}"
            else:
                band = f"Level {item.get('label', '')} ({int(float(band_min))}-{int(float(band_max))})"
            lines.append(f"  - {band}: {str(item.get('descriptor', '') or '').strip()}")
    evidence = normalized.get("evidence_requirements", {}) if isinstance(normalized.get("evidence_requirements", {}), dict) else {}
    if evidence:
        lines.append("- Evidence expectations:")
        for key, value in evidence.items():
            lines.append(f"  - {key}: {value}")
    if include_raw_text and normalized.get("raw_text"):
        lines.append("\nORIGINAL RUBRIC TEXT")
        lines.append(str(normalized.get("raw_text", "")))
    return "\n".join(lines).strip()


def runtime_rubric_context(
    rubric_path: Path,
    *,
    normalized_path: Path | None = None,
    verification_path: Path | None = None,
) -> dict:
    rubric_path = resolve_rubric_path(rubric_path)
    raw_text, extraction = extract_document_text(rubric_path)
    normalized = load_json(normalized_path) if normalized_path else {}
    verification = load_json(verification_path) if verification_path else {}
    if normalized and raw_text.strip():
        rubric_text = prompt_text_from_normalized(normalized, include_raw_text=True)
    else:
        rubric_text = raw_text
    return {
        "raw_text": raw_text,
        "rubric_text": rubric_text,
        "normalized_rubric": normalized,
        "verification": verification,
        "extraction": extraction,
    }


def build_run_scope_hints(artifacts: dict) -> dict:
    manifest = artifacts.get("rubric_manifest", {}) if isinstance(artifacts.get("rubric_manifest", {}), dict) else {}
    normalized = artifacts.get("normalized_rubric", {}) if isinstance(artifacts.get("normalized_rubric", {}), dict) else {}
    scope = normalize_scope_input(
        {
            "genre": normalized.get("genre", ""),
            "rubric_family": manifest.get("rubric_family", normalized.get("rubric_family", "")),
        }
    )
    scope["verification_status"] = manifest.get("verification_status", "")
    return scope
