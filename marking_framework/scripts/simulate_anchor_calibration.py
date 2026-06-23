#!/usr/bin/env python3
"""Simulate the teacher anchor-calibration loop against gold scores.

Plays the R2 anchor loop inside a completed pipeline workspace, standing in
for the teacher with the gold (blind-rater or human-adjudicated) scores of
the 4-6 machine-selected anchor papers, then measures rank agreement before
and after. This answers the question hold-harmless cannot: does anchor
calibration actually IMPROVE agreement with the human order, and by how much?

Reported tau excludes the anchor papers themselves (their placement is
informed by gold), alongside the all-students tau for context.

Usage:
  python3 scripts/simulate_anchor_calibration.py \
    --workspace /tmp/full_holdout_asap2_g6_cowboy_waves \
    --gold bench/holdout_asap2_g6_cowboy_waves/gold.jsonl
"""
import argparse
import csv
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def run(cmd: list[str], cwd: Path, extra_env: dict | None = None) -> None:
    # Current repo code, workspace data: scripts resolve from REPO, relative
    # data paths resolve from the workspace cwd.
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO)
    env.update(extra_env or {})
    cmd = [cmd[0], str(REPO / cmd[1]), *cmd[2:]] if cmd[1].startswith("scripts/") else cmd
    result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])} failed:\n{result.stdout[-800:]}\n{result.stderr[-800:]}")


def load_gold(path: Path) -> dict[str, dict]:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["student_id"]] = row
    return rows


def rank_map(csv_path: Path, key: str) -> dict[str, int]:
    with csv_path.open("r", encoding="utf-8") as handle:
        return {r["student_id"]: int(r[key]) for r in csv.DictReader(handle)}


def kendall(gold: dict[str, dict], ranks: dict[str, int], exclude: set[str] = frozenset()) -> float:
    ids = [s for s in gold if s in ranks and s not in exclude]
    conc = disc = 0
    for a, b in itertools.combinations(ids, 2):
        g = gold[a]["gold_rank"] - gold[b]["gold_rank"]
        p = ranks[a] - ranks[b]
        if g * p > 0:
            conc += 1
        elif g * p < 0:
            disc += 1
    total = conc + disc
    return (conc - disc) / total if total else 0.0


def teacher_scores_from_gold(selected: list[str], gold: dict[str, dict]) -> dict:
    anchors = []
    for sid in selected:
        row = gold.get(sid)
        if not row:
            continue
        anchor: dict = {"student_id": sid}
        band_min = row.get("gold_band_min")
        band_max = row.get("gold_band_max")
        if isinstance(band_min, (int, float)) and isinstance(band_max, (int, float)):
            anchor["teacher_mark"] = round((float(band_min) + float(band_max)) / 2.0, 1)
        level = row.get("gold_canonical_level") or row.get("gold_level")
        if level:
            anchor["teacher_level"] = str(level)
        anchors.append(anchor)
    return {"anchors": anchors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--gold", required=True)
    parser.add_argument("--candidate-count", type=int, default=5)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    ws = Path(args.workspace)
    gold = load_gold(Path(args.gold))

    pre_final = rank_map(ws / "outputs" / "final_order.csv", "final_rank")
    pre_tau_all = kendall(gold, pre_final)

    # 1. Machine selects anchors (same selector the product uses).
    run([sys.executable, "scripts/select_anchor_candidates.py", "--candidate-count", str(args.candidate_count)], ws)
    candidates = json.loads((ws / "outputs" / "anchor_candidates.json").read_text(encoding="utf-8"))
    selected = [str(s) for s in candidates.get("selected_student_ids", [])]

    # 2. "Teacher" scores them with gold values.
    scores = teacher_scores_from_gold(selected, gold)
    (ws / "outputs" / "teacher_anchor_scores.json").write_text(json.dumps(scores, indent=2), encoding="utf-8")

    # 3. Build the calibration patch (rank-evidence mode) and replay the
    #    anchor rerank exactly as the product does: same judgments file the
    #    pipeline's rerank consumed, ANCHOR_CALIBRATION_ACTIVE=1 so the
    #    teacher's anchor adjudications enter as committee-grade evidence.
    run([sys.executable, "scripts/apply_anchor_calibration.py"], ws)
    report = json.loads((ws / "outputs" / "consistency_report.json").read_text(encoding="utf-8"))
    judgments_file = report.get("inputs", {}).get("judgments", "outputs/consistency_checks.json")
    run(
        [sys.executable, "scripts/global_rerank.py", "--judgments", judgments_file],
        ws,
        extra_env={"ANCHOR_CALIBRATION_ACTIVE": "1"},
    )

    post_final = rank_map(ws / "outputs" / "final_order.csv", "final_rank")
    anchor_set = set(selected)
    result = {
        "workspace": str(ws),
        "anchors_selected": selected,
        "anchor_count": len(selected),
        "pre_tau_all": round(pre_tau_all, 4),
        "post_tau_all": round(kendall(gold, post_final), 4),
        "pre_tau_non_anchor": round(kendall(gold, pre_final, exclude=anchor_set), 4),
        "post_tau_non_anchor": round(kendall(gold, post_final, exclude=anchor_set), 4),
    }
    out = Path(args.output) if args.output else ws / "outputs" / "anchor_simulation.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
