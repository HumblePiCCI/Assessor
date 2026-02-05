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


def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return extract_docx_text(path)
    return path.read_text(encoding="utf-8", errors="ignore")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", required=True, help="Directory with student submissions")
    parser.add_argument("--output", required=True, help="Directory for normalized .txt files")
    parser.add_argument("--metadata", default=None, help="Optional path for metadata JSON")
    args = parser.parse_args()

    in_dir = Path(args.inputs)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    metadata = []
    for path in sorted(in_dir.iterdir()):
        if path.is_dir():
            continue
        if path.suffix.lower() not in {".docx", ".txt", ".md"}:
            continue
        text = extract_text(path)
        out_path = out_dir / (path.stem + ".txt")
        out_path.write_text(text, encoding="utf-8")

        words = re.findall(r"[A-Za-z']+", text)
        paras = [p for p in text.split("\n\n") if p.strip()]
        metadata.append(
            {
                "student_id": path.stem,
                "source_file": path.name,
                "word_count": len(words),
                "paragraph_count": len(paras),
                "char_count": len(text),
            }
        )

    if args.metadata:
        Path(args.metadata).write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
