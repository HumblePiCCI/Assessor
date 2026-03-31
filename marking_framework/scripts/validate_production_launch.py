#!/usr/bin/env python3
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from scripts.gate_profiles import profile_rank
    from server.runtime_context import launch_contract
except ImportError:  # pragma: no cover
    from gate_profiles import profile_rank  # pragma: no cover
    from server.runtime_context import launch_contract  # pragma: no cover


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def parse_dt(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def gate_state(path: Path) -> dict:
    payload = load_json(path)
    order = payload.get("profile_order", ["dev", "candidate", "release"])
    if not isinstance(order, list) or not order:
        order = ["dev", "candidate", "release"]
    highest = str(payload.get("highest_attained_profile", "") or payload.get("target_profile", "") or "").strip()
    failures = []
    profiles = payload.get("profiles", {}) if isinstance(payload.get("profiles"), dict) else {}
    for result in profiles.values():
        if not isinstance(result, dict):
            continue
        failures.extend(str(item) for item in result.get("failures", []) or [])
    return {
        "present": bool(payload),
        "ok": bool(payload.get("ok", False)),
        "target_profile": str(payload.get("target_profile", "") or "").strip(),
        "highest_attained_profile": highest,
        "profile_order": order,
        "failures": sorted(set(failures)),
        "path": str(path),
    }


def benchmark_dataset_inventory(bench_root: Path) -> dict:
    datasets = []
    if bench_root.exists():
        for path in sorted(bench_root.iterdir()):
            if not path.is_dir():
                continue
            gold = path / "gold.jsonl"
            if not gold.exists():
                gold = path / "gold.csv"
            if not gold.exists():
                continue
            datasets.append(
                {
                    "dataset": path.name,
                    "gold_path": str(gold),
                    "has_inputs": (path / "inputs").exists(),
                    "has_submissions": (path / "submissions").exists(),
                }
            )
    valid = [item for item in datasets if item["has_inputs"] and item["has_submissions"]]
    return {"count": len(valid), "datasets": valid}


def calibration_state(path: Path) -> dict:
    payload = load_json(path)
    generated_at = parse_dt(str(payload.get("generated_at", "") or ""))
    age_hours = None
    if generated_at is not None:
        age_hours = round((datetime.now(timezone.utc) - generated_at).total_seconds() / 3600.0, 6)
    return {
        "present": bool(payload),
        "synthetic": bool(payload.get("synthetic", False)),
        "generated_at": str(payload.get("generated_at", "") or ""),
        "generated_age_hours": age_hours,
        "model_version": str(payload.get("model_version", "") or ""),
        "scope_coverage": payload.get("scope_coverage", []) if isinstance(payload.get("scope_coverage"), list) else [],
        "path": str(path),
    }


def ops_state(path: Path) -> dict:
    payload = load_json(path)
    if not payload:
        return {
            "present": False,
            "recent_gate_failures": [],
            "recent_incidents": [],
            "cache_validation_failures": 0,
            "path": str(path),
        }
    return {
        "present": True,
        "recent_gate_failures": list(payload.get("recent_gate_failures", []) or []),
        "recent_incidents": list(payload.get("recent_incidents", []) or []),
        "cache_validation_failures": int(payload.get("cache_validation_failures", 0) or 0),
        "last_retention_report": payload.get("last_retention_report", {}),
        "path": str(path),
    }


def evaluate(root: Path, *, publish_path: Path, sota_path: Path, calibration_path: Path, bench_root: Path, ops_path: Path) -> dict:
    contract = launch_contract(root)
    publish = gate_state(publish_path)
    sota = gate_state(sota_path)
    calibration = calibration_state(calibration_path)
    benchmark_inventory = benchmark_dataset_inventory(bench_root)
    ops = ops_state(ops_path)
    incident = contract.get("incident", {})
    launch = contract.get("launch", {})
    privacy = contract.get("privacy", {})

    failures = []
    for section in ("auth", "retention", "observability", "launch", "privacy", "rollback", "incident"):
        if not isinstance(contract.get(section), dict) or not contract.get(section):
            failures.append(f"contract_section_missing:{section}")

    required_publish = str(launch.get("required_publish_profile", "") or "").strip()
    required_sota = str(launch.get("required_sota_profile", "") or "").strip()
    required_privacy = str(launch.get("required_privacy_posture", "") or "").strip()
    if not publish["present"]:
        failures.append("publish_gate_missing")
    if not sota["present"]:
        failures.append("sota_gate_missing")
    if publish["present"]:
        if not publish["ok"]:
            failures.append("publish_gate_not_ok")
        if required_publish:
            attained = profile_rank(publish["profile_order"], publish["highest_attained_profile"])
            required = profile_rank(publish["profile_order"], required_publish)
            if attained < required:
                failures.append("publish_profile_below_required")
    if sota["present"]:
        if not sota["ok"]:
            failures.append("sota_gate_not_ok")
        if required_sota:
            attained = profile_rank(sota["profile_order"], sota["highest_attained_profile"])
            required = profile_rank(sota["profile_order"], required_sota)
            if attained < required:
                failures.append("sota_profile_below_required")

    if benchmark_inventory["count"] < int(launch.get("required_benchmark_dataset_count", 0) or 0):
        failures.append("benchmark_dataset_coverage_below_required")

    if not calibration["present"]:
        failures.append("calibration_manifest_missing")
    else:
        max_age = float(launch.get("required_calibration_freshness_hours", 0.0) or 0.0)
        age = calibration.get("generated_age_hours")
        if age is None:
            failures.append("calibration_age_unknown")
        elif max_age > 0.0 and float(age) > max_age:
            failures.append("calibration_freshness_exceeded")
        if calibration["synthetic"]:
            failures.append("synthetic_calibration_not_allowed")

    if required_privacy and str(privacy.get("required_posture", "") or "").strip() != required_privacy:
        failures.append("privacy_posture_mismatch")

    if int(ops.get("cache_validation_failures", 0) or 0) > 0:
        failures.append("cache_validation_failures_present")
    if int(incident.get("max_recent_gate_failures", 0) or 0) >= 0:
        if len(ops.get("recent_gate_failures", []) or []) > int(incident.get("max_recent_gate_failures", 0) or 0):
            failures.append("recent_gate_failures_above_limit")
    if bool(incident.get("require_runbook", True)):
        runbook = root / "docs" / "INCIDENT_RESPONSE.md"
        if not runbook.exists():
            failures.append("incident_runbook_missing")

    result = {
        "generated_at": now_iso(),
        "ok": not failures,
        "decision_state": "launch_ready" if not failures else "blocked",
        "failures": failures,
        "contract": contract,
        "publish_gate": publish,
        "sota_gate": sota,
        "calibration": calibration,
        "benchmark_inventory": benchmark_inventory,
        "ops": ops,
    }
    return result


def write_markdown(path: Path, payload: dict) -> None:
    lines = [
        "# Production Launch Report",
        "",
        f"- generated_at: {payload.get('generated_at', '')}",
        f"- ok: {payload.get('ok', False)}",
        f"- decision_state: {payload.get('decision_state', '')}",
        "",
        "## Failures",
    ]
    failures = payload.get("failures", []) or []
    if not failures:
        lines.append("- none")
    else:
        lines.extend(f"- {item}" for item in failures)
    lines.extend(
        [
            "",
            "## Gate State",
            f"- publish_highest_attained_profile: {payload.get('publish_gate', {}).get('highest_attained_profile', '') or 'none'}",
            f"- sota_highest_attained_profile: {payload.get('sota_gate', {}).get('highest_attained_profile', '') or 'none'}",
            "",
            "## Coverage",
            f"- benchmark_dataset_count: {payload.get('benchmark_inventory', {}).get('count', 0)}",
            f"- calibration_generated_age_hours: {payload.get('calibration', {}).get('generated_age_hours', 'unknown')}",
            f"- recent_gate_failures: {len(payload.get('ops', {}).get('recent_gate_failures', []) or [])}",
            f"- cache_validation_failures: {payload.get('ops', {}).get('cache_validation_failures', 0)}",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the production launch contract against current artifacts.")
    parser.add_argument("--root", default=".", help="Repo root")
    parser.add_argument("--publish", default="outputs/publish_gate.json", help="Publish gate JSON path")
    parser.add_argument("--sota", default="outputs/sota_gate.json", help="SOTA gate JSON path")
    parser.add_argument("--calibration", default="outputs/calibration_manifest.json", help="Calibration manifest path")
    parser.add_argument("--bench-root", default="bench", help="Benchmark datasets root")
    parser.add_argument("--ops", default="server/data/pipeline_ops.json", help="Queue ops state path")
    parser.add_argument("--out", default="outputs/production_launch_report.json", help="Output JSON path")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    payload = evaluate(
        root,
        publish_path=(root / args.publish).resolve(),
        sota_path=(root / args.sota).resolve(),
        calibration_path=(root / args.calibration).resolve(),
        bench_root=(root / args.bench_root).resolve(),
        ops_path=(root / args.ops).resolve(),
    )
    out = (root / args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md = out.with_suffix(".md")
    write_markdown(md, payload)
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok", False) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
