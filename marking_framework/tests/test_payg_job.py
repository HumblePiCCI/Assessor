import types
from pathlib import Path

import scripts.payg_job as pj


def test_payg_job_success(tmp_path, monkeypatch):
    rubric = tmp_path / "rubric.md"
    outline = tmp_path / "outline.md"
    subs = tmp_path / "subs"
    subs.mkdir()
    (subs / "s1.txt").write_text("text", encoding="utf-8")
    rubric.write_text("rubric", encoding="utf-8")
    outline.write_text("outline", encoding="utf-8")

    def fake_run(cmd, cwd=None, env=None):
        assert env and env.get("LLM_MODE") == "openai"
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(pj.subprocess, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["pj", "--rubric", str(rubric), "--outline", str(outline), "--submissions", str(subs), "--workdir", str(tmp_path / "job")])
    assert pj.main() == 0


def test_payg_job_failure(tmp_path, monkeypatch):
    rubric = tmp_path / "rubric.md"
    outline = tmp_path / "outline.md"
    subs = tmp_path / "subs"
    subs.mkdir()
    (subs / "s1.txt").write_text("text", encoding="utf-8")
    rubric.write_text("rubric", encoding="utf-8")
    outline.write_text("outline", encoding="utf-8")

    def fake_run(cmd, cwd=None, env=None):
        return types.SimpleNamespace(returncode=1)

    monkeypatch.setattr(pj.subprocess, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["pj", "--rubric", str(rubric), "--outline", str(outline), "--submissions", str(subs), "--workdir", str(tmp_path / "job")])
    assert pj.main() == 1


def test_payg_job_default_workdir(tmp_path, monkeypatch):
    rubric = tmp_path / "rubric.md"
    outline = tmp_path / "outline.md"
    subs = tmp_path / "subs"
    subs.mkdir()
    (subs / "s1.txt").write_text("text", encoding="utf-8")
    rubric.write_text("rubric", encoding="utf-8")
    outline.write_text("outline", encoding="utf-8")

    def fake_run(cmd, cwd=None, env=None):
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(pj.subprocess, "run", fake_run)
    monkeypatch.setattr(pj.tempfile, "mkdtemp", lambda prefix="": str(tmp_path / "job"))
    monkeypatch.setattr("sys.argv", ["pj", "--rubric", str(rubric), "--outline", str(outline), "--submissions", str(subs)])
    assert pj.main() == 0


def test_copy_workspace_missing_dirs(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "scripts").mkdir()
    dst = tmp_path / "dst"
    pj.copy_workspace(src, dst)
    assert (dst / "inputs/submissions").exists()


def test_payg_job_llm_pricing_flags(tmp_path, monkeypatch):
    rubric = tmp_path / "rubric.md"
    outline = tmp_path / "outline.md"
    subs = tmp_path / "subs"
    subs.mkdir()
    (subs / "s1.txt").write_text("text", encoding="utf-8")
    (subs / "subdir").mkdir()
    rubric.write_text("rubric", encoding="utf-8")
    outline.write_text("outline", encoding="utf-8")

    calls = []

    def fake_run(cmd, cwd=None, env=None):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(pj.subprocess, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["pj", "--rubric", str(rubric), "--outline", str(outline), "--submissions", str(subs), "--workdir", str(tmp_path / "job"), "--llm", "--pricing", "--pairs"])
    assert pj.main() == 0
    assert any("--llm-assessors" in c for c in calls[0])
