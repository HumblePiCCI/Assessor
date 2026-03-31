import scripts.hero_path as hp
import subprocess


def setup_assessor_dirs(tmp_path):
    (tmp_path / "inputs/submissions").mkdir(parents=True, exist_ok=True)
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True, exist_ok=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True, exist_ok=True)
    (tmp_path / "assessments/pass1_individual/a.json").write_text('{"assessor_id":"a","scores":[]}')
    (tmp_path / "assessments/pass2_comparative/a.txt").write_text("s1")


def test_hero_path_missing_assessors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "inputs/submissions").mkdir(parents=True)
    monkeypatch.setattr("sys.argv", ["hp", "--skip-extract", "--skip-conventions"])
    assert hp.main() == 1


def test_hero_path_full_flow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "processing").mkdir(parents=True)
    setup_assessor_dirs(tmp_path)

    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return 0

    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["hp", "--skip-extract", "--skip-conventions", "--llm-assessors", "--pricing-report", "--generate-pairs", "--apply-pairs", "--build-dashboard"])
    assert hp.main() == 0
    assert calls
    assert any("review_and_grade.py" in str(part) for call in calls for part in call)


def test_hero_path_ignore_cost_limits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)

    cmds = []
    def fake_run(cmd):
        cmds.append(cmd)
        return 0

    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["hp", "--skip-extract", "--skip-conventions", "--llm-assessors", "--ignore-cost-limits"])
    assert hp.main() == 0
    assert any("--ignore-cost-limits" in c for c in cmds)


def test_run_helper(monkeypatch):
    class Dummy:
        returncode = 5
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Dummy())
    assert hp.run(["echo"]) == 5


def test_hero_path_extract_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "inputs/submissions").mkdir(parents=True)
    monkeypatch.setattr(hp, "run", lambda *args, **kwargs: 1)
    monkeypatch.setattr("sys.argv", ["hp"])
    assert hp.main() == 1


def test_hero_path_conventions_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "inputs/submissions").mkdir(parents=True)
    monkeypatch.setattr(hp, "run", lambda *args, **kwargs: 1)
    monkeypatch.setattr("sys.argv", ["hp", "--skip-extract"])
    assert hp.main() == 1


def test_hero_path_llm_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)

    def fake_run(cmd):
        if any("run_llm_assessors.py" in str(part) for part in cmd):
            return 1
        return 0

    assert fake_run(["echo"]) == 0
    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["hp", "--skip-extract", "--skip-conventions", "--llm-assessors"])
    assert hp.main() == 1


def test_hero_path_aggregate_allow_missing_and_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)

    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        if any("aggregate_assessments.py" in str(part) for part in cmd):
            return 1
        return 0

    assert fake_run(["echo"]) == 0
    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["hp", "--skip-extract", "--skip-conventions", "--allow-missing-data"])
    assert hp.main() == 1
    assert any("--allow-missing-data" in c for c in calls)


def test_hero_path_generate_pairs_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)
    def fake_run(cmd):
        if any("generate_pairwise_review.py" in str(part) for part in cmd):
            return 1
        return 0
    assert fake_run(["echo"]) == 0
    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["hp", "--skip-extract", "--skip-conventions", "--skip-aggregate", "--generate-pairs"])
    assert hp.main() == 1


def test_hero_path_apply_pairs_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)
    def fake_run(cmd):
        if any("apply_pairwise_adjustments.py" in str(part) for part in cmd):
            return 1
        return 0
    assert fake_run(["echo"]) == 0
    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["hp", "--skip-extract", "--skip-conventions", "--skip-aggregate", "--apply-pairs"])
    assert hp.main() == 1


def test_hero_path_build_dashboard_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)
    def fake_run(cmd):
        if any("build_dashboard_data.py" in str(part) for part in cmd):
            return 1
        return 0
    assert fake_run(["echo"]) == 0
    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["hp", "--skip-extract", "--skip-conventions", "--skip-aggregate", "--build-dashboard"])
    assert hp.main() == 1


def test_hero_path_serve_ui_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)
    def fake_run(cmd):
        if any("serve_ui.py" in str(part) for part in cmd):
            return 1
        return 0
    assert fake_run(["echo"]) == 0
    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["hp", "--skip-extract", "--skip-conventions", "--skip-aggregate", "--serve-ui"])
    assert hp.main() == 1


def test_hero_path_extract_conventions_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)

    monkeypatch.setattr(hp, "run", lambda *args, **kwargs: 0)
    monkeypatch.setattr("sys.argv", ["hp"])
    assert hp.main() == 0


def test_hero_path_serve_ui_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)

    def fake_run(cmd):
        return 0

    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["hp", "--skip-extract", "--skip-conventions", "--skip-aggregate", "--serve-ui"])
    assert hp.main() == 0


def test_hero_path_calibrate_and_consistency(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return 0

    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr("sys.argv", [
        "hp",
        "--skip-extract",
        "--skip-conventions",
        "--skip-aggregate",
        "--calibrate",
        "--verify-consistency",
        "--apply-consistency",
    ])
    assert hp.main() == 0
    assert any("calibrate_assessors.py" in str(part) for call in calls for part in call)
    assert any("verify_consistency.py" in str(part) for call in calls for part in call)
    assert any("global_rerank.py" in str(part) for call in calls for part in call)


def test_hero_path_calibrate_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)

    def fake_run(cmd):
        if any("calibrate_assessors.py" in str(part) for part in cmd):
            return 1
        return 0

    assert fake_run(["echo"]) == 0
    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr("sys.argv", [
        "hp",
        "--skip-extract",
        "--skip-conventions",
        "--skip-aggregate",
        "--calibrate",
    ])
    assert hp.main() == 1


def test_hero_path_verify_consistency_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)

    def fake_run(cmd):
        if any("verify_consistency.py" in str(part) for part in cmd):
            return 1
        return 0

    assert fake_run(["echo"]) == 0
    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr("sys.argv", [
        "hp",
        "--skip-extract",
        "--skip-conventions",
        "--skip-aggregate",
        "--verify-consistency",
    ])
    assert hp.main() == 1


def test_hero_path_publish_gate_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)

    def fake_run(cmd):
        if any("publish_gate.py" in str(part) for part in cmd):
            return 2
        return 0

    assert fake_run(["echo"]) == 0
    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr("sys.argv", [
        "hp",
        "--skip-extract",
        "--skip-conventions",
        "--skip-aggregate",
        "--publish-gate",
    ])
    assert hp.main() == 1


def test_hero_path_accuracy_consistency_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return 0

    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["hp", "--skip-extract", "--skip-conventions", "--accuracy-consistency"])
    assert hp.main() == 0
    assert any("calibrate_assessors.py" in str(part) for call in calls for part in call)
    assert any("run_llm_assessors.py" in str(part) for call in calls for part in call)
    assert any("boundary_recheck.py" in str(part) for call in calls for part in call)
    assert any("verify_consistency.py" in str(part) for call in calls for part in call)
    assert any("global_rerank.py" in str(part) for call in calls for part in call)
    assert any("publish_gate.py" in str(part) for call in calls for part in call)
    assert any("sota_gate.py" in str(part) for call in calls for part in call)
    assert any("review_and_grade.py" in str(part) for call in calls for part in call)


def test_hero_path_skip_grading(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return 0

    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["hp", "--skip-extract", "--skip-conventions", "--skip-grading"])
    assert hp.main() == 0
    assert not any("review_and_grade.py" in str(part) for call in calls for part in call)


def test_hero_path_boundary_recheck_flow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return 0

    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr("sys.argv", [
        "hp",
        "--skip-extract",
        "--skip-conventions",
        "--boundary-recheck",
        "--boundary-margin",
        "1.5",
        "--boundary-replicates",
        "4",
        "--boundary-max-students",
        "3",
    ])
    assert hp.main() == 0
    aggregate_calls = [c for c in calls if any("aggregate_assessments.py" in str(p) for p in c)]
    assert len(aggregate_calls) == 2
    boundary_calls = [c for c in calls if any("boundary_recheck.py" in str(p) for p in c)]
    assert len(boundary_calls) == 1
    flat = [str(p) for p in boundary_calls[0]]
    assert "--margin" in flat and "1.5" in flat
    assert "--replicates" in flat and "4" in flat
    assert "--max-students" in flat and "3" in flat


def test_hero_path_boundary_recheck_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)

    def fake_run(cmd):
        if any("boundary_recheck.py" in str(part) for part in cmd):
            return 1
        return 0

    assert fake_run(["echo"]) == 0
    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr("sys.argv", [
        "hp",
        "--skip-extract",
        "--skip-conventions",
        "--boundary-recheck",
    ])
    assert hp.main() == 1
