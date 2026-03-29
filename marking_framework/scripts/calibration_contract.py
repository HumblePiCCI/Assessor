#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from scripts.assessor_context import grade_band_for_level, load_class_metadata, normalize_genre


CALIBRATION_MANIFEST_VERSION = 1
CALIBRATION_MANIFEST_NAME = "calibration_manifest.json"
DEFAULT_CALIBRATION_FRESHNESS_HOURS = 168.0
DEFAULT_GRADE_LEVEL = 7
DEFAULT_GENRE = "literary_analysis"
BOUNDARY_LEVEL_EDGES = (60.0, 70.0, 80.0, 90.0)
BOUNDARY_MARGIN = 5.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso8601(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def canonical_json_hash(payload) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _hash_file_into_digest(path: Path, digest, label: str):
    digest.update(label.encode("utf-8"))
    digest.update(b"\0")
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    digest.update(b"\0")


def tree_hash(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    digest = hashlib.sha256()
    if path.is_file():
        _hash_file_into_digest(path, digest, path.name)
        return digest.hexdigest()
    files = [item for item in sorted(path.rglob("*")) if item.is_file() and item.name != ".DS_Store"]
    for item in files:
        _hash_file_into_digest(item, digest, str(item.relative_to(path)))
    return digest.hexdigest()


def calibration_manifest_path(bias_path: Path) -> Path:
    return bias_path.with_name(CALIBRATION_MANIFEST_NAME)


def pass1_routing_profile(routing: dict) -> dict:
    tasks = routing.get("tasks", {}) if isinstance(routing, dict) else {}
    pass1 = tasks.get("pass1_assessor", {}) if isinstance(tasks, dict) else {}
    if not isinstance(pass1, dict):
        pass1 = {}
    return {
        "mode": routing.get("mode") if isinstance(routing, dict) else None,
        "pass1_assessor": {
            key: pass1.get(key)
            for key in ("model", "reasoning", "temperature", "max_output_tokens", "require_evidence")
            if key in pass1
        },
    }


def routing_profile_hash_from_payload(routing: dict) -> str | None:
    if not isinstance(routing, dict) or not routing:
        return None
    return canonical_json_hash(pass1_routing_profile(routing))


def model_version_from_routing(routing: dict) -> str:
    if not isinstance(routing, dict):
        return ""
    tasks = routing.get("tasks", {})
    if not isinstance(tasks, dict):
        return ""
    pass1 = tasks.get("pass1_assessor", {})
    if not isinstance(pass1, dict):
        return ""
    value = pass1.get("model")
    return str(value).strip() if value else ""


def _normalize_label(value: str | None) -> str:
    if not value:
        return ""
    lowered = str(value).strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered)
    lowered = re.sub(r"_+", "_", lowered).strip("_")
    return lowered


def model_family_from_version(model_version: str | None) -> str:
    normalized = str(model_version or "").strip()
    if not normalized:
        return ""
    normalized = normalized.split("@", 1)[0]
    match = re.match(r"^(.*)-\d{4}-\d{2}-\d{2}$", normalized)
    if match:
        normalized = match.group(1)
    return normalized


def parse_grade_level(value) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def default_metadata() -> dict:
    return {
        "grade_level": DEFAULT_GRADE_LEVEL,
        "genre": DEFAULT_GENRE,
    }


def normalize_metadata_scope(metadata: dict | None) -> tuple[dict, str]:
    raw = dict(metadata or {})
    source = "class_metadata" if raw else "bootstrap_default"
    explicit_grade_level = parse_grade_level(raw.get("grade_level"))
    used_default_grade_level = explicit_grade_level is None
    grade_level = explicit_grade_level
    if used_default_grade_level:
        grade_level = DEFAULT_GRADE_LEVEL
        source = "bootstrap_default" if not raw.get("grade_level") else source
    explicit_genre = normalize_genre(raw.get("genre") or raw.get("assignment_genre"))
    used_default_genre = not explicit_genre
    genre = explicit_genre or DEFAULT_GENRE
    if used_default_genre:
        source = "bootstrap_default" if source != "class_metadata" else source
    normalized = dict(raw)
    normalized["grade_level"] = grade_level
    normalized["genre"] = genre
    normalized.setdefault("assignment_genre", genre)
    normalized["_used_default_grade_level"] = used_default_grade_level
    normalized["_used_default_genre"] = used_default_genre
    return normalized, source


def rubric_family_from_metadata(metadata: dict | None, rubric_path: Path | None = None) -> str:
    meta = metadata or {}
    for key in ("rubric_family", "rubric_family_id", "rubric_name"):
        if meta.get(key):
            return _normalize_label(str(meta[key]))
    digest = file_sha256(rubric_path)
    if digest:
        return f"rubric_{digest[:12]}"
    return "rubric_unknown"


def build_run_scope(
    metadata: dict | None = None,
    routing: dict | None = None,
    rubric_path: Path | None = None,
) -> dict:
    normalized, source = normalize_metadata_scope(metadata)
    grade_level = int(normalized["grade_level"])
    grade_band = grade_band_for_level(grade_level)
    if not grade_band and bool(normalized.get("_used_default_grade_level")):
        grade_band = grade_band_for_level(DEFAULT_GRADE_LEVEL) or ""
    genre = normalize_genre(normalized.get("genre") or normalized.get("assignment_genre")) or DEFAULT_GENRE
    model_version = model_version_from_routing(routing or {})
    model_family = model_family_from_version(model_version)
    rubric_family = rubric_family_from_metadata(normalized, rubric_path)
    key = f"{grade_band}|{genre}" if grade_band and genre else ""
    scope_id_parts = [grade_band, genre, rubric_family, model_family]
    scope_id = "|".join(part for part in scope_id_parts if part)
    return {
        "grade_level": grade_level,
        "grade_band": grade_band,
        "genre": genre,
        "rubric_family": rubric_family,
        "model_family": model_family,
        "model_version": model_version,
        "key": key,
        "scope_id": scope_id,
        "source": source,
    }


def parse_scope_key(value: str | None) -> dict:
    text = str(value or "").strip()
    if "|" not in text:
        return {"key": text, "grade_band": "", "genre": ""}
    grade_band, genre = text.split("|", 1)
    return {"key": text, "grade_band": grade_band.strip(), "genre": normalize_genre(genre.strip()) or genre.strip()}


def normalize_scope_input(run_scope: dict | str | None) -> dict:
    if isinstance(run_scope, dict):
        payload = dict(run_scope)
        if not payload.get("key") and payload.get("grade_band") and payload.get("genre"):
            payload["key"] = f"{payload['grade_band']}|{payload['genre']}"
        if not payload.get("scope_id"):
            parts = [payload.get("grade_band"), payload.get("genre"), payload.get("rubric_family"), payload.get("model_family")]
            payload["scope_id"] = "|".join(part for part in parts if part)
        return payload
    return parse_scope_key(run_scope)


def build_scope_coverage_entry(
    scope: dict | str,
    *,
    samples: int = 0,
    observations: int = 0,
    synthetic: bool = False,
) -> dict:
    payload = normalize_scope_input(scope)
    return {
        "key": payload.get("key", ""),
        "scope_id": payload.get("scope_id", ""),
        "grade_band": payload.get("grade_band", ""),
        "genre": payload.get("genre", ""),
        "rubric_family": payload.get("rubric_family", ""),
        "model_family": payload.get("model_family", ""),
        "model_version": payload.get("model_version", ""),
        "samples": int(samples or 0),
        "observations": int(observations or 0),
        "synthetic": bool(synthetic),
    }


def scope_mismatch_fields(run_scope: dict | str | None, coverage_scope: dict | str | None) -> list[str]:
    run_payload = normalize_scope_input(run_scope)
    coverage_payload = normalize_scope_input(coverage_scope)
    mismatches = []
    for key in ("grade_band", "genre", "rubric_family", "model_family"):
        run_value = str(run_payload.get(key, "") or "").strip()
        coverage_value = str(coverage_payload.get(key, "") or "").strip()
        if run_value and coverage_value and run_value != coverage_value:
            mismatches.append(key)
    return mismatches


def scope_matches(run_scope: dict | str | None, coverage_scope: dict | str | None) -> bool:
    run_payload = normalize_scope_input(run_scope)
    coverage_payload = normalize_scope_input(coverage_scope)
    run_key = str(run_payload.get("key", "") or "").strip()
    coverage_key = str(coverage_payload.get("key", "") or "").strip()
    if run_key and coverage_key and run_key != coverage_key:
        return False
    return not scope_mismatch_fields(run_payload, coverage_payload)


def source_exemplar_set_hash(calibration_path: Path | None, exemplars_path: Path | None) -> str | None:
    payload = {}
    if calibration_path is not None:
        digest = file_sha256(calibration_path)
        if digest:
            payload["calibration_set_sha256"] = digest
    if exemplars_path is not None:
        digest = tree_hash(exemplars_path)
        if digest:
            payload["exemplar_tree_hash"] = digest
    if not payload:
        return None
    return canonical_json_hash(payload)


def build_calibration_manifest(
    *,
    profile_type: str,
    synthetic: bool,
    scope_coverage: list[dict],
    routing: dict | None = None,
    routing_profile_hash: str | None = None,
    model_version: str | None = None,
    rubric_path: Path | None = None,
    rubric_hash: str | None = None,
    source_exemplar_set_hash_value: str | None = None,
    freshness_window_hours: float | None = None,
    generated_at: str | None = None,
    artifact_hashes: dict | None = None,
) -> dict:
    version = str(model_version or model_version_from_routing(routing or {}))
    manifest = {
        "manifest_version": CALIBRATION_MANIFEST_VERSION,
        "profile_type": profile_type,
        "synthetic": bool(synthetic),
        "generated_at": generated_at or now_iso(),
        "freshness_window_hours": float(freshness_window_hours or DEFAULT_CALIBRATION_FRESHNESS_HOURS),
        "source_exemplar_set_hash": source_exemplar_set_hash_value,
        "model_version": version,
        "model_family": model_family_from_version(version),
        "routing_profile_hash": routing_profile_hash or routing_profile_hash_from_payload(routing or {}),
        "rubric_hash": rubric_hash or file_sha256(rubric_path),
        "scope_coverage": sorted(
            [dict(item) for item in scope_coverage],
            key=lambda item: (
                str(item.get("grade_band", "")),
                str(item.get("genre", "")),
                str(item.get("rubric_family", "")),
                str(item.get("model_family", "")),
                str(item.get("key", "")),
            ),
        ),
        "artifact_hashes": dict(artifact_hashes or {}),
    }
    return manifest


def infer_scope_coverage_from_bias(
    bias_payload: dict,
    *,
    run_scope: dict | str | None = None,
    synthetic: bool = False,
) -> list[dict]:
    by_key = {}
    assessors = bias_payload.get("assessors", {}) if isinstance(bias_payload, dict) else {}
    for assessor_payload in assessors.values() if isinstance(assessors, dict) else []:
        if not isinstance(assessor_payload, dict):
            continue
        for scope_key, profile in (assessor_payload.get("scopes", {}) or {}).items():
            if not isinstance(profile, dict):
                continue
            scope = build_scope_coverage_entry(
                normalize_scope_input(run_scope) | parse_scope_key(scope_key),
                samples=int(profile.get("samples", 0) or 0),
                observations=int(profile.get("observations", 0) or 0),
                synthetic=synthetic,
            )
            existing = by_key.get(scope["key"])
            if existing is None:
                by_key[scope["key"]] = scope
            else:
                existing["samples"] = max(existing["samples"], scope["samples"])
                existing["observations"] = max(existing["observations"], scope["observations"])
    if not by_key and run_scope:
        scope = build_scope_coverage_entry(run_scope, synthetic=synthetic)
        if scope.get("key"):
            by_key[scope["key"]] = scope
    return sorted(by_key.values(), key=lambda item: (item.get("grade_band", ""), item.get("genre", ""), item.get("key", "")))


def manifest_integrity_ok(bias_path: Path, manifest_payload: dict) -> bool:
    expected = ((manifest_payload or {}).get("artifact_hashes", {}) or {}).get("calibration_bias_sha256")
    if not expected:
        return True
    actual = file_sha256(bias_path)
    return bool(actual and actual == expected)


def hours_since(timestamp: str | None) -> float | None:
    dt = parse_iso8601(timestamp)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0


def is_boundary_score(score: float | int | None, margin: float = BOUNDARY_MARGIN) -> bool:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return False
    return any(abs(value - edge) <= float(margin) for edge in BOUNDARY_LEVEL_EDGES)


def load_run_scope_from_paths(
    class_metadata_path: Path | None,
    routing_path: Path | None,
    rubric_path: Path | None,
) -> dict:
    metadata = load_class_metadata(class_metadata_path) if class_metadata_path else {}
    routing = load_json(routing_path) if routing_path else {}
    return build_run_scope(metadata=metadata, routing=routing, rubric_path=rubric_path)
