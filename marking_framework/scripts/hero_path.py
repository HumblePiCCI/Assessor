#!/usr/bin/env python3
import argparse
import subprocess
from pathlib import Path


def run(cmd):
    result = subprocess.run(cmd, check=False)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Hero Path orchestration")
    parser.add_argument("--accuracy-consistency", action="store_true", help="Enable strict calibration + consistency + publish gates")
    parser.add_argument("--skip-extract", action="store_true", help="Skip text extraction")
    parser.add_argument("--skip-conventions", action="store_true", help="Skip conventions scan")
    parser.add_argument("--skip-aggregate", action="store_true", help="Skip aggregation")
    parser.add_argument("--llm-assessors", action="store_true", help="Run LLM assessors to generate pass1/pass2")
    parser.add_argument("--calibrate", action="store_true", help="Run calibration against gold set")
    parser.add_argument("--pricing-report", action="store_true", help="Generate usage cost report after LLM runs")
    parser.add_argument("--ignore-cost-limits", action="store_true", help="Skip LLM cost limit checks")
    parser.add_argument("--generate-pairs", action="store_true", help="Generate pairwise review file")
    parser.add_argument("--apply-pairs", action="store_true", help="Apply pairwise review decisions")
    parser.add_argument("--verify-consistency", action="store_true", help="Verify adjacent rank consistency")
    parser.add_argument("--apply-consistency", action="store_true", help="Apply high-confidence consistency swaps")
    parser.add_argument("--boundary-recheck", action="store_true", help="Recheck near-boundary essays and update pass1 scores")
    parser.add_argument("--boundary-margin", type=float, default=1.0, help="Boundary recheck margin in percentage points")
    parser.add_argument("--boundary-replicates", type=int, default=3, help="Boundary recheck replicate attempts")
    parser.add_argument("--boundary-max-students", type=int, default=8, help="Boundary recheck max students")
    parser.add_argument("--publish-gate", action="store_true", help="Run publish quality gate")
    parser.add_argument("--gate-config", default="config/accuracy_gate.json", help="Publish gate config JSON")
    parser.add_argument("--build-dashboard", action="store_true", help="Build dashboard data JSON")
    parser.add_argument("--serve-ui", action="store_true", help="Serve the review UI")
    parser.add_argument("--allow-missing-data", action="store_true", help="Allow missing data in aggregation")
    parser.add_argument("--port", type=int, default=7860, help="UI port")
    args = parser.parse_args()

    base = Path(".")
    inputs = base / "inputs" / "submissions"
    normalized = base / "processing" / "normalized_text"
    meta = base / "processing" / "submission_metadata.json"
    conventions = base / "processing" / "conventions_report.csv"

    if args.accuracy_consistency:
        args.calibrate = True
        args.llm_assessors = True
        args.boundary_recheck = True
        args.verify_consistency = True
        args.apply_consistency = True
        args.publish_gate = True

    if not args.skip_extract:
        cmd = ["python3", "scripts/extract_text.py", "--inputs", str(inputs), "--output", str(normalized), "--metadata", str(meta)]
        if run(cmd) != 0:
            return 1

    if not args.skip_conventions:
        if run(["python3", "scripts/conventions_scan.py", "--inputs", str(normalized), "--output", str(conventions)]) != 0:
            return 1

    if args.calibrate:
        if run(["python3", "scripts/calibrate_assessors.py"]) != 0:
            return 1

    if args.llm_assessors:
        cmd = ["python3", "scripts/run_llm_assessors.py"]
        if args.ignore_cost_limits:
            cmd.append("--ignore-cost-limits")
        if run(cmd) != 0:
            return 1
        if args.pricing_report:
            run(["python3", "scripts/usage_pricing.py"])

    # Check assessor outputs exist
    pass1_dir = base / "assessments" / "pass1_individual"
    pass2_dir = base / "assessments" / "pass2_comparative"
    if not any(pass1_dir.glob("*.json")) or not any(pass2_dir.glob("*")):
        print("Missing assessor outputs. Run Pass 1 and Pass 2 first.")
        return 1

    if not args.skip_aggregate:
        cmd = ["python3", "scripts/aggregate_assessments.py", "--config", "config/marking_config.json"]
        if args.allow_missing_data:
            cmd.append("--allow-missing-data")
        if run(cmd) != 0:
            return 1
        if args.boundary_recheck:
            cmd = [
                "python3",
                "scripts/boundary_recheck.py",
                "--margin",
                str(args.boundary_margin),
                "--replicates",
                str(args.boundary_replicates),
                "--max-students",
                str(args.boundary_max_students),
            ]
            if run(cmd) != 0:
                return 1
            cmd = ["python3", "scripts/aggregate_assessments.py", "--config", "config/marking_config.json"]
            if args.allow_missing_data:
                cmd.append("--allow-missing-data")
            if run(cmd) != 0:
                return 1

    if args.generate_pairs:
        if run(["python3", "scripts/generate_pairwise_review.py"]) != 0:
            return 1

    if args.apply_pairs:
        if run(["python3", "scripts/apply_pairwise_adjustments.py"]) != 0:
            return 1

    if args.verify_consistency:
        cmd = ["python3", "scripts/verify_consistency.py"]
        if args.apply_consistency:
            cmd.append("--apply")
        if run(cmd) != 0:
            return 1

    if args.publish_gate:
        cmd = ["python3", "scripts/publish_gate.py", "--gate-config", args.gate_config]
        if run(cmd) != 0:
            return 1

    if args.build_dashboard:
        if run(["python3", "scripts/build_dashboard_data.py"]) != 0:
            return 1

    if args.serve_ui:
        if run(["python3", "scripts/serve_ui.py", "--port", str(args.port)]) != 0:
            return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
