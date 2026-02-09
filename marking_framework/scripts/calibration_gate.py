#!/usr/bin/env python3
import json
from datetime import datetime, timezone
from pathlib import Path


def _parse_iso8601(value: str) -> datetime | None:
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


def calibration_gate_error(routing: dict, assessor_ids: list[str], scope_key: str) -> str | None:
    cfg = routing.get("calibration_gate", {})
    if not cfg.get("enabled", False):
        return None
    bias_path = Path(cfg.get("bias_path", "outputs/calibration_bias.json"))
    if not bias_path.exists():
        return f"Calibration gate failed: missing bias file at {bias_path}. Run scripts/calibrate_assessors.py first."
    try:
        payload = json.loads(bias_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return f"Calibration gate failed: invalid JSON in {bias_path}."
    max_age_hours = float(cfg.get("max_age_hours", 0.0) or 0.0)
    generated = _parse_iso8601(payload.get("generated_at", ""))
    if max_age_hours > 0:
        if generated is None:
            return "Calibration gate failed: calibration_bias.json missing valid generated_at timestamp."
        age_hours = (datetime.now(timezone.utc) - generated).total_seconds() / 3600.0
        if age_hours > max_age_hours:
            return (
                f"Calibration gate failed: calibration is stale ({age_hours:.1f}h old > {max_age_hours:.1f}h). "
                "Re-run scripts/calibrate_assessors.py."
            )
    if not scope_key:
        return "Calibration gate failed: missing grade/genre scope for this run (requires class metadata grade_level + genre)."
    assessors = payload.get("assessors", {}) if isinstance(payload, dict) else {}
    min_samples = int(cfg.get("min_scope_samples", 1) or 1)
    min_weight = float(cfg.get("min_scope_weight", 0.0) or 0.0)
    min_level_hit = cfg.get("min_scope_level_hit_rate")
    max_mae = cfg.get("max_scope_mae")
    min_pairwise = cfg.get("min_scope_pairwise_order_agreement")
    min_repeat_consistency = cfg.get("min_scope_repeat_level_consistency")
    max_abs_bias = cfg.get("max_scope_abs_bias")
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
    return None
