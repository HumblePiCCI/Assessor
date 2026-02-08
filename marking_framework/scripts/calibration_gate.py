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
    return None
