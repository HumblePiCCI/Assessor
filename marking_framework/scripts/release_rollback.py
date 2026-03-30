#!/usr/bin/env python3
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from server.runtime_context import launch_contract
except ImportError:  # pragma: no cover
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


def build_plan(root: Path, *, reason: str, target_git_sha: str, target_manifest_hash: str) -> dict:
    contract = launch_contract(root)
    manifest = load_json(root / "pipeline_manifest.json")
    if not manifest:
        manifest = load_json(root / "outputs" / "pipeline_manifest.json")
    publish = load_json(root / "outputs" / "publish_gate.json")
    sota = load_json(root / "outputs" / "sota_gate.json")
    rollback_cfg = contract.get("rollback", {})
    current_sha = str(manifest.get("git", {}).get("sha", "") or "")
    current_manifest_hash = str(manifest.get("manifest_hash", "") or "")
    generated_at = parse_dt(str(manifest.get("generated_at", "") or ""))
    release_age_hours = None
    if generated_at is not None:
        release_age_hours = round((datetime.now(timezone.utc) - generated_at).total_seconds() / 3600.0, 6)

    failures = []
    if bool(rollback_cfg.get("require_manifest_hash", True)) and not current_manifest_hash:
        failures.append("current_manifest_hash_missing")
    if bool(rollback_cfg.get("require_git_sha", True)) and not current_sha:
        failures.append("current_git_sha_missing")
    if not target_git_sha and bool(rollback_cfg.get("require_git_sha", True)):
        failures.append("target_git_sha_missing")
    max_age = float(rollback_cfg.get("max_release_age_hours", 0.0) or 0.0)
    if release_age_hours is not None and max_age > 0.0 and release_age_hours > max_age:
        failures.append("current_release_age_exceeds_policy")

    effective_target_manifest = target_manifest_hash or current_manifest_hash
    effective_target_git_sha = target_git_sha or current_sha
    steps = [
        {
            "order": 1,
            "action": "freeze_new_jobs",
            "detail": "Pause new submissions or place the service in maintenance mode before changing runtime assets.",
        },
        {
            "order": 2,
            "action": "restore_release_inputs",
            "detail": f"Restore runtime code, prompts, and configs to git SHA {effective_target_git_sha or 'UNKNOWN_TARGET_SHA'}.",
        },
        {
            "order": 3,
            "action": "invalidate_manifest_cache",
            "detail": (
                f"Invalidate cached artifacts for manifest {effective_target_manifest or current_manifest_hash or 'UNKNOWN_MANIFEST'}."
                if bool(rollback_cfg.get('invalidate_cache_on_rollback', True))
                else "Cache invalidation is not required by policy."
            ),
        },
        {
            "order": 4,
            "action": "rerun_quality_gates",
            "detail": "Rerun benchmark, publish gate, and SOTA gate on the rollback candidate before reopening traffic.",
        },
        {
            "order": 5,
            "action": "publish_incident_record",
            "detail": "Record the regression cause, impacted scope, and rollback evidence in the incident log and runbook.",
        },
    ]

    return {
        "generated_at": now_iso(),
        "ok": not failures,
        "reason": str(reason or "").strip() or "unspecified_regression",
        "failures": failures,
        "rollback_contract": rollback_cfg,
        "current_release": {
            "manifest_hash": current_manifest_hash,
            "git_sha": current_sha,
            "generated_at": str(manifest.get("generated_at", "") or ""),
            "release_age_hours": release_age_hours,
            "publish_gate_profile": str(publish.get("highest_attained_profile", "") or publish.get("target_profile", "") or ""),
            "sota_gate_profile": str(sota.get("highest_attained_profile", "") or sota.get("target_profile", "") or ""),
        },
        "target_release": {
            "git_sha": effective_target_git_sha,
            "manifest_hash": effective_target_manifest,
        },
        "steps": steps,
    }


def write_markdown(path: Path, payload: dict) -> None:
    lines = [
        "# Release Rollback Plan",
        "",
        f"- generated_at: {payload.get('generated_at', '')}",
        f"- ok: {payload.get('ok', False)}",
        f"- reason: {payload.get('reason', '')}",
        "",
        "## Failures",
    ]
    failures = payload.get("failures", []) or []
    if not failures:
        lines.append("- none")
    else:
        lines.extend(f"- {item}" for item in failures)
    lines.extend(["", "## Steps"])
    for step in payload.get("steps", []) or []:
        lines.append(f"{int(step.get('order', 0))}. {step.get('action', '')}: {step.get('detail', '')}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a manifest-aware rollback plan for a bad release.")
    parser.add_argument("--root", default=".", help="Repo root")
    parser.add_argument("--reason", default="model_or_prompt_regression", help="Rollback reason")
    parser.add_argument("--target-git-sha", default="", help="Known-good target git SHA")
    parser.add_argument("--target-manifest-hash", default="", help="Known-good target manifest hash")
    parser.add_argument("--out", default="outputs/release_rollback_plan.json", help="Output JSON path")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    payload = build_plan(
        root,
        reason=args.reason,
        target_git_sha=str(args.target_git_sha or "").strip(),
        target_manifest_hash=str(args.target_manifest_hash or "").strip(),
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
