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


GENRE_ALIASES = {
    "literary_analysis": {"literary_analysis", "literary analysis", "theme analysis"},
    "argumentative": {"argumentative", "argument", "argumentative essay"},
    "informational_report": {"informational_report", "informational report", "report", "expository"},
    "news_report": {"news_report", "news report", "osstl", "osslt"},
    "narrative": {"narrative", "personal narrative", "story"},
    "descriptive": {"descriptive", "description", "sensory"},
    "summary_report": {"summary_report", "summary report", "summary"},
    "opinion_letter": {"opinion_letter", "opinion letter", "letter to the editor"},
    "advertisement": {"advertisement", "ad", "persuasive ad"},
    "letter": {"letter", "reader response", "response letter"},
}


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
            return key
    return lowered.replace(" ", "_")


def grade_band_for_level(grade_level: int | None) -> str | None:
    if grade_level is None:
        return None
    if 6 <= grade_level <= 7:
        return "grade_6_7"
    if 8 <= grade_level <= 10:
        return "grade_8_10"
    if 11 <= grade_level <= 12:
        return "grade_11_12"
    return None


def resolve_exemplars_dir(base_dir: Path, grade_level: int | None, genre: str | None) -> Path:
    band = grade_band_for_level(grade_level)
    normalized = normalize_genre(genre)
    if band and normalized:
        candidate = base_dir / band / normalized
        if candidate.exists():
            return candidate
    if normalized:
        candidate = base_dir / "genres" / normalized
        if candidate.exists():
            return candidate
    return base_dir
