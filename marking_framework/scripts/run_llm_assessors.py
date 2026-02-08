#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.assessor_context import (
    build_grade_context, format_exemplars, grade_band_for_level, infer_genre_from_text, load_class_metadata,
    load_exemplars, load_grade_profiles, normalize_genre, resolve_exemplars_dir, select_grade_level,
)
from scripts.rubric_criteria import criteria_ids, criteria_prompt, evidence_requirements, load_rubric_criteria
from scripts.assessor_utils import extract_docx_text, load_file_text, normalize_ranking_ids, resolve_input_path, summarize_text
from scripts.llm_assessors_core import (
    build_pass1_prompt, build_pass1_repair_prompt, build_pass2_prompt, ensure_dir, json_from_text, load_json, load_routing,
    load_texts, looks_like_prompt_echo, parse_pass1_item, pass1_text_format, preflight_costs,
)
from scripts.fallback_assessor import deterministic_pass1_item
from scripts.calibration_gate import calibration_gate_error
from scripts.pass1_guard import stabilize_pass1_item
from scripts.pass2_contract import build_pass2_repair_prompt, normalize_full_ranking, pass2_text_format
try:
    from scripts.openai_client import responses_create, extract_text, extract_usage
except ImportError:  # pragma: no cover - Support running as a script without package context
    from openai_client import responses_create, extract_text, extract_usage  # pragma: no cover
def reset_assessor_outputs(path: Path):
    for file in path.glob("assessor_*"):
        if file.is_file():
            file.unlink()
def write_text_atomic(path: Path, content: str):
    tmp = path.with_suffix(path.suffix + ".tmp"); tmp.write_text(content, encoding="utf-8"); tmp.replace(path)
def ranking_from_scores(scores: dict, known_ids: list) -> list:
    ranked = [(sid, float(scores.get(sid, 0.0) or 0.0)) for sid in known_ids]
    ranked.sort(key=lambda item: (-item[1], item[0].lower()))
    return [sid for sid, _ in ranked]
def main() -> int:
    parser = argparse.ArgumentParser(description="Run LLM assessors for Pass 1 and Pass 2")
    parser.add_argument("--texts", default="processing/normalized_text", help="Normalized text directory")
    parser.add_argument("--rubric", default="inputs/rubric.md", help="Rubric file (md or txt)")
    parser.add_argument("--outline", default="inputs/assignment_outline.md", help="Assignment outline file")
    parser.add_argument("--routing", default="config/llm_routing.json", help="LLM routing config")
    parser.add_argument("--pass1-out", default="assessments/pass1_individual", help="Pass 1 output dir")
    parser.add_argument("--pass2-out", default="assessments/pass2_comparative", help="Pass 2 output dir")
    parser.add_argument("--max-summary-chars", type=int, default=800, help="Max chars for summaries in pass2")
    parser.add_argument("--assessors", default="A,B,C", help="Comma-separated assessor IDs")
    parser.add_argument("--cost-limits", default="config/cost_limits.json", help="Cost limits config")
    parser.add_argument("--pricing", default="config/pricing.json", help="Pricing config")
    parser.add_argument("--ignore-cost-limits", action="store_true", help="Skip cost limit checks")
    parser.add_argument("--grade-level", type=int, default=None, help="Grade level for expectations")
    parser.add_argument("--grade-profiles", default="config/grade_level_profiles.json", help="Grade profiles config")
    parser.add_argument("--class-metadata", default="inputs/class_metadata.json", help="Class metadata JSON")
    parser.add_argument("--exemplars", default="inputs/exemplars", help="Exemplars directory")
    parser.add_argument("--genre", default=None, help="Assignment genre for exemplar selection")
    parser.add_argument("--rubric-criteria", default="config/rubric_criteria.json", help="Rubric criteria JSON")
    parser.add_argument("--fallback", choices=["none", "deterministic"], default="deterministic", help="Fallback strategy when model output is invalid")
    parser.add_argument("--require-model-usage", action="store_true", help="Fail if no model outputs are accepted")
    args = parser.parse_args()
    routing = load_routing(Path(args.routing))
    mode = os.environ.get("LLM_MODE") or routing.get("mode", "openai")
    if mode != "codex_local" and not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. Aborting.")
        return 1
    pass1_model = routing["tasks"]["pass1_assessor"]["model"]
    pass1_reasoning = routing["tasks"]["pass1_assessor"].get("reasoning", "medium")
    pass1_temp = routing["tasks"]["pass1_assessor"].get("temperature", 0.2)
    pass1_max_tokens = routing["tasks"]["pass1_assessor"].get("max_output_tokens")
    pass2_model = routing["tasks"]["pass2_ranker"]["model"]
    pass2_reasoning = routing["tasks"]["pass2_ranker"].get("reasoning", "medium")
    pass2_temp = routing["tasks"]["pass2_ranker"].get("temperature", 0.2)
    pass2_max_tokens = routing["tasks"]["pass2_ranker"].get("max_output_tokens")
    guard_cfg = routing.get("pass1_guard", {})
    guard_enabled = bool(guard_cfg.get("enabled", False))
    guard_max_score_delta = float(guard_cfg.get("max_score_delta", 8.0) or 8.0)
    guard_max_level_gap = int(guard_cfg.get("max_level_gap", 1) or 1)
    guard_anchor_blend = float(guard_cfg.get("anchor_blend", 0.0) or 0.0)
    min_model_coverage = float(routing.get("quality_gates", {}).get("min_model_coverage", 0.0) or 0.0)
    texts = load_texts(Path(args.texts))
    rubric_path = resolve_input_path(Path(args.rubric), "rubric")
    outline_path = resolve_input_path(Path(args.outline), "assignment_outline")
    rubric = load_file_text(rubric_path)
    outline = load_file_text(outline_path)
    if not rubric.strip():
        print(f"Rubric text is empty. Check file at {rubric_path}.")
        return 1
    metadata = load_class_metadata(Path(args.class_metadata))
    profiles = load_grade_profiles(Path(args.grade_profiles))
    grade_level = select_grade_level(args.grade_level, metadata)
    grade_context = build_grade_context(grade_level, profiles)
    genre = args.genre or metadata.get("genre") or metadata.get("assignment_genre")
    if not genre:
        genre = infer_genre_from_text(rubric, outline)
    genre = normalize_genre(genre)
    base_exemplars = Path(args.exemplars)
    exemplars_dir = base_exemplars
    if str(args.exemplars) == "inputs/exemplars":
        exemplars_dir = resolve_exemplars_dir(base_exemplars, grade_level, genre)
    exemplars = load_exemplars(exemplars_dir)
    exemplar_block = format_exemplars(exemplars)
    criteria_cfg = load_rubric_criteria(Path(args.rubric_criteria))
    criteria_block = criteria_prompt(criteria_cfg, None) if criteria_cfg else ""
    required_ids = criteria_ids(criteria_cfg, None) if criteria_cfg else []
    reqs = evidence_requirements(criteria_cfg) if criteria_cfg else {}
    if reqs:
        reqs = dict(reqs)
        reqs["quote_validation"] = False
        reqs["rationale_min_words"] = 0
    assessors = [a.strip() for a in args.assessors.split(",") if a.strip()]
    scope = f"{grade_band_for_level(grade_level)}|{genre}" if grade_band_for_level(grade_level) and genre else ""
    gate_error = calibration_gate_error(routing, assessors, scope)
    if gate_error:
        print(gate_error)
        return 1
    ensure_dir(Path(args.pass1_out))
    ensure_dir(Path(args.pass2_out))
    reset_assessor_outputs(Path(args.pass1_out))
    reset_assessor_outputs(Path(args.pass2_out))
    usage_log = Path("outputs/usage_log.jsonl")
    usage_log.parent.mkdir(parents=True, exist_ok=True)
    failure_log = Path("logs/llm_failures.jsonl")
    failure_log.parent.mkdir(parents=True, exist_ok=True)
    summaries = [{"student_id": sid, "summary": summarize_text(text, args.max_summary_chars)} for sid, text in texts.items()]
    if mode != "codex_local" and not args.ignore_cost_limits:
        pricing = load_json(Path(args.pricing))
        limits = load_json(Path(args.cost_limits))
        preflight = preflight_costs(texts, rubric, outline, summaries, routing, pricing, limits, grade_context, exemplar_block)
        if not preflight.get("ok"):
            print(f"Cost preflight failed: {preflight.get('reason')}")
            if limits.get("abort_on_limit", True):
                return 1
        else:
            per_student_max = limits.get("per_student_max_usd", None)
            per_job_max = limits.get("per_job_max_usd", None)
            alert_at = limits.get("alert_at_percent", 80)
            per_student_cost = preflight.get("per_student_cost", 0.0)
            total_cost = preflight.get("total_cost", 0.0)
            print(f"Estimated cost: ${total_cost:.2f} total (~${per_student_cost:.2f}/student)")
            if per_student_max and per_student_cost > per_student_max:
                msg = f"Estimated per-student cost ${per_student_cost:.2f} exceeds limit ${per_student_max:.2f}"
                print(msg)
                if limits.get("abort_on_limit", True):
                    return 1
            if per_job_max and total_cost > per_job_max:
                msg = f"Estimated total cost ${total_cost:.2f} exceeds job limit ${per_job_max:.2f}"
                print(msg)
                if limits.get("abort_on_limit", True):
                    return 1
            if per_job_max and total_cost > (per_job_max * (alert_at / 100.0)):
                print(f"Warning: estimated total cost ${total_cost:.2f} is above {alert_at}% of job limit ${per_job_max:.2f}")
    pass1_scores_by_assessor = {}
    model_successes = 0
    model_attempts = 0
    for assessor in assessors:
        scores = []
        for student_id, text in texts.items():
            anchor_item = deterministic_pass1_item(student_id, text, assessor, required_ids, exemplars)
            prompt = build_pass1_prompt(
                assessor,
                rubric,
                outline,
                student_id,
                text,
                grade_context,
                exemplar_block,
                criteria_block,
                reqs,
            )
            item = None
            for attempt in range(3):
                try:
                    model_attempts += 1
                    response = responses_create(
                        model=pass1_model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=pass1_temp,
                        reasoning=pass1_reasoning,
                        routing_path=args.routing,
                        text_format=pass1_text_format(),
                        max_output_tokens=pass1_max_tokens,
                    )
                    content = extract_text(response)
                    usage = extract_usage(response)
                    with usage_log.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"task": "pass1", "assessor": assessor, "student_id": student_id, "usage": usage, "model": pass1_model}) + "\n")
                except Exception as exc:
                    content = f"[model_error] {exc}"
                try:
                    if mode == "codex_local" and looks_like_prompt_echo(content, student_id):
                        raise ValueError("Model returned prompt echo instead of scored JSON.")
                    item = parse_pass1_item(content, student_id, required_ids, reqs, text, strict=False)
                    if str(item.get("student_id", "")).strip() != student_id:
                        raise ValueError("Pass1 response student_id mismatch.")
                    score = item.get("rubric_total_points")
                    if not isinstance(score, (int, float)):
                        raise ValueError("Pass1 response missing numeric rubric_total_points.")
                    if guard_enabled:
                        item = stabilize_pass1_item(item, anchor_item, guard_max_score_delta, guard_max_level_gap, guard_anchor_blend)
                    model_successes += 1
                    break
                except ValueError as exc:
                    failure = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "task": "pass1",
                        "assessor": assessor,
                        "student_id": student_id,
                        "attempt": attempt + 1,
                        "mode": mode,
                        "error": str(exc),
                        "response_preview": content[:2000],
                    }
                    with failure_log.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(failure) + "\n")
                    prompt = build_pass1_repair_prompt(student_id, content, bool(required_ids))
            if item is None:
                if args.fallback == "deterministic":
                    item = anchor_item
                else:
                    raise ValueError(f"Pass1 response invalid after retry. See {failure_log}.")
            scores.append(item)
        pass1_scores_by_assessor[assessor] = {
            s["student_id"]: float(s.get("rubric_total_points", 0.0) or 0.0) for s in scores
        }
        pass1_payload = {
            "assessor_id": f"assessor_{assessor}",
            "role": "llm_assessor",
            "rubric_points_possible": None,
            "scores": scores,
        }
        out_path = Path(args.pass1_out) / f"assessor_{assessor}.json"
        write_text_atomic(out_path, json.dumps(pass1_payload, indent=2))
    student_summaries = summaries
    known_ids = list(texts.keys())
    for assessor in assessors:
        score_order = ranking_from_scores(pass1_scores_by_assessor.get(assessor, {}), known_ids)
        prompt = build_pass2_prompt(assessor, rubric, outline, student_summaries, grade_context)
        error = ""
        try:
            model_attempts += 1
            response = responses_create(
                model=pass2_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=pass2_temp,
                reasoning=pass2_reasoning,
                routing_path=args.routing,
                text_format=pass2_text_format(),
                max_output_tokens=pass2_max_tokens,
            )
            content = extract_text(response)
            usage = extract_usage(response)
            with usage_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"task": "pass2", "assessor": assessor, "usage": usage, "model": pass2_model}) + "\n")
            try:
                lines, missing = normalize_full_ranking(content, known_ids)
                if not missing:
                    model_successes += 1
            except ValueError as exc:
                lines = []
                missing = known_ids
                error = str(exc)
        except Exception as exc:
            content = f"[model_error] {exc}"
            lines = []
            missing = known_ids
            error = str(exc)
        if error or missing:
            repair_prompt = build_pass2_repair_prompt(known_ids, content, missing)
            try:
                response = responses_create(
                    model=pass2_model,
                    messages=[{"role": "user", "content": repair_prompt}],
                    temperature=0.0,
                    reasoning=pass2_reasoning,
                    routing_path=args.routing,
                    text_format=pass2_text_format(),
                    max_output_tokens=pass2_max_tokens,
                )
                repair_content = extract_text(response)
                try:
                    lines, missing = normalize_full_ranking(repair_content, known_ids)
                    error = ""
                    if not missing:
                        model_successes += 1
                except ValueError as exc:
                    error = str(exc)
                    lines = list(score_order)
                    missing = []
            except Exception as exc:
                repair_content = f"[model_error] {exc}"
                error = str(exc)
                lines = list(score_order)
                missing = []
            if missing:
                for sid in score_order:
                    if sid not in missing:
                        continue
                    lines.append(sid)
            if error or missing:
                failure = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "task": "pass2",
                    "assessor": assessor,
                    "mode": mode,
                    "error": error or f"Missing ids after retry: {missing}",
                    "response_preview": content[:2000],
                    "response_repair_preview": repair_content[:2000],
                }
                with failure_log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(failure) + "\n")
        if not lines:
            lines = list(score_order)
        out_path = Path(args.pass2_out) / f"assessor_{assessor}.txt"
        write_text_atomic(out_path, "\n".join(lines))
    if mode == "openai":
        print(f"Model coverage: {model_successes}/{model_attempts} successful structured outputs.")
        coverage = (model_successes / model_attempts) if model_attempts else 0.0
        if min_model_coverage > 0 and coverage < min_model_coverage:
            print(f"Model coverage {coverage:.2%} below gate {min_model_coverage:.2%}. Failing run.")
            return 1
        if args.require_model_usage and model_successes == 0:
            print("No model outputs were accepted; failing because --require-model-usage is set.")
            return 1
    print("LLM assessor runs completed.")
    return 0
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
