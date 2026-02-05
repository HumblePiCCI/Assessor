#!/usr/bin/env python3
import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a pay-as-you-go grading job")
    parser.add_argument("--rubric", required=True, help="Rubric file (md/docx)")
    parser.add_argument("--outline", required=True, help="Assignment outline file (md/docx)")
    parser.add_argument("--submissions", required=True, help="Directory of submissions")
    parser.add_argument("--workdir", default="", help="Job workspace directory")
    parser.add_argument("--llm", action="store_true", help="Run LLM assessors")
    parser.add_argument("--pairs", action="store_true", help="Generate pairwise review file")
    parser.add_argument("--pricing", action="store_true", help="Generate pricing report")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent

    if args.workdir:
        job_dir = Path(args.workdir)
        job_dir.mkdir(parents=True, exist_ok=True)
    else:
        job_dir = Path(tempfile.mkdtemp(prefix="hero_path_job_"))

    copy_workspace(repo_root, job_dir)

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
    env["LLM_MODE"] = "openai"
    result = subprocess.run(cmd, cwd=str(job_dir), env=env)
    if result.returncode != 0:
        print(f"Job failed. Workspace preserved at: {job_dir}")
        return result.returncode

    print(f"Job completed. Workspace: {job_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
