import csv
import json

import pytest

from scripts import benchmark_main_vs_fallback as bmf


def _write_consensus(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_ensure_dataset_shape_requires_gold(tmp_path):
    inputs = tmp_path / "inputs"
    submissions = tmp_path / "submissions"
    inputs.mkdir()
    submissions.mkdir()
    (tmp_path / "gold.jsonl").write_text(
        '{"student_id":"s001","gold_level":"1","gold_band_min":50,"gold_band_max":59,"gold_rank":1}\n',
        encoding="utf-8",
    )
    got_inputs, got_submissions, got_gold = bmf.ensure_dataset_shape(tmp_path)
    assert got_inputs == inputs
    assert got_submissions == submissions
    assert got_gold == tmp_path / "gold.jsonl"
    with pytest.raises(ValueError):
        bmf.ensure_dataset_shape(tmp_path / "missing")


def test_load_gold_rows_supports_jsonl_and_csv(tmp_path):
    gold_jsonl = tmp_path / "gold.jsonl"
    gold_jsonl.write_text(
        "\n".join(
            [
                '{"student_id":"s001","source_file":"essay-1.txt","gold_level":"1","gold_band_min":50,"gold_band_max":59,"gold_rank":2,"gold_neighbors":["s002"],"boundary_flag":false}',
                '{"student_id":"s002","source_file":"essay-2.txt","gold_level":"2","gold_band_min":60,"gold_band_max":69,"gold_rank":1,"gold_neighbors":["s001"],"boundary_flag":true}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    rows = bmf.load_gold_rows(gold_jsonl)
    assert rows[0]["student_id"] == "s001"
    assert rows[0]["gold_canonical_level"] == "1"
    assert rows[1]["boundary_flag"] is True
    assert rows[1]["gold_neighbors"] == ["s001"]

    gold_csv = tmp_path / "gold.csv"
    with gold_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["student_id", "gold_level", "gold_band_min", "gold_band_max", "gold_rank", "gold_neighbors", "boundary_flag"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "student_id": "s001",
                "gold_level": "1",
                "gold_band_min": 50,
                "gold_band_max": 59,
                "gold_rank": 1,
                "gold_neighbors": '["s002"]',
                "boundary_flag": "false",
            }
        )
    csv_rows = bmf.load_gold_rows(gold_csv)
    assert csv_rows[0]["gold_neighbors"] == ["s002"]

    broken = tmp_path / "broken.jsonl"
    broken.write_text('{"student_id":"s001","gold_level":"9","gold_band_min":50,"gold_band_max":59,"gold_rank":1}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        bmf.load_gold_rows(broken)


def test_load_gold_rows_supports_source_native_levels_with_canonical_mapping(tmp_path):
    gold_jsonl = tmp_path / "gold.jsonl"
    gold_jsonl.write_text(
        '{"student_id":"s001","gold_level":"Excellent","gold_canonical_level":"4","gold_band_min":85,"gold_band_max":89,"gold_rank":1}\n',
        encoding="utf-8",
    )
    rows = bmf.load_gold_rows(gold_jsonl)
    assert rows[0]["gold_level"] == "Excellent"
    assert rows[0]["gold_canonical_level"] == "4"
    assert rows[0]["gold_level_ordinal"] == 4.0

    broken = tmp_path / "broken_noncanonical.jsonl"
    broken.write_text(
        '{"student_id":"s001","gold_level":"Excellent","gold_band_min":85,"gold_band_max":89,"gold_rank":1}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        bmf.load_gold_rows(broken)


def test_build_mode_env_is_portable():
    env = {"PATH": "/usr/bin:/bin", "LLM_MODE": "codex_local"}
    candidate_env = bmf.build_mode_env(env)
    assert candidate_env["PATH"] == "/usr/bin:/bin"
    assert "Library/Frameworks" not in candidate_env["PATH"]
    assert "LLM_MODE" not in candidate_env
    assert candidate_env["PYTHONHASHSEED"] == "0"
    assert candidate_env["OPENAI_MAX_RETRIES"] == "3"
    assert candidate_env["OPENAI_RETRY_BACKOFF_SECONDS"] == "0.2"

    fallback_env = bmf.build_mode_env(env, "codex_local")
    assert fallback_env["PATH"] == "/usr/bin:/bin"
    assert fallback_env["LLM_MODE"] == "codex_local"


def test_build_mode_env_sets_shared_cache_dir(tmp_path):
    env = {"PATH": "/usr/bin:/bin"}
    cache_dir = tmp_path / "shared-cache"
    candidate_env = bmf.build_mode_env(env, shared_cache_dir=cache_dir)
    assert candidate_env["LLM_CACHE_DIR"] == str(cache_dir.resolve())
    assert cache_dir.exists()


def test_setup_run_copies_calibration_manifest(tmp_path):
    repo_root = tmp_path / "repo"
    base_inputs = tmp_path / "dataset" / "inputs"
    base_submissions = tmp_path / "dataset" / "submissions"
    run_dir = tmp_path / "run"
    for dirname in ("scripts", "config", "prompts", "templates", "docs", "ui"):
        (repo_root / dirname).mkdir(parents=True, exist_ok=True)
    (repo_root / "outputs").mkdir(parents=True, exist_ok=True)
    (repo_root / "outputs" / "calibration_bias.json").write_text(json.dumps({"synthetic": False}), encoding="utf-8")
    (repo_root / "outputs" / "calibration_manifest.json").write_text(json.dumps({"model_version": "gpt-5.4-mini"}), encoding="utf-8")
    (base_inputs).mkdir(parents=True)
    (base_submissions).mkdir(parents=True)
    (base_inputs / "assignment_outline.md").write_text("outline", encoding="utf-8")
    (base_inputs / "rubric.md").write_text("rubric", encoding="utf-8")
    (base_inputs / "class_metadata.json").write_text(json.dumps({"grade_level": 6, "assignment_genre": "argumentative"}), encoding="utf-8")
    (base_submissions / "s001.txt").write_text("essay", encoding="utf-8")

    bmf.setup_run(base_inputs, base_submissions, repo_root, run_dir)

    assert (run_dir / "outputs" / "calibration_bias.json").exists()
    assert (run_dir / "outputs" / "calibration_manifest.json").exists()
    manifest = json.loads((run_dir / "outputs" / "calibration_manifest.json").read_text(encoding="utf-8"))
    assert manifest["model_version"] == "gpt-5.4-mini"


def test_pass1_model_usage_ratio(tmp_path):
    pass1 = tmp_path / "pass1"
    pass1.mkdir()
    payload = {
        "scores": [
            {"student_id": "s1", "notes": "Fallback deterministic score for assessor A."},
            {"student_id": "s2", "notes": "Model rationale"},
        ]
    }
    (pass1 / "assessor_A.json").write_text(json.dumps(payload), encoding="utf-8")
    assert bmf.pass1_model_usage_ratio(pass1) == 0.5


def test_evaluate_run_with_explicit_gold(tmp_path):
    run = tmp_path / "run"
    (run / "processing").mkdir(parents=True)
    (run / "outputs").mkdir(parents=True)
    (run / "assessments/pass1_individual").mkdir(parents=True)
    (run / "processing/submission_metadata.json").write_text(
        json.dumps(
            [
                {"student_id": "s001", "display_name": "essay one", "source_file": "essay-1.txt"},
                {"student_id": "s002", "display_name": "essay two", "source_file": "essay-2.txt"},
            ]
        ),
        encoding="utf-8",
    )
    _write_consensus(
        run / "outputs/consensus_scores.csv",
        [
            {
                "student_id": "s001",
                "adjusted_level": "1",
                "consensus_rank": "2",
                "rubric_after_penalty_percent": "55.0",
            },
            {
                "student_id": "s002",
                "adjusted_level": "2",
                "consensus_rank": "1",
                "rubric_after_penalty_percent": "66.0",
            },
        ],
    )
    (run / "assessments/pass1_individual/assessor_A.json").write_text(
        json.dumps({"scores": [{"student_id": "s001", "notes": "Model"}, {"student_id": "s002", "notes": "Model"}]}),
        encoding="utf-8",
    )
    (run / "outputs/usage_costs.json").write_text(json.dumps({"grand_total": 1.25}), encoding="utf-8")
    gold_rows = [
        {
            "student_id": "s001",
            "gold_level": "1",
            "gold_canonical_level": "1",
            "gold_level_ordinal": 1.0,
            "gold_band_min": 50.0,
            "gold_band_max": 59.0,
            "gold_rank": 2,
            "gold_neighbors": ["s002"],
            "boundary_flag": False,
            "adjudication_notes": "",
            "source_file": "essay-1.txt",
            "display_name": "essay one",
        },
        {
            "student_id": "s002",
            "gold_level": "2",
            "gold_canonical_level": "2",
            "gold_level_ordinal": 2.0,
            "gold_band_min": 60.0,
            "gold_band_max": 69.0,
            "gold_rank": 1,
            "gold_neighbors": ["s001"],
            "boundary_flag": False,
            "adjudication_notes": "",
            "source_file": "essay-2.txt",
            "display_name": "essay two",
        },
    ]
    out = bmf.evaluate_run(run, gold_rows, latency_seconds=3.5)
    assert out["exact_level_hit_rate"] == 1.0
    assert out["pairwise_order_agreement"] == 1.0
    assert out["kendall_tau"] == 1.0
    assert out["model_usage_ratio"] == 1.0
    assert out["cost_usd"] == 1.25
    assert out["latency_seconds"] == 3.5
    assert out["students"]["s001"]["source_file"] == "essay-1.txt"
    assert out["students"]["s001"]["gold_canonical_level"] == "1"


def test_evaluate_run_uses_canonical_level_for_exact_match(tmp_path):
    run = tmp_path / "run"
    (run / "processing").mkdir(parents=True)
    (run / "outputs").mkdir(parents=True)
    (run / "assessments/pass1_individual").mkdir(parents=True)
    (run / "processing/submission_metadata.json").write_text(
        json.dumps([{"student_id": "s001", "display_name": "essay one", "source_file": "essay-1.txt"}]),
        encoding="utf-8",
    )
    _write_consensus(
        run / "outputs/consensus_scores.csv",
        [
            {
                "student_id": "s001",
                "adjusted_level": "4",
                "consensus_rank": "1",
                "rubric_after_penalty_percent": "86.0",
            }
        ],
    )
    gold_rows = [
        {
            "student_id": "s001",
            "gold_level": "Excellent",
            "gold_canonical_level": "4",
            "gold_level_ordinal": 4.0,
            "gold_band_min": 85.0,
            "gold_band_max": 89.0,
            "gold_rank": 1,
            "gold_neighbors": [],
            "boundary_flag": False,
            "adjudication_notes": "",
            "source_file": "essay-1.txt",
            "display_name": "essay one",
        }
    ]
    out = bmf.evaluate_run(run, gold_rows, latency_seconds=1.0)
    assert out["exact_level_hit_rate"] == 1.0
    assert out["students"]["s001"]["gold_level"] == "Excellent"
    assert out["students"]["s001"]["gold_canonical_level"] == "4"


def test_summarize_runs_includes_stability():
    runs = [
        {
            "ok": True,
            "student_count": 2,
            "exact_level_hit_rate": 1.0,
            "within_one_level_hit_rate": 1.0,
            "score_band_mae": 0.0,
            "mean_rank_displacement": 0.0,
            "max_rank_displacement": 0.0,
            "kendall_tau": 1.0,
            "pairwise_order_agreement": 1.0,
            "model_usage_ratio": 1.0,
            "cost_usd": 1.0,
            "latency_seconds": 2.0,
            "students": {
                "s001": {"predicted_level_ordinal": 1.0, "predicted_level": "1", "predicted_rank": 2, "predicted_score": 55.0},
                "s002": {"predicted_level_ordinal": 2.0, "predicted_level": "2", "predicted_rank": 1, "predicted_score": 66.0},
            },
        },
        {
            "ok": True,
            "student_count": 2,
            "exact_level_hit_rate": 0.5,
            "within_one_level_hit_rate": 1.0,
            "score_band_mae": 1.0,
            "mean_rank_displacement": 0.5,
            "max_rank_displacement": 1.0,
            "kendall_tau": 0.0,
            "pairwise_order_agreement": 0.5,
            "model_usage_ratio": 0.75,
            "cost_usd": 1.5,
            "latency_seconds": 3.0,
            "students": {
                "s001": {"predicted_level_ordinal": 2.0, "predicted_level": "2", "predicted_rank": 1, "predicted_score": 61.0},
                "s002": {"predicted_level_ordinal": 2.0, "predicted_level": "2", "predicted_rank": 2, "predicted_score": 68.0},
            },
        },
    ]
    summary = bmf.summarize_runs(runs)
    assert summary["runs_successful"] == 2
    assert summary["exact_level_hit_rate_mean"] == 0.75
    assert summary["stability"]["mean_student_level_variance"] > 0.0
    assert summary["stability"]["cohort_metric_variance"]["latency_seconds"] > 0.0
