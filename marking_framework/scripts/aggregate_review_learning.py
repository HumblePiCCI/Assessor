#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from scripts.calibration_contract import normalize_scope_input, parse_iso8601
except ImportError:  # pragma: no cover - Support running as a script
    from calibration_contract import normalize_scope_input, parse_iso8601  # pragma: no cover


AGGREGATE_SCHEMA_VERSION = "aggregate_review_learning_v1"
DEFAULT_RETENTION_DAYS = 365
AGGREGATE_COLLECTION_MODES = {"local_only", "opt_in", "policy_compliant"}
CONTROLLED_REASON_CODES = {
    "analysis_depth",
    "boundary_case",
    "completeness",
    "concision",
    "eloquence",
    "evidence_fit",
    "evidence_misaligned",
    "evidence_strong",
    "evidence_thin",
    "evidence_unclear",
    "high_disagreement",
    "insight",
    "level_override",
    "low_confidence_move",
    "organization",
    "pairwise_reversal",
    "rank_reorder",
    "voice",
}
COMMENT_REASON_KEYWORDS = {
    "analysis_depth": ("analysis", "interpretation", "depth", "deepen", "explain why"),
    "eloquence": ("eloquent", "elegant", "well-phrased", "phrase", "style", "graceful"),
    "insight": ("insight", "insightful", "nuance", "nuanced", "original", "perceptive"),
    "completeness": ("complete", "completeness", "thorough", "fully", "more fully", "developed"),
    "concision": ("concise", "concision", "succinct", "tighten", "trim", "efficient"),
    "organization": ("organize", "organization", "structure", "coherence", "cohesion", "flow"),
    "voice": ("voice", "tone", "authentic", "personality", "presence"),
    "evidence_fit": ("evidence", "support", "quotation", "quote", "example", "because", "proof"),
}
FORBIDDEN_RAW_KEYS = {
    "display_name",
    "source_file",
    "text",
    "teacher_comment",
    "teacher_notes",
    "review_notes",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def canonical_hash(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def file_sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_sha(root: Path | None = None) -> str:
    cwd = root or Path(__file__).resolve().parents[1]
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=cwd, stderr=subprocess.DEVNULL, text=True)
            .strip()
        )
    except Exception:  # pragma: no cover - best effort only
        return ""


def aggregate_root(base_dir: Path) -> Path:
    path = base_dir / "data" / "review_aggregate"
    path.mkdir(parents=True, exist_ok=True)
    return path


def eligible_root(base_dir: Path) -> Path:
    path = aggregate_root(base_dir) / "eligible_reviews"
    path.mkdir(parents=True, exist_ok=True)
    return path


def eligible_scope_dir(base_dir: Path, scope_id: str) -> Path:
    path = eligible_root(base_dir) / str(scope_id or "workspace")
    path.mkdir(parents=True, exist_ok=True)
    return path


def tombstones_root(base_dir: Path) -> Path:
    path = aggregate_root(base_dir) / "tombstones"
    path.mkdir(parents=True, exist_ok=True)
    return path


def outbox_root(base_dir: Path) -> Path:
    path = aggregate_root(base_dir) / "outbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ingested_root(base_dir: Path) -> Path:
    path = aggregate_root(base_dir) / "ingested"
    path.mkdir(parents=True, exist_ok=True)
    return path


def promotions_root(base_dir: Path) -> Path:
    path = aggregate_root(base_dir) / "promotions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def promotion_proposals_root(base_dir: Path) -> Path:
    path = promotions_root(base_dir) / "proposals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def promotion_audit_log_path(base_dir: Path) -> Path:
    path = promotions_root(base_dir) / "promotion_audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def salt_path(base_dir: Path) -> Path:
    path = aggregate_root(base_dir) / "salt.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def anonymization_salt(base_dir: Path) -> str:
    path = salt_path(base_dir)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    salt = hashlib.sha256(f"{now_iso()}:{Path(base_dir).resolve()}".encode("utf-8")).hexdigest()
    path.write_text(salt, encoding="utf-8")
    return salt


def hash_identifier(base_dir: Path, namespace: str, value: str, *, scope_id: str = "") -> str:
    salt = anonymization_salt(base_dir)
    return hashlib.sha256(f"{salt}:{namespace}:{scope_id}:{value}".encode("utf-8")).hexdigest()[:16]


def default_aggregate_learning_policy() -> dict:
    return {
        "mode": "local_only",
        "policy_reference": "",
        "retention_days": DEFAULT_RETENTION_DAYS,
        "finalized_only": True,
        "anonymized_only": True,
        "eligible": False,
        "eligibility_reason": "local_only",
        "updated_at": "",
    }


def _coerce_policy_fields(raw: dict | None) -> dict:
    payload = dict(raw or {})
    mode = str(payload.get("mode", "local_only") or "local_only").strip().lower()
    if mode not in AGGREGATE_COLLECTION_MODES:
        mode = "local_only"
    try:
        retention_days = int(payload.get("retention_days", DEFAULT_RETENTION_DAYS) or DEFAULT_RETENTION_DAYS)
    except (TypeError, ValueError):
        retention_days = DEFAULT_RETENTION_DAYS
    retention_days = max(1, retention_days)
    policy_reference = str(payload.get("policy_reference", "") or "").strip()
    return {
        "mode": mode,
        "policy_reference": policy_reference,
        "retention_days": retention_days,
        "finalized_only": True,
        "anonymized_only": True,
        "updated_at": str(payload.get("updated_at", "") or ""),
    }


def _eligibility_from_normalized(policy: dict) -> tuple[bool, str]:
    mode = policy.get("mode")
    if mode == "opt_in":
        return True, "opt_in_enabled"
    if mode == "policy_compliant":
        if policy.get("policy_reference"):
            return True, "policy_reference_present"
        return False, "missing_policy_reference"
    return False, "local_only"


def normalize_aggregate_learning_policy(raw: dict | None) -> dict:
    normalized = _coerce_policy_fields(raw)
    eligible, reason = _eligibility_from_normalized(normalized)
    normalized["eligible"] = eligible
    normalized["eligibility_reason"] = reason
    return normalized


def collection_eligibility(policy: dict | None) -> tuple[bool, str]:
    return _eligibility_from_normalized(_coerce_policy_fields(policy))


def expires_at(saved_at: str, retention_days: int) -> str:
    dt = parse_iso8601(saved_at)
    if dt is None:
        return ""
    return (dt + timedelta(days=max(1, int(retention_days)))).isoformat()


def is_expired(expires_at_value: str, *, now: datetime | None = None) -> bool:
    expires = parse_iso8601(expires_at_value)
    if expires is None:
        return False
    current = now or datetime.now(timezone.utc)
    return expires <= current


def redact_text(text: str, replacements: list[str], *, limit: int = 500) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    for candidate in sorted({item for item in replacements if item}, key=len, reverse=True):
        value = re.sub(re.escape(candidate), "[student]", value, flags=re.IGNORECASE)
    value = re.sub(r"https?://\S+", "[url]", value)
    value = re.sub(r"\b[\w.+-]+@[\w.-]+\.\w+\b", "[email]", value)
    value = re.sub(r"\b\d{4,}\b", "[number]", value)
    value = re.sub(r'"[^"]+"', "[quote]", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def normalize_reason_tags(raw_tags) -> list[str]:
    tags = []
    if isinstance(raw_tags, str):
        raw_values = [raw_tags]
    elif isinstance(raw_tags, list):
        raw_values = raw_tags
    else:
        raw_values = []
    for item in raw_values:
        token = re.sub(r"[^a-z0-9]+", "_", str(item or "").strip().lower()).strip("_")
        if token in CONTROLLED_REASON_CODES and token not in tags:
            tags.append(token)
    return tags


def infer_reason_codes_from_text(text: str) -> list[str]:
    redacted = str(text or "").strip().lower()
    if not redacted:
        return []
    codes = []
    for code, keywords in COMMENT_REASON_KEYWORDS.items():
        if any(keyword in redacted for keyword in keywords):
            codes.append(code)
    return sorted(set(codes))


def merge_reason_codes(*groups) -> list[str]:
    merged = []
    for group in groups:
        for item in group or []:
            if item in CONTROLLED_REASON_CODES and item not in merged:
                merged.append(item)
    return merged


def reason_count_summary(records: list[dict]) -> dict[str, int]:
    counts = {}
    for record in records:
        for code in record.get("normalized_reason_codes", []) or []:
            counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def anonymization_integrity_errors(payload: dict) -> list[str]:
    errors = []
    if not isinstance(payload, dict):
        return ["payload_not_dict"]
    for key in FORBIDDEN_RAW_KEYS:
        if key in payload:
            errors.append(f"forbidden_key:{key}")
    blob = json.dumps(payload, sort_keys=True)
    for marker in ("display_name", "source_file"):
        if marker in blob:
            errors.append(f"forbidden_marker:{marker}")
    return errors


def eligible_record_path(base_dir: Path, scope_id: str, aggregate_record_id: str) -> Path:
    return eligible_scope_dir(base_dir, scope_id) / f"{aggregate_record_id}.json"


def tombstone_path(base_dir: Path, aggregate_record_id: str) -> Path:
    return tombstones_root(base_dir) / f"{aggregate_record_id}.json"


def list_eligible_records(base_dir: Path, scope_id: str | None = None) -> list[dict]:
    paths = []
    if scope_id:
        scope_path = eligible_root(base_dir) / str(scope_id or "workspace")
        if scope_path.exists():
            paths.extend(sorted(scope_path.glob("*.json")))
    else:
        paths.extend(sorted(eligible_root(base_dir).glob("*/*.json")))
    rows = []
    for path in paths:
        payload = load_json(path)
        if isinstance(payload, dict) and payload:
            rows.append(payload)
    return rows


def list_tombstones(base_dir: Path) -> list[dict]:
    rows = []
    for path in sorted(tombstones_root(base_dir).glob("*.json")):
        payload = load_json(path)
        if isinstance(payload, dict) and payload:
            rows.append(payload)
    return rows


def prune_expired_records(base_dir: Path, *, scope_id: str | None = None, now: datetime | None = None) -> dict:
    current = now or datetime.now(timezone.utc)
    removed = []
    for record in list_eligible_records(base_dir, scope_id=scope_id):
        retention = record.get("retention", {}) if isinstance(record.get("retention"), dict) else {}
        if not is_expired(str(retention.get("expires_at", "") or ""), now=current):
            continue
        record_id = str(record.get("aggregate_record_id", "") or "")
        if not record_id:
            continue
        path = eligible_record_path(base_dir, str(record.get("scope_id", "") or "workspace"), record_id)
        if path.exists():
            path.unlink()
        tombstone = {
            "aggregate_record_id": record_id,
            "deleted_at": now_iso(),
            "reason": "retention_expired",
            "scope_hash": str(record.get("scope_hash", "") or ""),
            "project_hash": str(record.get("project_hash", "") or ""),
        }
        write_json(tombstone_path(base_dir, record_id), tombstone)
        removed.append(record_id)
    return {"removed_record_ids": removed, "removed_count": len(removed)}


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True) + "\n")
