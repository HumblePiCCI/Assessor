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


def level_midpoints(config: dict) -> dict[str, float]:
    bands = (((config or {}).get("levels", {}) or {}).get("bands", []) if isinstance(config, dict) else [])
    mids = {}
    for band in bands if isinstance(bands, list) else []:
        if not isinstance(band, dict):
            continue
        try:
            label = str(band.get("level", "") or "").strip()
            low = float(band.get("min", 0.0) or 0.0)
            high = float(band.get("max", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if label:
            mids[label] = round((low + high) / 2.0, 4)
    return mids


def dedupe_points(points: list[dict]) -> list[dict]:
    ordered = sorted(points, key=lambda item: (float(item["x"]), float(item["y"])))
    result = []
    for point in ordered:
        if result and float(point["x"]) == float(result[-1]["x"]):
            result[-1] = point
        else:
            result.append(point)
    return result


def build_anchor_patch(*, rows: list[dict], teacher_scores: dict, config: dict) -> dict:
    by_id = {str(row.get("student_id", "") or ""): row for row in rows if row.get("student_id")}
    mids = level_midpoints(config)
    anchors = []
    deltas = []
    points = []
    scores = teacher_scores.get("anchors", []) if isinstance(teacher_scores, dict) else []
    for entry in scores if isinstance(scores, list) else []:
        if not isinstance(entry, dict):
            continue
        sid = str(entry.get("student_id", "") or "").strip()
        row = by_id.get(sid)
        if not sid or not row:
            continue
        machine_score = num(row.get("rubric_after_penalty_percent"), num(row.get("rubric_mean_percent"), 0.0))
        teacher_mark = entry.get("teacher_mark")
        teacher_level = str(entry.get("teacher_level", "") or "").strip()
        if teacher_mark not in (None, ""):
            target_score = num(teacher_mark, machine_score)
        else:
            target_score = mids.get(teacher_level, machine_score)
        delta = round(target_score - machine_score, 6)
        anchors.append(
            {
                "student_id": sid,
                "machine_score": round(machine_score, 4),
                "target_score": round(target_score, 4),
                "teacher_level": teacher_level,
                "teacher_mark": teacher_mark if teacher_mark not in (None, "") else "",
                "delta": delta,
            }
        )
        deltas.append(delta)
        points.append({"x": round(machine_score, 4), "y": round(target_score, 4), "student_id": sid})
    mean_delta = round((sum(deltas) / len(deltas)) if deltas else 0.0, 6)
    return {
        "generated_at": now_iso(),
        "status": "prepared",
        "active": True,
        "accepted": None,
        "supersedes_local_teacher_prior": True,
        "fit_method": "piecewise_score_interpolation" if len(points) >= 2 else "global_shift",
        "mean_delta": mean_delta,
        "interpolation_basis": "rubric_after_penalty_percent",
        "interpolation_points": dedupe_points(points),
        "anchors": anchors,
        "fallback_reason": "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a local anchor calibration patch from teacher-scored anchor papers.")
    parser.add_argument("--rows", default="outputs/consensus_scores.csv")
    parser.add_argument("--teacher-scores", default="outputs/teacher_anchor_scores.json")
    parser.add_argument("--config", default="config/marking_config.json")
    parser.add_argument("--output", default="outputs/cohort_anchor_calibration.json")
    args = parser.parse_args()

    patch = build_anchor_patch(
        rows=load_rows(Path(args.rows)),
        teacher_scores=load_json(Path(args.teacher_scores)),
        config=load_json(Path(args.config)),
    )
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(patch, indent=2), encoding="utf-8")
    print(f"Wrote anchor calibration patch to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
