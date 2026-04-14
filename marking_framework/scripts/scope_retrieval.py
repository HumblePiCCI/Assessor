#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.calibration_contract import build_run_scope
    from scripts.local_teacher_prior import scope_matches
    from scripts.rubric_contract import load_json as load_rubric_json
    from scripts.assessor_context import load_class_metadata
except ImportError:  # pragma: no cover
    from calibration_contract import build_run_scope  # pragma: no cover
    from local_teacher_prior import scope_matches  # pragma: no cover
    from rubric_contract import load_json as load_rubric_json  # pragma: no cover
    from assessor_context import load_class_metadata  # pragma: no cover


DEFAULT_ACCEPTANCE_THRESHOLD = 0.72
DEFAULT_COMMITTEE_THRESHOLD = 0.55


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


def _safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _current_scope(metadata_path: Path, routing_path: Path, rubric_path: Path, rubric_manifest_path: Path) -> dict:
    metadata = load_class_metadata(metadata_path)
    routing = load_json(routing_path)
    rubric_manifest = load_rubric_json(rubric_manifest_path)
    return build_run_scope(
        metadata=metadata,
        routing=routing if isinstance(routing, dict) else {},
        rubric_path=rubric_path,
        rubric_manifest=rubric_manifest if isinstance(rubric_manifest, dict) else {},
    )


def _criteria_names(normalized_rubric: dict) -> set[str]:
    criteria = normalized_rubric.get("criteria", []) if isinstance(normalized_rubric, dict) else []
    names = set()
    for entry in criteria if isinstance(criteria, list) else []:
        if not isinstance(entry, dict):
            continue
        token = str(entry.get("name", "") or entry.get("criterion", "") or "").strip().lower()
        if token:
            names.add(token)
    return names


def _scope_match_score(current: dict, candidate: dict, *, criteria_overlap: float = 0.0) -> float:
    score = 0.0
    for field, weight in (("grade_band", 0.4), ("genre", 0.35), ("rubric_family", 0.15), ("model_family", 0.10)):
        left = str((current or {}).get(field, "") or "").strip().lower()
        right = str((candidate or {}).get(field, "") or "").strip().lower()
        if not left or not right:
            continue
        if left == right:
            score += weight
    if criteria_overlap > 0.0:
        score += min(0.1, float(criteria_overlap) * 0.1)
    return round(min(1.0, score), 6)


def _find_exemplar_hits(exemplars_root: Path, current_scope: dict) -> list[dict]:
    hits = []
    if not exemplars_root.exists():
        return hits
    current_grade = str(current_scope.get("grade_band", "") or "").strip().lower()
    current_genre = str(current_scope.get("genre", "") or "").strip().lower()
    for grade_dir in sorted(exemplars_root.iterdir()) if exemplars_root.exists() else []:
        if not grade_dir.is_dir():
            continue
        for genre_dir in sorted(grade_dir.iterdir()):
            if not genre_dir.is_dir():
                continue
            file_count = len(sorted(genre_dir.glob("*")))
            candidate_scope = {
                "grade_band": grade_dir.name,
                "genre": genre_dir.name,
                "rubric_family": "",
                "model_family": str(current_scope.get("model_family", "") or ""),
            }
            confidence = _scope_match_score(current_scope, candidate_scope)
            if grade_dir.name.lower() == current_grade and genre_dir.name.lower() == current_genre:
                confidence = round(min(1.0, confidence + min(0.15, file_count * 0.02)), 6)
            hits.append(
                {
                    "type": "exemplar_family",
                    "scope_id": f"{grade_dir.name}|{genre_dir.name}",
                    "path": str(genre_dir),
                    "confidence": confidence,
                    "distance": round(1.0 - confidence, 6),
                    "support_count": file_count,
                    "candidate_scope": candidate_scope,
                }
            )
    return sorted(hits, key=lambda item: (-item["confidence"], -item["support_count"], item["scope_id"]))


def _find_calibrated_hits(calibration_manifest: dict, current_scope: dict, criteria_overlap: float) -> list[dict]:
    hits = []
    coverage = calibration_manifest.get("scope_coverage", []) if isinstance(calibration_manifest, dict) else []
    for entry in coverage if isinstance(coverage, list) else []:
        if not isinstance(entry, dict):
            continue
        candidate_scope = {
            "grade_band": entry.get("grade_band", ""),
            "genre": entry.get("genre", ""),
            "rubric_family": entry.get("rubric_family", ""),
            "model_family": entry.get("model_family", ""),
        }
        confidence = _scope_match_score(current_scope, candidate_scope, criteria_overlap=criteria_overlap)
        samples = int(_safe_float(entry.get("samples"), 0.0))
        observations = int(_safe_float(entry.get("observations"), 0.0))
        confidence = round(min(1.0, confidence + min(0.1, observations / 100.0)), 6)
        hits.append(
            {
                "type": "calibrated_cohort",
                "scope_id": str(entry.get("key", "") or ""),
                "path": "",
                "confidence": confidence,
                "distance": round(1.0 - confidence, 6),
                "support_count": max(samples, observations),
                "candidate_scope": candidate_scope,
                "profile_type": str(calibration_manifest.get("profile_type", "") or ""),
                "synthetic": bool(calibration_manifest.get("synthetic", False)),
            }
        )
    return sorted(hits, key=lambda item: (-item["confidence"], -item["support_count"], item["scope_id"]))


def _find_teacher_hits(local_prior: dict, current_scope: dict) -> list[dict]:
    if not isinstance(local_prior, dict) or not local_prior:
        return []
    prior_scope = local_prior.get("run_scope", {}) if isinstance(local_prior.get("run_scope", {}), dict) else {}
    if not prior_scope:
        return []
    confidence = _scope_match_score(current_scope, prior_scope)
    if scope_matches(prior_scope, current_scope):
        confidence = round(min(1.0, confidence + 0.1), 6)
    return [
        {
            "type": "teacher_prior",
            "scope_id": str(local_prior.get("scope_id", "") or prior_scope.get("scope_id", "") or ""),
            "path": "",
            "confidence": confidence,
            "distance": round(1.0 - confidence, 6),
            "support_count": int(_safe_float(local_prior.get("support", {}).get("finalized_review_count"), 0.0)),
            "candidate_scope": prior_scope,
            "active": bool(local_prior.get("active", False)),
        }
    ]


def _cost_headroom(cost_limits: dict) -> float:
    return max(0.0, _safe_float(cost_limits.get("per_student_max_usd"), 0.25))


def build_scope_grounding(
    *,
    metadata_path: Path,
    routing_path: Path,
    rubric_path: Path,
    rubric_manifest_path: Path,
    normalized_rubric_path: Path,
    exemplars_root: Path,
    calibration_manifest_path: Path,
    local_prior_path: Path,
    cost_limits_path: Path,
) -> dict:
    current_scope = _current_scope(metadata_path, routing_path, rubric_path, rubric_manifest_path)
    normalized_rubric = load_rubric_json(normalized_rubric_path)
    calibration_manifest = load_json(calibration_manifest_path)
    local_prior = load_json(local_prior_path)
    cost_limits = load_json(cost_limits_path)

    criteria_overlap = 0.0
    criteria_names = _criteria_names(normalized_rubric if isinstance(normalized_rubric, dict) else {})
    if criteria_names:
        criteria_overlap = min(1.0, len(criteria_names) / 10.0)

    exemplar_hits = _find_exemplar_hits(exemplars_root, current_scope)
    calibrated_hits = _find_calibrated_hits(calibration_manifest if isinstance(calibration_manifest, dict) else {}, current_scope, criteria_overlap)
    teacher_hits = _find_teacher_hits(local_prior if isinstance(local_prior, dict) else {}, current_scope)
    hits = sorted(exemplar_hits + calibrated_hits + teacher_hits, key=lambda item: (-item["confidence"], -item["support_count"], item["type"]))

    best_hit = hits[0] if hits else {}
    calibrated_support = sum(1 for item in calibrated_hits if item.get("confidence", 0.0) >= DEFAULT_ACCEPTANCE_THRESHOLD)
    exemplar_support = sum(1 for item in exemplar_hits if item.get("confidence", 0.0) >= DEFAULT_ACCEPTANCE_THRESHOLD)
    teacher_support = sum(1 for item in teacher_hits if item.get("confidence", 0.0) >= DEFAULT_ACCEPTANCE_THRESHOLD and item.get("active"))
    synthetic_only = bool(calibration_manifest.get("synthetic", False)) if isinstance(calibration_manifest, dict) else False
    rubric_family = str(current_scope.get("rubric_family", "") or "").strip().lower()
    accepted = bool(
        best_hit
        and best_hit.get("confidence", 0.0) >= DEFAULT_ACCEPTANCE_THRESHOLD
        and (calibrated_support >= 2 or exemplar_support >= 3 or teacher_support >= 1)
    )
    fallback_reason = ""
    if not hits:
        fallback_reason = "no_grounding_hits"
    elif best_hit.get("confidence", 0.0) < DEFAULT_ACCEPTANCE_THRESHOLD:
        fallback_reason = "best_hit_below_threshold"
    elif not (calibrated_support >= 2 or exemplar_support >= 3 or teacher_support >= 1):
        fallback_reason = "insufficient_family_support"

    if accepted:
        familiarity = "familiar"
    elif hits:
        familiarity = "sparse"
    else:
        familiarity = "novel"
    if synthetic_only and not accepted:
        familiarity = "novel"

    suggested_scope = dict(current_scope)
    if accepted and rubric_family in {"", "rubric_unknown"}:
        candidate_scope = best_hit.get("candidate_scope", {}) if isinstance(best_hit.get("candidate_scope", {}), dict) else {}
        suggested_family = str(candidate_scope.get("rubric_family", "") or "").strip()
        if suggested_family:
            suggested_scope["rubric_family"] = suggested_family

    committee_recommended = bool(
        familiarity != "familiar"
        and best_hit.get("confidence", 0.0) >= DEFAULT_COMMITTEE_THRESHOLD
        and _cost_headroom(cost_limits if isinstance(cost_limits, dict) else {}) >= 0.08
    )
    retrieval_prompt = ""
    if best_hit:
        retrieval_prompt = (
            f"Nearest grounded family: {best_hit.get('scope_id') or best_hit.get('path')}. "
            f"Confidence {best_hit.get('confidence', 0.0):.2f}. "
            f"Use this only as calibration context; do not override the rubric contract."
        )

    payload = {
        "generated_at": now_iso(),
        "resolved_scope": current_scope,
        "suggested_scope": suggested_scope,
        "retrieval_hits": hits[:12],
        "accepted": accepted,
        "match_confidence": float(best_hit.get("confidence", 0.0) or 0.0),
        "familiarity_label": familiarity,
        "fallback_used": not accepted,
        "fallback_reason": fallback_reason,
        "committee_mode_recommended": committee_recommended,
        "retrieval_prompt": retrieval_prompt,
        "support": {
            "calibrated_scope_hits": calibrated_support,
            "exemplar_family_hits": exemplar_support,
            "teacher_prior_hits": teacher_support,
            "synthetic_only": synthetic_only,
            "criteria_overlap": round(criteria_overlap, 6),
            "budget_headroom_usd": round(_cost_headroom(cost_limits if isinstance(cost_limits, dict) else {}), 6),
        },
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic retrieval-backed scope grounding for a live cohort.")
    parser.add_argument("--class-metadata", default="inputs/class_metadata.json")
    parser.add_argument("--routing", default="config/llm_routing.json")
    parser.add_argument("--rubric", default="inputs/rubric.md")
    parser.add_argument("--rubric-manifest", default="outputs/rubric_manifest.json")
    parser.add_argument("--normalized-rubric", default="outputs/normalized_rubric.json")
    parser.add_argument("--exemplars", default="inputs/exemplars")
    parser.add_argument("--calibration-manifest", default="outputs/calibration_manifest.json")
    parser.add_argument("--local-prior", default="outputs/local_teacher_prior.json")
    parser.add_argument("--cost-limits", default="config/cost_limits.json")
    parser.add_argument("--output", default="outputs/scope_grounding.json")
    args = parser.parse_args()

    payload = build_scope_grounding(
        metadata_path=Path(args.class_metadata),
        routing_path=Path(args.routing),
        rubric_path=Path(args.rubric),
        rubric_manifest_path=Path(args.rubric_manifest),
        normalized_rubric_path=Path(args.normalized_rubric),
        exemplars_root=Path(args.exemplars),
        calibration_manifest_path=Path(args.calibration_manifest),
        local_prior_path=Path(args.local_prior),
        cost_limits_path=Path(args.cost_limits),
    )
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote scope grounding to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
