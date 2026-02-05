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


def load_file_text(path: Path) -> str:
    if not path.exists():
        return ""
    if path.suffix.lower() == ".pages":
        raise ValueError(f"Unsupported file format for {path.name}. Export as .docx or .txt.")
    if path.suffix.lower() == ".docx":
        return extract_docx_text(path)
    return path.read_text(encoding="utf-8", errors="ignore")


def resolve_input_path(path: Path, stem: str) -> Path:
    if path.exists():
        return path
    search_dir = path.parent
    candidates = [p for p in search_dir.glob(f"{stem}.*") if p.is_file()]
    if not candidates:
        return path
    preferred = {".md": 0, ".txt": 1, ".docx": 2}
    candidates.sort(key=lambda p: (preferred.get(p.suffix.lower(), 99), p.name))
    return candidates[0]


def normalize_ranking_ids(lines: list, known_ids: list) -> list:
    known_lower = {k.lower(): k for k in known_ids}
    normalized = []
    seen = set()
    for raw in [line.strip() for line in lines if line.strip()]:
        if raw in known_ids:
            mapped = raw
        elif raw.lower() in known_lower:
            mapped = known_lower[raw.lower()]
        else:
            lower = raw.lower()
            prefix = [k for k in known_ids if k.lower().startswith(lower)]
            if len(prefix) == 1:
                mapped = prefix[0]
            else:
                tokens = [t for t in re.split(r"[\s\-–—]+", lower) if t]
                token_matches = [k for k in known_ids if all(t in k.lower() for t in tokens)]
                if len(token_matches) == 1:
                    mapped = token_matches[0]
                else:
                    raise ValueError(f"Unrecognized or ambiguous student id: {raw}")
        if mapped in seen:
            raise ValueError(f"Duplicate student id in ranking: {mapped}")
        seen.add(mapped)
        normalized.append(mapped)
    return normalized


def summarize_text(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if max_chars and len(text) > max_chars:
        return text[:max_chars] + "..."
    return text
