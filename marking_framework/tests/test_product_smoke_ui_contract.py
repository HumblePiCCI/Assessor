from pathlib import Path


UI_APP = Path(__file__).resolve().parents[1] / "ui" / "app.js"
UI_INDEX = Path(__file__).resolve().parents[1] / "ui" / "index.html"


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


def test_curve_controls_are_visible_and_rank_bound():
    source = UI_APP.read_text(encoding="utf-8")
    markup = UI_INDEX.read_text(encoding="utf-8")

    assert '<div class="curve-panel">' in markup
    assert 'id="topGrade"' in markup
    assert 'id="bottomGrade"' in markup
    assert 'id="curveStatus"' in markup
    assert "function resetMarkAdjustments()" in source
    assert "function restorePipelineRankOrder" in source
    assert "student._pipeline_rank" in source
    assert "applyCurveBounds(top, bottom, true);" in source
    assert "resetMarkAdjustments();" in source
    assert "Curve needs a top mark higher than bottom mark." in source
    assert "original assessment order" in source
