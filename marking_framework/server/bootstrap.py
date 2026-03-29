#!/usr/bin/env python3
import json
from pathlib import Path

from scripts.assessor_context import grade_band_for_level, normalize_genre
from scripts.calibration_contract import (
    build_calibration_manifest,
    build_run_scope,
    build_scope_coverage_entry,
    calibration_manifest_path,
    file_sha256,
    infer_scope_coverage_from_bias,
    load_json,
    now_iso,
)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        data = _read_json(path)
        if data:
            return data
    metadata = {
        "grade_level": 7,
        "genre": "literary_analysis",
        "generated_by": "bootstrap",
        "generated_at": now_iso(),
    }
    path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def _bootstrap_manifest_payload(root: Path, metadata: dict, bias_payload: dict, synthetic: bool = True) -> dict:
    routing = load_json(root / "config" / "llm_routing.json")
    run_scope = build_run_scope(metadata=metadata, routing=routing, rubric_path=root / "inputs" / "rubric.md")
    scope_coverage = infer_scope_coverage_from_bias(bias_payload, run_scope=run_scope, synthetic=synthetic)
    if not scope_coverage:
        samples = int((bias_payload.get("summary", {}) or {}).get("samples", 0) or 0)
        scope_coverage = [build_scope_coverage_entry(run_scope, samples=samples, observations=samples, synthetic=synthetic)]
    return build_calibration_manifest(
        profile_type="bootstrap_neutral" if synthetic else str(bias_payload.get("method") or "legacy_import"),
        synthetic=synthetic,
        scope_coverage=scope_coverage,
        routing=routing,
        rubric_path=root / "inputs" / "rubric.md",
        source_exemplar_set_hash_value=None,
        freshness_window_hours=float((routing.get("calibration_gate", {}) or {}).get("max_age_hours", 168) or 168),
        generated_at=str(bias_payload.get("generated_at") or now_iso()),
        artifact_hashes={},
    )


def _write_manifest_for_bias(root: Path, bias_path: Path, bias_payload: dict, synthetic: bool = True) -> Path:
    manifest_path = calibration_manifest_path(bias_path)
    manifest = _bootstrap_manifest_payload(root, ensure_class_metadata(root / "inputs"), bias_payload, synthetic=synthetic)
    manifest["artifact_hashes"]["calibration_bias_sha256"] = file_sha256(bias_path)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def ensure_bootstrap_calibration(root: Path, metadata: dict, assessors: list[str] | None = None) -> Path:
    assessors = assessors or ["A", "B", "C"]
    outputs_dir = root / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    path = outputs_dir / "calibration_bias.json"
    manifest_path = calibration_manifest_path(path)
    if path.exists() and manifest_path.exists():
        return path
    if path.exists() and not manifest_path.exists():
        payload = _read_json(path)
        synthetic = bool(payload.get("synthetic", payload.get("method") == "bootstrap_neutral"))
        _write_manifest_for_bias(root, path, payload, synthetic=synthetic)
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
        "boundary_mae": 0.0,
        "pairwise_order_agreement": 1.0,
        "boundary_pairwise_disagreement": 0.0,
        "boundary_pairwise_disagreement_concentration": 0.0,
        "rank_stability_sd": 0.0,
        "repeat_level_consistency": 1.0,
    }
    payload = {
        "method": "bootstrap_neutral",
        "synthetic": True,
        "generated_at": now_iso(),
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
    _write_manifest_for_bias(root, path, payload, synthetic=True)
    return path
