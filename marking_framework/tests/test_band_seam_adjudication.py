import csv
import json
from pathlib import Path

import scripts.band_seam_adjudication as bsa


LEVEL_BANDS = [
    {"level": "1", "min": 50, "max": 59, "letter": "D"},
    {"level": "2", "min": 60, "max": 69, "letter": "C"},
    {"level": "3", "min": 70, "max": 79, "letter": "B"},
    {"level": "4", "min": 80, "max": 89, "letter": "A"},
]


def write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def base_rows() -> list[dict]:
    return [
        {
            "student_id": "s3a",
            "consensus_rank": "1",
            "seed_rank": "1",
            "adjusted_level": "3",
            "adjusted_letter": "B",
            "level_modifier": "",
            "level_with_modifier": "3",
            "rubric_after_penalty_percent": "72",
            "composite_score": "0.70",
            "borda_points": "7",
            "borda_percent": "0.7",
            "rubric_sd_points": "0.4",
            "rank_sd": "0.2",
            "conventions_mistake_rate_percent": "1.0",
            "flags": "",
        },
        {
            "student_id": "s3b",
            "consensus_rank": "2",
            "seed_rank": "2",
            "adjusted_level": "3",
            "adjusted_letter": "B",
            "level_modifier": "",
            "level_with_modifier": "3",
            "rubric_after_penalty_percent": "70",
            "composite_score": "0.68",
            "borda_points": "6",
            "borda_percent": "0.6",
            "rubric_sd_points": "0.3",
            "rank_sd": "0.1",
            "conventions_mistake_rate_percent": "1.0",
            "flags": "",
        },
        {
            "student_id": "s2a",
            "consensus_rank": "3",
            "seed_rank": "3",
            "adjusted_level": "2",
            "adjusted_letter": "C",
            "level_modifier": "",
            "level_with_modifier": "2",
            "rubric_after_penalty_percent": "66",
            "composite_score": "0.76",
            "borda_points": "8",
            "borda_percent": "0.8",
            "rubric_sd_points": "1.5",
            "rank_sd": "0.2",
            "conventions_mistake_rate_percent": "1.0",
            "flags": "rubric_sd",
        },
        {
            "student_id": "s2b",
            "consensus_rank": "4",
            "seed_rank": "4",
            "adjusted_level": "2",
            "adjusted_letter": "C",
            "level_modifier": "",
            "level_with_modifier": "2",
            "rubric_after_penalty_percent": "64",
            "composite_score": "0.58",
            "borda_points": "4",
            "borda_percent": "0.4",
            "rubric_sd_points": "0.5",
            "rank_sd": "0.2",
            "conventions_mistake_rate_percent": "1.0",
            "flags": "",
        },
    ]


def test_select_band_seam_candidates_includes_top_lower_and_bottom_upper():
    boundaries = bsa.select_band_seam_candidates(base_rows(), LEVEL_BANDS, per_side=2, margin=1.0)
    l2_l3 = next(item for item in boundaries if item["boundary"] == "2/3")
    assert [item["student_id"] for item in l2_l3["candidates"]] == ["s3a", "s3b", "s2a", "s2b"]
    assert l2_l3["candidate_count"] == 4


def test_apply_adjudications_promotes_before_rerank_and_resorts():
    adjudications = [
        {
            "boundary": "2/3",
            "lower_level": "2",
            "upper_level": "3",
            "decisions": [
                {
                    "student_id": "s2a",
                    "decision": "promote",
                    "confidence": "medium",
                    "current_level": "2",
                    "recommended_level": "3",
                    "rationale": "Stronger task-grounded interpretation than bottom Level 3 candidates.",
                }
            ],
        }
    ]
    updated, applied = bsa.apply_adjudications(base_rows(), LEVEL_BANDS, adjudications)
    assert len(applied) == 1
    assert applied[0]["student_id"] == "s2a"
    assert applied[0]["boundary"] == "2/3"
    assert applied[0]["decision"] == "promote"
    assert applied[0]["confidence"] == "medium"
    assert applied[0]["from_level"] == "2"
    assert applied[0]["to_level"] == "3"
    assert applied[0]["guard"] == "applied"
    promoted = next(row for row in updated if row["student_id"] == "s2a")
    assert promoted["adjusted_level"] == "3"
    assert promoted["pre_band_adjudication_level"] == "2"
    assert "band_seam_adjudicated" in promoted["flags"]
    assert [row["student_id"] for row in updated][:2] == ["s2a", "s3a"]
    assert [str(row["consensus_rank"]) for row in updated] == ["1", "2", "3", "4"]


def test_main_writes_artifacts_and_overwrites_consensus_with_band_adjusted_rows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rows = base_rows()
    scores = tmp_path / "outputs" / "consensus_scores.csv"
    write_csv(scores, rows)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"levels": {"bands": LEVEL_BANDS}}), encoding="utf-8")
    routing = tmp_path / "routing.json"
    routing.write_text(json.dumps({"mode": "codex_local"}), encoding="utf-8")
    texts = tmp_path / "texts"
    texts.mkdir()
    for row in rows:
        (texts / f"{row['student_id']}.txt").write_text(f"Essay for {row['student_id']}", encoding="utf-8")
    rubric = tmp_path / "rubric.md"
    outline = tmp_path / "outline.md"
    metadata = tmp_path / "class_metadata.json"
    rubric.write_text("rubric", encoding="utf-8")
    outline.write_text("outline", encoding="utf-8")
    metadata.write_text(json.dumps({"assignment_genre": "literary_analysis", "grade": "7"}), encoding="utf-8")

    def fake_create(model, messages, temperature, reasoning, routing_path, text_format=None, max_output_tokens=None):
        payload = {
            "boundary": "2/3",
            "decisions": [
                {
                    "student_id": "s2a",
                    "decision": "promote",
                    "confidence": "high",
                    "current_level": "2",
                    "recommended_level": "3",
                    "rationale": "Interpretation crosses the seam.",
                    "decisive_evidence": ["explains evidence"],
                    "risks": [],
                }
            ],
            "pairwise_checks_needed": [{"higher_candidate": "s2a", "lower_candidate": "s3b", "reason": "Confirm promoted order."}],
        }
        return {"model": model, "usage": {"input_tokens": 10}, "output": [{"type": "output_text", "text": json.dumps(payload)}]}

    monkeypatch.setattr(bsa, "responses_create", fake_create)
    monkeypatch.setattr(
        "sys.argv",
        [
            "band_seam",
            "--scores",
            str(scores),
            "--config",
            str(config),
            "--routing",
            str(routing),
            "--texts",
            str(texts),
            "--rubric",
            str(rubric),
            "--outline",
            str(outline),
            "--class-metadata",
            str(metadata),
            "--per-side",
            "2",
        ],
    )
    assert bsa.main() == 0
    adjusted = list(csv.DictReader(scores.open("r", encoding="utf-8")))
    assert adjusted[0]["student_id"] == "s2a"
    assert adjusted[0]["adjusted_level"] == "3"
    assert (tmp_path / "outputs" / "band_seam_candidates.json").exists()
    report = json.loads((tmp_path / "outputs" / "band_seam_report.json").read_text(encoding="utf-8"))
    assert report["applied_count"] == 1
    assert report["pairwise_checks_needed"][0]["higher_candidate"] == "s2a"
    backup = list(csv.DictReader((tmp_path / "outputs" / "consensus_scores.pre_band_seam.csv").open("r", encoding="utf-8")))
    assert backup[0]["student_id"] == "s3a"


def test_adjudicate_boundaries_chunks_large_candidate_sets(monkeypatch):
    rows = [
        {
            "student_id": f"s{idx}",
            "adjusted_level": "1" if idx > 4 else "2",
            "consensus_rank": str(idx),
            "rubric_after_penalty_percent": "59",
            "composite_score": "0.5",
        }
        for idx in range(1, 10)
    ]
    boundary = {
        "boundary": "1/2",
        "lower_level": "1",
        "upper_level": "2",
        "candidate_count": 9,
        "candidates": [
            {
                "student_id": row["student_id"],
                "current_level": row["adjusted_level"],
                "rank": idx,
                "rubric_after_penalty_percent": 59.0,
                "composite_score": 0.5,
                "borda_percent": 0.5,
                "flags": "",
            }
            for idx, row in enumerate(rows, start=1)
        ],
    }
    seen_candidate_counts = []

    def fake_create(model, messages, temperature, reasoning, routing_path, text_format=None, max_output_tokens=None):
        prompt = messages[0]["content"]
        ids = [row["student_id"] for row in rows if f"Candidate {row['student_id']}" in prompt]
        seen_candidate_counts.append(len(ids))
        payload = {
            "boundary": "1/2",
            "decisions": [
                {
                    "student_id": sid,
                    "decision": "hold",
                    "confidence": "medium",
                    "current_level": "1",
                    "recommended_level": "1",
                    "rationale": "chunked",
                    "decisive_evidence": [],
                    "risks": [],
                }
                for sid in ids
            ],
            "pairwise_checks_needed": [],
        }
        return {"model": model, "output": [{"type": "output_text", "text": json.dumps(payload)}]}

    monkeypatch.setattr(bsa, "responses_create", fake_create)
    outputs = bsa.adjudicate_boundaries(
        [boundary],
        rows,
        {row["student_id"]: "Essay" for row in rows},
        "rubric",
        "outline",
        {},
        model="gpt-5.4-mini",
        routing="routing.json",
        reasoning="low",
        max_output_tokens=1000,
        max_candidates_per_call=4,
    )
    assert seen_candidate_counts == [4, 4, 1]
    assert sum(len(item["decisions"]) for item in outputs) == 9
    assert [item["model_metadata"]["chunk_index"] for item in outputs] == [1, 2, 3]


def test_write_csv_includes_fields_added_after_first_row(tmp_path):
    path = tmp_path / "rows.csv"
    bsa.write_csv(path, [{"student_id": "s1"}, {"student_id": "s2", "band_adjudicated_level": "3"}])
    rows = list(csv.DictReader(path.open("r", encoding="utf-8")))
    assert rows[0]["band_adjudicated_level"] == ""
    assert rows[1]["band_adjudicated_level"] == "3"


def test_adjudicate_boundaries_retries_missing_candidate_decisions(monkeypatch):
    rows = [
        {"student_id": "s1", "adjusted_level": "1", "consensus_rank": "1", "rubric_after_penalty_percent": "59", "composite_score": "0.5"},
        {"student_id": "s2", "adjusted_level": "1", "consensus_rank": "2", "rubric_after_penalty_percent": "58", "composite_score": "0.4"},
    ]
    boundary = {
        "boundary": "1/2",
        "lower_level": "1",
        "upper_level": "2",
        "candidate_count": 2,
        "candidates": [
            {"student_id": "s1", "current_level": "1", "rank": 1, "rubric_after_penalty_percent": 59.0, "composite_score": 0.5, "borda_percent": 0.7, "flags": ""},
            {"student_id": "s2", "current_level": "1", "rank": 2, "rubric_after_penalty_percent": 58.0, "composite_score": 0.4, "borda_percent": 0.2, "flags": ""},
        ],
    }
    calls = []

    def fake_create(model, messages, temperature, reasoning, routing_path, text_format=None, max_output_tokens=None):
        calls.append(messages[0]["content"])
        sid = "s1" if len(calls) == 1 else "s2"
        payload = {
            "boundary": "1/2",
            "decisions": [
                {
                    "student_id": sid,
                    "decision": "hold",
                    "confidence": "medium",
                    "current_level": "1",
                    "recommended_level": "1",
                    "rationale": "present",
                    "decisive_evidence": [],
                    "risks": [],
                }
            ],
            "pairwise_checks_needed": [],
        }
        return {"model": model, "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}, "output": [{"type": "output_text", "text": json.dumps(payload)}]}

    monkeypatch.setattr(bsa, "responses_create", fake_create)
    outputs = bsa.adjudicate_boundaries(
        [boundary],
        rows,
        {"s1": "Essay one", "s2": "Essay two"},
        "rubric",
        "outline",
        {},
        model="gpt-5.4-mini",
        routing="routing.json",
        reasoning="low",
        max_output_tokens=1000,
        chunk_retries=1,
    )
    assert len(calls) == 2
    assert "omitted required candidate decisions for: s2" in calls[1]
    assert [decision["student_id"] for decision in outputs[0]["decisions"]] == ["s1", "s2"]
    assert outputs[0]["model_metadata"]["attempt_count"] == 2
    assert outputs[0]["model_metadata"]["missing_after_retries"] == []


def test_evidence_is_added_to_prompt():
    rows = base_rows()
    boundaries = bsa.select_band_seam_candidates(rows, LEVEL_BANDS, per_side=2, margin=1.0)
    enriched = bsa.add_evidence_to_boundaries(
        boundaries,
        rows,
        [{"assessor_id": "a", "ranking": ["s2a", "s3a", "s3b", "s2b"]}],
        [{"winner": "s2a", "loser": "s3b", "confidence": "high", "weight": 2.0, "rationale": "direct"}],
    )
    l2_l3 = next(item for item in enriched if item["boundary"] == "2/3")
    s2a = next(item for item in l2_l3["candidates"] if item["student_id"] == "s2a")
    assert s2a["evidence"]["pass2_boundary_net"] == 2
    assert s2a["evidence"]["direct_pairwise_net"] == 2.0
    prompt = bsa.build_prompt(l2_l3, {row["student_id"]: row for row in rows}, {"s2a": "Essay"}, "rubric", "outline", {})
    assert "Pass2 boundary pairwise: wins=2, losses=0, net=2" in prompt
    assert "Direct pairwise boundary support: support=2.00" in prompt


def test_evidence_guard_blocks_weak_judgment_against_strong_cross_evidence():
    rows = base_rows()
    adjudications = [
        {
            "boundary": "2/3",
            "lower_level": "2",
            "upper_level": "3",
            "decisions": [
                {
                    "student_id": "s2a",
                    "decision": "promote",
                    "confidence": "medium",
                    "current_level": "2",
                    "recommended_level": "3",
                    "rationale": "weak",
                    "candidate_evidence": {"direct_pairwise_net": -2.0, "pass2_boundary_net": -4, "borda_percent": 0.2},
                }
            ],
        }
    ]
    updated, applied = bsa.apply_adjudications(rows, LEVEL_BANDS, adjudications)
    assert applied == []
    row = next(item for item in updated if item["student_id"] == "s2a")
    assert row["adjusted_level"] == "2"
    assert row["band_adjudication_guard"] == "strong_cross_evidence_contradiction"


def test_main_iterates_until_band_movement_stabilizes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rows = [
        {**base_rows()[0], "student_id": "upper", "consensus_rank": "1", "seed_rank": "1", "adjusted_level": "3", "rubric_after_penalty_percent": "72", "composite_score": "0.5"},
        {**base_rows()[2], "student_id": "middle", "consensus_rank": "2", "seed_rank": "2", "adjusted_level": "2", "rubric_after_penalty_percent": "65", "composite_score": "0.4"},
        {**base_rows()[3], "student_id": "mover", "consensus_rank": "3", "seed_rank": "3", "adjusted_level": "1", "rubric_after_penalty_percent": "59", "composite_score": "0.9", "borda_percent": "0.95"},
    ]
    scores = tmp_path / "outputs" / "consensus_scores.csv"
    write_csv(scores, rows)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"levels": {"bands": LEVEL_BANDS}}), encoding="utf-8")
    routing = tmp_path / "routing.json"
    routing.write_text(json.dumps({"mode": "codex_local"}), encoding="utf-8")
    texts = tmp_path / "texts"
    texts.mkdir()
    for row in rows:
        (texts / f"{row['student_id']}.txt").write_text(f"Essay for {row['student_id']}", encoding="utf-8")
    rubric = tmp_path / "rubric.md"
    outline = tmp_path / "outline.md"
    metadata = tmp_path / "class_metadata.json"
    rubric.write_text("rubric", encoding="utf-8")
    outline.write_text("outline", encoding="utf-8")
    metadata.write_text("{}", encoding="utf-8")

    def fake_create(model, messages, temperature, reasoning, routing_path, text_format=None, max_output_tokens=None):
        prompt = messages[0]["content"]
        decisions = []
        for sid in ["upper", "middle", "mover"]:
            if f"Candidate {sid}" not in prompt:
                continue
            current = "1" if sid == "mover" and "Boundary under review: 1/2" in prompt else ("2" if sid != "upper" else "3")
            if sid == "mover":
                decision = "promote"
                recommended = "2" if "Boundary under review: 1/2" in prompt else "3"
            else:
                decision = "hold"
                recommended = current
            decisions.append(
                {
                    "student_id": sid,
                    "decision": decision,
                    "confidence": "high",
                    "current_level": current,
                    "recommended_level": recommended,
                    "rationale": "iterative",
                    "decisive_evidence": [],
                    "risks": [],
                }
            )
        return {"model": model, "output": [{"type": "output_text", "text": json.dumps({"boundary": "x", "decisions": decisions, "pairwise_checks_needed": []})}]}

    monkeypatch.setattr(bsa, "responses_create", fake_create)
    monkeypatch.setattr(
        "sys.argv",
        [
            "band_seam",
            "--scores",
            str(scores),
            "--config",
            str(config),
            "--routing",
            str(routing),
            "--texts",
            str(texts),
            "--rubric",
            str(rubric),
            "--outline",
            str(outline),
            "--class-metadata",
            str(metadata),
            "--per-side",
            "2",
            "--max-passes",
            "3",
        ],
    )
    assert bsa.main() == 0
    adjusted = {row["student_id"]: row for row in csv.DictReader(scores.open("r", encoding="utf-8"))}
    assert adjusted["mover"]["adjusted_level"] == "3"
    report = json.loads((tmp_path / "outputs" / "band_seam_report.json").read_text(encoding="utf-8"))
    assert report["pass_count"] >= 2
    assert any(item["student_id"] == "mover" and item["to_level"] == "3" for item in report["applied"])
