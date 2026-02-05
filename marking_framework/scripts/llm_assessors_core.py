import json
from pathlib import Path


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


def preflight_costs(texts, rubric, outline, summaries, routing, pricing, limits, grade_context="", exemplars=""):
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
    num_students = len(texts)
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
    if evidence_reqs:
        min_words = evidence_reqs.get("rationale_min_words", 0)
        evidence_note = f"Provide evidence quotes and rationale (min {min_words} words).\n"
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
  "rubric_total_points": <number>,
  "criteria_points": {{}},
  "criteria_evidence": [],
  "notes": "short justification"
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

Return ONLY a plain text list of the exact student_id strings above, one per line, best to worst.
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


def pass1_text_format() -> dict:
    return {"type": "json_schema", "strict": True, "schema": {"type": "object", "properties": {
        "student_id": {"type": "string"}, "rubric_total_points": {"type": "number"},
        "criteria_points": {"type": "object"}, "criteria_evidence": {"type": "array"},
        "notes": {"type": "string"}},
        "required": ["student_id", "rubric_total_points", "criteria_points", "notes"], "additionalProperties": False}}


def parse_pass1_item(text: str, student_id: str, required_ids: list | None = None,
                     reqs: dict | None = None, essay_text: str = "") -> dict:
    item = json_from_text(text)
    missing = [k for k in ("student_id", "rubric_total_points", "criteria_points", "notes") if k not in item]
    if missing:
        raise ValueError(f"Pass1 response missing keys: {', '.join(missing)}")
    if not isinstance(item.get("criteria_points"), dict):
        item["criteria_points"] = {}
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
            cid = entry.get("criterion_id")
            score = entry.get("score")
            if cid and not isinstance(score, (int, float)):
                derived = item["criteria_points"].get(cid)
                if isinstance(derived, (int, float)):
                    entry["score"] = derived
                    score = derived
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
                item["criteria_points"][cid] = score
    if required_ids:
        from scripts.rubric_criteria import validate_criteria_evidence
        errors = validate_criteria_evidence(evidence, required_ids, reqs or {})
        if not errors and reqs and reqs.get("quote_validation", True):
            lowered = essay_text.lower()
            for entry in evidence or []:
                quote = str(entry.get("evidence_quote", "")).strip().lower()
                if quote and quote not in lowered:
                    errors.append(f"Quote not found for {entry.get('criterion_id')}")
        if errors:
            raise ValueError("Pass1 evidence invalid: " + "; ".join(errors[:5]))
    item["student_id"] = student_id
    return item


def build_pass1_repair_prompt(student_id: str, raw: str, require_evidence: bool) -> str:
    base = ("You returned invalid JSON. Return ONLY valid JSON with keys "
            "student_id, rubric_total_points, criteria_points, notes")
    if require_evidence:
        base += ", criteria_evidence"
    return base + f'. Student ID must be "{student_id}".\n\nPrevious output:\n{raw}\n'
