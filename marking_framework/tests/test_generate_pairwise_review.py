import csv
from pathlib import Path

import scripts.generate_pairwise_review as gpr


def test_generate_pairwise_review(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    with input_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id", "consensus_rank"])
        writer.writeheader()
        writer.writerow({"student_id": "s1", "consensus_rank": "1"})
        writer.writerow({"student_id": "s2", "consensus_rank": "2"})

    out_json = tmp_path / "pairs.json"
    monkeypatch.setattr("sys.argv", ["gpr", "--input", str(input_csv), "--output", str(out_json)])
    assert gpr.main() == 0
    assert out_json.exists()


def test_generate_pairwise_review_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["gpr", "--input", str(tmp_path / "missing.csv"), "--output", str(tmp_path / "pairs.json")])
    assert gpr.main() == 1


def test_generate_pairwise_review_empty(tmp_path, monkeypatch):
    input_csv = tmp_path / "empty.csv"
    input_csv.write_text("student_id,consensus_rank\n", encoding="utf-8")
    out_json = tmp_path / "pairs.json"
    monkeypatch.setattr("sys.argv", ["gpr", "--input", str(input_csv), "--output", str(out_json)])
    assert gpr.main() == 1


def test_generate_pairwise_review_final_rank(tmp_path, monkeypatch):
    input_csv = tmp_path / "final.csv"
    with input_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id", "final_rank"])
        writer.writeheader()
        writer.writerow({"student_id": "s1", "final_rank": "1"})
        writer.writerow({"student_id": "s2", "final_rank": "2"})
    out_json = tmp_path / "pairs.json"
    monkeypatch.setattr("sys.argv", ["gpr", "--input", str(input_csv), "--output", str(out_json)])
    assert gpr.main() == 0
