import json

from scripts.assessor_utils import normalize_ranking_ids


def pass2_text_format() -> dict:
    return {
        "type": "json_schema",
        "name": "pass2_ranking",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "ranking": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                }
            },
            "required": ["ranking"],
            "additionalProperties": False,
        },
    }


def build_pass2_repair_prompt(known_ids: list, prior: str, missing: list) -> str:
    missing_block = ""
    if missing:
        missing_block = "Missing IDs: " + ", ".join(missing) + "\n"
    ids_block = "\n".join(known_ids)
    return (
        "You returned an invalid or incomplete ranking.\n"
        "Return ONLY a ranked list if you cannot output JSON.\n"
        "Return valid JSON only with this shape: {\"ranking\": [\"id1\", \"id2\", ...]}.\n"
        "The ranking array must contain ALL IDs exactly once.\n"
        f"{missing_block}"
        "Use these IDs exactly as written:\n"
        f"{ids_block}\n\nPrevious output:\n{prior}\n"
    )


def _json_candidates(text: str) -> list[dict]:
    decoder = json.JSONDecoder()
    idx = 0
    out = []
    while True:
        start = text.find("{", idx)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            idx = start + 1
            continue
        if isinstance(obj, dict):
            out.append(obj)
        idx = start + end
    return out


def normalize_full_ranking(content: str, known_ids: list) -> tuple[list, list]:
    parsed = None
    for obj in reversed(_json_candidates(content)):
        ranking = obj.get("ranking")
        if isinstance(ranking, list):
            parsed = [str(item) for item in ranking]
            break
    source = parsed if parsed is not None else content.splitlines()
    lines = normalize_ranking_ids(source, known_ids)
    missing = [sid for sid in known_ids if sid not in lines]
    return lines, missing
