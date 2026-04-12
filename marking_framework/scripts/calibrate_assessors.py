#!/usr/bin/env python3
import argparse
import bisect
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from scripts.assessor_context import (
        build_grade_context,
        format_exemplars,
        load_exemplars,
        load_grade_profiles,
        normalize_genre,
    )
    from scripts.assessor_utils import load_file_text, resolve_input_path
    from scripts.calibration_contract import (
        build_calibration_manifest,
        build_run_scope,
        build_scope_coverage_entry,
        calibration_manifest_path,
        file_sha256,
        is_boundary_score,
        routing_profile_hash_from_payload,
        source_exemplar_set_hash,
    )
    from scripts.levels import normalize_level
    from scripts.openai_client import extract_text, responses_create
    from scripts.rubric_contract import load_json as load_rubric_json, runtime_rubric_context
    from scripts.rubric_criteria import criteria_ids, criteria_prompt, evidence_requirements, load_rubric_criteria, total_points
    from scripts.run_llm_assessors import build_pass1_prompt, parse_pass1_item, pass1_text_format
    from scripts.fallback_assessor import deterministic_pass1_item
except ImportError:  # pragma: no cover - Running as script
    from assessor_context import build_grade_context, format_exemplars, load_exemplars, load_grade_profiles, normalize_genre  # pragma: no cover
    from assessor_utils import load_file_text, resolve_input_path  # pragma: no cover
    from calibration_contract import (  # pragma: no cover
        build_calibration_manifest,
        build_run_scope,
        build_scope_coverage_entry,
        calibration_manifest_path,
        file_sha256,
        is_boundary_score,
        routing_profile_hash_from_payload,
        source_exemplar_set_hash,
    )
    from levels import normalize_level  # pragma: no cover
    from openai_client import extract_text, responses_create  # pragma: no cover
    from rubric_contract import load_json as load_rubric_json, runtime_rubric_context  # pragma: no cover
    from rubric_criteria import criteria_ids, criteria_prompt, evidence_requirements, load_rubric_criteria, total_points  # pragma: no cover
    from run_llm_assessors import build_pass1_prompt, parse_pass1_item, pass1_text_format  # pragma: no cover
    from fallback_assessor import deterministic_pass1_item  # pragma: no cover


BAND_GRADE_LEVEL = {"grade_6_7": 7, "grade_8_10": 9, "grade_11_12": 11}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def score_to_percent(score: float, points_possible: int | None) -> float:
    if points_possible and score <= points_possible:
        return (score / points_possible) * 100.0
    return float(score)


def iter_gold_samples(calibration: dict):
    for band, genres in calibration.get("gold_samples", {}).items():
        for genre, samples in genres.items():
            for sample in samples:
                yield band, genre, sample


def scope_key(band: str, genre: str) -> str:
    return f"{band}|{normalize_genre(genre) or genre}"


def fit_affine_correction(pairs: list[tuple[float, float]]) -> dict:
    if not pairs:
        return {"slope": 1.0, "intercept": 0.0, "mean_error": 0.0, "mae": 0.0}
    obs = [p[0] for p in pairs]
    tgt = [p[1] for p in pairs]
    if len(pairs) < 2:
        intercept = tgt[0] - obs[0]
        err = obs[0] - tgt[0]
        return {"slope": 1.0, "intercept": round(intercept, 4), "mean_error": round(err, 4), "mae": abs(round(err, 4))}
    obs_mean = sum(obs) / len(obs)
    tgt_mean = sum(tgt) / len(tgt)
    var_obs = sum((x - obs_mean) ** 2 for x in obs)
    if var_obs <= 0:
        slope = 1.0
    else:
        cov = sum((x - obs_mean) * (y - tgt_mean) for x, y in pairs)
        slope = cov / var_obs
    slope = max(0.7, min(1.3, slope))
    intercept = tgt_mean - (slope * obs_mean)
    adjusted = [(slope * x) + intercept for x in obs]
    errors = [a - y for a, y in zip(adjusted, tgt)]
    raw_errors = [x - y for x, y in pairs]
    mae = sum(abs(e) for e in errors) / len(errors)
    mean_error = sum(errors) / len(errors)
    mean_error_raw = sum(raw_errors) / len(raw_errors)
    return {
        "slope": round(slope, 4),
        "intercept": round(intercept, 4),
        "mean_error": round(mean_error, 4),
        "mean_error_raw": round(mean_error_raw, 4),
        "mae": round(mae, 4),
    }


def _interpolate(points: list[dict], value: float) -> float:
    if not points:
        return float(value)
    ordered = sorted([(float(p["x"]), float(p["y"])) for p in points], key=lambda it: it[0])
    dedup = []
    for x0, y0 in ordered:
        if dedup and x0 == dedup[-1][0]:
            dedup[-1] = (x0, y0)
        else:
            dedup.append((x0, y0))
    ordered = dedup
    x = float(value)
    xs = [pt[0] for pt in ordered]
    idx = bisect.bisect_left(xs, x)
    if idx <= 0:
        return ordered[0][1]
    if idx >= len(ordered):
        return ordered[-1][1]
    x0, y0 = ordered[idx - 1]
    x1, y1 = ordered[idx]
    return y0 + ((x - x0) / (x1 - x0)) * (y1 - y0)


def build_map_points(pairs: list[tuple[float, float]], max_points: int = 7) -> list[dict]:
    if not pairs:
        return []
    observed = sorted(float(obs) for obs, _ in pairs)
    targets = sorted(float(tgt) for _, tgt in pairs)
    buckets = {}
    for idx, obs in enumerate(observed):
        buckets.setdefault(round(obs, 2), []).append(targets[idx])
    points = [{"x": x, "y": sum(vals) / len(vals)} for x, vals in sorted(buckets.items(), key=lambda it: it[0])]
    if len(points) <= max_points:
        return [{"x": round(p["x"], 2), "y": round(p["y"], 2)} for p in points]
    sampled = []
    for i in range(max_points):
        pos = round(i * (len(points) - 1) / (max_points - 1))
        sampled.append(points[pos])
    return [{"x": round(p["x"], 2), "y": round(p["y"], 2)} for p in sampled]


def _order_metrics(predicted: list[float], target: list[float], names: list[str]) -> tuple[float, float]:
    if not predicted or len(predicted) <= 1:
        return 1.0, 1.0
    tgt_order = sorted(range(len(target)), key=lambda i: (-target[i], names[i].lower()))
    pred_order = sorted(range(len(predicted)), key=lambda i: (-predicted[i], names[i].lower()))
    tgt_pos = {idx: pos for pos, idx in enumerate(tgt_order)}
    pred_pos = {idx: pos for pos, idx in enumerate(pred_order)}
    n = len(predicted)
    mean_pos_delta = sum(abs(tgt_pos[i] - pred_pos[i]) for i in range(n)) / n
    pos_hit = 1.0 - (mean_pos_delta / max(1, n - 1))
    agree = 0
    total = 0
    for i in range(n):
        for j in range(i + 1, n):
            t_sign = math.copysign(1, target[i] - target[j]) if target[i] != target[j] else 0
            p_sign = math.copysign(1, predicted[i] - predicted[j]) if predicted[i] != predicted[j] else 0
            agree += int(t_sign == p_sign)
            total += 1
    pairwise = (agree / total) if total else 1.0
    return round(pos_hit, 4), round(pairwise, 4)


def _stdev(values: list[float]) -> float:
    if not values:
        return 0.0
    m = sum(values) / len(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


def _repeat_rank_metrics(entries: list[dict]) -> tuple[float, float, float]:
    grouped = {}
    repeats = set()
    for item in entries:
        grouped.setdefault(item["name"], []).append(item)
        repeats.add(int(item.get("repeat_index", 0) or 0))
    if len(grouped) <= 1 or len(repeats) <= 1:
        return 0.0, 0.0, 0.0
    target_scores = {name: float(items[0]["target"]) for name, items in grouped.items()}
    boundary_names = {
        name
        for name, items in grouped.items()
        if bool(items[0].get("boundary_flag")) or is_boundary_score(items[0].get("target"))
    }
    rank_positions = {name: [] for name in grouped}
    boundary_disagreements = 0
    boundary_pairs = 0
    total_disagreements = 0
    ordered_names = sorted(grouped)
    for repeat_index in sorted(repeats):
        observed = {}
        for name, items in grouped.items():
            repeat_items = [entry for entry in items if int(entry.get("repeat_index", 0) or 0) == repeat_index]
            series = repeat_items or items
            observed[name] = sum(float(entry["observed"]) for entry in series) / len(series)
        run_order = sorted(ordered_names, key=lambda name: (-observed[name], name.lower()))
        positions = {name: idx for idx, name in enumerate(run_order)}
        for name in ordered_names:
            rank_positions[name].append(float(positions[name]))
        for i, first in enumerate(ordered_names):
            for second in ordered_names[i + 1:]:
                tgt_sign = math.copysign(1, target_scores[first] - target_scores[second]) if target_scores[first] != target_scores[second] else 0
                obs_sign = math.copysign(1, observed[first] - observed[second]) if observed[first] != observed[second] else 0
                disagree = int(tgt_sign != obs_sign)
                near_boundary = first in boundary_names or second in boundary_names
                if near_boundary:
                    boundary_pairs += 1
                    boundary_disagreements += disagree
                total_disagreements += disagree
    rank_stability_sd = sum(_stdev(values) for values in rank_positions.values()) / len(rank_positions)
    boundary_disagreement_rate = (boundary_disagreements / boundary_pairs) if boundary_pairs else 0.0
    boundary_disagreement_concentration = (boundary_disagreements / total_disagreements) if total_disagreements else 0.0
    return round(rank_stability_sd, 4), round(boundary_disagreement_rate, 4), round(boundary_disagreement_concentration, 4)


def _collapse_entries(entries: list[dict]) -> tuple[list[dict], float, float]:
    grouped = {}
    for item in entries:
        grouped.setdefault(item["name"], []).append(item)
    collapsed = []
    stability = []
    repeat_consistency = []
    for name, items in grouped.items():
        observed = [float(it["observed"]) for it in items]
        target = float(items[0]["target"])
        level = items[0]["target_level"]
        collapsed.append(
            {
                "name": name,
                "observed": sum(observed) / len(observed),
                "target": target,
                "target_level": level,
                "boundary_flag": bool(items[0].get("boundary_flag")) or is_boundary_score(target),
            }
        )
        stability.append(_stdev(observed))
        repeat_levels = [normalize_level(v) for v in observed]
        if repeat_levels:  # pragma: no branch - observed is never empty for a grouped sample
            mode_level = max(set(repeat_levels), key=repeat_levels.count)
            agree = sum(1 for lv in repeat_levels if lv == mode_level) / len(repeat_levels)
            repeat_consistency.append(agree)
    avg_stability = (sum(stability) / len(stability)) if stability else 0.0
    avg_repeat_consistency = (sum(repeat_consistency) / len(repeat_consistency)) if repeat_consistency else 1.0
    return collapsed, avg_stability, avg_repeat_consistency


def compute_profile(entries: list[dict]) -> dict:
    if not entries:
        return {
            "samples": 0,
            "observations": 0,
            "slope": 1.0,
            "intercept": 0.0,
            "bias": 0.0,
            "mae": 0.0,
            "boundary_mae": 0.0,
            "boundary_samples": 0,
            "weight": 1.0,
            "rank_stability_sd": 0.0,
            "boundary_pairwise_disagreement": 0.0,
            "boundary_pairwise_disagreement_concentration": 0.0,
        }
    collapsed, stability_sd, repeat_consistency = _collapse_entries(entries)
    pairs = [(float(e["observed"]), float(e["target"])) for e in collapsed]
    names = [e["name"] for e in collapsed]
    points = build_map_points(pairs)
    corrected = [_interpolate(points, float(e["observed"])) if points else float(e["observed"]) for e in collapsed]
    target = [float(e["target"]) for e in collapsed]
    raw_mae = sum(abs(o - t) for o, t in pairs) / len(pairs)
    corr_mae = sum(abs(c - t) for c, t in zip(corrected, target)) / len(collapsed)
    boundary_errors = [
        abs(c - t)
        for c, t, item in zip(corrected, target, collapsed)
        if bool(item.get("boundary_flag"))
    ]
    level_hits = 0
    for value, item in zip(corrected, collapsed):
        if normalize_level(value) == normalize_level(item["target_level"]):
            level_hits += 1
    level_hit_rate = level_hits / len(collapsed)
    pos_hit, pairwise = _order_metrics(corrected, target, names)
    rank_stability_sd, boundary_pairwise_disagreement, boundary_pairwise_concentration = _repeat_rank_metrics(entries)
    reliability = (
        (0.40 * level_hit_rate)
        + (0.30 * pairwise)
        + (0.15 * pos_hit)
        + (0.15 * repeat_consistency)
    )
    penalty = min(0.45, corr_mae / 25.0) + min(0.20, stability_sd / 10.0)
    weight = max(0.45, min(1.25, 0.75 + reliability - penalty))
    affine = fit_affine_correction(pairs)
    raw_bias = sum(o - t for o, t in pairs) / len(pairs)
    corrected_bias = sum(c - t for c, t in zip(corrected, target)) / len(collapsed)
    return {
        "samples": len(collapsed),
        "observations": len(entries),
        "map_points": points,
        "slope": 1.0 if points else affine["slope"],
        "intercept": 0.0 if points else affine["intercept"],
        "bias": round(corrected_bias if points else affine["mean_error"], 4),
        "bias_raw": round(raw_bias, 4),
        "mae_raw": round(raw_mae, 4),
        "mae": round(corr_mae if points else affine["mae"], 4),
        "boundary_mae": round((sum(boundary_errors) / len(boundary_errors)) if boundary_errors else 0.0, 4),
        "boundary_samples": len(boundary_errors),
        "level_hit_rate": round(level_hit_rate, 4),
        "order_position_hit_rate": pos_hit,
        "pairwise_order_agreement": pairwise,
        "stability_sd": round(stability_sd, 4),
        "rank_stability_sd": rank_stability_sd,
        "boundary_pairwise_disagreement": boundary_pairwise_disagreement,
        "boundary_pairwise_disagreement_concentration": boundary_pairwise_concentration,
        "repeat_level_consistency": round(repeat_consistency, 4),
        "weight": round(weight, 4),
    }


def _coverage_scope_for_manifest(scope_name: str, model_version: str) -> dict:
    parts = scope_name.split("|", 1)
    grade_band = parts[0].strip() if parts else ""
    genre = normalize_genre(parts[1]) if len(parts) > 1 else ""
    model_family = model_version.split("@", 1)[0] if model_version else ""
    scope_id_parts = [grade_band, genre, model_family]
    return {
        "key": scope_name,
        "grade_band": grade_band,
        "genre": genre,
        # The built-in exemplar bank is grade/genre scoped and intentionally rubric-agnostic.
        # Leave rubric_family empty so run-time scope checks can accept rubric-specific runs
        # that are still covered by the shared calibration bank for this model family.
        "rubric_family": "",
        "model_family": model_family,
        "model_version": model_version,
        "scope_id": "|".join(part for part in scope_id_parts if part),
    }


def build_records(args, calibration, routing, rubric, outline, profiles, criteria_cfg, points_possible, assessors):
    pass1_model = routing["tasks"]["pass1_assessor"]["model"]
    pass1_reasoning = routing["tasks"]["pass1_assessor"].get("reasoning", "medium")
    records = []
    repeats = max(1, int(args.repeats))
    for band, genre, sample in iter_gold_samples(calibration):
        genre_norm = normalize_genre(genre)
        criteria_block = criteria_prompt(criteria_cfg, genre_norm) if criteria_cfg else ""
        reqs = evidence_requirements(criteria_cfg, genre_norm) if criteria_cfg else {}
        if reqs:
            reqs = dict(reqs)
            reqs["quote_validation"] = False
            reqs["rationale_min_words"] = 0
        required_ids = criteria_ids(criteria_cfg, genre_norm) if criteria_cfg else []
        grade_level = BAND_GRADE_LEVEL.get(band)
        grade_context = build_grade_context(grade_level, profiles)
        exemplars_dir = Path(args.exemplars) / band / genre_norm
        essay_path = exemplars_dir / sample["file"]
        if not essay_path.exists():
            continue
        essay = load_file_text(essay_path)
        exemplar_set = load_exemplars(exemplars_dir, exclude_files={essay_path.name})
        exemplar_block = format_exemplars(exemplar_set)
        for assessor in assessors:
            prompt = build_pass1_prompt(
                assessor, rubric, outline, essay_path.stem, essay, grade_context, exemplar_block, criteria_block, reqs
            )
            for repeat_index in range(repeats):
                try:
                    response = responses_create(
                        model=pass1_model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.0,
                        reasoning=pass1_reasoning,
                        routing_path=args.routing,
                        text_format=pass1_text_format(),
                    )
                    content = extract_text(response)
                    item = parse_pass1_item(content, essay_path.stem, required_ids, reqs, essay, strict=False)
                except Exception:
                    item = deterministic_pass1_item(essay_path.stem, essay, assessor, required_ids, exemplar_set)
                observed = score_to_percent(float(item["rubric_total_points"]), points_possible)
                records.append(
                    {
                        "assessor_id": f"assessor_{assessor}",
                        "scope": scope_key(band, genre_norm or genre),
                        "name": f"{band}/{genre_norm}/{sample['file']}",
                        "target": float(sample["target_pct"]),
                        "target_level": sample.get("target_level") or normalize_level(sample.get("target_pct")),
                        "boundary_flag": bool(sample.get("boundary_flag")) or is_boundary_score(sample.get("target_pct")),
                        "repeat_index": repeat_index,
                        "observed": float(observed),
                    }
                )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate assessors using a gold exemplar set")
    parser.add_argument("--calibration", default="config/calibration_set.json", help="Calibration set JSON")
    parser.add_argument("--exemplars", default="inputs/exemplars", help="Exemplars root")
    parser.add_argument("--rubric", default="inputs/rubric.md", help="Rubric file")
    parser.add_argument("--outline", default="inputs/assignment_outline.md", help="Assignment outline file")
    parser.add_argument("--routing", default="config/llm_routing.json", help="Routing config")
    parser.add_argument("--assessors", default="A,B,C", help="Assessor IDs")
    parser.add_argument("--grade-profiles", default="config/grade_level_profiles.json", help="Grade profiles")
    parser.add_argument("--rubric-criteria", default="config/rubric_criteria.json", help="Rubric criteria JSON")
    parser.add_argument("--normalized-rubric", default="outputs/normalized_rubric.json", help="Normalized rubric contract JSON")
    parser.add_argument("--rubric-manifest", default="outputs/rubric_manifest.json", help="Rubric manifest JSON")
    parser.add_argument("--rubric-verification", default="outputs/rubric_verification.json", help="Rubric verification JSON")
    parser.add_argument("--output", default="outputs/calibration_bias.json", help="Bias output")
    parser.add_argument("--manifest-output", default="", help="Optional calibration manifest output")
    parser.add_argument("--freshness-window-hours", type=float, default=0.0, help="Override calibration freshness window")
    parser.add_argument("--repeats", type=int, default=1, help="Calibration repeats per exemplar/assessor")
    args = parser.parse_args()

    calibration = load_json(Path(args.calibration))
    cfg_repeats = calibration.get("bias_correction", {}).get("repeats")
    if args.repeats == 1 and isinstance(cfg_repeats, int) and cfg_repeats > 1:
        args.repeats = cfg_repeats
    rubric_path = resolve_input_path(Path(args.rubric), "rubric")
    rubric_context = runtime_rubric_context(
        rubric_path,
        normalized_path=Path(args.normalized_rubric),
        verification_path=Path(args.rubric_verification),
    )
    rubric = rubric_context["rubric_text"]
    outline = load_file_text(resolve_input_path(Path(args.outline), "assignment_outline"))
    if not rubric.strip():
        print(f"Rubric text is empty. Check file at {args.rubric}.")
        return 1
    profiles = load_grade_profiles(Path(args.grade_profiles))
    criteria_cfg = load_rubric_criteria(Path(args.rubric_criteria))
    points_possible = total_points(criteria_cfg) if criteria_cfg else None
    assessors = [a.strip() for a in args.assessors.split(",") if a.strip()]
    routing = load_json(Path(args.routing))
    rubric_manifest = load_rubric_json(Path(args.rubric_manifest))
    run_scope_template = build_run_scope(
        metadata={"grade_level": BAND_GRADE_LEVEL.get("grade_8_10", 9), "genre": "literary_analysis"},
        routing=routing,
        rubric_path=rubric_path,
        rubric_manifest=rubric_manifest,
    )

    records = build_records(args, calibration, routing, rubric, outline, profiles, criteria_cfg, points_possible, assessors)
    grouped = {}
    for record in records:
        grouped.setdefault(record["assessor_id"], []).append(record)

    scope_prior = float(calibration.get("bias_correction", {}).get("scope_prior", 12.0) or 12.0)
    assessors_payload = {}
    summary = {"samples": len(records), "assessors": len(grouped), "scope_coverage": {}}
    for assessor_id, items in grouped.items():
        global_profile = compute_profile(items)
        global_profile["scope_prior"] = scope_prior
        scopes = {}
        for key in sorted({i["scope"] for i in items}):
            scope_items = [i for i in items if i["scope"] == key]
            scope_profile = compute_profile(scope_items)
            scope_profile["scope_prior"] = scope_prior
            scopes[key] = scope_profile
            summary["scope_coverage"][key] = summary["scope_coverage"].get(key, 0) + len(scope_items)
        assessors_payload[assessor_id] = {"global": global_profile, "scopes": scopes}

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "method": calibration.get("bias_correction", {}).get("method", "piecewise_monotonic"),
        "synthetic": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope_template": "<grade_band>|<genre>",
        "assessors": assessors_payload,
        "summary": summary,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    manifest_path = Path(args.manifest_output) if args.manifest_output else calibration_manifest_path(out_path)
    scope_coverage = []
    model_version = routing["tasks"]["pass1_assessor"]["model"]
    for scope_name, sample_count in sorted(summary["scope_coverage"].items()):
        coverage_scope = build_scope_coverage_entry(
            _coverage_scope_for_manifest(scope_name, model_version),
            samples=int(sample_count or 0),
            observations=int(sample_count or 0),
            synthetic=False,
        )
        scope_coverage.append(coverage_scope)
    manifest = build_calibration_manifest(
        profile_type=str(payload["method"]),
        synthetic=False,
        scope_coverage=scope_coverage,
        routing=routing,
        routing_profile_hash=routing_profile_hash_from_payload(routing),
        model_version=routing["tasks"]["pass1_assessor"]["model"],
        rubric_path=None,
        rubric_hash=None,
        source_exemplar_set_hash_value=source_exemplar_set_hash(Path(args.calibration), Path(args.exemplars)),
        freshness_window_hours=args.freshness_window_hours or float((routing.get("calibration_gate", {}) or {}).get("max_age_hours", 168) or 168),
        generated_at=str(payload["generated_at"]),
        artifact_hashes={"calibration_bias_sha256": file_sha256(out_path)},
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Calibration saved to {out_path}")
    print(f"Calibration manifest saved to {manifest_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
