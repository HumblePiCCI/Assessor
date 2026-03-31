import json
from pathlib import Path

from scripts import aggregate_output as ao


def test_write_outputs(tmp_path):
    rows = [
        {"student_id": "s1", "consensus_rank": 1, "flags": ""},
        {"student_id": "s2", "consensus_rank": 2, "flags": "flag"},
    ]

    out_csv = tmp_path / "consensus.csv"
    ao.write_consensus_csv(rows, out_csv)
    assert out_csv.exists()

    ranked = tmp_path / "ranked.md"
    ao.write_ranked_list(rows, ranked)
    assert "s2" in ranked.read_text()

    disagreements = ao.write_disagreements(rows, tmp_path / "disagreements.md")
    assert len(disagreements) == 1

    irr = {"rubric_icc": 0.95, "rank_kendall_w": 0.8}
    irr_path = tmp_path / "irr.json"
    irr_full = ao.write_irr_metrics(irr, irr_path, 2, 3, 3, 28, 1, 0)
    assert irr_full["interpretation"]["rubric_icc"] == "excellent"
    assert json.loads(irr_path.read_text())["quality_summary"]["students_flagged"] == 1


def test_write_disagreements_none(tmp_path):
    rows = [{"student_id": "s1", "consensus_rank": 1, "flags": ""}]
    disagreements = ao.write_disagreements(rows, tmp_path / "d.md")
    assert disagreements == []


def test_write_consensus_empty(tmp_path):
    out = tmp_path / "c.csv"
    ao.write_consensus_csv([], out)
    assert out.exists()
