#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def load_pricing(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate cost from usage_log.jsonl")
    parser.add_argument("--usage", default="outputs/usage_log.jsonl", help="Usage log path")
    parser.add_argument("--pricing", default="config/pricing.json", help="Pricing config path")
    parser.add_argument("--output", default="outputs/usage_costs.json", help="Output cost report")
    args = parser.parse_args()

    usage_path = Path(args.usage)
    if not usage_path.exists():
        print(f"Usage log not found: {usage_path}")
        return 1

    pricing = load_pricing(Path(args.pricing))
    models = pricing.get("models", {})

    totals = {}
    with usage_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            model = entry.get("model")
            usage = entry.get("usage", {})
            if model not in models:
                continue
            input_tokens = usage.get("input_tokens", 0) or 0
            output_tokens = usage.get("output_tokens", 0) or 0
            if model not in totals:
                totals[model] = {"input_tokens": 0, "output_tokens": 0}
            totals[model]["input_tokens"] += input_tokens
            totals[model]["output_tokens"] += output_tokens

    cost_breakdown = {}
    grand_total = 0.0
    for model, toks in totals.items():
        price = models.get(model, {})
        input_cost = (toks["input_tokens"] / 1_000_000) * price.get("input_per_million", 0.0)
        output_cost = (toks["output_tokens"] / 1_000_000) * price.get("output_per_million", 0.0)
        total = input_cost + output_cost
        cost_breakdown[model] = {
            "input_tokens": toks["input_tokens"],
            "output_tokens": toks["output_tokens"],
            "input_cost": round(input_cost, 6),
            "output_cost": round(output_cost, 6),
            "total_cost": round(total, 6),
        }
        grand_total += total

    report = {
        "currency": pricing.get("currency", "USD"),
        "models": cost_breakdown,
        "grand_total": round(grand_total, 6),
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote cost report: {out_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
