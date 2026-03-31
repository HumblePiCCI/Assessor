#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.calibration_contract import (
    calibration_manifest_path,
    file_sha256,
    hours_since,
    infer_scope_coverage_from_bias,
    load_json,
    manifest_integrity_ok,
    normalize_scope_input,
    parse_iso8601,
    routing_profile_hash_from_payload,
    scope_matches,
    scope_mismatch_fields,
    source_exemplar_set_hash,
)


def _parse_iso8601(value: str | None):
    return parse_iso8601(value)


def _context_path(context: dict | None, key: str, default: str) -> Path:
    raw = (context or {}).get(key, default)
    return Path(str(raw))


def _load_payload(path: Path) -> tuple[dict, str | None]:
    if not path.exists():
        return {}, f"missing:{path}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}, f"invalid:{path}"
    return (data if isinstance(data, dict) else {}), None


def _coverage_entries(manifest_payload: dict, bias_payload: dict, run_scope: dict) -> list[dict]:
    scope_coverage = manifest_payload.get("scope_coverage", []) if isinstance(manifest_payload, dict) else []
    if isinstance(scope_coverage, list) and scope_coverage:
        return [item for item in scope_coverage if isinstance(item, dict)]
    synthetic = bool((manifest_payload or {}).get("synthetic", bias_payload.get("synthetic", False)))
    return infer_scope_coverage_from_bias(bias_payload, run_scope=run_scope, synthetic=synthetic)


def inspect_calibration_profile(
    bias_path: Path,
    assessor_ids: list[str],
    run_scope: dict | str | None,
    *,
    context: dict | None = None,
) -> dict:
    normalized_scope = normalize_scope_input(run_scope)
    report = {
        "bias_path": str(bias_path),
        "bias_present": bias_path.exists(),
        "bias_error": "",
        "manifest_path": str(calibration_manifest_path(bias_path)),
        "manifest_present": False,
        "manifest_error": "",
        "manifest_integrity_ok": True,
        "generated_at": "",
        "generated_age_hours": None,
        "freshness_window_hours": None,
        "synthetic": False,
        "profile_type": "",
        "scope": normalized_scope,
        "scope_match": False,
        "scope_mismatch_fields": [],
        "coverage_scope": {},
        "coverage_entries": [],
        "routing_profile_hash": "",
        "current_routing_profile_hash": "",
        "routing_profile_match": True,
        "rubric_hash": "",
        "current_rubric_hash": "",
        "rubric_hash_match": True,
        "source_exemplar_set_hash": "",
        "current_source_exemplar_set_hash": "",
        "source_exemplar_match": True,
        "missing_assessors": [],
        "assessor_profiles": {},
        "drift_failures": [],
    }
    bias_payload, bias_error = _load_payload(bias_path)
    if bias_error:
        report["bias_error"] = bias_error
        return report
    manifest_path = _context_path(context, "manifest_path", str(calibration_manifest_path(bias_path)))
    report["manifest_path"] = str(manifest_path)
    manifest_payload, manifest_error = _load_payload(manifest_path)
    report["manifest_present"] = manifest_path.exists()
    if manifest_error:
        report["manifest_error"] = manifest_error
        if manifest_error.startswith("invalid:"):
            return report
    if manifest_payload:
        report["manifest_integrity_ok"] = manifest_integrity_ok(bias_path, manifest_payload)
    report["generated_at"] = str((manifest_payload or {}).get("generated_at") or bias_payload.get("generated_at") or "")
    report["generated_age_hours"] = hours_since(report["generated_at"])
    report["freshness_window_hours"] = float(
        (manifest_payload or {}).get("freshness_window_hours") or (context or {}).get("freshness_window_hours") or 0.0
    )
    report["synthetic"] = bool((manifest_payload or {}).get("synthetic", bias_payload.get("synthetic", bias_payload.get("method") == "bootstrap_neutral")))
    report["profile_type"] = str((manifest_payload or {}).get("profile_type") or bias_payload.get("method") or "")

    coverage_entries = _coverage_entries(manifest_payload, bias_payload, normalized_scope)
    report["coverage_entries"] = coverage_entries
    exact_match = next((entry for entry in coverage_entries if scope_matches(normalized_scope, entry)), None)
    if exact_match is None and normalized_scope.get("key"):
        same_key = [entry for entry in coverage_entries if str(entry.get("key", "")) == str(normalized_scope.get("key", ""))]
        if same_key:
            report["scope_mismatch_fields"] = scope_mismatch_fields(normalized_scope, same_key[0])
    report["scope_match"] = exact_match is not None
    report["coverage_scope"] = exact_match or {}

    routing_payload = (context or {}).get("routing_payload")
    if routing_payload is None:
        routing_payload = load_json(_context_path(context, "routing_path", "config/llm_routing.json"))
    report["routing_profile_hash"] = str((manifest_payload or {}).get("routing_profile_hash") or "")
    report["current_routing_profile_hash"] = str(routing_profile_hash_from_payload(routing_payload or {}) or "")
    if report["routing_profile_hash"] and report["current_routing_profile_hash"]:
        report["routing_profile_match"] = report["routing_profile_hash"] == report["current_routing_profile_hash"]

    rubric_path = _context_path(context, "rubric_path", "inputs/rubric.md")
    report["rubric_hash"] = str((manifest_payload or {}).get("rubric_hash") or "")
    report["current_rubric_hash"] = str(file_sha256(rubric_path) or "")
    if report["rubric_hash"] and report["current_rubric_hash"]:
        report["rubric_hash_match"] = report["rubric_hash"] == report["current_rubric_hash"]

    calibration_path = _context_path(context, "calibration_set_path", "config/calibration_set.json")
    exemplars_path = _context_path(context, "exemplars_path", "inputs/exemplars")
    report["source_exemplar_set_hash"] = str((manifest_payload or {}).get("source_exemplar_set_hash") or "")
    report["current_source_exemplar_set_hash"] = str(source_exemplar_set_hash(calibration_path, exemplars_path) or "")
    if report["source_exemplar_set_hash"] and report["current_source_exemplar_set_hash"]:
        report["source_exemplar_match"] = report["source_exemplar_set_hash"] == report["current_source_exemplar_set_hash"]

    assessors = bias_payload.get("assessors", {}) if isinstance(bias_payload, dict) else {}
    scope_key = str(normalized_scope.get("key", "") or "")
    for raw_id in assessor_ids:
        aid = raw_id if raw_id.startswith("assessor_") else f"assessor_{raw_id}"
        entry = assessors.get(aid)
        if not isinstance(entry, dict):
            report["missing_assessors"].append(aid)
            continue
        scoped = entry.get("scopes", {}).get(scope_key)
        if isinstance(scoped, dict):
            report["assessor_profiles"][aid] = scoped

    if report["manifest_present"] and not report["manifest_integrity_ok"]:
        report["drift_failures"].append("manifest_integrity")
    if report["generated_age_hours"] is not None and report["freshness_window_hours"]:
        if report["generated_age_hours"] > float(report["freshness_window_hours"]):
            report["drift_failures"].append("stale")
    if coverage_entries and not report["scope_match"]:
        report["drift_failures"].append("scope_mismatch")
    if report["routing_profile_hash"] and not report["routing_profile_match"]:
        report["drift_failures"].append("routing_profile_mismatch")
    if report["rubric_hash"] and not report["rubric_hash_match"]:
        report["drift_failures"].append("rubric_hash_mismatch")
    if report["source_exemplar_set_hash"] and not report["source_exemplar_match"]:
        report["drift_failures"].append("exemplar_set_mismatch")
    if report["synthetic"]:
        report["drift_failures"].append("synthetic")
    return report


def calibration_gate_error(routing: dict, assessor_ids: list[str], run_scope: dict | str | None, context: dict | None = None) -> str | None:
    cfg = routing.get("calibration_gate", {}) if isinstance(routing, dict) else {}
    if not cfg.get("enabled", False):
        return None
    normalized_scope = normalize_scope_input(run_scope)
    bias_path = Path(str(cfg.get("bias_path", (context or {}).get("bias_path", "outputs/calibration_bias.json"))))
    report = inspect_calibration_profile(
        bias_path=bias_path,
        assessor_ids=assessor_ids,
        run_scope=normalized_scope,
        context={
            **(context or {}),
            "routing_payload": routing,
            "routing_path": (context or {}).get("routing_path", "config/llm_routing.json"),
            "rubric_path": (context or {}).get("rubric_path", "inputs/rubric.md"),
            "calibration_set_path": (context or {}).get("calibration_set_path", "config/calibration_set.json"),
            "exemplars_path": (context or {}).get("exemplars_path", "inputs/exemplars"),
            "freshness_window_hours": float(cfg.get("max_age_hours", 0.0) or 0.0),
        },
    )
    if report["bias_error"].startswith("missing:"):
        return f"Calibration gate failed: missing bias file at {bias_path}. Run scripts/calibrate_assessors.py first."
    if report["bias_error"].startswith("invalid:"):
        return f"Calibration gate failed: invalid JSON in {bias_path}."
    max_age_hours = float(cfg.get("max_age_hours", 0.0) or 0.0)
    if max_age_hours > 0:
        generated = parse_iso8601(report["generated_at"])
        if generated is None:
            return "Calibration gate failed: calibration_bias.json missing valid generated_at timestamp."
        age_hours = (datetime.now(timezone.utc) - generated).total_seconds() / 3600.0
        if age_hours > max_age_hours:
            return (
                f"Calibration gate failed: calibration is stale ({age_hours:.1f}h old > {max_age_hours:.1f}h). "
                "Re-run scripts/calibrate_assessors.py."
            )
    if not normalized_scope.get("key"):
        return "Calibration gate failed: missing grade/genre scope for this run (requires class metadata grade_level + genre)."
    require_manifest = bool(cfg.get("require_manifest", False))
    if require_manifest and not report["manifest_present"]:
        manifest_path = calibration_manifest_path(bias_path)
        return f"Calibration gate failed: missing calibration manifest at {manifest_path}."
    if require_manifest and report["manifest_error"].startswith("invalid:"):
        return f"Calibration gate failed: invalid JSON in {report['manifest_path']}."
    if require_manifest and not report["manifest_integrity_ok"]:
        return "Calibration gate failed: calibration manifest artifact hash does not match calibration_bias.json."

    if report["manifest_present"] and bool(cfg.get("enforce_scope_match", True)) and report["coverage_entries"] and not report["scope_match"]:
        if report["scope_mismatch_fields"]:
            mismatches = ", ".join(report["scope_mismatch_fields"])
            return (
                f"Calibration gate failed: scope mismatch for '{normalized_scope.get('key')}' "
                f"(mismatched: {mismatches})."
            )
        return f"Calibration gate failed: missing scoped profile for '{normalized_scope.get('key')}' in calibration manifest."
    if report["manifest_present"] and bool(cfg.get("enforce_routing_match", True)) and not report["routing_profile_match"]:
        return "Calibration gate failed: routing profile changed since calibration. Re-run scripts/calibrate_assessors.py."
    if report["manifest_present"] and bool(cfg.get("enforce_rubric_match", True)) and not report["rubric_hash_match"]:
        return "Calibration gate failed: rubric changed since calibration. Re-run scripts/calibrate_assessors.py."
    if (
        report["manifest_present"]
        and not report["synthetic"]
        and bool(cfg.get("enforce_exemplar_hash_match", True))
        and not report["source_exemplar_match"]
    ):
        return "Calibration gate failed: exemplar bank changed since calibration. Re-run scripts/calibrate_assessors.py."
    if bool(cfg.get("reject_synthetic", False)) and report["synthetic"]:
        return "Calibration gate failed: synthetic bootstrap calibration is not allowed for this run."

    assessors = load_json(bias_path).get("assessors", {})
    min_samples = int(cfg.get("min_scope_samples", 1) or 1)
    min_weight = float(cfg.get("min_scope_weight", 0.0) or 0.0)
    min_level_hit = cfg.get("min_scope_level_hit_rate")
    max_mae = cfg.get("max_scope_mae")
    min_pairwise = cfg.get("min_scope_pairwise_order_agreement")
    min_repeat_consistency = cfg.get("min_scope_repeat_level_consistency")
    max_abs_bias = cfg.get("max_scope_abs_bias")
    max_boundary_mae = cfg.get("max_scope_boundary_mae")
    max_rank_stability_sd = cfg.get("max_scope_rank_stability_sd")
    max_boundary_pairwise = cfg.get("max_scope_boundary_pairwise_disagreement")
    scope_key = str(normalized_scope.get("key", "") or "")
    for raw_id in assessor_ids:
        aid = raw_id if raw_id.startswith("assessor_") else f"assessor_{raw_id}"
        entry = assessors.get(aid)
        if not isinstance(entry, dict):
            return f"Calibration gate failed: missing profile for {aid}."
        scope_profile = entry.get("scopes", {}).get(scope_key)
        if not isinstance(scope_profile, dict):
            return f"Calibration gate failed: missing scoped profile for {aid} at '{scope_key}'."
        observations = int(scope_profile.get("observations", 0) or 0)
        samples = int(scope_profile.get("samples", 0) or 0)
        gate_samples = observations if observations > 0 else samples
        if gate_samples < min_samples:
            return (
                f"Calibration gate failed: {aid} scope '{scope_key}' has "
                f"{gate_samples} observations (< {min_samples})."
            )
        weight = float(scope_profile.get("weight", 0.0) or 0.0)
        if weight < min_weight:
            return f"Calibration gate failed: {aid} scope '{scope_key}' weight {weight:.2f} (< {min_weight:.2f})."
        if min_level_hit is not None:
            value = float(scope_profile.get("level_hit_rate", 0.0) or 0.0)
            if value < float(min_level_hit):
                return (
                    f"Calibration gate failed: {aid} scope '{scope_key}' level_hit_rate "
                    f"{value:.2f} (< {float(min_level_hit):.2f})."
                )
        if max_mae is not None:
            value = float(scope_profile.get("mae", 100.0) or 100.0)
            if value > float(max_mae):
                return (
                    f"Calibration gate failed: {aid} scope '{scope_key}' mae "
                    f"{value:.2f} (> {float(max_mae):.2f})."
                )
        if min_pairwise is not None:
            value = float(scope_profile.get("pairwise_order_agreement", 0.0) or 0.0)
            if value < float(min_pairwise):
                return (
                    f"Calibration gate failed: {aid} scope '{scope_key}' pairwise_order_agreement "
                    f"{value:.2f} (< {float(min_pairwise):.2f})."
                )
        if min_repeat_consistency is not None:
            value = float(scope_profile.get("repeat_level_consistency", 0.0) or 0.0)
            if value < float(min_repeat_consistency):
                return (
                    f"Calibration gate failed: {aid} scope '{scope_key}' repeat_level_consistency "
                    f"{value:.2f} (< {float(min_repeat_consistency):.2f})."
                )
        if max_abs_bias is not None:
            value = abs(float(scope_profile.get("bias", 0.0) or 0.0))
            if value > float(max_abs_bias):
                return (
                    f"Calibration gate failed: {aid} scope '{scope_key}' |bias| "
                    f"{value:.2f} (> {float(max_abs_bias):.2f})."
                )
        if max_boundary_mae is not None:
            value = float(scope_profile.get("boundary_mae", 0.0) or 0.0)
            if value > float(max_boundary_mae):
                return (
                    f"Calibration gate failed: {aid} scope '{scope_key}' boundary_mae "
                    f"{value:.2f} (> {float(max_boundary_mae):.2f})."
                )
        if max_rank_stability_sd is not None:
            value = float(scope_profile.get("rank_stability_sd", 0.0) or 0.0)
            if value > float(max_rank_stability_sd):
                return (
                    f"Calibration gate failed: {aid} scope '{scope_key}' rank_stability_sd "
                    f"{value:.2f} (> {float(max_rank_stability_sd):.2f})."
                )
        if max_boundary_pairwise is not None:
            value = float(scope_profile.get("boundary_pairwise_disagreement", 0.0) or 0.0)
            if value > float(max_boundary_pairwise):
                return (
                    f"Calibration gate failed: {aid} scope '{scope_key}' boundary_pairwise_disagreement "
                    f"{value:.2f} (> {float(max_boundary_pairwise):.2f})."
                )
    return None


__all__ = ["inspect_calibration_profile", "parse_iso8601", "_parse_iso8601", "calibration_gate_error"]
