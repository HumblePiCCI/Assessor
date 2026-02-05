import json
import csv
from pathlib import Path

import scripts.aggregate_assessments as agg


def write_pass1(dir_path: Path, assessor_id: str, scores):
    data = {"assessor_id": assessor_id, "scores": scores}
    path = dir_path / f"{assessor_id}.json"
    path.write_text(json.dumps(data), encoding="utf-8")


def write_pass2(dir_path: Path, assessor_id: str, ranking):
    path = dir_path / f"{assessor_id}.txt"
    path.write_text("\n".join(ranking), encoding="utf-8")


def write_conventions(path: Path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_aggregate_assessments_success(tmp_path, monkeypatch):
    # Setup workspace
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)

    config = {
        "weights": {"rubric": 0.7, "conventions": 0.15, "comparative": 0.15},
        "consensus": {"rank_disagreement_threshold": 3, "rubric_sd_threshold": 0.8},
        "rubric": {"points_possible": None},
        "conventions": {"mistake_rate_threshold": 0.07, "max_level_drop": 1, "missing_data_mistake_rate_percent": 100.0},
        "levels": {"bands": [{"level": "1", "min": 50, "max": 59, "letter": "D"}, {"level": "4", "min": 80, "max": 89, "letter": "A"}, {"level": "4+", "min": 90, "max": 100, "letter": "A+"}]},
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(config), encoding="utf-8")

    pass1_dir = tmp_path / "assessments/pass1_individual"
    scores = [
        {"student_id": "s1", "rubric_total_points": 20},
        {"student_id": "s2", "rubric_total_points": 10},
    ]
    for assessor in ["a", "b", "c"]:
        write_pass1(pass1_dir, assessor, scores)

    pass2_dir = tmp_path / "assessments/pass2_comparative"
    for assessor in ["a", "b", "c"]:
        write_pass2(pass2_dir, assessor, ["s1", "s2"])

    conv_path = tmp_path / "processing/conventions_report.csv"
    write_conventions(conv_path, [
        {"student_id": "s1", "word_count": 100, "mistake_rate_percent": 1.0},
        {"student_id": "s2", "word_count": 100, "mistake_rate_percent": 10.0},
    ])

    out_path = tmp_path / "outputs/consensus_scores.csv"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["agg", "--config", str(cfg_path), "--output", str(out_path)])
    assert agg.main() == 0

    assert out_path.exists()
    data = out_path.read_text(encoding="utf-8")
    assert "composite_score" in data
    assert "level_with_modifier" in data
    # Ensure no 4++ for top band with + modifier
    assert "4++" not in data

    irr_path = tmp_path / "outputs/irr_metrics.json"
    assert irr_path.exists()


def test_aggregate_assessments_missing_data(tmp_path, monkeypatch):
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"weights": {}, "consensus": {}, "conventions": {}, "rubric": {}}), encoding="utf-8")

    pass1_dir = tmp_path / "assessments/pass1_individual"
    write_pass1(pass1_dir, "a", [{"student_id": "s1", "rubric_total_points": 1}])
    write_pass1(pass1_dir, "b", [{"student_id": "s1", "rubric_total_points": 1}])

    pass2_dir = tmp_path / "assessments/pass2_comparative"
    write_pass2(pass2_dir, "a", ["s1"])
    # Missing pass2 for assessor b

    conv_path = tmp_path / "processing/conventions_report.csv"
    write_conventions(conv_path, [{"student_id": "s1", "word_count": 10, "mistake_rate_percent": 0.0}])

    out_path = tmp_path / "outputs/consensus_scores.csv"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["agg", "--config", str(cfg_path), "--output", str(out_path)])
    assert agg.main() == 1

    monkeypatch.setattr("sys.argv", ["agg", "--config", str(cfg_path), "--output", str(out_path), "--allow-missing-data"])
    assert agg.main() == 0


def test_aggregate_assessments_missing_conventions_allowed(tmp_path, monkeypatch):
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"weights": {}, "consensus": {}, "conventions": {"missing_data_mistake_rate_percent": 99.0}, "rubric": {}}), encoding="utf-8")

    pass1_dir = tmp_path / "assessments/pass1_individual"
    for assessor in ["a", "b", "c"]:
        write_pass1(pass1_dir, assessor, [{"student_id": "s1", "rubric_total_points": 1}])

    pass2_dir = tmp_path / "assessments/pass2_comparative"
    for assessor in ["a", "b", "c"]:
        write_pass2(pass2_dir, assessor, ["s1"])

    # No conventions report written
    out_path = tmp_path / "outputs/consensus_scores.csv"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["agg", "--config", str(cfg_path), "--output", str(out_path), "--allow-missing-data"])
    assert agg.main() == 0


def test_aggregate_assessments_rubric_points_from_assessor(tmp_path, monkeypatch):
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"weights": {}, "consensus": {}, "conventions": {}, "rubric": {"points_possible": None}}), encoding="utf-8")

    pass1_dir = tmp_path / "assessments/pass1_individual"
    scores = [{"student_id": "s1", "rubric_total_points": None, "criteria_points": {"c1": 5, "c2": 5}}]
    for assessor in ["a", "b", "c"]:
        data = {"assessor_id": assessor, "rubric_points_possible": 20, "scores": scores}
        (pass1_dir / f"{assessor}.json").write_text(json.dumps(data), encoding="utf-8")

    pass2_dir = tmp_path / "assessments/pass2_comparative"
    for assessor in ["a", "b", "c"]:
        write_pass2(pass2_dir, assessor, ["s1"])

    conv_path = tmp_path / "processing/conventions_report.csv"
    write_conventions(conv_path, [{"student_id": "s1", "word_count": 10, "mistake_rate_percent": 0.0}])

    out_path = tmp_path / "outputs/consensus_scores.csv"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["agg", "--config", str(cfg_path), "--output", str(out_path)])
    assert agg.main() == 0

    rows = out_path.read_text(encoding="utf-8")
    assert "rubric_after_penalty_percent" in rows


def test_aggregate_assessments_many_errors_and_flags(tmp_path, monkeypatch):
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)

    cfg = {
        "weights": {},
        "consensus": {"rubric_sd_threshold": 0.1, "rank_disagreement_threshold": 0.1},
        "conventions": {"mistake_rate_threshold": 0.01, "max_level_drop": 1, "missing_data_mistake_rate_percent": 100.0},
        "rubric": {"points_possible": None},
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    # Pass1: only s1 has scores, with high variance
    pass1_dir = tmp_path / "assessments/pass1_individual"
    scores_a = [{"student_id": "s1", "rubric_total_points": 0}]
    scores_b = [{"student_id": "s1", "rubric_total_points": 100}]
    scores_c = [{"student_id": "s1", "rubric_total_points": 50}]
    write_pass1(pass1_dir, "a", scores_a)
    write_pass1(pass1_dir, "b", scores_b)
    write_pass1(pass1_dir, "c", scores_c)

    # Pass2: rankings with different orders and one missing student to trigger missing_rank
    students = ["s1"] + [f"s{i}" for i in range(2, 13)]
    pass2_dir = tmp_path / "assessments/pass2_comparative"
    write_pass2(pass2_dir, "a", students)
    write_pass2(pass2_dir, "b", students[1:] + ["s1"])  # move s1 to last
    write_pass2(pass2_dir, "c", students[:-1])  # omit s12

    # Conventions: only s1 to trigger missing conventions for others
    conv_path = tmp_path / "processing/conventions_report.csv"
    write_conventions(conv_path, [{"student_id": "s1", "word_count": 100, "mistake_rate_percent": 50.0}])

    out_path = tmp_path / "outputs/consensus_scores.csv"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["agg", "--config", str(cfg_path), "--output", str(out_path), "--allow-missing-data"])
    assert agg.main() == 0

    rows = list(csv.DictReader(out_path.open("r", encoding="utf-8")))
    s1 = next(r for r in rows if r["student_id"] == "s1")
    assert "rubric_sd" in s1["flags"]
    assert "rank_sd" in s1["flags"]
    assert "conventions_penalty" in s1["flags"]


def test_aggregate_assessments_bias_and_criteria_points(tmp_path, monkeypatch):
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)
    (tmp_path / "outputs").mkdir(parents=True)

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"weights": {}, "consensus": {}, "conventions": {}, "rubric": {"points_possible": None}}), encoding="utf-8")

    criteria_path = tmp_path / "rubric_criteria.json"
    criteria_path.write_text(json.dumps({"categories": {"c1": {"max_points": 100, "criteria": []}}}), encoding="utf-8")

    pass1_dir = tmp_path / "assessments/pass1_individual"
    scores = [{"student_id": "s1", "rubric_total_points": 90}]
    for assessor in ["assessor_a", "assessor_b", "assessor_c"]:
        write_pass1(pass1_dir, assessor, scores)

    pass2_dir = tmp_path / "assessments/pass2_comparative"
    for assessor in ["a", "b", "c"]:
        write_pass2(pass2_dir, assessor, ["s1"])

    conv_path = tmp_path / "processing/conventions_report.csv"
    write_conventions(conv_path, [{"student_id": "s1", "word_count": 10, "mistake_rate_percent": 0.0}])

    bias_path = tmp_path / "outputs/calibration_bias.json"
    bias_path.write_text(json.dumps({"assessors": {"assessor_a": {"bias": 10}}}), encoding="utf-8")

    out_path = tmp_path / "outputs/consensus_scores.csv"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", [
        "agg",
        "--config", str(cfg_path),
        "--output", str(out_path),
        "--rubric-criteria", str(criteria_path),
        "--calibration-bias", str(bias_path),
    ])
    assert agg.main() == 0
    rows = list(csv.DictReader(out_path.open("r", encoding="utf-8")))
    assert float(rows[0]["rubric_mean_percent"]) < 90.0
    assert len(rows) == 1


def test_aggregate_assessments_no_level_band(tmp_path, monkeypatch):
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True)
    (tmp_path / "processing").mkdir(parents=True)

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"weights": {}, "consensus": {}, "conventions": {}, "rubric": {}}), encoding="utf-8")

    pass1_dir = tmp_path / "assessments/pass1_individual"
    for assessor in ["a", "b", "c"]:
        write_pass1(pass1_dir, assessor, [{"student_id": "s1", "rubric_total_points": 1}])

    pass2_dir = tmp_path / "assessments/pass2_comparative"
    for assessor in ["a", "b", "c"]:
        write_pass2(pass2_dir, assessor, ["s1"])

    conv_path = tmp_path / "processing/conventions_report.csv"
    write_conventions(conv_path, [{"student_id": "s1", "word_count": 10, "mistake_rate_percent": 0.0}])

    out_path = tmp_path / "outputs/consensus_scores.csv"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(agg, "get_level_band", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("sys.argv", ["agg", "--config", str(cfg_path), "--output", str(out_path)])
    assert agg.main() == 0
