import csv
import json

from scripts import build_reproducibility_report as br


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_run(run_dir, *, score="78.0", rank="1", level="3", cost=0.1, sd=1.0):
    (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
    (run_dir / "config").mkdir(parents=True, exist_ok=True)
    (run_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (run_dir / "inputs" / "class_metadata.json").write_text(json.dumps({"grade_level": 6, "assignment_genre": "argumentative"}), encoding="utf-8")
    (run_dir / "inputs" / "rubric.md").write_text("rubric", encoding="utf-8")
    (run_dir / "inputs" / "assignment_outline.md").write_text("outline", encoding="utf-8")
    (run_dir / "config" / "marking_config.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    (run_dir / "config" / "rubric_criteria.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    (run_dir / "config" / "calibration_set.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    (run_dir / "outputs" / "calibration_manifest.json").write_text(json.dumps({"model_version": "gpt-5.4-mini"}), encoding="utf-8")
    _write_csv(
        run_dir / "outputs" / "consensus_scores.csv",
        [
            {
                "student_id": "s001",
                "adjusted_level": level,
                "consensus_rank": rank,
                "rubric_after_penalty_percent": score,
            }
        ],
    )
    (run_dir / "outputs" / "consistency_report.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    (run_dir / "outputs" / "irr_metrics.json").write_text(
        json.dumps({"inter_rater_reliability": {"rubric_icc": 0.9, "rank_kendall_w": 1.0, "mean_rubric_sd": sd, "mean_rank_sd": 0.0}}),
        encoding="utf-8",
    )
    (run_dir / "outputs" / "usage_costs.json").write_text(json.dumps({"grand_total": cost}), encoding="utf-8")
    (run_dir / "outputs" / "boundary_calibration_report.json").write_text(json.dumps({"adjusted_rows": 0}), encoding="utf-8")


def test_build_summary_exact_match(tmp_path):
    mode_dir = tmp_path / "gpt54_split"
    _write_run(mode_dir / "run_1")
    _write_run(mode_dir / "run_2")

    summary = br.build_summary(mode_dir, tolerance=0.01)

    assert summary["runs_compared"] == 2
    assert summary["manifest_identical"] is True
    assert summary["final_outputs_exact_match"] is True
    assert summary["within_tolerance"] is True
    assert summary["max_intermediate_metric_delta"] == 0.0


def test_build_summary_detects_delta(tmp_path):
    mode_dir = tmp_path / "gpt54_split"
    _write_run(mode_dir / "run_1", score="78.0", rank="1", level="3", cost=0.1, sd=1.0)
    _write_run(mode_dir / "run_2", score="79.2", rank="2", level="2", cost=0.2, sd=1.4)

    summary = br.build_summary(mode_dir, tolerance=0.01)

    assert summary["final_outputs_exact_match"] is False
    assert summary["within_tolerance"] is False
    assert summary["max_intermediate_metric_delta"] >= 1.0
    assert "outputs/consensus_scores.csv" in summary["mismatched_final_artifacts"]

