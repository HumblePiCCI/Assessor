import csv
import json
from pathlib import Path

from scripts import committee_edge_resolver as cer


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "committee_edge"


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def base_rows():
    return [
        {
            "student_id": "s015",
            "seed_rank": "2",
            "consensus_rank": "2",
            "adjusted_level": "3",
            "composite_score": "0.60",
            "borda_percent": "0.60",
        },
        {
            "student_id": "s009",
            "seed_rank": "3",
            "consensus_rank": "3",
            "adjusted_level": "3",
            "composite_score": "0.91",
            "borda_percent": "0.92",
        },
        {
            "student_id": "s013",
            "seed_rank": "5",
            "consensus_rank": "5",
            "adjusted_level": "3",
            "composite_score": "0.80",
            "borda_percent": "0.80",
        },
        {
            "student_id": "s003",
            "seed_rank": "6",
            "consensus_rank": "6",
            "adjusted_level": "3",
            "composite_score": "0.70",
            "borda_percent": "0.70",
        },
    ]


def fixture_payload():
    return json.loads((FIXTURE_DIR / "escalated_ghost_mini.json").read_text(encoding="utf-8"))


def surface_texts():
    return {
        "s015": "\n\n".join(
            [
                "First, Ghost has consequences. He steals shoes. He runs fast. He learns a lesson. The paragraph is organized and complete.",
                "Second, Coach gives consequences. The team helps. Ghost changes. This paragraph has clean transitions and a clear topic sentence.",
                "Another reason is consequences. Ghost gets in trouble. He works hard. The essay stays neat and easy to follow.",
                "In conclusion, Ghost learns about consequences. The final paragraph repeats the claim with polished control.",
            ]
        ),
        "s009": (
            "Ghost keeps running because fear controls him after the gunshot. "
            "Coach's support reveals that trust is what lets him face consequences. "
            "This demonstrates growth because accountability becomes a way to heal."
        ),
        "s013": "Kyle explains support because it changes Ghost.",
        "s003": "Easton summarizes the plot.",
    }


def test_passthrough_when_no_decisions_preserves_checks_identical(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    inputs = tmp_path / "inputs"
    processing = tmp_path / "processing" / "normalized_text"
    outputs.mkdir()
    inputs.mkdir()
    processing.mkdir(parents=True)
    escalated = outputs / "consistency_checks.escalated.json"
    payload = fixture_payload()
    escalated.write_text(json.dumps(payload), encoding="utf-8")
    scores = outputs / "consensus_scores.csv"
    write_csv(scores, base_rows())
    (inputs / "class_metadata.json").write_text(json.dumps({"assignment_genre": "literary_analysis"}), encoding="utf-8")
    for student_id, text in surface_texts().items():
        (processing / f"{student_id}.txt").write_text(text, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "cer",
            "--escalated",
            str(escalated),
            "--scores",
            str(scores),
            "--class-metadata",
            str(inputs / "class_metadata.json"),
            "--texts",
            str(processing),
            "--candidates-output",
            str(outputs / "committee_edge_candidates.json"),
            "--decisions-output",
            str(outputs / "committee_edge_decisions.json"),
            "--report-output",
            str(outputs / "committee_edge_report.json"),
            "--merged-output",
            str(outputs / "consistency_checks.committee_edge.json"),
        ],
    )

    assert cer.main() == 0
    merged = json.loads((outputs / "consistency_checks.committee_edge.json").read_text(encoding="utf-8"))
    decisions = json.loads((outputs / "committee_edge_decisions.json").read_text(encoding="utf-8"))
    assert merged["checks"] == payload["checks"]
    assert merged["committee_edge"]["passthrough"] is True
    assert decisions["decisions"] == []


def test_trigger_polish_bias_suspected_selects_pair():
    payload = fixture_payload()
    candidates = cer.build_candidates(
        escalated_checks=payload["checks"],
        escalation_candidates={},
        matrix={},
        rows=base_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(),
        texts_by_id=surface_texts(),
    )
    candidate = next(item for item in candidates if item["pair_key"] == "s009::s015")
    assert "polish_bias_suspected" in candidate["triggers"]
    assert "rougher_but_stronger_latent" in candidate["triggers"]
    assert candidate["selection_status"] == ""


def test_trigger_rougher_but_stronger_latent_requires_aggregate_support():
    payload = fixture_payload()
    positive = cer.build_candidates(
        escalated_checks=payload["checks"],
        escalation_candidates={},
        matrix={},
        rows=base_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(min_trigger_score=1),
        texts_by_id=surface_texts(),
    )
    assert "rougher_but_stronger_latent" in next(item for item in positive if item["pair_key"] == "s009::s015")["triggers"]

    rows = base_rows()
    for row in rows:
        if row["student_id"] == "s009":
            row["composite_score"] = "0.50"
            row["borda_percent"] = "0.50"
    negative = cer.build_candidates(
        escalated_checks=payload["checks"],
        escalation_candidates={},
        matrix={},
        rows=rows,
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(min_trigger_score=1),
        texts_by_id=surface_texts(),
    )
    assert "rougher_but_stronger_latent" not in next(item for item in negative if item["pair_key"] == "s009::s015")["triggers"]


def test_trigger_escalated_vs_direct_matrix_conflict():
    payload = fixture_payload()
    matrix = {
        "comparisons": [
            {
                "pair": ["s015", "s009"],
                "left_over_right_weight": 0.0,
                "right_over_left_weight": 2.0,
            }
        ]
    }
    candidates = cer.build_candidates(
        escalated_checks=payload["checks"],
        escalation_candidates={},
        matrix=matrix,
        rows=base_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(),
        texts_by_id=surface_texts(),
    )
    assert "escalated_vs_direct_matrix_conflict" in next(item for item in candidates if item["pair_key"] == "s009::s015")["triggers"]


def test_trigger_cohort_confidence_missing_is_silent():
    assert cer.load_optional_json(Path("/definitely/not/here.json")) == {}
    payload = fixture_payload()
    candidates = cer.build_candidates(
        escalated_checks=payload["checks"],
        escalation_candidates={},
        matrix={},
        rows=base_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(),
        texts_by_id=surface_texts(),
    )
    assert all("cohort_confidence_unstable" not in item["triggers"] for item in candidates)


def test_budget_caps_enforced_per_bucket():
    candidates = [
        {
            "pair_key": f"s{i}::t{i}",
            "committee_score": 100 - i,
            "bucket": "top_pack",
            "seed_order": {"higher_rank": i + 1, "lower_rank": i + 2},
        }
        for i in range(3)
    ]
    selected, skipped, budget = cer.select_within_budget(
        candidates,
        config=cer.CandidateConfig(max_candidates=3, max_top_pack=1),
    )
    assert len(selected) == 1
    assert len(skipped) == 2
    assert skipped[0]["skip_reason"] == "max_top_pack_committee_edges_exceeded"
    assert budget["selected_bucket_counts"]["top_pack"] == 1


def test_committee_score_is_deterministic_under_input_reordering():
    payload = fixture_payload()
    kwargs = dict(
        escalation_candidates={},
        matrix={},
        rows=base_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(),
        texts_by_id=surface_texts(),
    )
    first = cer.build_candidates(escalated_checks=payload["checks"], **kwargs)
    second = cer.build_candidates(escalated_checks=list(reversed(payload["checks"])), **kwargs)
    assert first == second


def test_min_trigger_score_filters_weak_signals():
    check = {
        "pair": ["s013", "s003"],
        "seed_order": {"higher": "s013", "lower": "s003", "higher_rank": 5, "lower_rank": 6},
        "winner_side": "A",
        "decision": "KEEP",
        "confidence": "high",
        "decision_basis": "content_reasoning",
        "model_metadata": {"adjudication_source": "escalated_adjudication"},
    }
    candidates = cer.build_candidates(
        escalated_checks=[check],
        escalation_candidates={},
        matrix={},
        rows=base_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(),
        texts_by_id=surface_texts(),
    )
    assert candidates == []


def test_already_committee_edge_source_is_not_a_candidate():
    check = fixture_payload()["checks"][0]
    check = {**check, "model_metadata": {"adjudication_source": "committee_edge"}}
    candidates = cer.build_candidates(
        escalated_checks=[check],
        escalation_candidates={},
        matrix={},
        rows=base_rows(),
        band_seam_report={},
        cohort_confidence={},
        genre="literary_analysis",
        config=cer.CandidateConfig(min_trigger_score=1),
        texts_by_id=surface_texts(),
    )
    assert candidates == []


def test_decisions_fixture_supersedes_escalated_in_merged_file(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    inputs = tmp_path / "inputs"
    processing = tmp_path / "processing" / "normalized_text"
    outputs.mkdir()
    inputs.mkdir()
    processing.mkdir(parents=True)
    escalated = outputs / "consistency_checks.escalated.json"
    escalated.write_text(json.dumps(fixture_payload()), encoding="utf-8")
    scores = outputs / "consensus_scores.csv"
    write_csv(scores, base_rows())
    (inputs / "class_metadata.json").write_text(json.dumps({"assignment_genre": "literary_analysis"}), encoding="utf-8")
    for student_id, text in surface_texts().items():
        (processing / f"{student_id}.txt").write_text(text, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "cer",
            "--escalated",
            str(escalated),
            "--scores",
            str(scores),
            "--class-metadata",
            str(inputs / "class_metadata.json"),
            "--texts",
            str(processing),
            "--decisions",
            str(FIXTURE_DIR / "committee_decisions_one_override.json"),
            "--candidates-output",
            str(outputs / "committee_edge_candidates.json"),
            "--decisions-output",
            str(outputs / "committee_edge_decisions.json"),
            "--report-output",
            str(outputs / "committee_edge_report.json"),
            "--merged-output",
            str(outputs / "consistency_checks.committee_edge.json"),
        ],
    )

    assert cer.main() == 0
    merged = json.loads((outputs / "consistency_checks.committee_edge.json").read_text(encoding="utf-8"))
    assert merged["committee_edge"]["passthrough"] is False
    assert merged["committee_edge"]["decision_count"] == 1
    assert merged["checks"][0]["model_metadata"]["superseded_by_committee_edge"] is True
    assert merged["checks"][-1]["model_metadata"]["adjudication_source"] == "committee_edge"
    assert merged["checks"][-1]["winner"] == "s009"


def test_merged_file_has_expected_top_level_keys():
    payload = fixture_payload()
    merged = cer.merged_checks_payload(
        escalated_payload=payload,
        escalated_checks=payload["checks"],
        decisions=[],
        candidates=[],
        budget={"selected": 0, "skipped": 0},
    )
    assert {"generated_at", "checks", "pairwise_escalation", "committee_edge"} <= set(merged)
    assert merged["committee_edge"]["phase"] == 1


def test_main_returns_1_when_escalated_file_missing(tmp_path, monkeypatch):
    report = tmp_path / "report.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "cer",
            "--escalated",
            str(tmp_path / "missing.json"),
            "--report-output",
            str(report),
        ],
    )
    assert cer.main() == 1
    assert "not found" in json.loads(report.read_text(encoding="utf-8"))["error"]
