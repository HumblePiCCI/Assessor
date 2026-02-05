#!/usr/bin/env python3
import argparse
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    paragraphs = []
    for p in root.iter(f"{{{WORD_NS}}}p"):
        text = "".join(node.text or "" for node in p.iter(f"{{{WORD_NS}}}t"))
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def read_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return extract_docx_text(path)
    return path.read_text(encoding="utf-8", errors="ignore")


def load_outline(outline_path: Path) -> str:
    if outline_path.exists():
        return read_text(outline_path)
    return ""


def load_pairs(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "pairs" in data:
        return data
    return {"pairs": data}


def load_texts(text_dir: Path) -> dict:
    texts = {}
    for path in text_dir.glob("*.txt"):
        texts[path.stem] = path.read_text(encoding="utf-8", errors="ignore")
    return texts


def truncate(text: str, max_chars: int) -> str:
    if max_chars and max_chars > 0 and len(text) > max_chars:
        return text[:max_chars].rstrip() + "..."
    return text


def build_payload(pairs, outline, texts, max_chars):
    payload_pairs = []
    for pair in pairs:
        left_id = pair.get("left", {}).get("student_id")
        right_id = pair.get("right", {}).get("student_id")
        left_text = truncate(texts.get(left_id, ""), max_chars)
        right_text = truncate(texts.get(right_id, ""), max_chars)

        payload_pairs.append(
            {
                "pair_id": pair.get("pair_id"),
                "left": {
                    **pair.get("left", {}),
                    "text": left_text,
                },
                "right": {
                    **pair.get("right", {}),
                    "text": right_text,
                },
                "decision": {
                    "action": pair.get("decision", {}).get("action", "keep"),
                    "reason": pair.get("decision", {}).get("reason", ""),
                    "confidence": pair.get("decision", {}).get("confidence", ""),
                },
            }
        )

    return {
        "instructions": {
            "task": "For each adjacent pair, decide keep or swap.",
            "focus": "Assignment outline alignment, coherence, student voice, grade-level fit.",
            "rule": "Swap only if the lower-ranked essay clearly outperforms the higher-ranked essay.",
            "output": "Fill decision.action (keep|swap), decision.reason, decision.confidence (low|med|high).",
        },
        "assignment_outline": outline,
        "pairs": payload_pairs,
    }


def apply_decisions(original_pairs, decisions):
    decision_map = {}
    for pair in decisions.get("pairs", []):
        decision_map[pair.get("pair_id")] = pair.get("decision", {})

    for pair in original_pairs.get("pairs", []):
        pid = pair.get("pair_id")
        if pid in decision_map:
            pair["decision"] = {
                **pair.get("decision", {}),
                **decision_map[pid],
            }
    return original_pairs


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM helper for final pairwise review")
    parser.add_argument("--pairs", default="assessments/final_review_pairs.json", help="Pairs JSON file")
    parser.add_argument("--texts", default="processing/normalized_text", help="Normalized text directory")
    parser.add_argument("--outline", default="inputs/assignment_outline.md", help="Assignment outline path")
    parser.add_argument("--output", default="assessments/final_review_llm_input.json", help="LLM input JSON")
    parser.add_argument("--decisions", default="assessments/final_review_llm_output.json", help="LLM output JSON")
    parser.add_argument("--apply", action="store_true", help="Apply decisions back to pairs file")
    parser.add_argument("--max-chars", type=int, default=0, help="Truncate essay text to max chars (0 = no limit)")
    args = parser.parse_args()

    pairs_path = Path(args.pairs)
    if not pairs_path.exists():
        print(f"Pairs file not found: {pairs_path}")
        return 1

    if args.apply:
        decisions_path = Path(args.decisions)
        if not decisions_path.exists():
            print(f"Decisions file not found: {decisions_path}")
            return 1
        original_pairs = load_pairs(pairs_path)
        decisions = load_pairs(decisions_path)
        merged = apply_decisions(original_pairs, decisions)
        pairs_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        print(f"Applied decisions to: {pairs_path}")
        return 0

    texts = load_texts(Path(args.texts))
    outline = load_outline(Path(args.outline))
    pairs = load_pairs(pairs_path)
    payload = build_payload(pairs.get("pairs", []), outline, texts, args.max_chars)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote LLM input: {output_path}")
    print("Next: run your LLM, then save output to --decisions and apply with --apply.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
