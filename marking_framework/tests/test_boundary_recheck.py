import csv
import json

import scripts.boundary_recheck as br


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_helper_selection_and_update():
    rows = [
        {"student_id": "s1", "rubric_after_penalty_percent": "79.6"},
        {"student_id": "s2", "rubric_after_penalty_percent": "82"},
        {"student_id": "s3", "rubric_after_penalty_percent": "bad"},
    ]
    picked = br.select_boundary_students(rows, [80.0], 2.0, 2)
    assert [p["student_id"] for p in picked] == ["s1", "s2"]
    assert br._safe_score({"rubric_after_penalty_percent": "bad"}) == 0.0
    item = {"rubric_total_points": 70, "criteria_points": {"k1": 60}, "notes": "start"}
    br.apply_score_update(item, 80)
    assert item["rubric_total_points"] == 80.0
    assert item["criteria_points"]["k1"] == 70.0
    assert "Boundary recheck" in item["notes"]
    score, capped = br.capped_score(70.0, 90.0, 4.0)
    assert score == 74.0 and capped is True
    score2, capped2 = br.capped_score(70.0, 72.0, 4.0)
    assert score2 == 72.0 and capped2 is False


def test_assessor_role_and_find_score():
    assert br.assessor_role("assessor_A") == "A"
    assert br.assessor_role("teacher_b") == "B"
    assert br.assessor_role("") == "A"
    scores = [{"student_id": "s1"}]
    assert br.find_score_item(scores, "s1") is scores[0]
    assert br.find_score_item(scores, "missing") is None


def test_loaders_and_boundaries(tmp_path):
    consensus = tmp_path / "consensus.csv"
    _write_csv(consensus, [{"student_id": "s1", "rubric_after_penalty_percent": "70"}])
    assert len(br.load_consensus(consensus)) == 1
    texts_dir = tmp_path / "texts"
    texts_dir.mkdir()
    (texts_dir / "s1.txt").write_text("essay", encoding="utf-8")
    assert br.load_texts(texts_dir)["s1"] == "essay"
    cfg = tmp_path / "marking_config.json"
    cfg.write_text(json.dumps({"levels": {"bands": [{"min": 50}, {"min": 60}, {"min": 70}]}}), encoding="utf-8")
    assert br.load_level_boundaries(cfg) == [60.0, 70.0]


def test_write_json(tmp_path):
    path = tmp_path / "out.json"
    br.write_json(path, {"ok": True})
    assert json.loads(path.read_text(encoding="utf-8"))["ok"] is True


def test_main_requires_api_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config/llm_routing.json").write_text(json.dumps({"mode": "openai"}), encoding="utf-8")
    _write_csv(tmp_path / "outputs/consensus_scores.csv", [{"student_id": "s1", "rubric_after_penalty_percent": "70"}])
    (tmp_path / "config/marking_config.json").write_text(json.dumps({"levels": {"bands": [{"min": 50}, {"min": 60}]}}), encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODE", raising=False)
    monkeypatch.setattr("sys.argv", ["boundary_recheck"])
    assert br.main() == 1


def test_main_no_boundary_students(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config/llm_routing.json").write_text(json.dumps({"mode": "codex_local"}), encoding="utf-8")
    _write_csv(tmp_path / "outputs/consensus_scores.csv", [{"student_id": "s1", "rubric_after_penalty_percent": "73"}])
    (tmp_path / "config/marking_config.json").write_text(
        json.dumps({"levels": {"bands": [{"min": 50}, {"min": 60}, {"min": 70}, {"min": 80}]}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_MODE", "codex_local")
    monkeypatch.setattr("sys.argv", ["boundary_recheck"])
    assert br.main() == 0
    out = json.loads((tmp_path / "outputs/boundary_recheck.json").read_text(encoding="utf-8"))
    assert out["status"] == "no_boundary_students"


def test_main_updates_boundary_scores(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    routing = {
        "mode": "codex_local",
        "tasks": {"pass1_assessor": {"model": "gpt-5.2", "reasoning": "low", "temperature": 0.0}},
    }
    (tmp_path / "config/llm_routing.json").write_text(json.dumps(routing), encoding="utf-8")
    _write_csv(
        tmp_path / "outputs/consensus_scores.csv",
        [{"student_id": "s1", "rubric_after_penalty_percent": "79.5", "adjusted_level": "3"}],
    )
    (tmp_path / "config/marking_config.json").write_text(
        json.dumps({"levels": {"bands": [{"min": 50}, {"min": 60}, {"min": 70}, {"min": 80}, {"min": 90}]}}),
        encoding="utf-8",
    )
    (tmp_path / "processing/normalized_text").mkdir(parents=True, exist_ok=True)
    (tmp_path / "processing/normalized_text/s1.txt").write_text("Student essay text", encoding="utf-8")
    (tmp_path / "inputs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "inputs/rubric.md").write_text("Rubric text", encoding="utf-8")
    (tmp_path / "inputs/assignment_outline.md").write_text("Outline text", encoding="utf-8")
    (tmp_path / "inputs/class_metadata.json").write_text(json.dumps({"grade_level": 8, "assignment_genre": "argumentative"}), encoding="utf-8")
    (tmp_path / "config/grade_level_profiles.json").write_text(json.dumps({}), encoding="utf-8")
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True, exist_ok=True)
    pass1 = {
        "assessor_id": "assessor_A",
        "scores": [
            {"student_id": "s1", "rubric_total_points": 70.0, "criteria_points": {"k1": 65.0}, "notes": "base"}
        ],
    }
    (tmp_path / "assessments/pass1_individual/assessor_A.json").write_text(json.dumps(pass1), encoding="utf-8")

    monkeypatch.setenv("LLM_MODE", "codex_local")

    def fake_responses_create(**_kwargs):
        return {"output": [{"type": "output_text", "text": '{"student_id":"s1","rubric_total_points":80,"criteria_points":[],"notes":"ok"}'}]}

    monkeypatch.setattr(br, "responses_create", fake_responses_create)
    monkeypatch.setattr(br, "extract_text", lambda resp: resp["output"][0]["text"])
    monkeypatch.setattr(
        "sys.argv",
        [
            "boundary_recheck",
            "--replicates",
            "2",
            "--max-students",
            "5",
            "--margin",
            "1.0",
        ],
    )
    assert br.main() == 0
    updated = json.loads((tmp_path / "assessments/pass1_individual/assessor_A.json").read_text(encoding="utf-8"))
    score = updated["scores"][0]["rubric_total_points"]
    assert score == 74.0
    assert updated["scores"][0]["criteria_points"]["k1"] == 69.0
    report = json.loads((tmp_path / "outputs/boundary_recheck.json").read_text(encoding="utf-8"))
    assert report["updated"] == 1
    assert report["updates"][0]["capped"] is True


def test_main_handles_recheck_failures(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    routing = {
        "mode": "codex_local",
        "tasks": {"pass1_assessor": {"model": "gpt-5.2", "reasoning": "low", "temperature": 0.0}},
    }
    (tmp_path / "config/llm_routing.json").write_text(json.dumps(routing), encoding="utf-8")
    _write_csv(
        tmp_path / "outputs/consensus_scores.csv",
        [{"student_id": "s1", "rubric_after_penalty_percent": "79.9", "adjusted_level": "3"}],
    )
    (tmp_path / "config/marking_config.json").write_text(
        json.dumps({"levels": {"bands": [{"min": 50}, {"min": 60}, {"min": 70}, {"min": 80}]}}),
        encoding="utf-8",
    )
    (tmp_path / "processing/normalized_text").mkdir(parents=True, exist_ok=True)
    (tmp_path / "processing/normalized_text/s1.txt").write_text("Student essay text", encoding="utf-8")
    (tmp_path / "inputs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "inputs/rubric.md").write_text("Rubric text", encoding="utf-8")
    (tmp_path / "inputs/assignment_outline.md").write_text("Outline text", encoding="utf-8")
    (tmp_path / "inputs/class_metadata.json").write_text(json.dumps({"grade_level": 8, "assignment_genre": "argumentative"}), encoding="utf-8")
    (tmp_path / "config/grade_level_profiles.json").write_text(json.dumps({}), encoding="utf-8")
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True, exist_ok=True)
    pass1 = {"assessor_id": "assessor_A", "scores": [{"student_id": "s1", "rubric_total_points": 70.0, "notes": "base"}]}
    (tmp_path / "assessments/pass1_individual/assessor_A.json").write_text(json.dumps(pass1), encoding="utf-8")

    monkeypatch.setenv("LLM_MODE", "codex_local")
    monkeypatch.setattr(br, "responses_create", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr("sys.argv", ["boundary_recheck", "--replicates", "1"])
    assert br.main() == 0
    report = json.loads((tmp_path / "outputs/boundary_recheck.json").read_text(encoding="utf-8"))
    assert report["updated"] == 0
