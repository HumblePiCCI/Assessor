#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.levels import LEVEL_TO_PERCENT, normalize_level


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


def allowed_anchor_levels(config: dict) -> tuple[str, ...]:
    mids = level_midpoints(config)
    if mids:
        return tuple(mids.keys())
    return tuple(LEVEL_TO_PERCENT.keys())


def normalize_teacher_scores(teacher_scores: dict, config: dict) -> dict:
    allowed_levels = set(allowed_anchor_levels(config))
    normalized = []
    seen_ids = set()
    raw_scores = teacher_scores.get("anchors", []) if isinstance(teacher_scores, dict) else []
    for index, entry in enumerate(raw_scores if isinstance(raw_scores, list) else [], start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Anchor {index} must be an object.")
        sid = str(entry.get("student_id", "") or "").strip()
        if not sid:
            raise ValueError(f"Anchor {index} is missing student_id.")
        if sid in seen_ids:
            raise ValueError(f"Anchor {sid} was submitted more than once.")
        seen_ids.add(sid)
        teacher_level_raw = entry.get("teacher_level", "")
        teacher_level = normalize_level(teacher_level_raw)
        if teacher_level_raw not in (None, "") and not teacher_level:
            raise ValueError(f"Anchor {sid} has an invalid teacher_level '{teacher_level_raw}'.")
        if teacher_level and teacher_level not in allowed_levels:
            allowed = ", ".join(sorted(allowed_levels))
            raise ValueError(f"Anchor {sid} level '{teacher_level}' is not allowed for this rubric ({allowed}).")
        teacher_mark_raw = entry.get("teacher_mark")
        teacher_mark = ""
        if teacher_mark_raw not in (None, ""):
            try:
                teacher_mark = round(float(teacher_mark_raw), 4)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Anchor {sid} has an invalid teacher_mark '{teacher_mark_raw}'.") from exc
            if teacher_mark < 0.0 or teacher_mark > 100.0:
                raise ValueError(f"Anchor {sid} mark must be between 0 and 100.")
        if not teacher_level and teacher_mark == "":
            raise ValueError(f"Anchor {sid} must include a level or a mark.")
        normalized.append(
            {
                "student_id": sid,
                "teacher_level": teacher_level or "",
                "teacher_mark": teacher_mark,
            }
        )
    return {"anchors": normalized}


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
    scores = normalize_teacher_scores(teacher_scores, config).get("anchors", [])
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
