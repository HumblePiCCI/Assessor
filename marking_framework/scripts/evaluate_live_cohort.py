#!/usr/bin/env python3
"""Score a live cohort's final order against a human-adjudicated gold file.

The gold file (evals/pairwise/*.json) carries `human_order` and `pairs`.
Live imports can assign different student_ids than the gold file used, so
students are matched by display name (exact, then first name with a
last-initial disambiguator for collisions).

Usage:
  python3 scripts/evaluate_live_cohort.py \
    --gold evals/pairwise/ghost_literary_hard_pairs.json \
    --final-order outputs/final_order.csv \
    --dashboard outputs/dashboard_data.json \
    --output outputs/live_cohort_eval.json
"""
import argparse
import csv
import itertools
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def name_key(name: str, collisions: set[str]) -> str:
    """First name, plus last-initial when the first name collides."""
    parts = str(name or "").strip().split()
    if not parts:
        return ""
    first = parts[0]
    if first in collisions and len(parts) > 1:
        return f"{first} {parts[-1][0]}"
    return first


def first_name_collisions(names: list[str]) -> set[str]:
    seen: dict[str, int] = {}
    for name in names:
        parts = str(name or "").strip().split()
        if parts:
            seen[parts[0]] = seen.get(parts[0], 0) + 1
    return {first for first, count in seen.items() if count > 1}


def build_name_maps(gold: dict, dashboard: dict) -> tuple[dict[str, int], dict[str, str], dict[str, str]]:
    """Returns (gold_rank_by_key, workspace key->student_id, student_id->key)."""
    gold_names = [h.get("display_name", "") for h in gold.get("human_order", [])]
    ws_students = dashboard.get("students", []) if isinstance(dashboard, dict) else []
    ws_names = [s.get("display_name", "") for s in ws_students]
    collisions = first_name_collisions(gold_names) | first_name_collisions(ws_names)
    gold_rank_by_key = {
        name_key(h.get("display_name", ""), collisions): int(h.get("rank", 0))
        for h in gold.get("human_order", [])
    }
    ws_key_to_id = {}
    ws_id_to_key = {}
    for s in ws_students:
        key = name_key(s.get("display_name", ""), collisions)
        sid = str(s.get("student_id", "") or "")
        if key and sid:
            ws_key_to_id[key] = sid
            ws_id_to_key[sid] = key
    return gold_rank_by_key, ws_key_to_id, ws_id_to_key


def kendall_tau(gold_rank: dict[str, int], pipe_rank: dict[str, int]) -> tuple[float, int, int]:
    common = [k for k in gold_rank if k in pipe_rank]
    concordant = discordant = 0
    for a, b in itertools.combinations(common, 2):
        g = gold_rank[a] - gold_rank[b]
        p = pipe_rank[a] - pipe_rank[b]
        if g * p > 0:
            concordant += 1
        elif g * p < 0:
            discordant += 1
    total = concordant + discordant
    return ((concordant - discordant) / total if total else 0.0), concordant, discordant


def evaluate(gold: dict, final_rows: list[dict], dashboard: dict) -> dict:
    gold_rank_by_key, ws_key_to_id, ws_id_to_key = build_name_maps(gold, dashboard)
    gold_id_to_key = {}
    collisions = first_name_collisions(
        [h.get("display_name", "") for h in gold.get("human_order", [])]
    ) | first_name_collisions([s.get("display_name", "") for s in dashboard.get("students", [])])
    for h in gold.get("human_order", []):
        gold_id_to_key[str(h.get("student_id", "") or "")] = name_key(h.get("display_name", ""), collisions)

    rank_field = "final_rank" if final_rows and "final_rank" in final_rows[0] else "consensus_rank"
    pipe_rank_by_key = {}
    for row in final_rows:
        key = ws_id_to_key.get(str(row.get("student_id", "") or ""))
        if key:
            pipe_rank_by_key[key] = int(float(row.get(rank_field) or 0))

    matched = sorted(set(gold_rank_by_key) & set(pipe_rank_by_key), key=lambda k: gold_rank_by_key[k])
    tau, concordant, discordant = kendall_tau(gold_rank_by_key, pipe_rank_by_key)

    pair_results = []
    violated = {"critical": 0, "important": 0, "standard": 0}
    evaluated_pairs = 0
    for pair in gold.get("pairs", []):
        winner_key = gold_id_to_key.get(str(pair.get("winner", "") or ""))
        loser_id = next((x for x in pair.get("pair", []) if x != pair.get("winner")), None)
        loser_key = gold_id_to_key.get(str(loser_id or ""))
        priority = str(pair.get("priority", "standard") or "standard")
        if winner_key not in pipe_rank_by_key or loser_key not in pipe_rank_by_key:
            pair_results.append({"id": pair.get("id"), "priority": priority, "status": "unmatched"})
            continue
        evaluated_pairs += 1
        ok = pipe_rank_by_key[winner_key] < pipe_rank_by_key[loser_key]
        if not ok:
            violated[priority] = violated.get(priority, 0) + 1
        pair_results.append(
            {
                "id": pair.get("id"),
                "priority": priority,
                "status": "ok" if ok else "violated",
                "winner": winner_key,
                "loser": loser_key,
                "winner_rank": pipe_rank_by_key[winner_key],
                "loser_rank": pipe_rank_by_key[loser_key],
            }
        )

    top5_gold = matched[:5]
    top5_pipe = sorted(matched, key=lambda k: pipe_rank_by_key[k])[:5]
    displacements = {
        key: pipe_rank_by_key[key] - gold_rank_by_key[key] for key in matched
    }

    return {
        "matched_students": len(matched),
        "gold_students": len(gold_rank_by_key),
        "kendall_tau": round(tau, 4),
        "concordant": concordant,
        "discordant": discordant,
        "gold_pairs_evaluated": evaluated_pairs,
        "gold_pairs_violated": sum(violated.values()),
        "gold_pairs_violated_by_priority": violated,
        "critical_pair_accuracy": round(
            1.0
            - (
                violated.get("critical", 0)
                / max(1, sum(1 for p in pair_results if p.get("priority") == "critical" and p.get("status") != "unmatched"))
            ),
            4,
        ),
        "top5_overlap": len(set(top5_gold) & set(top5_pipe)),
        "top5_gold": top5_gold,
        "top5_pipeline": top5_pipe,
        "mean_abs_displacement": round(
            sum(abs(v) for v in displacements.values()) / max(1, len(displacements)), 3
        ),
        "displacements": displacements,
        "pairs": pair_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", default="evals/pairwise/ghost_literary_hard_pairs.json")
    parser.add_argument("--final-order", default="outputs/final_order.csv")
    parser.add_argument("--dashboard", default="outputs/dashboard_data.json")
    parser.add_argument("--output", default="outputs/live_cohort_eval.json")
    args = parser.parse_args()

    gold = load_json(Path(args.gold))
    dashboard = load_json(Path(args.dashboard))
    with Path(args.final_order).open("r", encoding="utf-8") as handle:
        final_rows = list(csv.DictReader(handle))

    result = evaluate(gold, final_rows, dashboard)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        f"tau={result['kendall_tau']} top5={result['top5_overlap']}/5 "
        f"pairs_violated={result['gold_pairs_violated']}/{result['gold_pairs_evaluated']} "
        f"critical_acc={result['critical_pair_accuracy']} "
        f"mean_disp={result['mean_abs_displacement']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
