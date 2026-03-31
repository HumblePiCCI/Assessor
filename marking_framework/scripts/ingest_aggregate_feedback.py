#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

try:
    from scripts.aggregate_review_learning import (
        AGGREGATE_SCHEMA_VERSION,
        anonymization_integrity_errors,
        file_sha256,
        ingested_root,
        load_json,
        now_iso,
        read_jsonl,
        write_json,
        write_jsonl,
    )
except ImportError:  # pragma: no cover
    from aggregate_review_learning import (  # pragma: no cover
        AGGREGATE_SCHEMA_VERSION,
        anonymization_integrity_errors,
        file_sha256,
        ingested_root,
        load_json,
        now_iso,
        read_jsonl,
        write_json,
        write_jsonl,
    )


def validate_package(package_dir: Path) -> tuple[dict, list[dict], list[dict], list[str]]:
    manifest = load_json(package_dir / "package_manifest.json")
    records = read_jsonl(package_dir / "eligible_records.jsonl")
    tombstones = read_jsonl(package_dir / "tombstones.jsonl")
    errors = []
    if not manifest:
        errors.append("missing_manifest")
        return manifest, records, tombstones, errors
    if str(manifest.get("schema_version", "") or "") != AGGREGATE_SCHEMA_VERSION:
        errors.append("schema_version_mismatch")
    for name in ("eligible_records.jsonl", "tombstones.jsonl"):
        expected = str(((manifest.get("files", {}) or {}).get(name, {}) or {}).get("sha256", "") or "")
        actual = file_sha256(package_dir / name)
        if expected and actual and expected != actual:
            errors.append(f"sha256_mismatch:{name}")
    for record in records:
        if str(record.get("review_state", "") or "") != "final":
            errors.append("non_final_record")
        policy = record.get("collection_policy", {}) if isinstance(record.get("collection_policy"), dict) else {}
        if not bool(policy.get("eligible", False)):
            errors.append("ineligible_record")
        payload_errors = anonymization_integrity_errors(record)
        if payload_errors:
            errors.extend(payload_errors)
    for tombstone in tombstones:
        if not tombstone.get("aggregate_record_id"):
            errors.append("invalid_tombstone")
    return manifest, records, tombstones, sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and ingest governed aggregate feedback packages.")
    parser.add_argument("--server-dir", default="server", help="Server directory containing data/review_aggregate")
    parser.add_argument("--package-dir", required=True, help="Exported package directory")
    args = parser.parse_args()

    base_dir = Path(args.server_dir)
    package_dir = Path(args.package_dir)
    manifest, records, tombstones, errors = validate_package(package_dir)
    if errors:
        print(f"Ingestion failed: {', '.join(errors)}")
        return 1

    package_id = str(manifest.get("package_id", "") or package_dir.name)
    target = ingested_root(base_dir) / package_id
    target.mkdir(parents=True, exist_ok=True)
    write_json(target / "package_manifest.json", manifest)
    write_jsonl(target / "eligible_records.jsonl", records)
    write_jsonl(target / "tombstones.jsonl", tombstones)
    receipt = {
        "package_id": package_id,
        "ingested_at": now_iso(),
        "record_count": len(records),
        "tombstone_count": len(tombstones),
        "schema_version": AGGREGATE_SCHEMA_VERSION,
    }
    write_json(target / "ingest_receipt.json", receipt)
    print(f"Ingested aggregate feedback package: {target}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
