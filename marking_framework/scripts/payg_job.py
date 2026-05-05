#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    from scripts.runtime_profiles import apply_runtime_profile_to_routing, resolve_runtime_profile, write_runtime_profile_artifact
except ImportError:  # pragma: no cover - standalone workspace fallback
    from runtime_profiles import apply_runtime_profile_to_routing, resolve_runtime_profile, write_runtime_profile_artifact  # type: ignore


def copy_workspace(src: Path, dst: Path):
    # Copy minimal workspace assets
    for name in ["scripts", "config", "prompts", "templates", "docs", "ui"]:
        src_path = src / name
        if src_path.exists():
            shutil.copytree(src_path, dst / name)
    # Create required dirs
    for name in ["inputs", "processing", "assessments", "outputs"]:
        (dst / name).mkdir(parents=True, exist_ok=True)
        if name == "inputs":
            (dst / name / "submissions").mkdir(parents=True, exist_ok=True)


def json_load(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a pay-as-you-go grading job")
    parser.add_argument("--rubric", required=True, help="Rubric file (md/docx)")
    parser.add_argument("--outline", required=True, help="Assignment outline file (md/docx)")
    parser.add_argument("--submissions", required=True, help="Directory of submissions")
    parser.add_argument("--workdir", default="", help="Job workspace directory")
    parser.add_argument("--llm", action="store_true", help="Run LLM assessors")
    parser.add_argument("--pairs", action="store_true", help="Generate pairwise review file")
    parser.add_argument("--pricing", action="store_true", help="Generate pricing report")
    parser.add_argument("--profile", default="teacher_payg_openai", help="Runtime profile to apply")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent

    if args.workdir:
        job_dir = Path(args.workdir)
        job_dir.mkdir(parents=True, exist_ok=True)
    else:
        job_dir = Path(tempfile.mkdtemp(prefix="hero_path_job_"))

    copy_workspace(repo_root, job_dir)
    profile = resolve_runtime_profile(args.profile, job_dir / "config" / "runtime_profiles.json")
    routing_path = job_dir / "config" / "llm_routing.json"
    routing = apply_runtime_profile_to_routing(json_load(routing_path), profile)
    routing_path.write_text(json.dumps(routing, indent=2, sort_keys=True), encoding="utf-8")
    write_runtime_profile_artifact(profile, routing, job_dir / "outputs" / "runtime_profile.json")

    # Copy inputs
    shutil.copy2(args.rubric, job_dir / "inputs" / Path(args.rubric).name)
    shutil.copy2(args.outline, job_dir / "inputs" / Path(args.outline).name)
    for item in Path(args.submissions).iterdir():
        if item.is_file():
            shutil.copy2(item, job_dir / "inputs" / "submissions" / item.name)

    cmd = ["python3", "scripts/hero_path.py"]
    if args.llm:
        cmd.extend(["--llm-assessors", "--pricing-report" if args.pricing else ""])
    if args.pairs:
        cmd.append("--generate-pairs")

    cmd = [c for c in cmd if c]
    env = os.environ.copy()
    mode = str(profile.get("mode") or "openai")
    env["LLM_MODE"] = mode
    env["LLM_RUNTIME_PROFILE"] = str(profile.get("name") or args.profile)
    env["LLM_PROVIDER"] = str(profile.get("provider") or "")
    billing = profile.get("billing", {}) if isinstance(profile.get("billing", {}), dict) else {}
    env["BILLING_BILLABLE"] = "1" if billing.get("billable", False) else "0"
    env["BILLING_CUSTOMER_MARKUP_PERCENT"] = str(billing.get("customer_markup_percent", 0.0) or 0.0)
    if mode == "codex_local" or str(profile.get("provider") or "") != "openai":
        env.pop("OPENAI_API_KEY", None)
    result = subprocess.run(cmd, cwd=str(job_dir), env=env)
    if result.returncode != 0:
        print(f"Job failed. Workspace preserved at: {job_dir}")
        return result.returncode

    print(f"Job completed. Workspace: {job_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
