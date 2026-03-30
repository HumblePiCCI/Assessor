#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

try:
    from scripts.aggregate_review_learning import (
        AGGREGATE_SCHEMA_VERSION,
        append_jsonl,
        canonical_hash,
        file_sha256,
        ingested_root,
        load_json,
        now_iso,
        promotion_audit_log_path,
        promotion_proposals_root,
        read_jsonl,
        write_json,
        write_jsonl,
    )
except ImportError:  # pragma: no cover
    from aggregate_review_learning import (  # pragma: no cover
        AGGREGATE_SCHEMA_VERSION,
        append_jsonl,
        canonical_hash,
        file_sha256,
        ingested_root,
        load_json,
        now_iso,
        promotion_audit_log_path,
        promotion_proposals_root,
        read_jsonl,
        write_json,
        write_jsonl,
    )


def active_ingested_records(base_dir: Path) -> tuple[list[dict], list[str]]:
    records_by_id = {}
    deleted_ids = set()
    package_ids = []
    for package_dir in sorted(ingested_root(base_dir).glob("*")):
        if not package_dir.is_dir():
            continue
        package_ids.append(package_dir.name)
        for record in read_jsonl(package_dir / "eligible_records.jsonl"):
            record_id = str(record.get("aggregate_record_id", "") or "")
            if record_id:
                records_by_id[record_id] = record
        for tombstone in read_jsonl(package_dir / "tombstones.jsonl"):
            record_id = str(tombstone.get("aggregate_record_id", "") or "")
            if record_id:
                deleted_ids.add(record_id)
    rows = [row for record_id, row in sorted(records_by_id.items()) if record_id not in deleted_ids]
    return rows, package_ids


def build_candidate_rows(records: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    benchmark = []
    boundary = []
    calibration = []
    for record in records:
        source = {
            "aggregate_record_id": str(record.get("aggregate_record_id", "") or ""),
            "review_hash": str(record.get("review_hash", "") or ""),
            "project_hash": str(record.get("project_hash", "") or ""),
            "scope_hash": str(record.get("scope_hash", "") or ""),
            "pipeline_manifest_hash": str(((record.get("provenance", {}) or {}).get("pipeline_manifest_hash", "") or "")),
        }
        for row in (record.get("replay_candidates", {}) or {}).get("benchmark_gold", []) or []:
            benchmark.append({**row, **source})
        for row in (record.get("replay_candidates", {}) or {}).get("boundary_challenges", []) or []:
            boundary.append({**row, **source})
        for row in (record.get("replay_candidates", {}) or {}).get("calibration_exemplars", []) or []:
            calibration.append({**row, **source})
    return benchmark, boundary, calibration


def propose(base_dir: Path) -> int:
    records, package_ids = active_ingested_records(base_dir)
    if not records:
        print("No ingested aggregate records available for proposal.")
        return 1
    benchmark_rows, boundary_rows, calibration_rows = build_candidate_rows(records)
    proposal_id = f"aggregate_promotion_{canonical_hash({'records': [row.get('aggregate_record_id') for row in records]})[:12]}"
    proposal_dir = promotion_proposals_root(base_dir) / proposal_id
    proposal_dir.mkdir(parents=True, exist_ok=True)
    benchmark_path = proposal_dir / "benchmark_gold_candidates.jsonl"
    boundary_path = proposal_dir / "boundary_challenge_candidates.jsonl"
    calibration_path = proposal_dir / "calibration_exemplar_candidates.jsonl"
    write_jsonl(benchmark_path, benchmark_rows)
    write_jsonl(boundary_path, boundary_rows)
    write_jsonl(calibration_path, calibration_rows)
    manifest = {
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "proposal_id": proposal_id,
        "generated_at": now_iso(),
        "source_package_ids": package_ids,
        "source_record_ids": [str(row.get("aggregate_record_id", "") or "") for row in records],
        "counts": {
            "benchmark_gold_candidates": len(benchmark_rows),
            "boundary_challenge_candidates": len(boundary_rows),
            "calibration_exemplar_candidates": len(calibration_rows),
        },
        "files": {
            "benchmark_gold_candidates.jsonl": file_sha256(benchmark_path),
            "boundary_challenge_candidates.jsonl": file_sha256(boundary_path),
            "calibration_exemplar_candidates.jsonl": file_sha256(calibration_path),
        },
        "adjudication_required": True,
    }
    write_json(proposal_dir / "proposal_manifest.json", manifest)
    print(f"Wrote aggregate promotion proposal: {proposal_dir}")
    return 0


def _approved_asset_flags(adjudication: dict) -> dict:
    return {
        "benchmark_gold": bool(adjudication.get("approve_benchmark_gold", False)),
        "boundary_challenges": bool(adjudication.get("approve_boundary_challenges", False)),
        "calibration_exemplars": bool(adjudication.get("approve_calibration_exemplars", False)),
    }


def promote(base_dir: Path, proposal_dir: Path, adjudication_path: Path) -> int:
    manifest = load_json(proposal_dir / "proposal_manifest.json")
    adjudication = load_json(adjudication_path)
    if not manifest:
        print("Promotion failed: missing proposal manifest.")
        return 1
    decision = str(adjudication.get("decision", "") or "").strip().lower()
    approved_by = str(adjudication.get("approved_by", "") or "").strip()
    approved_at = str(adjudication.get("approved_at", "") or "").strip()
    asset_flags = _approved_asset_flags(adjudication)
    if decision not in {"approve", "approved"} or not approved_by or not approved_at or not any(asset_flags.values()):
        print("Promotion failed: adjudication file must include approved_by, approved_at, decision=approve, and at least one approved asset.")
        return 1

    repo_root = base_dir.parent
    proposal_id = str(manifest.get("proposal_id", "") or proposal_dir.name)
    promoted_files = {}
    if asset_flags["benchmark_gold"]:
        dst = repo_root / "bench" / "promoted" / "benchmark_gold" / proposal_id
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(proposal_dir / "benchmark_gold_candidates.jsonl", dst / "gold.jsonl")
        promoted_files["benchmark_gold"] = str(dst / "gold.jsonl")
    if asset_flags["boundary_challenges"]:
        dst = repo_root / "bench" / "promoted" / "boundary_challenges" / proposal_id
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(proposal_dir / "boundary_challenge_candidates.jsonl", dst / "boundary_challenges.jsonl")
        promoted_files["boundary_challenges"] = str(dst / "boundary_challenges.jsonl")
    if asset_flags["calibration_exemplars"]:
        dst = repo_root / "inputs" / "exemplars" / "promoted" / proposal_id
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(proposal_dir / "calibration_exemplar_candidates.jsonl", dst / "calibration_exemplars.jsonl")
        promoted_files["calibration_exemplars"] = str(dst / "calibration_exemplars.jsonl")

    manifest_copy_dir = base_dir / "data" / "review_aggregate" / "promotions" / "completed" / proposal_id
    manifest_copy_dir.mkdir(parents=True, exist_ok=True)
    write_json(manifest_copy_dir / "proposal_manifest.json", manifest)
    write_json(manifest_copy_dir / "adjudication.json", adjudication)
    audit_row = {
        "proposal_id": proposal_id,
        "promoted_at": now_iso(),
        "approved_by": approved_by,
        "approved_at": approved_at,
        "decision": decision,
        "promoted_files": promoted_files,
        "proposal_manifest_hash": canonical_hash(manifest),
    }
    append_jsonl(promotion_audit_log_path(base_dir), audit_row)
    print(f"Promoted aggregate learning assets for {proposal_id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Propose and promote governed aggregate review-learning assets.")
    parser.add_argument("--server-dir", default="server", help="Server directory containing data/review_aggregate")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("propose", help="Build candidate benchmark/boundary/calibration promotion bundles")

    promote_parser = subparsers.add_parser("promote", help="Promote a candidate bundle after human adjudication")
    promote_parser.add_argument("--proposal-dir", required=True, help="Proposal directory created by the propose command")
    promote_parser.add_argument("--adjudication", required=True, help="Adjudication JSON with human approval metadata")

    args = parser.parse_args()
    base_dir = Path(args.server_dir)
    if args.command == "propose":
        return propose(base_dir)
    return promote(base_dir, Path(args.proposal_dir), Path(args.adjudication))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
