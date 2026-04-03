import json
import re
from pathlib import Path

from scripts.levels import coerce_level_and_score_to_percent, score_to_percent
from scripts.pass1_normalize import canonical_criterion_id, criterion_lookup, rescue_pass1_item

def load_texts(text_dir: Path) -> dict:
    texts = {}
    for path in sorted(text_dir.glob("*.txt")):
        texts[path.stem.strip()] = path.read_text(encoding="utf-8", errors="ignore")
    return texts


def load_routing(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def estimate_cost(input_tokens: int, output_tokens: int, model: str, pricing: dict) -> float:
    model_prices = pricing.get("models", {}).get(model, {})
    input_rate = model_prices.get("input_per_million", 0.0)
    output_rate = model_prices.get("output_per_million", 0.0)
    return (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate


def preflight_costs(
    texts,
    rubric,
    outline,
    summaries,
    routing,
    pricing,
    limits,
    grade_context="",
    exemplars="",
    student_count_override: int | None = None,
):
    pass1_model = routing["tasks"]["pass1_assessor"]["model"]
    pass2_model = routing["tasks"]["pass2_ranker"]["model"]
    pass1_out_est = limits.get("estimates", {}).get("pass1_output_tokens", 300)
    pass2_out_est = limits.get("estimates", {}).get("pass2_output_tokens", 200)
    context_block = ""
    if grade_context:
        context_block += grade_context.strip() + "\n\n"
    if exemplars:
        context_block += exemplars.strip() + "\n\n"
    base_prompt = "You are Assessor. Score this student using the rubric."
    pass1_input_tokens = 0
    pass1_per_student_costs = {}
    max_call_tokens = limits.get("per_call_max_tokens", 8000)
    for student_id, text in texts.items():
        prompt = f"{base_prompt}\n{context_block}Rubric:\n{rubric}\nAssignment Outline:\n{outline}\nStudent ID: {student_id}\nEssay:\n{text}\n"
        input_tokens = estimate_tokens(prompt)
        total_tokens = input_tokens + pass1_out_est
        if total_tokens > max_call_tokens:
            return {
                "ok": False,
                "reason": f"Pass1 call exceeds per_call_max_tokens ({total_tokens} > {max_call_tokens}). Reduce essay size or raise limit."
            }
        pass1_input_tokens += input_tokens
        pass1_per_student_costs[student_id] = estimate_cost(input_tokens, pass1_out_est, pass1_model, pricing)
    summary_block = "\n".join([f"- {s['student_id']}: {s['summary']}" for s in summaries])
    pass2_prompt = f"Rank students best to worst.\n{grade_context}\nRubric:\n{rubric}\nAssignment Outline:\n{outline}\nStudent summaries:\n{summary_block}\n"
    pass2_input_tokens = estimate_tokens(pass2_prompt)
    total_pass2_tokens = pass2_input_tokens + pass2_out_est
    if total_pass2_tokens > max_call_tokens:
        return {
            "ok": False,
            "reason": f"Pass2 call exceeds per_call_max_tokens ({total_pass2_tokens} > {max_call_tokens}). Reduce summaries or raise limit."
        }
    pass2_cost = estimate_cost(pass2_input_tokens, pass2_out_est, pass2_model, pricing)
    num_students = int(student_count_override or len(texts) or 0)
    per_student_cost = (sum(pass1_per_student_costs.values()) + pass2_cost) / max(1, num_students)
    total_cost = sum(pass1_per_student_costs.values()) + pass2_cost
    return {
        "ok": True,
        "pass1_input_tokens": pass1_input_tokens,
        "pass2_input_tokens": pass2_input_tokens,
        "pass2_cost": pass2_cost,
        "per_student_cost": per_student_cost,
        "total_cost": total_cost,
        "pass1_per_student_costs": pass1_per_student_costs,
    }


def build_pass1_prompt(role_name: str, rubric: str, outline: str, student_id: str, text: str,
                       grade_context: str = "", exemplars: str = "", criteria_block: str = "",
                       evidence_reqs: dict | None = None) -> str:
    context = ""
    if grade_context:
        context += grade_context.strip() + "\n\n"
    if exemplars:
        context += exemplars.strip() + "\n\n"
    if criteria_block:
        context += criteria_block.strip() + "\n\n"
    evidence_note = ""
    evidence_field = ""
    if evidence_reqs:
        min_words = evidence_reqs.get("rationale_min_words", 0)
        evidence_field = '  "criteria_evidence": [],\n'
        evidence_note = (
            "For EACH criterion ID above, include one criteria_evidence item with:\n"
            "- criterion_id (use the ID exactly)\n"
            "- level (one of: 1, 2, 3, 4, 4+)\n"
            "- evidence_quote (exact words copied from the essay)\n"
            f"- rationale (min {min_words} words)\n"
            "If you include a numeric score, use a 0-100 percent scale.\n"
        )
    return f"""You are Assessor {role_name}. Score this student using the rubric.

{context}Rubric:
{rubric}

Assignment Outline:
{outline}

Student ID: {student_id}
Essay:
{text}

Return ONLY valid JSON in this exact format:
{{
  "student_id": "{student_id}",
  "rubric_total_points": <number 0-100 percent>,
  "criteria_points": {{}},
{evidence_field}  "notes": "short justification"
}}
{evidence_note}
"""


def build_pass2_prompt(role_name: str, rubric: str, outline: str, student_summaries: list, grade_context: str = "") -> str:
    items = "\n".join([f"- {s['student_id']}: {s['summary']}" for s in student_summaries])
    return f"""You are Assessor {role_name}. Rank the students best to worst.

{grade_context}
Rubric (for reference):
{rubric}

Assignment Outline:
{outline}

Student summaries:
{items}

Return JSON only:
{{"ranking": ["id_best", "id_next", "..."]}}
Use exact student_id strings from the list above, once each, best to worst.
"""


def json_from_text(text: str):
    decoder = json.JSONDecoder()
    candidates = []
    idx = 0
    while True:
        start = text.find("{", idx)
        if start == -1:
            break
        try:
            obj, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            idx = start + 1
            continue
        candidates.append(obj)
        idx = start + end
    if not candidates:
        raise ValueError("No JSON object found in model response.")
    for obj in reversed(candidates):
        if isinstance(obj, dict) and "student_id" in obj:
            return obj
    return candidates[-1]


def pass1_text_format(require_evidence: bool = False) -> dict:
    properties = {
        "student_id": {"type": "string"},
        "rubric_total_points": {"type": "number", "minimum": 0, "maximum": 100},
        "criteria_points": {"type": "array", "items": {"type": "object", "properties": {
            "criterion_id": {"type": "string"},
            "score": {"type": "number"},
        }, "required": ["criterion_id", "score"], "additionalProperties": False}},
        "notes": {"type": "string"},
    }
    required = ["student_id", "rubric_total_points", "criteria_points", "notes"]
    if require_evidence:
        properties["criteria_evidence"] = {"type": "array", "items": {"type": "object", "properties": {
            "criterion_id": {"type": "string"}, "level": {"type": "string"}, "score": {"type": "number"},
            "evidence_quote": {"type": "string"}, "rationale": {"type": "string"},
        }, "required": ["criterion_id", "level", "score", "evidence_quote", "rationale"], "additionalProperties": False}}
        required.append("criteria_evidence")
    return {"type": "json_schema", "name": "pass1_assessment", "strict": True, "schema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False}}


def _normalize_for_match(text: str) -> str:
    lowered = str(text).lower()
    lowered = re.sub(r"\s+", " ", lowered).strip()
    lowered = re.sub(r"[^a-z0-9 ]+", "", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def parse_pass1_item(text: str, student_id: str, required_ids: list | None = None,
                     reqs: dict | None = None, essay_text: str = "", strict: bool = True) -> dict:
    lookup = criterion_lookup(required_ids)
    expected_keys = ("student_id", "rubric_total_points", "criteria_points", "notes")
    try:
        item = json_from_text(text)
    except ValueError:
        if strict:
            raise
        item = rescue_pass1_item(text, student_id, required_ids)
        if item.get("rubric_total_points") is None and not item.get("criteria_points"):
            raise ValueError("Unable to parse pass1 response.")
    else:
        if not isinstance(item, dict) or not any(key in item for key in expected_keys):
            if strict:
                raise ValueError("Unable to parse pass1 response.")
            item = rescue_pass1_item(text, student_id, required_ids)
        elif not strict and any(key not in item for key in expected_keys):
            rescued = rescue_pass1_item(text, student_id, required_ids)
            if rescued.get("rubric_total_points") is not None or rescued.get("criteria_points"):
                item = rescued
    if strict:
        missing = [k for k in expected_keys if k not in item]
        if missing:
            raise ValueError(f"Pass1 response missing keys: {', '.join(missing)}")
    else:
        item.setdefault("notes", "")
        item.setdefault("rubric_total_points", 0)
    criteria_points_raw = item.get("criteria_points")
    if isinstance(criteria_points_raw, list):
        collapsed = {}
        for entry in criteria_points_raw:
            if not isinstance(entry, dict):
                continue
            cid = entry.get("criterion_id") or entry.get("criteria_id") or entry.get("criterion")
            score = entry.get("score")
            if cid is None or not isinstance(score, (int, float)):
                continue
            collapsed[str(cid)] = float(score)
        item["criteria_points"] = collapsed
    elif not isinstance(criteria_points_raw, dict):
        item["criteria_points"] = {}
    normalized_points = {}
    for raw_cid, raw_score in item["criteria_points"].items():
        cid = canonical_criterion_id(raw_cid, lookup)
        percent = score_to_percent(raw_score)
        if cid and isinstance(percent, (int, float)):
            normalized_points[cid] = float(percent)
    item["criteria_points"] = normalized_points
    evidence = item.get("criteria_evidence")
    if isinstance(evidence, list):
        for entry in evidence:
            if not isinstance(entry, dict):
                continue
            if "criteria_id" in entry and "criterion_id" not in entry:
                entry["criterion_id"] = entry.get("criteria_id")
            if "criterion" in entry and "criterion_id" not in entry:
                entry["criterion_id"] = entry.get("criterion")
            if "criteria" in entry and "criterion_id" not in entry:
                entry["criterion_id"] = entry.get("criteria")
            if "evidence" in entry and "evidence_quote" not in entry:
                entry["evidence_quote"] = entry.get("evidence")
            cid = canonical_criterion_id(entry.get("criterion_id"), lookup)
            if cid:
                entry["criterion_id"] = cid
            score = entry.get("score")
            if cid and not isinstance(score, (int, float)):
                derived = item["criteria_points"].get(cid)
                if isinstance(derived, (int, float)):
                    entry["score"] = derived
                    score = derived
            level, percent = coerce_level_and_score_to_percent(entry.get("level"), score)
            if level:
                entry["level"] = level
            if percent is not None:
                entry["score"] = percent
                score = percent
            rationale = entry.get("rationale")
            if not isinstance(rationale, str) or not rationale.strip():
                fallback = entry.get("evidence_quote") or item.get("notes") or ""
                entry["rationale"] = str(fallback)
            if reqs:
                min_words = int(reqs.get("rationale_min_words", 0) or 0)
                if min_words and len(str(entry.get("rationale", "")).split()) < min_words:
                    notes = item.get("notes") or ""
                    if notes:
                        entry["rationale"] = str(notes)
            if cid and isinstance(score, (int, float)):
                item["criteria_points"][cid] = score_to_percent(score) or float(score)
    if required_ids:
        from scripts.rubric_criteria import validate_criteria_evidence
        errors = validate_criteria_evidence(evidence, required_ids, reqs or {})
        if not errors and reqs and reqs.get("quote_validation", True):
            lowered = essay_text.lower()
            normalized = _normalize_for_match(essay_text)
            for entry in evidence or []:
                quote = str(entry.get("evidence_quote", "")).strip()
                if quote.lower() in lowered:
                    continue
                if _normalize_for_match(quote) in normalized:
                    continue
                errors.append(f"Quote not found for {entry.get('criterion_id')}")
        if errors:
            hard_fail = bool((reqs or {}).get("hard_fail_on_evidence_errors", False))
            if strict or hard_fail:
                raise ValueError("Pass1 evidence invalid: " + "; ".join(errors[:5]))
            item.setdefault("warnings", [])
            item["warnings"].extend(errors)
        # Derive the overall rubric percent deterministically from per-criterion evidence.
        per_criterion = []
        for cid in required_ids:
            value = item["criteria_points"].get(cid)
            pct = score_to_percent(value)
            if isinstance(pct, (int, float)):
                per_criterion.append(float(pct))
        if per_criterion:
            item["rubric_total_points"] = sum(per_criterion) / len(per_criterion)
        else:
            if strict:
                raise ValueError("Pass1 evidence invalid: Unable to derive rubric_total_points from criteria evidence.")
            fallback = score_to_percent(item.get("rubric_total_points"))
            if fallback is None:
                raise ValueError("Pass1 evidence invalid: Unable to derive rubric_total_points from criteria evidence.")
            item["rubric_total_points"] = float(fallback)
    item["student_id"] = student_id
    return item


def build_pass1_repair_prompt(student_id: str, raw: str, require_evidence: bool, context_prompt: str | None = None) -> str:
    base = ("You returned invalid JSON. Return ONLY valid JSON with keys "
            "student_id, rubric_total_points, criteria_points, notes")
    if require_evidence:
        base += ", criteria_evidence"
    if context_prompt:
        return (
            base
            + f'. Student ID must be "{student_id}".\n\n'
            + "Re-score the same submission from scratch using the original context below.\n\n"
            + context_prompt.rstrip()
            + "\n\nPrevious invalid output:\n"
            + raw
            + "\n"
        )
    return base + f'. Student ID must be "{student_id}".\n\nPrevious output:\n{raw}\n'


def looks_like_prompt_echo(text: str, student_id: str) -> bool:
    lowered = str(text or "").lower()
    if "rubric_total_points" in lowered:
        return False
    markers = (
        "\"role\":\"user\"",
        "user: you are assessor",
        "previous output:",
        f"student id must be \"{student_id.lower()}\"",
    )
    return sum(1 for marker in markers if marker in lowered) >= 2
