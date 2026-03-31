#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

try:
    from scripts.assessor_utils import resolve_input_path
    from scripts.rubric_contract import build_rubric_artifacts, load_json, write_json
except ImportError:  # pragma: no cover - Support running as a script
    from assessor_utils import resolve_input_path  # pragma: no cover
    from rubric_contract import build_rubric_artifacts, load_json, write_json  # pragma: no cover


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize an uploaded rubric into a verified runtime contract")
    parser.add_argument("--rubric", default="inputs/rubric.md", help="Rubric source file")
    parser.add_argument("--outline", default="inputs/assignment_outline.md", help="Assignment outline file")
    parser.add_argument("--criteria-config", default="config/rubric_criteria.json", help="Canonical rubric criteria scaffold")
    parser.add_argument("--normalized-output", default="outputs/normalized_rubric.json", help="Normalized rubric JSON output")
    parser.add_argument("--manifest-output", default="outputs/rubric_manifest.json", help="Rubric manifest JSON output")
    parser.add_argument("--validation-output", default="outputs/rubric_validation_report.json", help="Rubric validation report output")
    parser.add_argument("--verification-output", default="outputs/rubric_verification.json", help="Rubric verification output")
    parser.add_argument("--existing-verification", default="", help="Existing verification JSON to preserve teacher confirmation state")
    parser.add_argument("--teacher-edits", default="", help="Optional teacher edits JSON payload")
    parser.add_argument("--confirm-action", default="", help="Optional explicit teacher action: confirm, edit, reject")
    args = parser.parse_args()

    rubric_path = resolve_input_path(Path(args.rubric), "rubric")
    outline_path = resolve_input_path(Path(args.outline), "assignment_outline")
    existing = load_json(Path(args.existing_verification)) if args.existing_verification else load_json(Path(args.verification_output))
    teacher_edits = load_json(Path(args.teacher_edits)) if args.teacher_edits else {}
    artifacts = build_rubric_artifacts(
        rubric_path,
        outline_path=outline_path,
        criteria_config_path=Path(args.criteria_config),
        existing_verification=existing,
        teacher_edits=teacher_edits,
        action=args.confirm_action or None,
    )
    write_json(Path(args.normalized_output), artifacts["normalized_rubric"])
    write_json(Path(args.manifest_output), artifacts["rubric_manifest"])
    write_json(Path(args.validation_output), artifacts["rubric_validation_report"])
    write_json(Path(args.verification_output), artifacts["rubric_verification"])

    verification = artifacts["rubric_verification"]
    validation = artifacts["rubric_validation_report"]
    print(f"Rubric verification status: {verification.get('status', '')}")
    print(f"Rubric proceed mode: {validation.get('proceed_mode', '')}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
