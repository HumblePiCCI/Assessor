import json
from pathlib import Path

from scripts.assessor_utils import load_file_text, resolve_input_path


EXEMPLAR_SPECS = [
    ("level_4_plus", "Level 4+ (90-100%)", ["level_4_plus", "level_4plus", "level_4+"]),
    ("level_4", "Level 4 (80-89%)", ["level_4"]),
    ("level_3", "Level 3 (70-79%)", ["level_3"]),
    ("level_2", "Level 2 (60-69%)", ["level_2"]),
    ("level_1", "Level 1 (50-59%)", ["level_1"]),
]


GRADE_BAND_SPECS = [
    ("grade_1_3", 1, 3),
    ("grade_4_5", 4, 5),
    ("grade_6_7", 6, 7),
    ("grade_8_10", 8, 10),
    ("grade_11_12", 11, 12),
]


GENRE_ALIASES = {
    "literary_analysis": {"literary_analysis", "literary analysis", "theme analysis"},
    "argumentative": {"argumentative", "argument", "argumentative essay"},
    "informational_report": {"informational_report", "informational report", "report", "expository"},
    "news_report": {"news_report", "news report", "osstl", "osslt"},
    "narrative": {"narrative", "personal narrative", "story"},
    "descriptive": {"descriptive", "description", "sensory"},
    "summary_report": {"summary_report", "summary report", "summary"},
    "instructions": {"instructions", "instruction", "procedural writing", "procedure", "how to", "how-to", "lab procedure"},
    "book_review": {"book_review", "book review", "reader response", "response to literature"},
    "informative_letter": {"informative_letter", "informative letter", "expository letter"},
    "speech": {"speech", "persuasive speech", "oral argument", "address"},
    "portfolio": {"portfolio", "writing portfolio", "mixed forms", "mixed form"},
    "research_report": {"research_report", "research report", "research project"},
    "opinion_letter": {"opinion_letter", "opinion letter", "letter to the editor"},
    "advertisement": {"advertisement", "ad", "persuasive ad"},
    "letter": {"letter", "reader response", "response letter"},
}

CANONICAL_GENRE_MAP = {
    "opinion_letter": "argumentative",
    "advertisement": "argumentative",
    "letter": "argumentative",
    "descriptive": "narrative",
    "research_report": "informational_report",
}

EXEMPLAR_GENRE_FALLBACKS = {
    "argumentative": ["argumentative", "informational_report", "literary_analysis", "news_report"],
    "book_review": ["literary_analysis", "informational_report", "argumentative", "news_report"],
    "informational_report": ["informational_report", "argumentative", "literary_analysis", "news_report"],
    "informative_letter": ["informational_report", "argumentative", "literary_analysis", "news_report"],
    "instructions": ["informational_report", "news_report", "argumentative", "literary_analysis"],
    "literary_analysis": ["literary_analysis", "argumentative", "informational_report", "news_report"],
    "narrative": ["literary_analysis", "informational_report", "argumentative", "news_report"],
    "news_report": ["news_report", "informational_report", "argumentative", "literary_analysis"],
    "portfolio": ["literary_analysis", "informational_report", "argumentative", "news_report"],
    "speech": ["argumentative", "informational_report", "literary_analysis", "news_report"],
    "summary_report": ["informational_report", "literary_analysis", "argumentative", "news_report"],
}

DEFAULT_BAND_ORDER = ["grade_8_10", "grade_6_7", "grade_11_12", "grade_4_5", "grade_1_3"]


def load_grade_profiles(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_class_metadata(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def select_grade_level(explicit: int | None, metadata: dict) -> int | None:
    if explicit is not None:
        return explicit
    try:
        if "grade_level" in metadata:
            return int(metadata["grade_level"])
    except (TypeError, ValueError):
        return None
    return None


def build_grade_context(grade_level: int | None, profiles: dict) -> str:
    if not grade_level or not profiles:
        return ""
    profile = profiles.get(f"grade_{grade_level}")
    if not profile:
        return ""
    parts = [
        f"GRADE LEVEL CONTEXT: Grade {grade_level}",
        f"- Vocabulary: {profile.get('vocabulary_expectations', 'N/A')}",
        f"- Sentence complexity: {profile.get('sentence_complexity', 'N/A')}",
        f"- Thesis expectations: {profile.get('thesis_expectations', 'N/A')}",
        f"- Evidence expectations: {profile.get('evidence_expectations', 'N/A')}",
    ]
    return "\n".join(parts)


def _find_exemplar_file(exemplars_dir: Path, aliases: list) -> Path | None:
    candidates = []
    for alias in aliases:
        candidate = resolve_input_path(exemplars_dir / f"{alias}.md", alias)
        if candidate.exists():
            candidates.append(candidate)
    if not candidates:
        return None
    preferred = {".md": 0, ".txt": 1, ".docx": 2}
    candidates.sort(key=lambda p: (preferred.get(p.suffix.lower(), 99), p.name))
    return candidates[0]


def load_exemplars(exemplars_dir: Path, exclude_files: set[str] | None = None) -> dict:
    if not exemplars_dir.exists():
        return {}
    exemplars = {}
    for key, _, aliases in EXEMPLAR_SPECS:
        path = _find_exemplar_file(exemplars_dir, aliases)
        if not path:
            continue
        if exclude_files and path.name in exclude_files:
            continue
        text = load_file_text(path).strip()
        if text:
            exemplars[key] = text
    return exemplars


def format_exemplars(exemplars: dict) -> str:
    if not exemplars:
        return ""
    lines = ["EXEMPLARS (calibration):"]
    for key, label, _ in EXEMPLAR_SPECS:
        text = exemplars.get(key)
        if text:
            lines.append(f"{label}:\n{text}")
    return "\n\n".join(lines)


def normalize_genre(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.strip().lower()
    for key, aliases in GENRE_ALIASES.items():
        if lowered == key or lowered in aliases:
            return CANONICAL_GENRE_MAP.get(key, key)
    normalized = lowered.replace(" ", "_")
    return CANONICAL_GENRE_MAP.get(normalized, normalized)


def infer_genre_from_text(rubric_text: str, outline_text: str) -> str | None:
    merged = f"{rubric_text}\n{outline_text}".lower()
    rules = [
        ("instructions", ("instructions", "procedure", "follow these steps", "materials", "safety")),
        ("summary_report", ("summary", "main idea", "key details", "in your own words")),
        ("speech", ("speech", "audience", "address", "fellow students", "fellow americans")),
        ("book_review", ("book review", "recommend this book", "would you recommend")),
        ("news_report", ("headline", "news report", "who what when where", "objective tone")),
        ("argumentative", ("persuasive", "convince", "opinion", "letter to the editor", "argument")),
        ("informational_report", ("informational", "report", "explain", "facts and details")),
        ("narrative", ("personal narrative", "story", "tell about a time", "once", "experience")),
        ("literary_analysis", ("theme", "character", "novel", "textual evidence", "analysis")),
    ]
    for genre, markers in rules:
        if any(marker in merged for marker in markers):
            return genre
    return None


def grade_band_for_level(grade_level: int | None) -> str | None:
    if grade_level is None:
        return None
    for band, start, end in GRADE_BAND_SPECS:
        if start <= grade_level <= end:
            return band
    return None


def _band_distance(grade_level: int, band: str) -> float:
    for key, start, end in GRADE_BAND_SPECS:
        if key == band:
            center = (start + end) / 2.0
            return abs(float(grade_level) - center)
    return 999.0


def exemplar_genre_order(genre: str | None) -> list[str]:
    normalized = normalize_genre(genre)
    order = []
    for candidate in EXEMPLAR_GENRE_FALLBACKS.get(normalized, [normalized] if normalized else []):
        if candidate and candidate not in order:
            order.append(candidate)
    for fallback in ("literary_analysis", "argumentative", "informational_report", "news_report"):
        if fallback not in order:
            order.append(fallback)
    return order


def _band_search_order(grade_level: int | None, preferred_band: str | None) -> list[str]:
    if grade_level is None:
        order = list(DEFAULT_BAND_ORDER)
    else:
        order = [band for band, _, _ in GRADE_BAND_SPECS]
        order.sort(key=lambda band: (_band_distance(grade_level, band), DEFAULT_BAND_ORDER.index(band)))
    if preferred_band and preferred_band in order:
        order = [preferred_band] + [band for band in order if band != preferred_band]
    return order


def resolve_exemplar_selection(base_dir: Path, grade_level: int | None, genre: str | None) -> dict:
    def _has_levels(path: Path) -> bool:
        if not path.exists():
            return False
        for _, _, aliases in EXEMPLAR_SPECS:
            if _find_exemplar_file(path, aliases):
                return True
        return False

    normalized = normalize_genre(genre)
    genre_order = exemplar_genre_order(normalized)
    band = grade_band_for_level(grade_level)

    if band:
        for key in genre_order:
            candidate = base_dir / band / key
            if _has_levels(candidate):
                match_quality = "exact_scope" if key == genre_order[0] else "band_fallback"
                return {
                    "path": candidate,
                    "requested_band": band,
                    "requested_genre": normalized,
                    "selected_band": band,
                    "selected_genre": key,
                    "match_quality": match_quality,
                }

    if normalized:
        for key in genre_order:
            candidate = base_dir / "genres" / key
            if _has_levels(candidate):
                match_quality = "genre_library" if key == genre_order[0] else "genre_library_fallback"
                return {
                    "path": candidate,
                    "requested_band": band,
                    "requested_genre": normalized,
                    "selected_band": None,
                    "selected_genre": key,
                    "match_quality": match_quality,
                }

    for fallback_band in _band_search_order(grade_level, band):
        if fallback_band == band:
            continue
        for key in genre_order:
            candidate = base_dir / fallback_band / key
            if _has_levels(candidate):
                return {
                    "path": candidate,
                    "requested_band": band,
                    "requested_genre": normalized,
                    "selected_band": fallback_band,
                    "selected_genre": key,
                    "match_quality": "cross_band",
                }

    if _has_levels(base_dir):
        return {
            "path": base_dir,
            "requested_band": band,
            "requested_genre": normalized,
            "selected_band": None,
            "selected_genre": None,
            "match_quality": "root_library",
        }

    return {
        "path": base_dir,
        "requested_band": band,
        "requested_genre": normalized,
        "selected_band": None,
        "selected_genre": None,
        "match_quality": "missing",
    }


def resolve_exemplars_dir(base_dir: Path, grade_level: int | None, genre: str | None) -> Path:
    return resolve_exemplar_selection(base_dir, grade_level, genre)["path"]
