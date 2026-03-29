import csv
import json
from pathlib import Path

import scripts.build_dashboard_data as bdd


def write_csv(path: Path, rows, fieldnames):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_build_dashboard_data(tmp_path, monkeypatch):
    fallback = tmp_path / "consensus.csv"
    rows = [{"student_id": "s1", "consensus_rank": "1"}]
    write_csv(fallback, rows, ["student_id", "consensus_rank"])

    grades = tmp_path / "grades.csv"
    write_csv(grades, [{"student_id": "s1", "final_grade": "90", "curve_top": "92", "curve_bottom": "58"}], ["student_id", "final_grade", "curve_top", "curve_bottom"])

    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "s1.txt").write_text("Essay", encoding="utf-8")
    feedback_dir = tmp_path / "feedback"
    feedback_dir.mkdir()
    (feedback_dir / "s1_feedback.md").write_text("Star 1", encoding="utf-8")

    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir()
    meta = inputs_dir / "class_metadata.json"
    meta.write_text(json.dumps({"grade_level": 7}), encoding="utf-8")

    out = tmp_path / "dash.json"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["bdd", "--input", str(tmp_path / "missing.csv"), "--fallback", str(fallback), "--grades", str(grades), "--texts", str(texts), "--feedback", str(feedback_dir), "--output", str(out)])
    assert bdd.main() == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["students"][0]["student_id"] == "s1"
    assert payload["curve_top"] == "92"
    assert payload["students"][0]["feedback_text"] == "Star 1"


def test_build_dashboard_helpers(tmp_path):
    assert bdd.load_csv(tmp_path / "missing.csv") == []
    assert bdd.load_texts(tmp_path / "missing_dir") == {}
    assert bdd.load_feedback_text(tmp_path / "missing_dir", "s1") == ""
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "s1 .txt").write_text("Essay", encoding="utf-8")
    assert bdd.load_texts(texts)["s1"] == "Essay"


def test_load_feedback_missing_file(tmp_path):
    feedback_dir = tmp_path / "feedback"
    feedback_dir.mkdir()
    assert bdd.load_feedback_text(feedback_dir, "s1") == ""


def test_build_dashboard_data_no_rows(tmp_path, monkeypatch):
    out = tmp_path / "dash.json"
    monkeypatch.setattr("sys.argv", ["bdd", "--input", str(tmp_path / "missing.csv"), "--fallback", str(tmp_path / "missing2.csv"), "--output", str(out)])
    assert bdd.main() == 1


def test_build_dashboard_data_no_grades(tmp_path, monkeypatch):
    fallback = tmp_path / "consensus.csv"
    rows = [{"student_id": "s1", "consensus_rank": "1"}]
    write_csv(fallback, rows, ["student_id", "consensus_rank"])
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "s1.txt").write_text("Essay", encoding="utf-8")
    out = tmp_path / "dash.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["bdd", "--input", str(tmp_path / "missing.csv"), "--fallback", str(fallback), "--output", str(out), "--texts", str(texts)])
    assert bdd.main() == 0


def test_build_dashboard_data_primary_input(tmp_path, monkeypatch):
    primary = tmp_path / "primary.csv"
    rows = [{"student_id": "s1", "final_rank": "1", "seed_rank": "2", "rerank_displacement": "-1", "rerank_notes": "moved_up_1"}]
    write_csv(primary, rows, ["student_id", "final_rank", "seed_rank", "rerank_displacement", "rerank_notes"])
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "consistency_report.json").write_text(json.dumps({"summary": {"pairwise_agreement_with_final_order": 1.0}}), encoding="utf-8")
    out = tmp_path / "dash.json"
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "s1.txt").write_text("Essay", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["bdd", "--input", str(primary), "--fallback", str(tmp_path / "missing.csv"), "--output", str(out), "--texts", str(texts)])
    assert bdd.main() == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["students"][0]["seed_rank"] == "2"
    assert payload["consistency_report"]["summary"]["pairwise_agreement_with_final_order"] == 1.0


def test_load_submission_metadata_variants(tmp_path):
    path = tmp_path / "m.json"
    path.write_text("not json", encoding="utf-8")
    assert bdd.load_submission_metadata(path) == {}
    path.write_text(json.dumps({"students": []}), encoding="utf-8")
    assert bdd.load_submission_metadata(path) == {}
    path.write_text(json.dumps([{"student_id": "s1", "display_name": "A"}]), encoding="utf-8")
    meta = bdd.load_submission_metadata(path)
    assert meta["s1"]["display_name"] == "A"


def test_build_dashboard_data_empty_feedback_and_cost_report(tmp_path, monkeypatch):
    fallback = tmp_path / "consensus.csv"
    rows = [{
        "student_id": "s1",
        "consensus_rank": "1",
        "rubric_mean_percent": "62",
        "rubric_after_penalty_percent": "61",
        "conventions_mistake_rate_percent": "9.4",
    }]
    write_csv(
        fallback,
        rows,
        ["student_id", "consensus_rank", "rubric_mean_percent", "rubric_after_penalty_percent", "conventions_mistake_rate_percent"],
    )
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "s1.txt").write_text("I think the theme is hope. Because the character keeps trying.", encoding="utf-8")
    out = tmp_path / "dash.json"
    cost = tmp_path / "usage_costs.json"
    cost.write_text(json.dumps({"currency": "USD", "grand_total": 1.2345}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "bdd",
            "--input",
            str(tmp_path / "missing.csv"),
            "--fallback",
            str(fallback),
            "--texts",
            str(texts),
            "--output",
            str(out),
            "--cost-report",
            str(cost),
        ],
    )
    assert bdd.main() == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["cost_report"]["grand_total"] == 1.2345
    assert payload["students"][0]["feedback_text"] == ""
    assert payload["distribution"]["cohort_size"] == 1
    assert payload["distribution"]["level_counts"]["2"] == 1


def test_feedback_helpers_cover_branches():
    assert bdd.num("x", 7.5) == 7.5
    assert bdd.sentences("") == []
    assert bdd.snippet("a" * 200).endswith("…")
    assert bdd.pick_sentence(["alpha", "beta"], ("zzz",)) == "alpha"
    long_text = " ".join(["Clear thesis sentence."] * 80)
    low_conv = bdd.fallback_feedback({"rubric_mean_percent": "85", "conventions_mistake_rate_percent": "2"}, long_text, 2, 10)
    low_rubric = bdd.fallback_feedback({"rubric_mean_percent": "61", "conventions_mistake_rate_percent": "2"}, "Claim. Evidence is here.", 4, 10)
    short = bdd.fallback_feedback({"rubric_mean_percent": "82", "conventions_mistake_rate_percent": "2"}, "Short text.", 5, 10)
    assert "tightening your thesis" in low_conv
    assert "deepen analysis" in low_rubric
    assert "expand your strongest idea" in short


def test_load_json_and_feedback_evidence_fallback(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert bdd.load_json(bad) == {}
    list_json = tmp_path / "list.json"
    list_json.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert bdd.load_json(list_json) == {}
    no_match = bdd.fallback_feedback({"rubric_mean_percent": "80", "conventions_mistake_rate_percent": "1"}, "", 1, 2)
    assert "Your opening establishes the topic clearly." in no_match


def test_build_dashboard_prefers_consistency_adjusted_when_primary_missing(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    consistency = outputs / "consistency_adjusted.csv"
    write_csv(consistency, [{"student_id": "s1", "consistency_rank": "1"}], ["student_id", "consistency_rank"])
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "s1.txt").write_text("Essay", encoding="utf-8")
    out = tmp_path / "dash.json"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["bdd", "--input", str(outputs / "final_order.csv"), "--fallback", str(tmp_path / "missing.csv"), "--output", str(out), "--texts", str(texts)],
    )
    assert bdd.main() == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["rank_key"] == "consistency_rank"
    assert payload["rank_source"].endswith("outputs/consistency_adjusted.csv")
