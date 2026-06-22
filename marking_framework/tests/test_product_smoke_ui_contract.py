from pathlib import Path


UI_APP = Path(__file__).resolve().parents[1] / "ui" / "app.js"
UI_INDEX = Path(__file__).resolve().parents[1] / "ui" / "index.html"


def test_review_controls_start_hidden_until_scored_result():
    source = UI_APP.read_text(encoding="utf-8")

    assert "section.className = 'auth review-section is-hidden';" in source
    assert "document.getElementById('reviewSection')?.classList.toggle('is-hidden', !hasScored);" in source


def test_pipeline_errors_are_teacher_facing():
    source = UI_APP.read_text(encoding="utf-8")
    styles = (UI_INDEX.parent / "style.css").read_text(encoding="utf-8")

    assert "function runErrorForTeacher(message)" in source
    assert "Calibration needs refresh before this class can run." in source
    assert "status connection timed out" in source
    assert "recoverActivePipelineJob" in source
    assert "assessor.activePipelineJob" in source
    assert "Still running; keeping the background watch active." in source
    assert "SOTA validation is checking edge cases in the background." in source
    assert "mode = a && a.connected ? 'api' : (c && c.connected ? 'codex_local' : '');" in source
    assert "dataset.runningMode = mode" in source
    assert "setRunning(true, 'background');" in source
    assert 'body[data-running-mode="background"] .pipeline-overlay' in styles
    assert "codex.reason || 'Codex not connected'" in source
    assert "setPipelineStatus(msg, 'danger')" in source


def test_feedback_baseline_drafts_seed_teacher_review():
    source = UI_APP.read_text(encoding="utf-8")

    assert "function seedBaselineFeedbackDrafts" in source
    assert "function baselineFeedbackForStudent" in source
    assert "feedback_drafts" in source
    assert "seedBaselineFeedbackDrafts(true);" in source


def test_anchor_and_exceptions_live_in_bottom_drawer():
    source = UI_APP.read_text(encoding="utf-8")
    markup = UI_INDEX.read_text(encoding="utf-8")

    assert 'id="reviewAdvancedDrawer"' in markup
    assert "Calibration and exceptions" in markup
    assert 'id="anchorPanelSlot"' in markup
    assert '<section id="exceptionsSection"' in markup
    assert "const slot = document.getElementById('anchorPanelSlot');" in source
    assert "slot.appendChild(section);" in source
    assert "document.getElementById('reviewAdvancedDrawer')?.classList.toggle('is-hidden', !showAdvancedDrawer);" in source


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


def test_project_save_persists_draft_review_curve_before_snapshot():
    source = UI_APP.read_text(encoding="utf-8")

    assert "async function persistDraftReviewBeforeProjectSave()" in source
    assert "Saving review choices..." in source
    assert "const payload = draftReviewPayload();" in source
    assert "body: JSON.stringify(payload)," in source
    assert "await persistDraftReviewBeforeProjectSave();" in source
    assert "fetch(apiUrl('/projects/save')" in source
    assert "curve_top: num(document.getElementById('topGrade')?.value, null)," in source
    assert "curve_bottom: num(document.getElementById('bottomGrade')?.value, null)," in source
    assert "assigned_marks: currentCohortMarks()," in source


def test_teacher_review_autosaves_interactions_and_recovers_refresh():
    source = UI_APP.read_text(encoding="utf-8")
    markup = UI_INDEX.read_text(encoding="utf-8")

    assert 'app.js?v=22' in markup
    assert "function queueReviewAutosave" in source
    assert "function flushReviewAutosave" in source
    assert "function writeLocalReviewDraftBackup" in source
    assert "function applyLocalReviewDraftBackupIfNewer" in source
    assert "function sendReviewAutosaveBeacon" in source
    assert "function waitForReviewAutosaveIdle" in source
    assert "navigator.sendBeacon(apiUrl('/projects/review')" in source
    assert "window.addEventListener('beforeunload', sendReviewAutosaveBeacon);" in source
    assert "document.visibilityState === 'hidden'" in source
    assert "queueReviewAutosave('assigned_mark')" in source
    assert "queueReviewAutosave('curve_bounds')" in source
    assert "queueReviewAutosave('feedback_star1')" in source
    assert "queueReviewAutosave('evidence_comment')" in source
    assert "queueReviewAutosave('pairwise_prefer_current')" in source
    assert "applyLocalReviewDraftBackupIfNewer();" in source
    assert "await waitForReviewAutosaveIdle();" in source
