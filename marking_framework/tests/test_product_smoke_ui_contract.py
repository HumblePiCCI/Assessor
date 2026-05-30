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


def test_review_ready_job_removes_blocking_overlay_immediately():
    source = UI_APP.read_text(encoding="utf-8")

    assert "function stopPipelineNarrative(msg, opts = {})" in source
    assert "stopPipelineNarrative(text, { delayMs: 0 });" in source


def test_dashboard_reload_restores_background_validation_status():
    source = UI_APP.read_text(encoding="utf-8")

    assert "function restorePipelineStatusFromDashboard()" in source
    assert "Review ready. Validation is checking edge cases in the background." in source
    assert "restorePipelineStatusFromDashboard();" in source


def test_classroom_blocker_counts_only_apply_to_attachment_blockers():
    source = UI_APP.read_text(encoding="utf-8")

    assert "const CLASSROOM_ATTACHMENT_BLOCKER_CODES = new Set" in source
    assert "function classroomBlockerLabel(code, blockerCount)" in source
    assert "CLASSROOM_ATTACHMENT_BLOCKER_CODES.has(key)" in source
    assert "label: classroomBlockerLabel(code, blockerCount)" in source
