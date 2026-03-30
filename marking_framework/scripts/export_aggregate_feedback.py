#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.aggregate_review_learning import (
        AGGREGATE_SCHEMA_VERSION,
        canonical_hash,
        file_sha256,
        git_sha,
        list_eligible_records,
        list_tombstones,
        now_iso,
        outbox_root,
        prune_expired_records,
        write_json,
        write_jsonl,
    )
except ImportError:  # pragma: no cover
    from aggregate_review_learning import (  # pragma: no cover
        AGGREGATE_SCHEMA_VERSION,
        canonical_hash,
        file_sha256,
        git_sha,
        list_eligible_records,
        list_tombstones,
        now_iso,
        outbox_root,
        prune_expired_records,
        write_json,
        write_jsonl,
    )


def build_package_manifest(base_dir: Path, package_id: str, records: list[dict], tombstones: list[dict], output_dir: Path) -> dict:
    record_ids = [str(row.get("aggregate_record_id", "") or "") for row in records if row.get("aggregate_record_id")]
    tombstone_ids = [str(row.get("aggregate_record_id", "") or "") for row in tombstones if row.get("aggregate_record_id")]
    manifest = {
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "package_id": package_id,
        "generated_at": now_iso(),
        "git_sha": git_sha(base_dir.parent),
        "record_count": len(records),
        "tombstone_count": len(tombstones),
        "aggregate_record_ids": record_ids,
        "tombstone_record_ids": tombstone_ids,
        "scope_hashes": sorted({str(row.get("scope_hash", "") or "") for row in records if row.get("scope_hash")}),
        "retention_summary": {
            "min_expires_at": min((str(row.get("retention", {}).get("expires_at", "") or "") for row in records), default=""),
            "max_expires_at": max((str(row.get("retention", {}).get("expires_at", "") or "") for row in records), default=""),
        },
        "files": {},
    }
    for name in ("eligible_records.jsonl", "tombstones.jsonl"):
        path = output_dir / name
        manifest["files"][name] = {
            "sha256": file_sha256(path),
            "size_bytes": path.stat().st_size if path.exists() else 0,
        }
    manifest["manifest_hash"] = canonical_hash(
        {
            "record_ids": record_ids,
            "tombstone_ids": tombstone_ids,
            "files": manifest["files"],
            "generated_at": manifest["generated_at"],
        }
    )
    return manifest


def exportable_record(record: dict) -> dict:
    payload = dict(record)
    payload.pop("scope_id", None)
    payload["collection_policy"] = dict(payload.get("collection_policy", {}) or {})
    payload["provenance"] = dict(payload.get("provenance", {}) or {})
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Package governed anonymized finalized-review feedback for product learning.")
    parser.add_argument("--server-dir", default="server", help="Server directory containing data/review_aggregate")
    parser.add_argument("--scope-id", default="", help="Optional review scope id")
    parser.add_argument("--output-root", default="", help="Override outbox root directory")
    args = parser.parse_args()

    base_dir = Path(args.server_dir)
    prune_expired_records(base_dir, scope_id=args.scope_id or None, now=datetime.now(timezone.utc))
    records = list_eligible_records(base_dir, scope_id=args.scope_id or None)
    tombstones = list_tombstones(base_dir)
    if not records and not tombstones:
        print("No eligible aggregate feedback records to export.")
        return 1

    package_seed = canonical_hash(
        {
            "record_ids": [row.get("aggregate_record_id", "") for row in records],
            "tombstone_ids": [row.get("aggregate_record_id", "") for row in tombstones],
            "generated_at_minute": now_iso()[:16],
        }
    )
    package_id = f"aggregate_feedback_{package_seed[:12]}"
    root = Path(args.output_root) if args.output_root else outbox_root(base_dir)
    output_dir = root / package_id
    output_dir.mkdir(parents=True, exist_ok=True)
    eligible_path = output_dir / "eligible_records.jsonl"
    tombstone_path = output_dir / "tombstones.jsonl"
    write_jsonl(eligible_path, [exportable_record(row) for row in records])
    write_jsonl(tombstone_path, tombstones)
    manifest = build_package_manifest(base_dir, package_id, records, tombstones, output_dir)
    write_json(output_dir / "package_manifest.json", manifest)
    print(f"Wrote governed aggregate feedback package: {output_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
