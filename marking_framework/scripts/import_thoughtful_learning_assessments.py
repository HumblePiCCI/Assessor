#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.document_extract import clean_text, extract_document_text


INDEX_URL = "https://k12.thoughtfullearning.com/resources/writingassessment"
BASE_URL = "https://k12.thoughtfullearning.com"
QUALITY_TO_LEVEL = {
    "poor": ("1", 50, 59),
    "okay": ("2", 60, 69),
    "good": ("3", 70, 79),
    "strong": ("4", 80, 89),
}
DATASET_SPECS = [
    {
        "dataset": "thoughtful_assessment_grade2_book_review",
        "grade_level": 2,
        "assignment_genre": "literary_analysis",
        "mode": "Response to Literature",
        "form": "Book Review",
        "cohort_shape": "same_rubric_family_cross_topic",
        "items": [
            {"slug": "julius-baby-world", "quality": "strong"},
            {"slug": "one-great-book", "quality": "good"},
            {"slug": "dear-mr-marc-brown", "quality": "okay"},
            {"slug": "snowflake-bentley", "quality": "poor"},
        ],
    },
    {
        "dataset": "thoughtful_assessment_grade3_personal_narrative",
        "grade_level": 3,
        "assignment_genre": "narrative",
        "mode": "Narrative Writing",
        "form": "Personal Narrative",
        "cohort_shape": "same_rubric_family_cross_topic",
        "items": [
            {"slug": "sled-run", "quality": "strong"},
            {"slug": "funny-dance", "quality": "good"},
            {"slug": "texas", "quality": "okay"},
            {"slug": "sad-day", "quality": "poor"},
        ],
    },
    {
        "dataset": "thoughtful_assessment_grade4_5_research",
        "grade_level": 4,
        "assignment_genre": "informational_report",
        "mode": "Research Writing",
        "form": "Report",
        "cohort_shape": "same_rubric_family_cross_topic",
        "items": [
            {"slug": "snow-leopard", "quality": "strong"},
            {"slug": "great-pyramid-giza", "quality": "good"},
            {"slug": "koalas", "quality": "okay"},
            {"slug": "ladybugs", "quality": "poor"},
        ],
    },
    {
        "dataset": "thoughtful_assessment_grade6_8_summary_iron",
        "grade_level": 7,
        "assignment_genre": "summary_report",
        "mode": "Explanatory Writing",
        "form": "Summary",
        "cohort_shape": "same_prompt",
        "items": [
            {"slug": "iron-summary-strong", "quality": "strong"},
            {"slug": "iron-summary-good", "quality": "good"},
            {"slug": "iron-summary-okay", "quality": "okay"},
            {"slug": "iron-summary-poor", "quality": "poor"},
        ],
    },
    {
        "dataset": "thoughtful_assessment_grade6_8_instructions_hydrochloric",
        "grade_level": 7,
        "assignment_genre": "informational_report",
        "mode": "Business Writing",
        "form": "Instructions",
        "cohort_shape": "same_prompt",
        "items": [
            {"slug": "using-hydrochloric-acid-strong", "quality": "strong"},
            {"slug": "using-hydrochloric-acid-good", "quality": "good"},
            {"slug": "using-hydrochloric-acid-okay", "quality": "okay"},
            {"slug": "using-hydrochloric-acid-poor", "quality": "poor"},
        ],
    },
    {
        "dataset": "thoughtful_assessment_grade6_8_persuasive_letter",
        "grade_level": 7,
        "assignment_genre": "opinion_letter",
        "mode": "Persuasive Writing",
        "form": "Persuasive Letter",
        "cohort_shape": "same_prompt",
        "items": [
            {"slug": "dear-dr-larson-strong", "quality": "strong"},
            {"slug": "dear-dr-larson-good", "quality": "good"},
            {"slug": "dear-dr-larson-okay", "quality": "okay"},
            {"slug": "dear-dr-larson-poor", "quality": "poor"},
        ],
    },
    {
        "dataset": "thoughtful_assessment_grade9_10_argument",
        "grade_level": 9,
        "assignment_genre": "argumentative",
        "mode": "Persuasive Writing",
        "form": "Argument Essay",
        "cohort_shape": "same_rubric_family_cross_topic",
        "items": [
            {"slug": "evening-odds", "quality": "strong"},
            {"slug": "lack-respect-growing-problem", "quality": "good"},
            {"slug": "right-dress", "quality": "okay"},
            {"slug": "grading-students-effort", "quality": "poor"},
        ],
    },
    {
        "dataset": "thoughtful_assessment_grade11_12_speech",
        "grade_level": 11,
        "assignment_genre": "argumentative",
        "mode": "Persuasive Writing",
        "form": "Speech",
        "cohort_shape": "same_rubric_family_cross_topic",
        "items": [
            {"slug": "generations-america", "quality": "strong"},
            {"slug": "inauguration-speech-49th-us-president", "quality": "good"},
            {"slug": "greatest-inauguration-speech", "quality": "okay"},
            {"slug": "what-i-will-do-country", "quality": "poor"},
        ],
    },
]


def fetch_url(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def fetch_html(url: str) -> BeautifulSoup:
    return BeautifulSoup(fetch_url(url).decode("utf-8", errors="ignore"), "html.parser")


def slug_to_url(slug: str) -> str:
    return f"{BASE_URL}/assessmentmodels/{slug}"


def normalize_text_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def title_to_filename(index: int, title: str) -> str:
    return f"sample_{index:02d}_{normalize_text_token(title)[:64]}.txt"


def read_existing_source_urls(bench_root: Path) -> set[str]:
    found: set[str] = set()
    for path in bench_root.glob("*/inputs/sources.md"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        found.update(re.findall(r"https?://\S+", text))
    return found


def read_dataset_source_urls(dataset_dir: Path) -> set[str]:
    sources_path = dataset_dir / "inputs" / "sources.md"
    if not sources_path.exists():
        return set()
    return set(re.findall(r"https?://\S+", sources_path.read_text(encoding="utf-8", errors="ignore")))


def links_for_page(soup: BeautifulSoup) -> dict[str, str]:
    result: dict[str, str] = {}
    for anchor in soup.find_all("a", href=True):
        label = clean_text(anchor.get_text(" ", strip=True))
        href = clean_text(anchor["href"])
        if not label or not href:
            continue
        result[label] = href
    return result


def parse_labelled_paragraphs(soup: BeautifulSoup) -> dict[str, str]:
    values: dict[str, str] = {}
    for paragraph in soup.find_all("p"):
        text = clean_text(paragraph.get_text(" ", strip=True))
        if ":" not in text:
            continue
        key, value = text.split(":", 1)
        if key in {"Title", "Level", "Mode", "Form", "Completed Rubric", "Blank Rubric"}:
            values[key.lower().replace(" ", "_")] = clean_text(value)
    return values


def extract_student_model_text(soup: BeautifulSoup) -> str:
    marker = None
    for heading in soup.find_all(["h2", "h3"]):
        if clean_text(heading.get_text(" ", strip=True)).lower() == "student model":
            marker = heading
            break
    if marker is None:
        raise ValueError("student model section not found")
    paragraphs: list[str] = []
    for node in marker.find_next_siblings():
        name = getattr(node, "name", None)
        if name == "h2":
            break
        candidates = []
        if name == "p":
            candidates = [node]
        elif hasattr(node, "find_all"):
            candidates = list(node.find_all("p"))
        for paragraph in candidates:
            text = clean_text(paragraph.get_text(" ", strip=True))
            if text:
                paragraphs.append(text)
    if not paragraphs:
        raise ValueError("student model text not found")
    return "\n\n".join(paragraphs)


def parse_assessment_page(url: str) -> dict:
    soup = fetch_html(url)
    labels = parse_labelled_paragraphs(soup)
    links = links_for_page(soup)
    title = labels.get("title")
    level_text = labels.get("level")
    mode = labels.get("mode")
    form = labels.get("form")
    completed_rubric = links.get(labels.get("completed_rubric", ""), "")
    blank_rubric = links.get(labels.get("blank_rubric", ""), "")
    if completed_rubric.startswith("/"):
        completed_rubric = f"{BASE_URL}{completed_rubric}"
    if blank_rubric.startswith("/"):
        blank_rubric = f"{BASE_URL}{blank_rubric}"
    footer_copy = ""
    for paragraph in soup.find_all("p"):
        text = clean_text(paragraph.get_text(" ", strip=True))
        if "Copying is permitted" in text:
            footer_copy = text
            break
    return {
        "url": url,
        "title": title or "",
        "level_text": level_text or "",
        "mode": mode or "",
        "form": form or "",
        "completed_rubric_url": completed_rubric,
        "blank_rubric_url": blank_rubric,
        "student_text": extract_student_model_text(soup),
        "copy_notice": footer_copy,
    }


def extract_remote_doc_text(url: str, cache_dir: Path) -> str:
    cache_dir.mkdir(parents=True, exist_ok=True)
    name = url.rstrip("/").split("/")[-1]
    path = cache_dir / name
    path.write_bytes(fetch_url(url))
    text, _ = extract_document_text(path)
    return clean_text(text)


def materialize_dataset(dataset_root: Path, spec: dict, existing_urls: set[str], cache_dir: Path):
    dataset_dir = dataset_root / spec["dataset"]
    inputs_dir = dataset_dir / "inputs"
    submissions_dir = dataset_dir / "submissions"
    if dataset_dir.exists():
        shutil.rmtree(dataset_dir)
    submissions_dir.mkdir(parents=True, exist_ok=True)
    inputs_dir.mkdir(parents=True, exist_ok=True)

    parsed_items = []
    for idx, item in enumerate(spec["items"], start=1):
        url = slug_to_url(item["slug"])
        if url in existing_urls:
            raise ValueError(f"Refusing to import duplicate source URL already present in bench corpus: {url}")
        page = parse_assessment_page(url)
        if not page["student_text"]:
            raise ValueError(f"Student text missing for {url}")
        filename = title_to_filename(idx, page["title"] or item["slug"])
        (submissions_dir / filename).write_text(page["student_text"].strip() + "\n", encoding="utf-8")
        parsed_items.append(
            {
                **page,
                "quality": item["quality"],
                "filename": filename,
                "student_id": f"s{idx:03d}",
            }
        )

    rubric_text = ""
    completed_text = ""
    blank_rubric_url = next((row["blank_rubric_url"] for row in parsed_items if row["blank_rubric_url"]), "")
    completed_rubric_url = next((row["completed_rubric_url"] for row in parsed_items if row["completed_rubric_url"]), "")
    if blank_rubric_url:
        rubric_text = extract_remote_doc_text(blank_rubric_url, cache_dir)
    if completed_rubric_url:
        completed_text = extract_remote_doc_text(completed_rubric_url, cache_dir)
    if not rubric_text:
        rubric_text = completed_text
    if not rubric_text:
        raise ValueError(f"Rubric text missing for dataset {spec['dataset']}")

    outline_lines = [
        f"Assignment Family: Thoughtful Learning Assessment Models ({spec['dataset']})",
        "",
        f"Source library: {INDEX_URL}",
        f"Grade level context: Grade {spec['grade_level']}",
        f"Mode: {spec['mode']}",
        f"Form: {spec['form']}",
        f"Cohort shape: {spec['cohort_shape']}",
        "",
        "Task interpretation:",
    ]
    if spec["cohort_shape"] == "same_prompt":
        outline_lines.extend(
            [
                f"- All four submissions come from the same prompt family and are labeled by the source as Strong, Good, Okay, and Poor.",
                f"- Evaluate performance against the shared {spec['form'].lower()} rubric and assign the closest Ontario-style achievement level.",
            ]
        )
    else:
        outline_lines.extend(
            [
                f"- These four submissions share a grade band, rubric family, mode, and form, but the exact topic varies across the set.",
                f"- Exact-level alignment to the source labels is the primary evaluation target for this benchmark.",
            ]
        )
    outline_lines.extend(
        [
            "",
            "Source titles in this cohort:",
            *[f"- {row['title']} ({row['quality'].title()})" for row in parsed_items],
        ]
    )
    (inputs_dir / "assignment_outline.md").write_text("\n".join(outline_lines).strip() + "\n", encoding="utf-8")

    rubric_lines = [
        f"Thoughtful Learning {spec['form']} Rubric",
        "",
        f"Primary rubric source: {blank_rubric_url or completed_rubric_url}",
        "",
        rubric_text,
    ]
    if completed_text and completed_text != rubric_text:
        rubric_lines.extend(
            [
                "",
                "Completed rubric exemplar text:",
                "",
                completed_text,
            ]
        )
    (inputs_dir / "rubric.md").write_text("\n".join(rubric_lines).strip() + "\n", encoding="utf-8")

    metadata = {
        "grade_level": spec["grade_level"],
        "assignment_genre": spec["assignment_genre"],
        "assignment_name": f"Thoughtful Learning {spec['mode']} {spec['form']} Benchmark",
        "source_family": "thoughtful_learning_assessment_models",
        "cohort_shape": spec["cohort_shape"],
    }
    (inputs_dir / "class_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    source_lines = [
        f"# Sources for {spec['dataset']}",
        "",
        f"Index page: {INDEX_URL}",
        "",
        "Student model pages:",
    ]
    for row in parsed_items:
        source_lines.append(f"- {row['title']} ({row['quality'].title()}): {row['url']}")
    source_lines.extend(
        [
            "",
            f"Blank rubric source: {blank_rubric_url or 'N/A'}",
            f"Completed rubric source: {completed_rubric_url or 'N/A'}",
            "",
            "License note:",
            f"- {parsed_items[0]['copy_notice'] or 'Thoughtful Learning page footer states copying is permitted.'}",
        ]
    )
    (inputs_dir / "sources.md").write_text("\n".join(source_lines).strip() + "\n", encoding="utf-8")

    gold_rows = []
    for idx, row in enumerate(parsed_items, start=1):
        gold_level, band_min, band_max = QUALITY_TO_LEVEL[row["quality"]]
        neighbors: list[str] = []
        if idx > 1:
            neighbors.append(f"s{idx - 1:03d}")
        if idx < len(parsed_items):
            neighbors.append(f"s{idx + 1:03d}")
        gold_rows.append(
            {
                "student_id": row["student_id"],
                "source_file": row["filename"],
                "display_name": row["title"],
                "gold_level": gold_level,
                "gold_band_min": band_min,
                "gold_band_max": band_max,
                "gold_rank": idx,
                "gold_neighbors": neighbors,
                "boundary_flag": row["quality"] in {"good", "okay"},
                "adjudication_notes": f"Thoughtful Learning assessment model labeled {row['quality'].title()} for {spec['mode']} / {spec['form']}.",
            }
        )
    with (dataset_dir / "gold.jsonl").open("w", encoding="utf-8") as handle:
        for row in gold_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def selected_specs(dataset_names: Iterable[str]) -> list[dict]:
    wanted = {name.strip() for name in dataset_names if name.strip()}
    if not wanted:
        return list(DATASET_SPECS)
    found = [spec for spec in DATASET_SPECS if spec["dataset"] in wanted]
    missing = sorted(wanted - {spec["dataset"] for spec in found})
    if missing:
        raise ValueError(f"Unknown dataset name(s): {', '.join(missing)}")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Import public Thoughtful Learning assessment quartets into benchmark-ready datasets.")
    parser.add_argument("--bench-root", default="bench", help="Benchmark dataset root")
    parser.add_argument("--cache-dir", default="tmp/thoughtful_learning_cache", help="Temporary download cache")
    parser.add_argument("--dataset", action="append", default=[], help="Optional dataset name to import; repeatable")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    bench_root = (repo_root / args.bench_root).resolve()
    cache_dir = (repo_root / args.cache_dir).resolve()
    specs = selected_specs(args.dataset)
    existing_urls = read_existing_source_urls(bench_root)
    for spec in specs:
        existing_urls -= read_dataset_source_urls(bench_root / spec["dataset"])
    imported = []
    for spec in specs:
        materialize_dataset(bench_root, spec, existing_urls, cache_dir)
        imported.append(spec["dataset"])
        for item in spec["items"]:
            existing_urls.add(slug_to_url(item["slug"]))
    print(json.dumps({"imported": imported}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
