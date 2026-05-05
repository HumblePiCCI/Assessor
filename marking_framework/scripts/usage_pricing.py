#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path

try:
    from scripts.runtime_profiles import billing_policy, resolve_runtime_profile
except ImportError:  # pragma: no cover - standalone workspace fallback
    from runtime_profiles import billing_policy, resolve_runtime_profile  # type: ignore


def load_pricing(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def cached_tokens_from_usage(usage: dict) -> int:
    details = usage.get("input_tokens_details", {})
    if isinstance(details, dict):
        for key in ("cached_tokens", "cached_input_tokens"):
            try:
                return max(0, int(details.get(key, 0) or 0))
            except (TypeError, ValueError):
                return 0
    try:
        return max(0, int(usage.get("cached_input_tokens", 0) or 0))
    except (TypeError, ValueError):
        return 0


def resolve_billing(args) -> dict:
    profile_name = str(args.profile or os.environ.get("LLM_RUNTIME_PROFILE", "") or "").strip()
    policy = {"billable": False, "customer_markup_percent": 0.0}
    if profile_name:
        try:
            policy = billing_policy(resolve_runtime_profile(profile_name, Path(args.profiles)))
        except KeyError:
            policy = {"billable": False, "customer_markup_percent": 0.0}
    if args.billable or truthy(os.environ.get("BILLING_BILLABLE")):
        policy["billable"] = True
    markup_raw = args.markup_percent if args.markup_percent is not None else os.environ.get("BILLING_CUSTOMER_MARKUP_PERCENT")
    if markup_raw is not None:
        try:
            policy["customer_markup_percent"] = float(markup_raw)
        except (TypeError, ValueError):
            policy["customer_markup_percent"] = 0.0
    policy["profile"] = profile_name
    return policy


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate cost from usage_log.jsonl")
    parser.add_argument("--usage", default="outputs/usage_log.jsonl", help="Usage log path")
    parser.add_argument("--pricing", default="config/pricing.json", help="Pricing config path")
    parser.add_argument("--output", default="outputs/usage_costs.json", help="Output cost report")
    parser.add_argument("--profiles", default="config/runtime_profiles.json", help="Runtime profiles config path")
    parser.add_argument("--profile", default="", help="Runtime profile name for billing policy")
    parser.add_argument("--markup-percent", type=float, default=None, help="Override customer markup percentage")
    parser.add_argument("--billable", action="store_true", help="Mark report as customer billable")
    parser.add_argument("--fail-on-missing-prices", action="store_true", help="Return nonzero if usage includes a model missing from pricing config")
    args = parser.parse_args()

    usage_path = Path(args.usage)
    if not usage_path.exists():
        print(f"Usage log not found: {usage_path}")
        return 1

    pricing = load_pricing(Path(args.pricing))
    models = pricing.get("models", {})
    billing = resolve_billing(args)

    totals = {}
    unpriced_models = {}
    with usage_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            model = entry.get("model")
            usage = entry.get("usage", {})
            if not model:
                continue
            input_tokens = usage.get("input_tokens", 0) or 0
            output_tokens = usage.get("output_tokens", 0) or 0
            cached_input_tokens = min(cached_tokens_from_usage(usage), int(input_tokens or 0))
            if model not in models:
                if model not in unpriced_models:
                    unpriced_models[model] = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}
                unpriced_models[model]["input_tokens"] += input_tokens
                unpriced_models[model]["output_tokens"] += output_tokens
                unpriced_models[model]["cached_input_tokens"] += cached_input_tokens
                continue
            if model not in totals:
                totals[model] = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}
            totals[model]["input_tokens"] += input_tokens
            totals[model]["output_tokens"] += output_tokens
            totals[model]["cached_input_tokens"] += cached_input_tokens

    cost_breakdown = {}
    grand_total = 0.0
    for model, toks in totals.items():
        price = models.get(model, {})
        cached_tokens = min(toks.get("cached_input_tokens", 0), toks["input_tokens"])
        uncached_tokens = max(0, toks["input_tokens"] - cached_tokens)
        cached_rate = price.get("cached_input_per_million", price.get("input_per_million", 0.0))
        input_cost = (uncached_tokens / 1_000_000) * price.get("input_per_million", 0.0)
        cached_input_cost = (cached_tokens / 1_000_000) * cached_rate
        output_cost = (toks["output_tokens"] / 1_000_000) * price.get("output_per_million", 0.0)
        total = input_cost + cached_input_cost + output_cost
        cost_breakdown[model] = {
            "input_tokens": toks["input_tokens"],
            "cached_input_tokens": cached_tokens,
            "output_tokens": toks["output_tokens"],
            "input_cost": round(input_cost, 6),
            "cached_input_cost": round(cached_input_cost, 6),
            "output_cost": round(output_cost, 6),
            "total_cost": round(total, 6),
        }
        grand_total += total
    markup = max(0.0, float(billing.get("customer_markup_percent", 0.0) or 0.0)) if billing.get("billable") else 0.0
    service_fee = grand_total * (markup / 100.0)

    report = {
        "currency": pricing.get("currency", "USD"),
        "pricing_source": pricing.get("pricing_source", ""),
        "pricing_checked_at": pricing.get("pricing_checked_at", ""),
        "runtime_profile": billing.get("profile", ""),
        "billable": bool(billing.get("billable", False)),
        "customer_markup_percent": round(markup, 6),
        "models": cost_breakdown,
        "unpriced_models": unpriced_models,
        "api_cost_total": round(grand_total, 6),
        "service_fee": round(service_fee, 6),
        "customer_total": round(grand_total + service_fee, 6),
        "grand_total": round(grand_total, 6),
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote cost report: {out_path}")
    print(f"Total API cost ({report['currency']}): ${report['api_cost_total']:.4f}")
    if report["billable"]:
        print(f"Customer total with {report['customer_markup_percent']:.2f}% service fee: ${report['customer_total']:.4f}")
    if unpriced_models:
        print(f"Missing pricing for models: {', '.join(sorted(unpriced_models))}")
        if args.fail_on_missing_prices or report["billable"]:
            return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
