import csv
from pathlib import Path

import scripts.apply_curve as ac


def test_round_grade_modes():
    assert ac.round_grade(89.9, "floor") == 89
    assert ac.round_grade(89.1, "ceil") == 90
    assert ac.round_grade(89.5, "nearest") == 90


def test_apply_curve_main(tmp_path, monkeypatch):
    input_csv = tmp_path / "in.csv"
    with input_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id", "consensus_rank"])
        writer.writeheader()
        writer.writerow({"student_id": "s1", "consensus_rank": "1"})
        writer.writerow({"student_id": "s2", "consensus_rank": "2"})

    config = tmp_path / "cfg.json"
    config.write_text('{"curve": {"top": 90, "bottom": 80, "rounding": "nearest"}}', encoding="utf-8")
    out_csv = tmp_path / "out.csv"

    monkeypatch.setattr("sys.argv", ["ac", "--config", str(config), "--input", str(input_csv), "--output", str(out_csv)])
    assert ac.main() == 0
    assert out_csv.exists()

    # Single row case
    input_csv2 = tmp_path / "in2.csv"
    with input_csv2.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id", "consensus_rank"])
        writer.writeheader()
        writer.writerow({"student_id": "s1", "consensus_rank": "1"})

    out_csv2 = tmp_path / "out2.csv"
    monkeypatch.setattr("sys.argv", ["ac", "--config", str(config), "--input", str(input_csv2), "--output", str(out_csv2)])
    assert ac.main() == 0

    input_csv3 = tmp_path / "in3.csv"
    with input_csv3.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id"])
        writer.writeheader()
        writer.writerow({"student_id": "s1"})
        writer.writerow({"student_id": "s2"})
    out_csv3 = tmp_path / "out3.csv"
    monkeypatch.setattr("sys.argv", ["ac", "--config", str(config), "--input", str(input_csv3), "--output", str(out_csv3)])
    assert ac.main() == 0


def test_apply_curve_empty(tmp_path, monkeypatch):
    input_csv = tmp_path / "in.csv"
    with input_csv.open("w", encoding="utf-8", newline="") as f:
        f.write("student_id,consensus_rank\n")
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    out_csv = tmp_path / "out.csv"
    monkeypatch.setattr("sys.argv", ["ac", "--config", str(config), "--input", str(input_csv), "--output", str(out_csv)])
    assert ac.main() == 0


def test_calculate_curve_rows_prefers_consistency_rank_and_locks_levels():
    config = {
        "curve": {
            "top": 92,
            "bottom": 58,
            "rounding": "nearest",
            "profile": "bell",
            "rubric_weight": 0.65,
            "rank_weight": 0.35,
            "level_lock": True,
        },
        "levels": {
            "bands": [
                {"level": "3", "min": 70, "max": 79, "letter": "B"},
                {"level": "4", "min": 80, "max": 89, "letter": "A"},
            ]
        },
    }
    rows = [
        {
            "student_id": "s2",
            "consensus_rank": "2",
            "consistency_rank": "2",
            "adjusted_level": "3",
            "rubric_after_penalty_percent": "78",
        },
        {
            "student_id": "s1",
            "consensus_rank": "1",
            "consistency_rank": "1",
            "adjusted_level": "4",
            "rubric_after_penalty_percent": "81",
        },
    ]

    graded_rows, meta = ac.calculate_curve_rows(rows, config)

    assert meta["rank_key"] == "consistency_rank"
    assert [row["student_id"] for row in graded_rows] == ["s1", "s2"]
    assert graded_rows[0]["final_grade"] >= 80
    assert graded_rows[0]["final_grade"] <= 89
    assert graded_rows[1]["final_grade"] <= 79


def test_calculate_curve_rows_handles_missing_levels():
    config = {"curve": {"top": 90, "bottom": 80, "rounding": "nearest", "profile": "bell"}}
    rows = [{"student_id": "s1", "consensus_rank": "1"}, {"student_id": "s2", "consensus_rank": "2"}]
    graded_rows, meta = ac.calculate_curve_rows(rows, config)
    assert meta["rank_key"] == "consensus_rank"
    assert graded_rows[0]["final_grade"] == 90
    assert graded_rows[1]["final_grade"] == 80
