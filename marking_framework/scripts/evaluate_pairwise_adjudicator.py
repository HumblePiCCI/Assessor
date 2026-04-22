#!/usr/bin/env python3
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from scripts.adjudication_source import dedupe_by_precedence, normalize_source
    from scripts import verify_consistency as vc
except ImportError:  # pragma: no cover - Support running as script without package context
    from adjudication_source import dedupe_by_precedence, normalize_source  # type: ignore  # pragma: no cover
    import verify_consistency as vc  # type: ignore  # pragma: no cover


DEFAULT_GOLD = Path(__file__).resolve().parents[1] / "evals" / "pairwise" / "ghost_literary_hard_pairs.json"
DEFAULT_OUTPUT = "outputs/pairwise_adjudicator_eval.json"
CONFIDENCE_WEIGHTS = {"low": 0.5, "medium": 1.0, "high": 2.0}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def normalize_tags(value) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    tags = []
    for item in value if isinstance(value, list) else []:
        token = str(item or "").strip()
        if token and token not in tags:
            tags.append(token)
    return tags


def normalize_gold_pair(item: dict, idx: int) -> dict:
    pair = item.get("pair")
    if not isinstance(pair, list) or len(pair) != 2:
        raise ValueError(f"Gold pair {idx}: pair must be a two-item list")
    left = str(pair[0] or "").strip()
    right = str(pair[1] or "").strip()
    winner = str(item.get("winner", "") or "").strip()
    if not left or not right or left == right:
        raise ValueError(f"Gold pair {idx}: invalid pair ids")
    if winner not in {left, right}:
        raise ValueError(f"Gold pair {idx}: winner must be one member of pair")
    priority = str(item.get("priority") or "standard").strip().lower()
    return {
        "id": str(item.get("id") or f"pair_{idx:03d}").strip(),
        "pair": [left, right],
        "winner": winner,
        "loser": right if winner == left else left,
        "priority": priority,
        "tags": normalize_tags(item.get("tags")),
        "rationale": str(item.get("rationale", "") or "").strip(),
        "risk": str(item.get("risk", "") or "").strip(),
    }


def load_gold(path: Path) -> dict:
    payload = load_json(path)
    pairs = payload.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise ValueError(f"{path}: expected non-empty pairs list")
    normalized_pairs = [normalize_gold_pair(item, idx) for idx, item in enumerate(pairs, start=1) if isinstance(item, dict)]
    if len(normalized_pairs) != len(pairs):
        raise ValueError(f"{path}: every pair must be an object")
    thresholds = payload.get("thresholds") if isinstance(payload.get("thresholds"), dict) else {}
    return {
        **payload,
        "pairs": normalized_pairs,
        "thresholds": {
            "min_accuracy": float(thresholds.get("min_accuracy", 0.85)),
            "min_critical_accuracy": float(thresholds.get("min_critical_accuracy", 1.0)),
            "min_coverage": float(thresholds.get("min_coverage", 1.0)),
        },
    }


def selected_pairs(gold_pairs: list[dict], *, tags: set[str], priorities: set[str], limit: int = 0) -> list[dict]:
    selected = []
    for pair in gold_pairs:
        if tags and not (set(pair.get("tags", [])) & tags):
            continue
        if priorities and str(pair.get("priority", "")).lower() not in priorities:
            continue
        selected.append(pair)
        if limit and len(selected) >= limit:
            break
    return selected


def pair_key(left: str, right: str) -> str:
    return "::".join(sorted((str(left).strip(), str(right).strip())))


def confidence_weight(confidence: str) -> float:
    return float(CONFIDENCE_WEIGHTS.get(vc.normalize_confidence(confidence), CONFIDENCE_WEIGHTS["low"]))


def adjudication_source(item: dict) -> str:
    return normalize_source(item)


def judgment_outcome(item: dict) -> dict | None:
    pair = item.get("pair")
    if not isinstance(pair, list) or len(pair) != 2:
        return None
    left = str(pair[0] or "").strip()
    right = str(pair[1] or "").strip()
    if not left or not right or left == right:
        return None
    winner = str(item.get("winner", "") or "").strip()
    loser = str(item.get("loser", "") or "").strip()
    if winner not in {left, right}:
        seed_order = item.get("seed_order", {}) if isinstance(item.get("seed_order"), dict) else {}
        higher = str(seed_order.get("higher") or left).strip()
        lower = str(seed_order.get("lower") or right).strip()
        decision = vc.decision_from_winner_side(item.get("winner_side")) or vc.normalize_decision(item.get("decision"))
        winner = lower if decision == "SWAP" else higher
        loser = higher if decision == "SWAP" else lower
    if winner not in {left, right} or loser not in {left, right} or winner == loser:
        return None
    return {
        "pair": [left, right],
        "key": pair_key(left, right),
        "winner": winner,
        "loser": loser,
        "confidence": vc.normalize_confidence(item.get("confidence")),
        "weight": confidence_weight(item.get("confidence")),
        "winner_side": vc.normalize_winner_side(item.get("winner_side")) or vc.winner_side_from_decision(item.get("decision")),
        "decision": vc.decision_from_winner_side(item.get("winner_side")) or vc.normalize_decision(item.get("decision")),
        "decision_basis": vc.normalize_decision_basis(item.get("decision_basis")),
        "cautions_applied": vc.normalize_cautions(item.get("cautions_applied")),
        "decision_checks": vc.normalize_decision_checks(item.get("decision_checks")),
        "adjudication_source": adjudication_source(item),
        "rationale": str(item.get("rationale", "") or "").strip(),
        "raw": item,
    }


def outcomes_from_judgments(path: Path) -> dict[str, dict]:
    payload = load_json(path)
    raw_items = payload.get("checks", payload.get("judgments", []))
    if (not isinstance(raw_items, list) or not raw_items) and isinstance(payload.get("comparisons"), list):
        raw_items = []
        for comparison in payload.get("comparisons", []):
            if not isinstance(comparison, dict):
                continue
            pair = comparison.get("pair")
            for judgment in comparison.get("judgments", []) if isinstance(comparison.get("judgments"), list) else []:
                if isinstance(judgment, dict):
                    raw_items.append({**judgment, "pair": pair})
    if not isinstance(raw_items, list):
        raw_items = []

    return aggregate_judgment_outcomes(raw_items, source=str(path))


def aggregate_judgment_outcomes(raw_items: list[dict], *, source: str) -> dict[str, dict]:
    all_outcomes = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        outcome = judgment_outcome(item)
        if outcome:
            all_outcomes.append(outcome)
    all_outcomes = dedupe_by_precedence(all_outcomes, key_fn=lambda outcome: outcome["key"])
    buckets: dict[str, dict] = {}
    for outcome in all_outcomes:
        bucket = buckets.setdefault(
            outcome["key"],
            {
                "pair": outcome["pair"],
                "weights": defaultdict(float),
                "judgments": [],
            },
        )
        bucket["weights"][outcome["winner"]] += outcome["weight"]
        bucket["judgments"].append(outcome)

    outcomes = {}
    for key, bucket in buckets.items():
        weights = dict(bucket["weights"])
        ordered = sorted(weights.items(), key=lambda item: (-item[1], item[0]))
        winner = ordered[0][0] if ordered else ""
        ambiguous = len(ordered) > 1 and abs(float(ordered[0][1]) - float(ordered[1][1])) < 1e-9
        strongest = sorted(bucket["judgments"], key=lambda item: (-item["weight"], item["winner"]))[0]
        outcomes[key] = {
            "pair": bucket["pair"],
            "winner": "" if ambiguous else winner,
            "ambiguous": ambiguous,
            "winner_weights": weights,
            "judgment_count": len(bucket["judgments"]),
            "strongest_judgment": strongest,
            "judgments": bucket["judgments"],
            "source": source,
        }
    return outcomes


def human_order_rows(gold: dict) -> dict[str, int]:
    ordered = {}
    for item in gold.get("human_order", []) if isinstance(gold.get("human_order"), list) else []:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("student_id", "") or "").strip()
        try:
            rank = int(item.get("rank"))
        except (TypeError, ValueError):
            continue
        if sid and rank > 0:
            ordered[sid] = rank
    return ordered


def minimal_row(student_id: str, seed_rank: int) -> dict:
    return {
        "student_id": student_id,
        "seed_rank": int(seed_rank),
        "adjusted_level": "",
        "base_level": "",
        "level": "",
        "rubric_after_penalty_percent": 0.0,
        "borda_percent": 0.0,
        "composite_score": 0.0,
        "source": {},
    }


def load_eval_rows(scores_path: Path | None, gold: dict, pairs: list[dict]) -> dict[str, dict]:
    if scores_path and scores_path.exists():
        return {row["student_id"]: row for row in vc.prepare_rows(vc.load_rows(scores_path))}
    rank_by_id = human_order_rows(gold)
    ids = []
    for pair in pairs:
        for sid in pair["pair"]:
            if sid not in ids:
                ids.append(sid)
    ids.sort(key=lambda sid: (rank_by_id.get(sid, 999999), sid))
    return {sid: minimal_row(sid, idx) for idx, sid in enumerate(ids, start=1)}


def orient_pair(gold_pair: dict, rows_by_id: dict[str, dict]) -> tuple[dict, dict]:
    left, right = gold_pair["pair"]
    left_row = rows_by_id.get(left) or minimal_row(left, 999998)
    right_row = rows_by_id.get(right) or minimal_row(right, 999999)
    ordered = sorted([left_row, right_row], key=lambda row: (int(row.get("seed_rank", 999999) or 999999), row["student_id"]))
    return ordered[0], ordered[1]


def live_outcomes(
    pairs: list[dict],
    *,
    rows_by_id: dict[str, dict],
    texts: dict[str, str],
    rubric: str,
    outline: str,
    metadata: dict,
    genre: str,
    model: str,
    routing: str,
    reasoning: str,
    max_output_tokens: int,
    anchor_dir: str,
    orientation_audit: bool = True,
    replicates: int = 1,
) -> dict[str, dict]:
    outcomes = {}
    missing_text = sorted({sid for pair in pairs for sid in pair["pair"] if not texts.get(sid)})
    if missing_text:
        raise ValueError(f"Missing essay text for hard-pair eval: {', '.join(missing_text)}")
    for gold_pair in pairs:
        higher, lower = orient_pair(gold_pair, rows_by_id)
        judgments = []
        for replicate_idx in range(max(1, int(replicates))):
            details = [
                "This pair was selected because prior adjudication marked it as a difficult ranking boundary.",
            ]
            if replicates > 1:
                details.append(f"Independent replicate {replicate_idx + 1} of {replicates}; re-read the essays from scratch.")
            judgments.append(
                vc.judge_pair_with_orientation_audit(
                    rubric,
                    outline,
                    higher,
                    lower,
                    texts.get(higher["student_id"], ""),
                    texts.get(lower["student_id"], ""),
                    model=model,
                    routing=routing,
                    reasoning=reasoning,
                    max_output_tokens=max_output_tokens,
                    genre=genre,
                    metadata=metadata,
                    selection_reasons=["gold_hard_pair_eval"],
                    selection_details=details,
                    anchor_dir=anchor_dir,
                    orientation_audit=orientation_audit,
                    student_count=len(rows_by_id),
                )
            )
        aggregated = aggregate_judgment_outcomes(judgments, source="live_model")
        outcome = aggregated.get(gold_pair_key(gold_pair))
        if outcome:
            outcomes[gold_pair_key(gold_pair)] = outcome
    return outcomes


def gold_pair_key(gold_pair: dict) -> str:
    return pair_key(gold_pair["pair"][0], gold_pair["pair"][1])


def likely_polish_bias(gold_pair: dict, outcome: dict | None) -> bool:
    if not outcome:
        return False
    strongest = outcome.get("strongest_judgment", {}) if isinstance(outcome, dict) else {}
    tags = set(gold_pair.get("tags", []))
    basis = strongest.get("decision_basis")
    cautions = set(str(item) for item in strongest.get("cautions_applied", []))
    return bool(
        {"rougher_stronger_interpretation", "polished_but_shallow", "formulaic_control_risk"} & tags
        and (basis in {"organization", "language_control"} or "polished_but_shallow" not in cautions)
    )


def evaluate_outcomes(gold: dict, pairs: list[dict], outcomes: dict[str, dict]) -> dict:
    rows = []
    by_tag = defaultdict(lambda: {"total": 0, "correct": 0, "missing": 0})
    by_priority = defaultdict(lambda: {"total": 0, "correct": 0, "missing": 0})
    misses = []
    missing = []
    evaluated = 0
    correct = 0
    critical_total = 0
    critical_correct = 0
    polish_bias_risks = []
    for gold_pair in pairs:
        key = gold_pair_key(gold_pair)
        outcome = outcomes.get(key)
        predicted = outcome.get("winner") if isinstance(outcome, dict) else ""
        is_missing = not predicted
        is_correct = predicted == gold_pair["winner"]
        if not is_missing:
            evaluated += 1
            if is_correct:
                correct += 1
        if gold_pair["priority"] == "critical":
            critical_total += 1
            if is_correct:
                critical_correct += 1
        for tag in gold_pair.get("tags", []):
            by_tag[tag]["total"] += 1
            by_tag[tag]["correct"] += int(is_correct)
            by_tag[tag]["missing"] += int(is_missing)
        by_priority[gold_pair["priority"]]["total"] += 1
        by_priority[gold_pair["priority"]]["correct"] += int(is_correct)
        by_priority[gold_pair["priority"]]["missing"] += int(is_missing)
        row = {
            "id": gold_pair["id"],
            "pair": gold_pair["pair"],
            "expected_winner": gold_pair["winner"],
            "predicted_winner": predicted,
            "correct": bool(is_correct),
            "missing": bool(is_missing),
            "priority": gold_pair["priority"],
            "tags": gold_pair.get("tags", []),
            "gold_rationale": gold_pair.get("rationale", ""),
            "outcome": outcome or {},
        }
        rows.append(row)
        if is_missing:
            missing.append(row)
        elif not is_correct:
            misses.append(row)
            if likely_polish_bias(gold_pair, outcome):
                polish_bias_risks.append(row)
    total = len(pairs)
    accuracy = (correct / evaluated) if evaluated else 0.0
    coverage = (evaluated / total) if total else 1.0
    critical_accuracy = (critical_correct / critical_total) if critical_total else 1.0
    thresholds = gold["thresholds"]
    failures = []
    if accuracy < thresholds["min_accuracy"]:
        failures.append("accuracy_below_threshold")
    if critical_accuracy < thresholds["min_critical_accuracy"]:
        failures.append("critical_accuracy_below_threshold")
    if coverage < thresholds["min_coverage"]:
        failures.append("coverage_below_threshold")
    if polish_bias_risks:
        failures.append("possible_polish_bias_misses")
    return {
        "summary": {
            "pair_count": total,
            "evaluated_count": evaluated,
            "correct_count": correct,
            "missing_count": len(missing),
            "accuracy": round(accuracy, 6),
            "coverage": round(coverage, 6),
            "critical_pair_count": critical_total,
            "critical_correct_count": critical_correct,
            "critical_accuracy": round(critical_accuracy, 6),
            "failures": failures,
        },
        "by_priority": summarize_buckets(by_priority),
        "by_tag": summarize_buckets(by_tag),
        "misses": misses,
        "missing": missing,
        "polish_bias_risks": polish_bias_risks,
        "pairs": rows,
    }


def summarize_buckets(buckets: dict) -> dict:
    summary = {}
    for key, stats in sorted(buckets.items()):
        total = int(stats["total"])
        correct = int(stats["correct"])
        missing = int(stats["missing"])
        evaluated = total - missing
        summary[key] = {
            "total": total,
            "evaluated": evaluated,
            "correct": correct,
            "missing": missing,
            "accuracy": round((correct / evaluated) if evaluated else 0.0, 6),
        }
    return summary


def resolve_workspace_path(workspace: Path | None, explicit: str, default_suffix: str) -> Path | None:
    if explicit:
        return Path(explicit)
    if workspace:
        return workspace / default_suffix
    return None


def parse_csv_tokens(value: str) -> set[str]:
    return {item.strip().lower() for item in str(value or "").split(",") if item.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the pairwise adjudicator against explicit hard-pair gold.")
    parser.add_argument("--gold", default=str(DEFAULT_GOLD), help="Hard-pair gold JSON")
    parser.add_argument("--workspace", default="", help="Optional workspace root for default texts/scores/rubric/outline paths")
    parser.add_argument("--judgments", default="", help="Existing consistency_checks.json or pairwise_matrix.json to score without model calls")
    parser.add_argument("--scores", default="", help="Seed scores CSV for live pair orientation")
    parser.add_argument("--texts", default="", help="Normalized essay text directory for live model eval")
    parser.add_argument("--rubric", default="", help="Rubric file for live model eval")
    parser.add_argument("--outline", default="", help="Assignment outline for live model eval")
    parser.add_argument("--class-metadata", default="", help="Class metadata JSON")
    parser.add_argument("--genre", default="", help="Override writing genre for prompt guidance")
    parser.add_argument("--routing", default="config/llm_routing.json", help="Routing config for live model eval")
    parser.add_argument("--model", default="gpt-5.4-mini", help="Model for live model eval")
    parser.add_argument("--reasoning", default="low", help="Reasoning effort for live model eval")
    parser.add_argument("--max-output-tokens", type=int, default=600, help="Max model output tokens")
    parser.add_argument("--anchor-dir", default=str(vc.DEFAULT_PAIRWISE_ANCHOR_DIR), help="Pairwise calibration anchor directory")
    parser.add_argument("--disable-orientation-audit", action="store_true", help="Disable swapped-read orientation auditing for high-risk literary-analysis live eval pairs")
    parser.add_argument("--replicates", type=int, default=1, help="Independent live model judgments per selected hard pair")
    parser.add_argument("--tags", default="", help="Comma-separated tag filter")
    parser.add_argument("--priorities", default="", help="Comma-separated priority filter")
    parser.add_argument("--limit", type=int, default=0, help="Limit selected pairs")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output JSON")
    parser.add_argument("--fail-on-threshold", action="store_true", help="Return 2 when configured thresholds fail")
    args = parser.parse_args()

    gold_path = Path(args.gold)
    gold = load_gold(gold_path)
    pairs = selected_pairs(
        gold["pairs"],
        tags=parse_csv_tokens(args.tags),
        priorities=parse_csv_tokens(args.priorities),
        limit=max(0, int(args.limit)),
    )
    if not pairs:
        raise SystemExit("No gold pairs selected.")

    workspace = Path(args.workspace) if args.workspace else None
    scores_path = resolve_workspace_path(workspace, args.scores, "outputs/consensus_scores.csv")
    metadata_path = resolve_workspace_path(workspace, args.class_metadata, "inputs/class_metadata.json")
    metadata = vc.load_pairwise_metadata(metadata_path) if metadata_path else {}
    genre = str(args.genre or gold.get("genre") or vc.resolve_pairwise_genre(metadata) or "").strip()

    if args.judgments:
        outcomes = outcomes_from_judgments(Path(args.judgments))
        mode = "existing_judgments"
    else:
        texts_path = resolve_workspace_path(workspace, args.texts, "processing/normalized_text")
        rubric_path = resolve_workspace_path(workspace, args.rubric, "inputs/rubric.md")
        outline_path = resolve_workspace_path(workspace, args.outline, "inputs/assignment_outline.md")
        if not texts_path or not rubric_path or not outline_path:
            raise SystemExit("Live pairwise eval requires --workspace or explicit --texts, --rubric, and --outline.")
        rows_by_id = load_eval_rows(scores_path, gold, pairs)
        texts = vc.load_texts(texts_path)
        rubric = vc.load_file_text(vc.resolve_input_path(rubric_path, "rubric"))
        outline = vc.load_file_text(vc.resolve_input_path(outline_path, "assignment_outline"))
        outcomes = live_outcomes(
            pairs,
            rows_by_id=rows_by_id,
            texts=texts,
            rubric=rubric,
            outline=outline,
            metadata=metadata,
            genre=genre,
            model=args.model,
            routing=args.routing,
            reasoning=args.reasoning,
            max_output_tokens=max(64, int(args.max_output_tokens)),
            anchor_dir=args.anchor_dir,
            orientation_audit=not args.disable_orientation_audit,
            replicates=max(1, int(args.replicates)),
        )
        mode = "live_model"

    evaluated = evaluate_outcomes(gold, pairs, outcomes)
    output_path = Path(args.output)
    if args.output == DEFAULT_OUTPUT and workspace:
        output_path = workspace / DEFAULT_OUTPUT
    payload = {
        "generated_at": now_iso(),
        "mode": mode,
        "gold": {
            "path": str(gold_path),
            "id": gold.get("id", ""),
            "genre": gold.get("genre", ""),
            "selected_pair_count": len(pairs),
            "thresholds": gold.get("thresholds", {}),
        },
        "inputs": {
            "workspace": str(workspace or ""),
            "judgments": args.judgments,
            "scores": str(scores_path or ""),
            "metadata": str(metadata_path or ""),
            "model": args.model if mode == "live_model" else "",
            "routing": args.routing if mode == "live_model" else "",
            "anchor_dir": args.anchor_dir,
            "orientation_audit": (not args.disable_orientation_audit) if mode == "live_model" else False,
            "replicates": max(1, int(args.replicates)) if mode == "live_model" else 1,
        },
        **evaluated,
    }
    write_json(output_path, payload)
    summary = payload["summary"]
    print(
        f"Pairwise eval saved to {output_path} "
        f"(accuracy={summary['accuracy']:.3f}, coverage={summary['coverage']:.3f}, failures={len(summary['failures'])})"
    )
    if args.fail_on_threshold and summary["failures"]:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
