#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_THRESHOLDS = {
    "min_dwell_seconds": 90.0,
    "min_student_decisions": 2,
    "min_pairwise_decisions": 1,
    "min_total_interactions": 3,
    "min_review_note_chars": 60,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso8601(value: str | None):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data


def evaluate_engagement(record: dict, *, collection_allowed: bool, thresholds: dict | None = None) -> dict:
    limits = dict(DEFAULT_THRESHOLDS)
    if isinstance(thresholds, dict):
        limits.update({key: value for key, value in thresholds.items() if value not in (None, "")})
    session = record.get("review_session", {}) if isinstance(record.get("review_session", {}), dict) else {}
    started_at = parse_iso8601(session.get("started_at"))
    saved_at = parse_iso8601(record.get("saved_at"))
    dwell_seconds = max(0.0, (saved_at - started_at).total_seconds()) if started_at and saved_at else 0.0
    students = record.get("students", []) if isinstance(record.get("students", []), list) else []
    pairwise = record.get("pairwise", []) if isinstance(record.get("pairwise", []), list) else []
    review_notes = str(record.get("review_notes", "") or "")
    level_overrides = sum(1 for item in students if str(item.get("level_override", "") or "").strip())
    rank_overrides = sum(1 for item in students if item.get("desired_rank") not in (None, ""))
    pairwise_overrides = sum(1 for item in pairwise if str(item.get("preferred_student_id", "") or "").strip())
    total_interactions = level_overrides + rank_overrides + pairwise_overrides
    intentional = bool(
        dwell_seconds >= float(limits["min_dwell_seconds"])
        and (
            total_interactions >= int(limits["min_total_interactions"])
            or len(students) >= int(limits["min_student_decisions"])
            or len(pairwise) >= int(limits["min_pairwise_decisions"])
            or len(review_notes.strip()) >= int(limits["min_review_note_chars"])
        )
    )
    if not intentional and len(students) >= int(limits["min_student_decisions"]):
        intentional = True
    if not intentional and len(pairwise) >= int(limits["min_pairwise_decisions"]):
        intentional = True
    if not intentional and len(review_notes.strip()) >= int(limits["min_review_note_chars"]):
        intentional = True
    if not intentional and total_interactions > 0:
        intentional = True

    if str(record.get("review_state", "") or "").strip().lower() != "final":
        retention_state = "discarded"
        reason = "review_not_final"
    elif not intentional:
        retention_state = "discarded"
        reason = "insufficient_teacher_engagement"
    elif not collection_allowed:
        retention_state = "local_only"
        reason = "aggregate_collection_not_allowed"
    else:
        retention_state = "aggregate_candidate"
        reason = "finalized_and_engaged"

    return {
        "generated_at": now_iso(),
        "eligible": retention_state == "aggregate_candidate",
        "retention_state": retention_state,
        "engagement_label": "intentional" if intentional else "insufficient",
        "reason": reason,
        "metrics": {
            "dwell_seconds": round(dwell_seconds, 6),
            "student_decision_count": len(students),
            "pairwise_decision_count": len(pairwise),
            "level_override_count": level_overrides,
            "rank_override_count": rank_overrides,
            "pairwise_override_count": pairwise_overrides,
            "review_note_chars": len(review_notes.strip()),
            "total_interactions": total_interactions,
        },
        "thresholds": limits,
        "collection_allowed": bool(collection_allowed),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate whether a finalized teacher review is eligible for governed aggregate learning.")
    parser.add_argument("--record", required=True)
    parser.add_argument("--collection-allowed", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = evaluate_engagement(load_json(Path(args.record)), collection_allowed=bool(args.collection_allowed))
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote engagement signal to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
