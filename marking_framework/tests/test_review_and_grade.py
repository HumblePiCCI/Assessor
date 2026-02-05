import csv
from pathlib import Path

import scripts.review_and_grade as rg


def make_csv(path: Path):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id", "consensus_rank", "rubric_mean_percent", "conventions_mistake_rate_percent", "flags"])
        writer.writeheader()
        writer.writerow({"student_id": "s1", "consensus_rank": "1", "rubric_mean_percent": "80", "conventions_mistake_rate_percent": "1", "flags": ""})
        writer.writerow({"student_id": "s2", "consensus_rank": "2", "rubric_mean_percent": "70", "conventions_mistake_rate_percent": "2", "flags": "flag"})


def test_review_and_grade_non_interactive(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    make_csv(input_csv)
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"curve": {"top": 92, "bottom": 58, "rounding": "nearest"}}', encoding="utf-8")
    out_csv = tmp_path / "grades.csv"

    monkeypatch.setattr("sys.argv", ["rg", "--input", str(input_csv), "--config", str(cfg), "--output", str(out_csv), "--non-interactive"])
    assert rg.main() == 0
    assert out_csv.exists()


def test_review_and_grade_rounding_modes():
    assert rg.round_grade(89.1, "floor") == 89
    assert rg.round_grade(89.1, "ceil") == 90
    assert rg.round_grade(89.5, "nearest") == 90


def test_review_and_grade_interactive(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    make_csv(input_csv)
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"curve": {"top": 92, "bottom": 58, "rounding": "nearest"}}', encoding="utf-8")
    out_csv = tmp_path / "grades.csv"

    inputs = iter(["50", "50", "95", "60", "yes"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr("sys.argv", ["rg", "--input", str(input_csv), "--config", str(cfg), "--output", str(out_csv)])
    assert rg.main() == 0


def test_review_and_grade_interactive_abort(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    make_csv(input_csv)
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"curve": {"top": 92, "bottom": 58, "rounding": "nearest"}}', encoding="utf-8")
    out_csv = tmp_path / "grades.csv"

    inputs = iter(["95", "60", "no"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr("sys.argv", ["rg", "--input", str(input_csv), "--config", str(cfg), "--output", str(out_csv)])
    assert rg.main() == 0


def test_review_and_grade_interactive_warning(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    make_csv(input_csv)
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"curve": {"top": 92, "bottom": 58, "rounding": "nearest"}}', encoding="utf-8")
    out_csv = tmp_path / "grades.csv"

    inputs = iter(["120", "-5", "yes"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr("sys.argv", ["rg", "--input", str(input_csv), "--config", str(cfg), "--output", str(out_csv)])
    assert rg.main() == 0


def test_review_and_grade_interactive_adjust_loop(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    make_csv(input_csv)
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"curve": {"top": 92, "bottom": 58, "rounding": "nearest"}}', encoding="utf-8")
    out_csv = tmp_path / "grades.csv"
    inputs = iter(["95", "60", "adjust", "96", "61", "yes"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr("sys.argv", ["rg", "--input", str(input_csv), "--config", str(cfg), "--output", str(out_csv)])
    assert rg.main() == 0


def test_review_and_grade_missing_input(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["rg", "--input", str(tmp_path / "missing.csv"), "--config", str(cfg), "--output", str(tmp_path / "out.csv")])
    assert rg.main() == 1


def test_review_and_grade_empty_file(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    input_csv.write_text("student_id,consensus_rank\n", encoding="utf-8")
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["rg", "--input", str(input_csv), "--config", str(cfg), "--output", str(tmp_path / "out.csv")])
    assert rg.main() == 1


def test_review_and_grade_default_input_and_sort(tmp_path, monkeypatch):
    # Use default input selection (final_order.csv preferred)
    final_order = tmp_path / "outputs/final_order.csv"
    final_order.parent.mkdir(parents=True)
    with final_order.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id", "final_rank", "flags"])
        writer.writeheader()
        writer.writerow({"student_id": "s2", "final_rank": "2", "flags": ""})
        writer.writerow({"student_id": "s1", "final_rank": "1", "flags": ""})
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}", encoding="utf-8")
    out_csv = tmp_path / "grades.csv"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["rg", "--config", str(cfg), "--output", str(out_csv), "--non-interactive"])
    assert rg.main() == 0


def test_review_and_grade_single_row(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    with input_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id", "consensus_rank", "flags"])
        writer.writeheader()
        writer.writerow({"student_id": "s1", "consensus_rank": "1", "flags": ""})
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}", encoding="utf-8")
    out_csv = tmp_path / "grades.csv"
    monkeypatch.setattr("sys.argv", ["rg", "--input", str(input_csv), "--config", str(cfg), "--output", str(out_csv), "--non-interactive"])
    assert rg.main() == 0


def test_review_and_grade_no_rank_columns(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    with input_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id", "flags"])
        writer.writeheader()
        writer.writerow({"student_id": "s1", "flags": ""})
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}", encoding="utf-8")
    out_csv = tmp_path / "grades.csv"
    monkeypatch.setattr("sys.argv", ["rg", "--input", str(input_csv), "--config", str(cfg), "--output", str(out_csv), "--non-interactive"])
    assert rg.main() == 0


def test_review_and_grade_no_config_file(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    make_csv(input_csv)
    out_csv = tmp_path / "grades.csv"
    monkeypatch.setattr("sys.argv", ["rg", "--input", str(input_csv), "--config", str(tmp_path / "missing.json"), "--output", str(out_csv), "--non-interactive"])
    assert rg.main() == 0


def test_display_ranking_summary_limit():
    rows = [{"consensus_rank": "1", "student_id": "s1", "rubric_mean_percent": "80", "conventions_mistake_rate_percent": "1", "flags": ""}] * 12
    rg.display_ranking_summary(rows, limit=10)


def test_flagged_more_than_five(tmp_path, monkeypatch):
    input_csv = tmp_path / "consensus.csv"
    with input_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["student_id", "consensus_rank", "flags"])
        writer.writeheader()
        for i in range(6):
            writer.writerow({"student_id": f"s{i}", "consensus_rank": str(i + 1), "flags": "flag"})
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}", encoding="utf-8")
    out_csv = tmp_path / "grades.csv"
    monkeypatch.setattr("sys.argv", ["rg", "--input", str(input_csv), "--config", str(cfg), "--output", str(out_csv), "--non-interactive"])
    assert rg.main() == 0


def test_preview_curve_single():
    rows = [{"student_id": "s1"}]
    grades = rg.preview_curve(rows, 90, 80, "nearest")
    assert grades == [90]


def test_get_user_input_invalid(monkeypatch):
    inputs = iter(["bad", "3"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    assert rg.get_user_input("Test", 1, int) == 3


def test_get_user_input_default(monkeypatch):
    inputs = iter([""])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    assert rg.get_user_input("Test", 7, int) == 7
