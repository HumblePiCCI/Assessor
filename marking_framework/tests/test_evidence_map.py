import json
from pathlib import Path

from scripts import evidence_map as em


def candidate(pair, active_winner, recommended_winner, confidence="high", margin=2.0):
    left, right = pair
    return {
        "pair": [left, right],
        "pair_key": "::".join(sorted(pair)),
        "escalated_summary": {"winner": active_winner},
        "evidence_map_pair_signal": {
            "pair": [left, right],
            "pair_key": "::".join(sorted(pair)),
            "recommended_winner": recommended_winner,
            "active_winner": active_winner,
            "confidence": confidence,
            "margin": margin,
            "scores": {left: 10.0, right: 9.0},
            "reasons": ["fixture signal"],
            "contradicts_active_winner": recommended_winner not in {"tie", active_winner},
        },
    }


def maps(*student_ids):
    return {
        student_id: {"summary": {"evidence_map_score": float(100 - index), "completion_floor_applied": False}}
        for index, student_id in enumerate(student_ids)
    }


def test_extract_evidence_units_counts_claim_moments_and_commentary():
    text = (
        "Ghost changes because Coach gives him a second chance. "
        "When Ghost steals the shoes, Coach makes him apologize. "
        "This shows that accountability helps Ghost heal."
    )
    units = em.extract_evidence_units(text)
    summary = em.score_evidence_map(text, units, genre="literary_analysis")

    assert summary["claim_count"] >= 1
    assert summary["text_evidence_unit_count"] >= 2
    assert summary["commentary_unit_count"] >= 2
    assert summary["explained_moment_count"] >= 1
    assert "shoe_theft" in summary["text_moments"]
    assert "accountability" in summary["literary_concepts"]


def test_completion_floor_uses_draft_quality():
    text = "\n".join(
        [
            "Thesis:",
            "Evidence 1:",
            "Analysis: because",
            "Evidence 2:",
            "Conclusion:",
        ]
    )
    student_map = em.build_student_evidence_map("s001", text, genre="literary_analysis")
    summary = student_map["summary"]

    assert summary["completion_floor_applied"] is True
    assert summary["band_signal"] == "completion_floor"
    assert summary["evidence_map_score"] < 0


def test_pair_signal_prefers_commentary_over_polished_summary():
    polished_summary = "\n\n".join(
        [
            "First, Ghost has consequences. He steals shoes. He gets punished.",
            "Second, Coach helps him. Ghost runs track. Ghost learns a lesson.",
            "In conclusion, Ghost changes. The paragraph is clean and organized.",
        ]
    )
    rougher_analysis = (
        "Ghost steals the shoes because shame controls him after people laugh. "
        "Coach makes him return them, which shows accountability can become support. "
        "The punishment reveals that Ghost heals when adults hold him responsible."
    )
    maps = em.build_evidence_maps(
        {"clean": polished_summary, "rough": rougher_analysis},
        genre="literary_analysis",
    )
    signal = em.compare_evidence_maps("clean", "rough", maps)

    assert signal["recommended_winner"] == "rough"
    assert signal["confidence"] in {"medium", "high"}
    assert maps["rough"]["summary"]["commentary_unit_count"] >= maps["clean"]["summary"]["commentary_unit_count"]


def test_ghost_residual_shaped_pairs_prefer_human_winners():
    texts = {
        "s015": (
            "First, Ghost makes choices. He steals shoes. He gets consequences. "
            "Second, Coach punishes him. In conclusion choices have consequences."
        ),
        "s009": (
            "Ghost runs from the gunshot because trauma controls his choices. "
            "When Coach gives him support, it reveals that accountability helps him heal. "
            "The shoe apology shows that trust can turn punishment into growth."
        ),
        "s003": (
            "Ghost joins track. Brandon throws food. Ghost steals shoes. Coach gets mad. "
            "Then Ghost runs more and learns consequences. The story has many events."
        ),
        "s013": (
            "Castle names himself Ghost because the shooting makes him want to disappear. "
            "His shoes and world-record dreams reveal a struggle with identity and self worth. "
            "By running with the team, he starts to believe he can become somebody."
        ),
        "s019": (
            "Trust is important. Mr. Charles helps Ghost. Coach helps Ghost. "
            "His mom helps Ghost. The team helps Ghost. Trust can be broken and rebuilt."
        ),
        "s022": (
            "Ghost gets second chances because adults believe he can change. "
            "Coach lets him race and later makes him repair the shoe theft, which shows faith with accountability. "
            "Mr. Charles and Ghost's mother also give him chances to change his course. "
            "This reveals that support matters only when it helps Ghost take responsibility."
        ),
        "s004": (
            "Sports gives structure. Ghost joins track. Coach gives laps. "
            "Ghost becomes nicer and confident."
        ),
        "s008": (
            "Coach leads Ghost because he sees a kid who needs direction. "
            "The dinner scene shows belonging, and the shoe punishment reveals leadership through responsibility. "
            "Ghost standing up for Sunny shows he is learning to lead himself and others."
        ),
    }
    maps = em.build_evidence_maps(texts, genre="literary_analysis")
    expected = {
        ("s009", "s015"): "s009",
        ("s009", "s003"): "s009",
        ("s013", "s003"): "s013",
        ("s022", "s019"): "s022",
        ("s008", "s004"): "s008",
    }

    for pair, winner in expected.items():
        signal = em.compare_evidence_maps(pair[0], pair[1], maps)
        assert signal["recommended_winner"] == winner, (pair, signal)


def test_cli_writes_map_and_pair_signals(tmp_path, monkeypatch):
    texts = tmp_path / "processing" / "normalized_text"
    texts.mkdir(parents=True)
    (texts / "s001.txt").write_text(
        "Ghost steals shoes because he feels shame. Coach makes him apologize, which shows accountability.",
        encoding="utf-8",
    )
    (texts / "s002.txt").write_text(
        "Ghost steals shoes. Coach is mad. Ghost runs track.",
        encoding="utf-8",
    )
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "class_metadata.json").write_text(json.dumps({"assignment_genre": "literary_analysis"}), encoding="utf-8")
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    candidates = outputs / "committee_edge_candidates.json"
    candidates.write_text(
        json.dumps({"candidates": [{"pair": ["s001", "s002"]}], "skipped": []}),
        encoding="utf-8",
    )
    output = outputs / "evidence_map.json"
    pair_output = outputs / "evidence_map_pair_signals.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "evidence_map",
            "--texts",
            str(texts),
            "--class-metadata",
            str(inputs / "class_metadata.json"),
            "--output",
            str(output),
            "--candidates",
            str(candidates),
            "--pair-signals-output",
            str(pair_output),
        ],
    )

    assert em.main() == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    pairs = json.loads(pair_output.read_text(encoding="utf-8"))
    assert payload["student_count"] == 2
    assert payload["students"]["s001"]["summary"]["band_signal"] in {
        "developing_analysis",
        "solid_analysis",
        "strong_substantive_analysis",
    }
    assert pairs["pair_count"] == 1
    assert pairs["pair_signals"][0]["recommended_winner"] == "s001"


def test_neighborhood_report_classifies_pair_guard_and_group_components():
    report = em.build_evidence_neighborhood_report(
        maps_by_id=maps("s009", "s015", "s003", "s013", "s022", "s019", "s008", "s004"),
        rows=[
            {"student_id": "s015", "seed_rank": "1"},
            {"student_id": "s003", "seed_rank": "2"},
            {"student_id": "s009", "seed_rank": "3"},
            {"student_id": "s013", "seed_rank": "4"},
            {"student_id": "s022", "seed_rank": "5"},
            {"student_id": "s019", "seed_rank": "6"},
            {"student_id": "s004", "seed_rank": "7"},
            {"student_id": "s008", "seed_rank": "8"},
        ],
        candidates=[
            candidate(("s015", "s009"), "s015", "s009", "high", 4.0),
            candidate(("s003", "s009"), "s003", "s009", "high", 4.0),
            candidate(("s003", "s013"), "s003", "tie", "low", 0.2),
            candidate(("s022", "s019"), "s019", "s022", "medium", 1.0),
            candidate(("s004", "s008"), "s004", "s008", "high", 5.0),
        ],
    )

    actions = {tuple(neighborhood["student_ids"]): neighborhood["recommended_next_action"] for neighborhood in report["neighborhoods"]}
    assert actions[("s015", "s003", "s009", "s013")] == "needs_group_calibration"
    assert actions[("s022", "s019")] == "pair_guard_only"
    assert actions[("s004", "s008")] == "pair_guard_only"
    top = next(n for n in report["neighborhoods"] if set(n["student_ids"]) == {"s015", "s003", "s009", "s013"})
    assert {edge["pair_key"] for edge in top["ambiguous_edges"]} == {"s003::s013"}
    assert top["evidence_order"][0] == "s009"


def test_neighborhood_report_disabled_without_evidence_map():
    report = em.build_evidence_neighborhood_report(
        maps_by_id={},
        rows=[],
        candidates=[candidate(("a", "b"), "a", "b")],
    )

    assert report["enabled"] is False
    assert report["reason"] == "evidence_map_missing"
    assert report["neighborhoods"] == []
