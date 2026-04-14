#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def rank_key(rows: list[dict]) -> str:
    if not rows:
        return ""
    for key in ("final_rank", "consistency_rank", "consensus_rank", "seed_rank"):
        if key in rows[0]:
            return key
    return ""


def level_boundaries(config: dict) -> list[tuple[str, str, float]]:
    levels = (((config or {}).get("levels", {}) or {}).get("bands", []) if isinstance(config, dict) else [])
    bands = []
    for band in levels if isinstance(levels, list) else []:
        if not isinstance(band, dict):
            continue
        try:
            bands.append((str(band.get("level", "") or ""), float(band.get("min", 0.0) or 0.0)))
        except (TypeError, ValueError):
            continue
    bands = sorted((item for item in bands if item[0] and item[1] > 0.0), key=lambda item: item[1])
    boundaries = []
    for idx in range(1, len(bands)):
        left_level = bands[idx - 1][0]
        right_level = bands[idx][0]
        boundaries.append((left_level, right_level, bands[idx][1]))
    return boundaries


def submission_meta(path: Path) -> dict[str, dict]:
    data = load_json(path)
    if isinstance(data, list):
        return {str(item.get("student_id", "") or ""): item for item in data if isinstance(item, dict) and item.get("student_id")}
    return {}


def movement_map(consistency_report: dict) -> dict[str, dict]:
    movements = consistency_report.get("movements", []) if isinstance(consistency_report, dict) else []
    return {str(item.get("student_id", "") or ""): item for item in movements if isinstance(item, dict) and item.get("student_id")}


def select_anchor_candidates(rows: list[dict], *, config: dict, consistency_report: dict, metadata: dict[str, dict], candidate_count: int = 5) -> dict:
    if not rows:
        return {
            "generated_at": now_iso(),
            "selected_student_ids": [],
            "selection_reasons": {},
            "candidates": [],
        }
    order_key = rank_key(rows)
    ordered = sorted(
        [dict(row) for row in rows if str(row.get("student_id", "") or "").strip()],
        key=lambda row: (int(num(row.get(order_key), 999999)), str(row.get("student_id", "")).lower()),
    )
    movements = movement_map(consistency_report)
    boundaries = level_boundaries(config if isinstance(config, dict) else {})
    selected: list[str] = []
    reasons: dict[str, list[str]] = {}

    def add_candidate(student_id: str, reason: str):
        if not student_id or student_id in selected:
            return
        selected.append(student_id)
        reasons.setdefault(student_id, []).append(reason)

    add_candidate(str(ordered[0].get("student_id", "") or ""), "predicted_top_band")
    add_candidate(str(ordered[-1].get("student_id", "") or ""), "predicted_bottom_band")

    for left, right, edge in boundaries:
        candidate = min(
            ordered,
            key=lambda row: (
                abs(num(row.get("rubric_after_penalty_percent"), num(row.get("rubric_mean_percent"), 0.0)) - edge),
                int(num(row.get(order_key), 999999)),
            ),
        )
        add_candidate(str(candidate.get("student_id", "") or ""), f"boundary_{left}_{right}")

    disagreement_row = max(
        ordered,
        key=lambda row: (
            num((movements.get(str(row.get("student_id", "") or ""), {}) or {}).get("support_weight"), 0.0)
            + num((movements.get(str(row.get("student_id", "") or ""), {}) or {}).get("opposition_weight"), 0.0),
            num((movements.get(str(row.get("student_id", "") or ""), {}) or {}).get("displacement"), 0.0),
            num(row.get("rubric_sd_points"), 0.0),
        ),
    )
    add_candidate(str(disagreement_row.get("student_id", "") or ""), "high_disagreement")

    if len(selected) < candidate_count:
        outlier_row = max(
            ordered,
            key=lambda row: (
                abs(num(row.get("rank_sd"), 0.0)) + abs(num(row.get("rubric_sd_points"), 0.0)),
                -int(num(row.get(order_key), 999999)),
            ),
        )
        add_candidate(str(outlier_row.get("student_id", "") or ""), "style_outlier")

    selected = selected[: max(1, int(candidate_count))]
    candidates = []
    by_id = {str(row.get("student_id", "") or ""): row for row in ordered}
    for student_id in selected:
        row = by_id.get(student_id, {})
        meta = metadata.get(student_id, {})
        candidates.append(
            {
                "student_id": student_id,
                "display_name": str(meta.get("display_name", "") or student_id),
                "source_file": str(meta.get("source_file", "") or ""),
                "machine_rank": int(num(row.get(order_key), 0.0) or 0.0),
                "machine_level": str(row.get("adjusted_level", "") or row.get("base_level", "") or ""),
                "rubric_after_penalty_percent": round(
                    num(row.get("rubric_after_penalty_percent"), num(row.get("rubric_mean_percent"), 0.0)),
                    2,
                ),
                "selection_reasons": reasons.get(student_id, []),
            }
        )
    return {
        "generated_at": now_iso(),
        "selected_student_ids": selected,
        "selection_reasons": reasons,
        "candidates": candidates,
    }


def teacher_anchor_packet(anchor_payload: dict) -> dict:
    candidates = anchor_payload.get("candidates", []) if isinstance(anchor_payload, dict) else []
    return {
        "generated_at": now_iso(),
        "instructions": "Score each anchor paper with a level, and optionally a mark, before resuming calibration.",
        "selected_student_ids": list(anchor_payload.get("selected_student_ids", []) or []),
        "anchors": [
            {
                "student_id": item.get("student_id", ""),
                "display_name": item.get("display_name", item.get("student_id", "")),
                "source_file": item.get("source_file", ""),
                "machine_rank": item.get("machine_rank"),
                "machine_level": item.get("machine_level", ""),
                "machine_percent": item.get("rubric_after_penalty_percent", ""),
                "selection_reasons": list(item.get("selection_reasons", []) or []),
                "teacher_level": "",
                "teacher_mark": "",
            }
            for item in candidates
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Select teacher anchor candidates for cold-start cohort calibration.")
    parser.add_argument("--rows", default="outputs/final_order.csv")
    parser.add_argument("--fallback", default="outputs/consensus_scores.csv")
    parser.add_argument("--config", default="config/marking_config.json")
    parser.add_argument("--consistency-report", default="outputs/consistency_report.json")
    parser.add_argument("--submission-metadata", default="processing/submission_metadata.json")
    parser.add_argument("--candidate-count", type=int, default=5)
    parser.add_argument("--output", default="outputs/anchor_candidates.json")
    parser.add_argument("--packet-output", default="outputs/teacher_anchor_packet.json")
    args = parser.parse_args()

    rows = load_rows(Path(args.rows)) or load_rows(Path(args.fallback))
    payload = select_anchor_candidates(
        rows,
        config=load_json(Path(args.config)),
        consistency_report=load_json(Path(args.consistency_report)),
        metadata=submission_meta(Path(args.submission_metadata)),
        candidate_count=max(1, int(args.candidate_count)),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    packet = teacher_anchor_packet(payload)
    packet_output = Path(args.packet_output)
    packet_output.parent.mkdir(parents=True, exist_ok=True)
    packet_output.write_text(json.dumps(packet, indent=2), encoding="utf-8")
    print(f"Wrote anchor candidates to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
