#!/usr/bin/env python3
import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.assessor_context import grade_band_for_level, normalize_genre


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _scope_from_metadata(metadata: dict) -> str:
    grade_level = metadata.get("grade_level")
    try:
        grade_level = int(grade_level) if grade_level is not None else None
    except (TypeError, ValueError):
        grade_level = None
    genre = normalize_genre(metadata.get("genre") or metadata.get("assignment_genre"))
    band = grade_band_for_level(grade_level)
    if band and genre:
        return f"{band}|{genre}"
    return "grade_6_7|literary_analysis"


def ensure_class_metadata(inputs_dir: Path) -> dict:
    path = inputs_dir / "class_metadata.json"
    if path.exists():
        data = _read_json(path)
        if data:
            return data
    metadata = {
        "grade_level": 7,
        "genre": "literary_analysis",
        "generated_by": "bootstrap",
        "generated_at": _now_iso(),
    }
    path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def ensure_bootstrap_calibration(root: Path, metadata: dict, assessors: list[str] | None = None) -> Path:
    assessors = assessors or ["A", "B", "C"]
    outputs_dir = root / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    path = outputs_dir / "calibration_bias.json"
    if path.exists():
        return path
    scope = _scope_from_metadata(metadata)
    profile = {
        "bias": 0.0,
        "slope": 1.0,
        "intercept": 0.0,
        "weight": 1.0,
        "samples": 10,
        "observations": 10,
        "level_hit_rate": 1.0,
        "mae": 0.0,
        "pairwise_order_agreement": 1.0,
        "repeat_level_consistency": 1.0,
    }
    payload = {
        "method": "bootstrap_neutral",
        "generated_at": _now_iso(),
        "scope_template": "<grade_band>|<genre>",
        "assessors": {},
        "summary": {"samples": 0, "assessors": len(assessors), "scope_coverage": {scope: 0}},
    }
    for assessor in assessors:
        key = assessor if assessor.startswith("assessor_") else f"assessor_{assessor}"
        payload["assessors"][key] = {"global": dict(profile), "scopes": {scope: dict(profile)}}
        payload["summary"]["samples"] += int(profile["samples"])
        payload["summary"]["scope_coverage"][scope] += int(profile["samples"])
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
