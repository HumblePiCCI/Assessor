#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_pass1_rows(pass1_dir: Path) -> list[dict]:
    rows = []
    for path in sorted(pass1_dir.glob("assessor_*.json")):
        payload = load_json(path)
        assessor_id = str(payload.get("assessor_id") or path.stem)
        for item in payload.get("scores", []):
            row = dict(item)
            row["assessor_id"] = assessor_id
            rows.append(row)
    return rows


def model_coverage(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    model_rows = 0
    for row in rows:
        notes = str(row.get("notes", ""))
        if "Fallback deterministic score" not in notes:
            model_rows += 1
    return model_rows / len(rows)


def score_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    valid = 0
    for row in rows:
        try:
            if float(row.get("rubric_total_points", 0.0) or 0.0) > 0.0:
                valid += 1
        except (TypeError, ValueError):
            continue
    return valid / len(rows)


def criteria_coverage(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    hit = 0
    for row in rows:
        points = row.get("criteria_points")
        if isinstance(points, dict) and points:
            hit += 1
    return hit / len(rows)


def evidence_coverage(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    hit = 0
    for row in rows:
        evidence = row.get("criteria_evidence")
        if isinstance(evidence, list) and evidence:
            hit += 1
    return hit / len(rows)


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / len(values)
    return variance ** 0.5


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


def assessor_spread(rows: list[dict]) -> tuple[float, float]:
    scores = {}
    for row in rows:
        sid = str(row.get("student_id", "")).strip()
        if not sid:
            continue
        try:
            score = float(row.get("rubric_total_points", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        scores.setdefault(sid, []).append(score)
    sds = [_stdev(items) for items in scores.values() if len(items) > 1]
    if not sds:
        return 0.0, 0.0
    return sum(sds) / len(sds), _percentile(sds, 0.95)


def consistency_metrics(path: Path) -> tuple[int, float, float]:
    payload = load_json(path)
    checks = payload.get("checks", []) if isinstance(payload, dict) else []
    if not checks:
        return 0, 0.0, 0.0
    swaps = 0
    low = 0
    for item in checks:
        decision = str(item.get("decision", "")).upper()
        if decision == "SWAP":
            swaps += 1
        confidence = str(item.get("confidence", "")).lower()
        if confidence == "low":
            low += 1
    total = len(checks)
    return total, swaps / total, low / total


def evaluate(metrics: dict, thresholds: dict) -> list[str]:
    failures = []
    if thresholds.get("require_publish_gate_ok", True) and not metrics["publish_gate_ok"]:
        failures.append("publish_gate_not_ok")
    if not metrics["publish_gate_present"]:
        failures.append("publish_gate_missing")
    if metrics["assessor_files"] < int(thresholds.get("min_assessor_files", 0)):
        failures.append("assessor_count_below_threshold")
    if metrics["model_coverage"] < float(thresholds.get("min_model_coverage", 0.0)):
        failures.append("model_coverage_below_threshold")
    if metrics["nonzero_score_rate"] < float(thresholds.get("min_nonzero_score_rate", 0.0)):
        failures.append("nonzero_score_rate_below_threshold")
    if metrics["criteria_coverage"] < float(thresholds.get("min_criteria_coverage", 0.0)):
        failures.append("criteria_coverage_below_threshold")
    if metrics["evidence_coverage"] < float(thresholds.get("min_evidence_coverage", 0.0)):
        failures.append("evidence_coverage_below_threshold")
    if metrics["mean_assessor_sd"] > float(thresholds.get("max_mean_assessor_sd", 999.0)):
        failures.append("mean_assessor_sd_above_threshold")
    if metrics["p95_assessor_sd"] > float(thresholds.get("max_p95_assessor_sd", 999.0)):
        failures.append("p95_assessor_sd_above_threshold")
    if metrics["consistency_swap_rate"] > float(thresholds.get("max_consistency_swap_rate", 1.0)):
        failures.append("consistency_swap_rate_above_threshold")
    if metrics["consistency_low_confidence_rate"] > float(thresholds.get("max_consistency_low_confidence_rate", 1.0)):
        failures.append("consistency_low_confidence_rate_above_threshold")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="SOTA readiness gate for assessment quality.")
    parser.add_argument("--publish-gate", default="outputs/publish_gate.json", help="Publish gate JSON")
    parser.add_argument("--pass1", default="assessments/pass1_individual", help="Pass1 assessor directory")
    parser.add_argument("--consistency", default="outputs/consistency_checks.json", help="Consistency checks JSON")
    parser.add_argument("--gate-config", default="config/sota_gate.json", help="SOTA thresholds JSON")
    parser.add_argument("--output", default="outputs/sota_gate.json", help="SOTA result JSON")
    args = parser.parse_args()

    config = load_json(Path(args.gate_config))
    thresholds = config.get("thresholds", config)

    publish = load_json(Path(args.publish_gate))
    rows = load_pass1_rows(Path(args.pass1))
    consistency_total, swap_rate, low_conf_rate = consistency_metrics(Path(args.consistency))
    mean_sd, p95_sd = assessor_spread(rows)

    metrics = {
        "publish_gate_present": bool(publish),
        "publish_gate_ok": bool(publish.get("ok", False)) if publish else False,
        "assessor_files": len(list(Path(args.pass1).glob("assessor_*.json"))),
        "pass1_rows": len(rows),
        "model_coverage": model_coverage(rows),
        "nonzero_score_rate": score_rate(rows),
        "criteria_coverage": criteria_coverage(rows),
        "evidence_coverage": evidence_coverage(rows),
        "mean_assessor_sd": mean_sd,
        "p95_assessor_sd": p95_sd,
        "consistency_checks": consistency_total,
        "consistency_swap_rate": swap_rate,
        "consistency_low_confidence_rate": low_conf_rate,
    }
    failures = evaluate(metrics, thresholds)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": len(failures) == 0,
        "failures": failures,
        "thresholds": thresholds,
        "metrics": metrics,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md = out.with_suffix(".md")
    lines = ["# SOTA Gate", "", f"- **ok**: {payload['ok']}"]
    for key in (
        "assessor_files",
        "pass1_rows",
        "model_coverage",
        "nonzero_score_rate",
        "criteria_coverage",
        "evidence_coverage",
        "mean_assessor_sd",
        "p95_assessor_sd",
        "consistency_checks",
        "consistency_swap_rate",
        "consistency_low_confidence_rate",
    ):
        lines.append(f"- **{key}**: {metrics.get(key)}")
    if failures:
        lines.extend(["", "## Failures"] + [f"- {item}" for item in failures])
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out}")
    print(f"Wrote {md}")
    return 0 if payload["ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
