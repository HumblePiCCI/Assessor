import csv
import json
from pathlib import Path

import scripts.apply_pairwise_adjustments as apa


def write_csv(path: Path):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id", "consensus_rank"])
        writer.writeheader()
        writer.writerow({"student_id": "s1", "consensus_rank": "1"})
        writer.writerow({"student_id": "s2", "consensus_rank": "2"})


def test_apply_pairwise_adjustments(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    write_csv(input_csv)

    decisions = {
        "pairs": [
            {
                "left": {"student_id": "s1"},
                "right": {"student_id": "s2"},
                "decision": {"action": "swap", "reason": "test", "confidence": "med"},
            }
        ]
    }
    decisions_path = tmp_path / "pairs.json"
    decisions_path.write_text(json.dumps(decisions), encoding="utf-8")

    out_csv = tmp_path / "final.csv"
    monkeypatch.setattr("sys.argv", ["apa", "--input", str(input_csv), "--decisions", str(decisions_path), "--output", str(out_csv), "--min-confidence", "medium"])
    assert apa.main() == 0
    assert out_csv.exists()
    flagged = tmp_path / "final_review_flagged.md"
    assert flagged.exists()


def test_apply_pairwise_adjustments_flagged(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    write_csv(input_csv)
    decisions = {
        "pairs": [
            {
                "left": {"student_id": "s1"},
                "right": {"student_id": "s2"},
                "decision": {"action": "swap", "reason": "test", "confidence": "low"},
            }
        ]
    }
    decisions_path = tmp_path / "pairs.json"
    decisions_path.write_text(json.dumps(decisions), encoding="utf-8")
    out_csv = tmp_path / "final.csv"
    monkeypatch.setattr("sys.argv", ["apa", "--input", str(input_csv), "--decisions", str(decisions_path), "--output", str(out_csv), "--min-confidence", "high"])
    assert apa.main() == 0
    flagged = tmp_path / "final_review_flagged.md"
    assert "swap" in flagged.read_text(encoding="utf-8")


def test_apply_pairwise_adjustments_unknown_confidence(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    write_csv(input_csv)
    decisions = {
        "pairs": [
            {
                "left": {"student_id": "s1"},
                "right": {"student_id": "s2"},
                "decision": {"action": "swap", "reason": "test", "confidence": "weird"},
            }
        ]
    }
    decisions_path = tmp_path / "pairs.json"
    decisions_path.write_text(json.dumps(decisions), encoding="utf-8")
    out_csv = tmp_path / "final.csv"
    monkeypatch.setattr("sys.argv", ["apa", "--input", str(input_csv), "--decisions", str(decisions_path), "--output", str(out_csv), "--min-confidence", "high"])
    assert apa.main() == 0


def test_apply_pairwise_adjustments_invalid_conf(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    write_csv(input_csv)
    decisions_path = tmp_path / "pairs.json"
    decisions_path.write_text(json.dumps({"pairs": []}), encoding="utf-8")
    out_csv = tmp_path / "final.csv"
    monkeypatch.setattr("sys.argv", ["apa", "--input", str(input_csv), "--decisions", str(decisions_path), "--output", str(out_csv), "--min-confidence", "bad"])
    assert apa.main() == 1


def test_apply_pairwise_adjustments_missing_files(tmp_path, monkeypatch):
    missing_input = tmp_path / "missing.csv"
    decisions_path = tmp_path / "pairs.json"
    decisions_path.write_text(json.dumps({"pairs": []}), encoding="utf-8")
    out_csv = tmp_path / "final.csv"
    monkeypatch.setattr("sys.argv", ["apa", "--input", str(missing_input), "--decisions", str(decisions_path), "--output", str(out_csv)])
    assert apa.main() == 1

    input_csv = tmp_path / "consensus.csv"
    write_csv(input_csv)
    missing_decisions = tmp_path / "missing.json"
    monkeypatch.setattr("sys.argv", ["apa", "--input", str(input_csv), "--decisions", str(missing_decisions), "--output", str(out_csv)])
    assert apa.main() == 1


def test_apply_pairwise_adjustments_no_rows(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    input_csv.write_text("student_id,consensus_rank\n", encoding="utf-8")
    decisions_path = tmp_path / "pairs.json"
    decisions_path.write_text(json.dumps({"pairs": []}), encoding="utf-8")
    out_csv = tmp_path / "final.csv"
    monkeypatch.setattr("sys.argv", ["apa", "--input", str(input_csv), "--decisions", str(decisions_path), "--output", str(out_csv)])
    assert apa.main() == 1


def test_apply_pairwise_adjustments_medium_confidence(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    write_csv(input_csv)
    decisions = {
        "pairs": [
            {
                "left": {"student_id": "s1"},
                "right": {"student_id": "s2"},
                "decision": {"action": "swap", "reason": "test", "confidence": "medium"},
            },
            {
                "left": {"student_id": "s1"},
                "right": {"student_id": "s2"},
                "decision": {"action": "swap", "reason": "test", "confidence": "high"},
            },
        ]
    }
    decisions_path = tmp_path / "pairs.json"
    decisions_path.write_text(json.dumps(decisions), encoding="utf-8")
    out_csv = tmp_path / "final.csv"
    monkeypatch.setattr("sys.argv", ["apa", "--input", str(input_csv), "--decisions", str(decisions_path), "--output", str(out_csv)])
    assert apa.main() == 0


def test_apply_pairwise_adjustments_keep_action(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    write_csv(input_csv)
    decisions = {
        "pairs": [
            {
                "left": {"student_id": "s1"},
                "right": {"student_id": "s2"},
                "decision": {"action": "keep", "reason": "close", "confidence": "high"},
            }
        ]
    }
    decisions_path = tmp_path / "pairs.json"
    decisions_path.write_text(json.dumps(decisions), encoding="utf-8")
    out_csv = tmp_path / "final.csv"
    monkeypatch.setattr("sys.argv", ["apa", "--input", str(input_csv), "--decisions", str(decisions_path), "--output", str(out_csv)])
    assert apa.main() == 0
