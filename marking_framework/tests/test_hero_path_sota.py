import scripts.hero_path as hp


def setup_assessor_dirs(tmp_path):
    (tmp_path / "inputs/submissions").mkdir(parents=True, exist_ok=True)
    (tmp_path / "assessments/pass1_individual").mkdir(parents=True, exist_ok=True)
    (tmp_path / "assessments/pass2_comparative").mkdir(parents=True, exist_ok=True)
    (tmp_path / "assessments/pass1_individual/a.json").write_text('{"assessor_id":"a","scores":[]}')
    (tmp_path / "assessments/pass2_comparative/a.txt").write_text("s1")


def test_hero_path_sota_gate_fail_and_custom_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup_assessor_dirs(tmp_path)
    seen = []

    def fake_run(cmd):
        seen.append(cmd)
        if any("sota_gate.py" in str(part) for part in cmd):
            return 2
        return 0

    monkeypatch.setattr(hp, "run", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "hp",
            "--skip-extract",
            "--skip-conventions",
            "--skip-aggregate",
            "--sota-gate",
            "--sota-config",
            "config/custom_sota_gate.json",
        ],
    )
    assert hp.main() == 1
    sota_calls = [call for call in seen if any("sota_gate.py" in str(part) for part in call)]
    assert len(sota_calls) == 1
    flat = [str(part) for part in sota_calls[0]]
    assert "--gate-config" in flat
    assert "config/custom_sota_gate.json" in flat
