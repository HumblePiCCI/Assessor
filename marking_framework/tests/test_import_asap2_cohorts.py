import csv
import json
from pathlib import Path

import scripts.import_asap2_cohorts as imp
from scripts.benchmark_main_vs_fallback import ensure_dataset_shape, load_gold_rows


def fake_corpus(tmp_path):
    rows = []
    for prompt in [c["prompt_name"] for c in imp.DEFAULT_COHORTS]:
        for score in range(1, 7):
            for k in range(3):
                words = ["argument"] * (200 + score * 20 + k)
                rows.append(
                    {
                        "essay_id": f"{abs(hash(prompt)) % 1000:03d}{score}{k}",
                        "score": str(score),
                        "full_text": " ".join(words),
                        "assignment": f"Write about {prompt}.",
                        "prompt_name": prompt,
                        "grade_level": "8",
                        "essay_word_count": str(len(words)),
                    }
                )
    csv_path = tmp_path / "train.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    rubric = tmp_path / "rubric.txt"
    rubric.write_text("SCORE OF 6: mastery.\nSCORE OF 1: little mastery.", encoding="utf-8")
    return csv_path, rubric


def test_importer_builds_valid_deterministic_datasets(tmp_path, monkeypatch):
    csv_path, rubric = fake_corpus(tmp_path)
    out_a = tmp_path / "bench_a"
    out_b = tmp_path / "bench_b"
    for out in (out_a, out_b):
        monkeypatch.setattr(
            "sys.argv",
            ["imp", "--csv", str(csv_path), "--rubric-text", str(rubric), "--output-root", str(out)],
        )
        assert imp.main() == 0
    datasets = sorted(p.name for p in out_a.iterdir())
    assert len(datasets) == 4
    for name in datasets:
        ensure_dataset_shape(out_a / name)
        gold = load_gold_rows(out_a / name / "gold.jsonl")
        ranks = sorted(g["gold_rank"] for g in gold)
        assert ranks == list(range(1, len(gold) + 1))
        # Deterministic: both runs byte-identical.
        assert (out_a / name / "gold.jsonl").read_bytes() == (out_b / name / "gold.jsonl").read_bytes()
        meta = json.loads((out_a / name / "inputs" / "class_metadata.json").read_text())
        assert meta["holdout"] is True
        assert meta["license"] == "CC BY 4.0"


def test_anonymization_density_flags_token_heavy_text():
    clean = "This is a normal essay about driverless cars and their safety."
    dirty = "@PERSON1 went to @LOCATION1 with @PERSON2 and @ORGANIZATION1."
    assert imp.anonymization_density(clean) == 0
    assert imp.anonymization_density(dirty) > 0.2
