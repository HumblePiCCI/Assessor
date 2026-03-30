#!/usr/bin/env python3
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    from scripts.extract_text import extract_docx_text
except ImportError:  # pragma: no cover - Support running as a script
    from extract_text import extract_docx_text  # pragma: no cover


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".webp", ".gif", ".bmp"}
TEXT_SUFFIXES = {".md", ".txt", ".json", ".csv"}


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _run_command(cmd: list[str], *, input_path: Path | None = None) -> str:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    text = result.stdout or result.stderr or ""
    if input_path is not None and not text and input_path.exists():
        return input_path.read_text(encoding="utf-8", errors="ignore")
    return clean_text(text)


def _rtf_to_text(path: Path) -> tuple[str, list[str]]:
    methods = []
    if shutil.which("textutil"):
        methods.append("textutil")
        text = _run_command(["textutil", "-convert", "txt", "-stdout", str(path)])
        if text:
            return text, methods
    methods.append("naive_strip")
    raw = path.read_text(encoding="utf-8", errors="ignore")
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", raw)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)
    text = re.sub(r"[{}]", " ", text)
    return clean_text(text), methods


def _pdf_to_text(path: Path) -> tuple[str, list[str]]:
    methods = []
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = __import__(module_name)
        except Exception:
            continue
        methods.append(module_name)
        try:
            reader_cls = getattr(module, "PdfReader")
            reader = reader_cls(str(path))
            text = clean_text("\n\n".join(page.extract_text() or "" for page in reader.pages))
        except Exception:
            text = ""
        if text:
            return text, methods
    if shutil.which("pdftotext"):
        methods.append("pdftotext")
        text = _run_command(["pdftotext", "-layout", str(path), "-"])
        if text:
            return text, methods
    if shutil.which("textutil"):
        methods.append("textutil")
        text = _run_command(["textutil", "-convert", "txt", "-stdout", str(path)])
        if text:
            return text, methods
    if shutil.which("mdls"):
        methods.append("mdls")
        text = _run_command(["mdls", "-raw", "-name", "kMDItemTextContent", str(path)])
        if text and text != "(null)":
            return text, methods
    return "", methods


def _image_to_text(path: Path) -> tuple[str, list[str]]:
    methods = []
    if shutil.which("tesseract"):
        methods.append("tesseract")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "ocr"
            try:
                result = subprocess.run(
                    ["tesseract", str(path), str(base)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except Exception:
                result = None
            txt_path = base.with_suffix(".txt")
            if result and result.returncode == 0 and txt_path.exists():
                text = clean_text(txt_path.read_text(encoding="utf-8", errors="ignore"))
                if text:
                    return text, methods
    if shutil.which("python3"):
        methods.append("macos_vision")
        code = (
            "import sys\n"
            "try:\n"
            " import Vision\n import Quartz\n"
            "except Exception:\n"
            " sys.exit(2)\n"
            "path = sys.argv[1]\n"
            "path_bytes = path.encode()\n"
            "url = Quartz.CFURLCreateFromFileSystemRepresentation(None, path_bytes, len(path_bytes), False)\n"
            "handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)\n"
            "request = Vision.VNRecognizeTextRequest.alloc().init()\n"
            "request.setRecognitionLevel_(1)\n"
            "handler.performRequests_error_([request], None)\n"
            "lines = []\n"
            "for obs in request.results() or []:\n"
            " top = obs.topCandidates_(1)\n"
            " if top:\n"
            "  lines.append(str(top[0].string()))\n"
            "print('\\n'.join(lines))\n"
        )
        text = _run_command(["python3", "-c", code, str(path)])
        if text:
            return text, methods
    return "", methods


def extract_document_text(path: Path) -> tuple[str, dict]:
    if not path.exists():
        return "", {"source_format": path.suffix.lstrip(".") or "unknown", "methods": [], "warnings": ["file_missing", "text_extraction_empty"]}
    suffix = path.suffix.lower()
    methods = []
    warnings = []
    text = ""
    if suffix in TEXT_SUFFIXES:
        methods.append("plain_text")
        text = path.read_text(encoding="utf-8", errors="ignore")
    elif suffix == ".docx":
        methods.append("docx_xml")
        text = extract_docx_text(path)
    elif suffix == ".rtf":
        text, methods = _rtf_to_text(path)
    elif suffix == ".pdf":
        text, methods = _pdf_to_text(path)
    elif suffix in IMAGE_SUFFIXES:
        text, methods = _image_to_text(path)
        if not text:
            warnings.append("image_ocr_unavailable")
    elif suffix == ".pages":
        raise ValueError(f"Unsupported file format for {path.name}. Export it as PDF, DOCX, RTF, TXT, or Markdown.")
    else:
        methods.append("plain_text_fallback")
        text = path.read_text(encoding="utf-8", errors="ignore")
    cleaned = clean_text(text)
    if not cleaned:
        warnings.append("text_extraction_empty")
    return cleaned, {
        "source_format": suffix.lstrip(".") or "unknown",
        "methods": methods,
        "warnings": warnings,
    }


def resolve_document_path(path: Path) -> Path:
    if path.exists():
        return path
    candidates = [item for item in path.parent.glob(f"{path.stem}.*") if item.is_file()]
    if not candidates:
        return path
    preferred = {
        ".md": 0,
        ".txt": 1,
        ".docx": 2,
        ".rtf": 3,
        ".pdf": 4,
        ".png": 5,
        ".jpg": 6,
        ".jpeg": 7,
    }
    candidates.sort(key=lambda item: (preferred.get(item.suffix.lower(), 99), item.name))
    return candidates[0]
