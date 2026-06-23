#!/usr/bin/env python3
"""Build holdout benchmark cohorts from the ASAP 2.0 corpus (CC BY 4.0).

ASAP 2.0 (Crossley et al., 2025; github.com/scrosseye/ASAP_2.0) contains
24,278 source-based argumentative essays from US state standardized writing
assessments, grades 6-10, holistically scored 1-6 by trained blind raters.

This importer deterministically samples classroom-sized cohorts (about two
essays per score point, spanning the full 1-6 range) and writes them in the
bench/ dataset schema. The resulting datasets are HOLDOUT sets: they must not
be used for prompt/engine tuning so they stay virgin territory for release
validation.

Selection is fully deterministic: for each score point, candidates inside the
length window are ordered by closeness to the score group's median length,
then essay_id; the first N are taken. Re-running the importer reproduces the
same cohorts byte-for-byte.

Usage:
  python3 scripts/import_asap2_cohorts.py \
    --csv /tmp/asap2/ASAP_2_Final_github_train.csv \
    --rubric-text /tmp/asap2/rubric_extracted.txt \
    --output-root bench
"""
import argparse
import csv
import json
import re
import statistics
from pathlib import Path

CANONICAL_BY_SCORE = {
    "6": {"canonical": "4+", "band_min": 90, "band_max": 100},
    "5": {"canonical": "4", "band_min": 80, "band_max": 89},
    "4": {"canonical": "3", "band_min": 75, "band_max": 79},
    "3": {"canonical": "3", "band_min": 70, "band_max": 74},
    "2": {"canonical": "2", "band_min": 60, "band_max": 69},
    "1": {"canonical": "1", "band_min": 50, "band_max": 59},
}

DEFAULT_COHORTS = [
    {
        "prompt_name": '"A Cowboy Who Rode the Waves"',
        "dataset": "holdout_asap2_g6_cowboy_waves",
        "grade": 6,
        "genre_form": "source-based argumentative essay",
    },
    {
        "prompt_name": "The Face on Mars",
        "dataset": "holdout_asap2_g8_face_on_mars",
        "grade": 8,
        "genre_form": "source-based argumentative essay",
    },
    {
        "prompt_name": "Does the electoral college work?",
        "dataset": "holdout_asap2_g9_electoral_college",
        "grade": 9,
        "genre_form": "source-based argumentative letter",
    },
    {
        "prompt_name": "Driverless cars",
        "dataset": "holdout_asap2_g10_driverless_cars",
        "grade": 10,
        "genre_form": "source-based argumentative essay",
    },
]

ANON_TOKEN = re.compile(r"@[A-Z_]+\d*|Generic_[A-Za-z]+|PROPER_NAME|STUDENT_NAME|TEACHER_NAME|LOCATION_NAME|\[\s*(?:name|location|school)\s*\]", re.IGNORECASE)


def word_count(row: dict) -> int:
    try:
        return int(float(row.get("essay_word_count") or 0))
    except (TypeError, ValueError):
        return len(str(row.get("full_text", "")).split())


def anonymization_density(text: str) -> float:
    words = max(1, len(text.split()))
    return len(ANON_TOKEN.findall(text)) / words


def select_cohort(rows: list[dict], *, per_score: int, min_words: int, max_words: int) -> list[dict]:
    chosen = []
    for score in ("6", "5", "4", "3", "2", "1"):
        group = [r for r in rows if r["score"] == score]
        eligible = [
            r
            for r in group
            if min_words <= word_count(r) <= max_words
            and anonymization_density(r["full_text"]) < 0.01
        ]
        if not eligible:
            eligible = sorted(group, key=lambda r: r["essay_id"])
        lengths = [word_count(r) for r in eligible]
        median_len = statistics.median(lengths) if lengths else 0
        eligible.sort(key=lambda r: (abs(word_count(r) - median_len), r["essay_id"]))
        chosen.extend(eligible[:per_score])
    return chosen


def write_dataset(out_dir: Path, cohort_cfg: dict, picked: list[dict], rubric_md: str) -> dict:
    submissions = out_dir / "submissions"
    inputs = out_dir / "inputs"
    submissions.mkdir(parents=True, exist_ok=True)
    inputs.mkdir(parents=True, exist_ok=True)

    # Strongest first so gold_rank == file order (matching extract_text ids).
    picked = sorted(picked, key=lambda r: (-int(r["score"]), r["essay_id"]))
    gold_rows = []
    for idx, row in enumerate(picked, start=1):
        sid = f"s{idx:03d}"
        (submissions / f"{sid}.txt").write_text(row["full_text"].strip() + "\n", encoding="utf-8")
        mapping = CANONICAL_BY_SCORE[row["score"]]
        same_score = [r for r in picked if r["score"] == row["score"]]
        tie_note = (
            " Within-score order is arbitrary (the source corpus assigns one holistic score per essay); "
            "within-score pair orderings should not be treated as meaningful."
            if len(same_score) > 1
            else ""
        )
        gold_rows.append(
            {
                "student_id": sid,
                "display_name": f"ASAP2 score {row['score']} ({row['essay_id'][:8]})",
                "gold_level": row["score"],
                "gold_canonical_level": mapping["canonical"],
                "gold_band_min": mapping["band_min"],
                "gold_band_max": mapping["band_max"],
                "gold_rank": idx,
                "adjudication_notes": (
                    "ASAP 2.0 holistic score assigned by trained blind raters on the released 1-6 rubric. "
                    "Canonical mapping: 6=4+, 5=4, 4=3 (upper band), 3=3 (lower band), 2=2, 1=1. "
                    "Submissions are ordered strongest-to-weakest so gold_rank=1 is the strongest paper."
                    + tie_note
                ),
                "source_file": f"{sid}.txt",
            }
        )
    with (out_dir / "gold.jsonl").open("w", encoding="utf-8") as handle:
        for row in gold_rows:
            handle.write(json.dumps(row) + "\n")

    (inputs / "rubric.md").write_text(rubric_md, encoding="utf-8")
    assignment = picked[0]["assignment"].strip()
    (inputs / "assignment_outline.md").write_text(
        "# Assignment\n\n"
        f"{assignment}\n\n"
        "Note: this is a source-based task from a state writing assessment. The source article was "
        "presented to students during the assessment but is not included in this dataset (the released "
        "source PDFs are image scans). Essays should be judged on argument quality, use of evidence as "
        "presented in the essay, organization, and language control.\n",
        encoding="utf-8",
    )
    (inputs / "sources.md").write_text(
        "# Provenance\n\n"
        "- Corpus: ASAP 2.0 (Automated Student Assessment Prize 2.0)\n"
        "- Source: https://github.com/scrosseye/ASAP_2.0 (train split)\n"
        "- Citation: Crossley, S. A., et al. (2025). The Automated Student Assessment Prize 2.0.\n"
        "- License: CC BY 4.0 (attribution required; redistribution permitted)\n"
        f"- Prompt: {cohort_cfg['prompt_name']}\n"
        f"- Grade level: {cohort_cfg['grade']}\n"
        "- Scores: holistic 1-6, assigned by trained human raters scoring blind on the released rubric\n"
        "- HOLDOUT SET: reserved for release validation. Do not use for prompt, calibration, or engine "
        "tuning. Selection is deterministic (see scripts/import_asap2_cohorts.py).\n",
        encoding="utf-8",
    )
    (inputs / "class_metadata.json").write_text(
        json.dumps(
            {
                "dataset_name": cohort_cfg["dataset"],
                "assessment_unit": "single_prompt",
                "grade": f"Grade {cohort_cfg['grade']}",
                "grade_numeric": cohort_cfg["grade"],
                "grade_level": cohort_cfg["grade"],
                "country": "United States",
                "language": "English",
                "genre": "argumentative",
                "genre_form": cohort_cfg["genre_form"],
                "source_family": "ASAP 2.0 / The Learning Agency Lab",
                "rubric_family": "ASAP 2.0 holistic 1-6 writing rubric",
                "prompt_shared": True,
                "sample_count": len(gold_rows),
                "holdout": True,
                "source_text_included": False,
                "license": "CC BY 4.0",
                "scoring_scale": {
                    "type": "ordinal",
                    "labels": ["1", "2", "3", "4", "5", "6"],
                    "canonical_mapping": {k: v["canonical"] for k, v in CANONICAL_BY_SCORE.items()},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"dataset": cohort_cfg["dataset"], "students": len(gold_rows), "scores": [r["gold_level"] for r in gold_rows]}


def build_rubric_md(rubric_text: str) -> str:
    lines = ["# Rubric", "", "ASAP 2.0 holistic writing rubric (1 = minimum, 6 = maximum)."]
    for paragraph in rubric_text.splitlines():
        clean = paragraph.strip()
        if not clean or clean.startswith("Holistic Rating Form"):
            continue
        match = re.match(r"SCORE OF (\d):\s*(.*)", clean)
        if match:
            lines.append("")
            lines.append(f"## Score {match.group(1)}")
            lines.append(match.group(2))
        else:
            lines.append(clean)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="ASAP_2_Final_github_train.csv path")
    parser.add_argument("--rubric-text", required=True, help="Extracted rubric text file")
    parser.add_argument("--output-root", default="bench")
    parser.add_argument("--per-score", type=int, default=2)
    parser.add_argument("--min-words", type=int, default=150)
    parser.add_argument("--max-words", type=int, default=600)
    args = parser.parse_args()

    with open(args.csv, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rubric_md = build_rubric_md(Path(args.rubric_text).read_text(encoding="utf-8"))

    results = []
    for cohort_cfg in DEFAULT_COHORTS:
        prompt_rows = [r for r in rows if r["prompt_name"] == cohort_cfg["prompt_name"]]
        picked = select_cohort(prompt_rows, per_score=args.per_score, min_words=args.min_words, max_words=args.max_words)
        out_dir = Path(args.output_root) / cohort_cfg["dataset"]
        results.append(write_dataset(out_dir, cohort_cfg, picked, rubric_md))
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
