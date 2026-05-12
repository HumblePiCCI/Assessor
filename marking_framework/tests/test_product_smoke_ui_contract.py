from pathlib import Path


UI_APP = Path(__file__).resolve().parents[1] / "ui" / "app.js"


def test_review_controls_start_hidden_until_scored_result():
    source = UI_APP.read_text(encoding="utf-8")

    assert "section.className = 'auth review-section is-hidden';" in source
    assert "document.getElementById('reviewSection')?.classList.toggle('is-hidden', !hasScored);" in source


def test_pipeline_errors_are_teacher_facing():
    source = UI_APP.read_text(encoding="utf-8")

    assert "function runErrorForTeacher(message)" in source
    assert "Calibration needs refresh before this class can run." in source
    assert "codex.reason || 'Codex not connected'" in source
    assert "setPipelineStatus(msg, 'danger')" in source
