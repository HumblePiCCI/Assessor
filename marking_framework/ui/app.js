let data = null, currentIndex = 0, grades = [], overrides = {}, adjustments = {}, feedbackDrafts = {}, reviewBundle = null, reviewStudents = {}, reviewPairs = {}, reviewSessionId = '', scrollTicking = false, compareDirection = 1, previewStudents = [], running = false, shuffleTimer = null, pipelineTimer = null, pipelineStep = 0, projects = [], currentProject = null, sliderStudentId = null, focusLock = false, activeJobId = '', rubricReview = null;
let API_BASE = null;
const apiUrl = path => API_BASE ? `${API_BASE}${path}` : path;
async function detectApiBase() {
  if (API_BASE !== null) return API_BASE;
  const sameOriginOk = await fetch('/auth/status').then(res => res.ok).catch(() => false);
  if (sameOriginOk) { API_BASE = ''; return API_BASE; }
  const alt = `${location.protocol}//${location.hostname}:8000`;
  const altOk = await fetch(`${alt}/auth/status`).then(res => res.ok).catch(() => false);
  API_BASE = altOk ? alt : '';
  return API_BASE;
}
function num(value, fallback = 0) { const n = parseFloat(value); return Number.isFinite(n) ? n : fallback; }
function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }
function computeGrades(top, bottom, count) { if (count <= 0) return []; if (count === 1) return [Math.round(top)]; const result = []; for (let i = 0; i < count; i += 1) { const grade = top - (top - bottom) * (i / (count - 1)); result.push(Math.round(grade)); } return result; }
function baseName(name) { return name.replace(/\.[^.]+$/, ''); }
function labelFor(s) { return (s && (s.display_name || s.student_id)) ? (s.display_name || s.student_id) : ''; }
function getStudents() { return previewStudents.length ? previewStudents : ((data && data.students && data.students.length) ? data.students : []); }
function pairKey(studentId, otherStudentId) { return [studentId, otherStudentId].sort().join('::'); }
function studentReview(studentId) {
  if (!reviewStudents[studentId]) reviewStudents[studentId] = { student_id: studentId, level_override: '', desired_rank: '', evidence_quality: '', evidence_comment: '' };
  return reviewStudents[studentId];
}
function pairReview(studentId, otherStudentId) {
  const key = pairKey(studentId, otherStudentId);
  if (!reviewPairs[key]) reviewPairs[key] = { student_id: studentId, other_student_id: otherStudentId, preferred_student_id: '', confidence: 'teacher', rationale: '' };
  return reviewPairs[key];
}
function compactLabel(text, max = 42) {
  const clean = String(text || '').trim();
  return clean.length > max ? `${clean.slice(0, max - 1).trimEnd()}…` : clean;
}
function setNodeState(node, text, state = 'idle') {
  if (!node) return;
  node.textContent = text;
  node.dataset.state = state;
}
function inferConnectionState(text) {
  const low = String(text || '').toLowerCase();
  if (low.includes('connected')) return 'ready';
  if (low.includes('started') || low.includes('login')) return 'warn';
  if (low.includes('failed') || low.includes('offline') || low.includes('invalid')) return 'danger';
  return 'idle';
}
function inferPipelineState(text) {
  const low = String(text || '').toLowerCase();
  if (running || low.includes('running') || low.includes('working')) return 'running';
  if (low.includes('complete') || low.includes('ready') || low.includes('done')) return 'ready';
  if (low.includes('failed') || low.includes('rejected') || low.includes('timed out')) return 'danger';
  if (low.includes('need') || low.includes('add ') || low.includes('checking') || low.includes('idle')) return 'warn';
  return 'idle';
}
function updateWorkflowState() {
  const authText = document.getElementById('authStatus')?.textContent || 'Offline';
  const projectText = currentProject ? currentProject.name : 'unsaved';
  const pipelineText = document.getElementById('pipelineStatus')?.textContent || 'Idle';
  const authState = inferConnectionState(authText);
  const pipelineState = inferPipelineState(pipelineText);
  const essayCount = document.getElementById('uploadEssays')?.files?.length || 0;
  const rubricReady = !!document.getElementById('uploadRubric')?.files?.[0];
  const outlineReady = !!document.getElementById('uploadOutline')?.files?.[0];
  const students = getStudents();
  const hasReview = !!(data?.students?.length);
  const filesReady = essayCount > 0 && rubricReady && outlineReady;
  setNodeState(document.getElementById('projectBadge'), `Project · ${compactLabel(projectText, 28)}`, currentProject ? 'ready' : 'idle');
  setNodeState(document.getElementById('connectionBadge'), `Connection · ${compactLabel(authText, 24)}`, authState);
  setNodeState(document.getElementById('runBadge'), `Pipeline · ${compactLabel(pipelineText, 26)}`, pipelineState);
  const hint = document.getElementById('intakeHint');
  if (hint) {
    if (hasReview) {
      hint.textContent = `${students.length} essays loaded. Review the order, correct the exceptions, then finalize.`;
    } else if (!essayCount && !rubricReady && !outlineReady) {
      hint.textContent = 'Add essays, rubric, and outline. Then run the assessment.';
    } else {
      const parts = [
        essayCount ? `${essayCount} essay file${essayCount === 1 ? '' : 's'} ready` : 'add essays',
        rubricReady ? 'rubric ready' : 'add rubric',
        outlineReady ? 'outline ready' : 'add outline',
      ];
      hint.textContent = parts.join(' · ');
    }
  }
  const railMeta = document.getElementById('railMeta');
  if (railMeta) railMeta.textContent = students.length ? `${students.length} essays in order` : 'No essays loaded';
  const runButton = document.getElementById('runPipelinePrimary');
  if (runButton) {
    runButton.disabled = running || !filesReady || authState !== 'ready';
    runButton.textContent = running ? 'Running…' : 'Run assessment';
  }
}
function setPipelineStatus(text, state = inferPipelineState(text)) {
  setNodeState(document.getElementById('pipelineStatus'), text, state);
  updateWorkflowState();
}
function updateControlVisibility() {
  const hasScored = !!(data && data.students && data.students.length);
  const multipleStudents = hasScored && data.students.length > 1;
  document.getElementById('actionsEmpty')?.classList.toggle('is-hidden', hasScored);
  document.getElementById('teacherSpotlight')?.classList.toggle('is-hidden', !hasScored);
  document.getElementById('feedbackSection')?.classList.toggle('is-hidden', !hasScored);
  const prevBtn = document.getElementById('prevBtn');
  const nextBtn = document.getElementById('nextBtn');
  if (prevBtn) prevBtn.disabled = !hasScored || currentIndex <= 0;
  if (nextBtn) nextBtn.disabled = !hasScored || currentIndex >= (data.students.length - 1);
  const viewToggle = document.getElementById('viewToggle');
  if (viewToggle) {
    viewToggle.disabled = !multipleStudents;
    if (!multipleStudents && document.body.dataset.view === 'split') document.body.dataset.view = 'single';
    viewToggle.textContent = document.body.dataset.view === 'split' ? 'Single view' : 'Compare';
  }
  const copyFeedback = document.getElementById('copyFeedback');
  if (copyFeedback) copyFeedback.disabled = !hasScored;
  const generateFeedback = document.getElementById('generateFeedback');
  if (generateFeedback) generateFeedback.disabled = !hasScored;
}
async function refreshAuthStatus() {
  const status = document.getElementById('authStatus');
  if (!status) return;
  const codexBtn = document.getElementById('codexLogin');
  try {
    const [codexRes, apiRes] = await Promise.all([fetch(apiUrl('/codex/status')), fetch(apiUrl('/auth/status'))]);
    const codex = codexRes.ok ? await codexRes.json() : null;
    const api = apiRes.ok ? await apiRes.json() : null;
    if (codex && codex.available && codex.connected) {
      status.textContent = 'Codex connected';
      if (codexBtn) { codexBtn.disabled = true; codexBtn.textContent = 'Codex connected'; }
    } else if (api && api.connected) {
      status.textContent = 'API key connected';
      if (codexBtn) { codexBtn.disabled = false; codexBtn.textContent = 'Sign in with Codex'; }
    } else if (codex && codex.available) {
      status.textContent = 'Codex not connected';
      if (codexBtn) { codexBtn.disabled = false; codexBtn.textContent = 'Sign in with Codex'; }
    } else {
      status.textContent = 'Offline';
      if (codexBtn) { codexBtn.disabled = false; codexBtn.textContent = 'Sign in with Codex'; }
    }
  } catch (err) {
    status.textContent = 'Offline';
    if (codexBtn) { codexBtn.disabled = false; codexBtn.textContent = 'Sign in with Codex'; }
  }
  updateWorkflowState();
}
async function connectApiKey() {
  const input = document.getElementById('apiKeyInput');
  const status = document.getElementById('authStatus');
  if (!input || !status) return;
  const key = input.value.trim();
  if (!key) return;
  try {
    const res = await fetch(apiUrl('/auth'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ api_key: key }) });
    if (!res.ok) {
      status.textContent = 'Invalid key';
      updateWorkflowState();
      return;
    }
    input.value = '';
    status.textContent = 'API key connected';
  } catch (err) {
    status.textContent = 'Offline';
  }
  updateWorkflowState();
}
async function startCodexLogin() {
  const status = document.getElementById('authStatus');
  if (!status) return;
  try {
    const res = await fetch(apiUrl('/codex/login'), { method: 'POST' });
    if (!res.ok) {
      let msg = 'Codex login failed';
      try { const err = await res.json(); if (err.detail) msg = err.detail; } catch (_) {}
      status.textContent = msg;
      updateWorkflowState();
      return;
    }
    const payload = await res.json().catch(() => ({}));
    status.textContent = payload.status === 'already_connected' ? 'Codex connected' : 'Codex login started';
    updateWorkflowState();
    setTimeout(refreshAuthStatus, 1500);
  } catch (err) {
    status.textContent = 'Offline';
    updateWorkflowState();
  }
}
async function loadProjects() {
  const select = document.getElementById('projectSelect');
  if (!select) return;
  try {
    const res = await fetch(apiUrl('/projects'));
    if (!res.ok) return;
    const payload = await res.json();
    projects = payload.projects || [];
    currentProject = payload.current || null;
    select.innerHTML = '';
    if (!projects.length) {
      const opt = document.createElement('option');
      opt.textContent = 'No saved projects';
      opt.value = '';
      opt.disabled = true;
      opt.selected = true;
      select.appendChild(opt);
    } else {
      projects.forEach(p => {
        const opt = document.createElement('option');
        opt.textContent = p.name || p.id;
        opt.value = p.id;
        if (currentProject && p.id === currentProject.id) opt.selected = true;
        select.appendChild(opt);
      });
    }
    const status = document.getElementById('projectStatus');
    if (status) status.textContent = currentProject ? `Current: ${currentProject.name}` : 'No project loaded';
  } catch (_) {}
  updateWorkflowState();
}
async function saveProject() { const name = currentProject ? null : prompt('Project name', '') || ''; if (!currentProject && !name) return; try { const res = await fetch(apiUrl('/projects/save'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(name ? { name } : {}) }); if (!res.ok) return; currentProject = await res.json(); await loadProjects(); } catch (_) {} }
async function newProject() { const name = prompt('New project name', '') || ''; if (!name) return; try { const res = await fetch(apiUrl('/projects/new'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) }); if (!res.ok) return; currentProject = await res.json(); location.reload(); } catch (_) {} }
function resetUploadLabels() {
  document.querySelectorAll('.upload').forEach(zone => {
    const input = zone.querySelector('input');
    const label = zone.querySelector('span');
    if (!input || !label) return;
    input.value = '';
    if (input.id === 'uploadEssays') label.textContent = 'Drop essays';
    else if (input.id === 'uploadRubric') label.textContent = 'Drop rubric';
    else if (input.id === 'uploadOutline') label.textContent = 'Drop outline';
  });
}
function clearLocalState() {
  data = { students: [] };
  previewStudents = [];
  overrides = {};
  adjustments = {};
  feedbackDrafts = {};
  reviewBundle = null;
  reviewStudents = {};
  reviewPairs = {};
  reviewSessionId = '';
  activeJobId = '';
  rubricReview = null;
  grades = [];
  currentIndex = 0; sliderStudentId = null; focusLock = false;
  resetUploadLabels();
  setPipelineStatus('Idle', 'idle');
  renderRubricReview(null);
  renderRail(); renderDetail(); updateWorkflowState();
}
async function clearProject() { if (!confirm('Clear the current session?')) return; clearLocalState(); const status = document.getElementById('projectStatus'); if (status) status.textContent = 'Clearing session...'; try { const res = await fetch(apiUrl('/projects/clear'), { method: 'POST' }); if (!res.ok) throw new Error('clear failed'); await loadProjects(); location.href = `${location.pathname}?t=${Date.now()}`; } catch (_) { if (status) status.textContent = 'Server unavailable: local view cleared only'; } }
async function loadProject() { const select = document.getElementById('projectSelect'); if (!select || !select.value) return; try { const res = await fetch(apiUrl('/projects/load'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: select.value }) }); if (!res.ok) return; location.reload(); } catch (_) {} }
async function deleteProject() { const select = document.getElementById('projectSelect'); if (!select || !select.value) return; if (!confirm('Delete this project?')) return; try { const res = await fetch(apiUrl(`/projects/${select.value}`), { method: 'DELETE' }); if (!res.ok) return; await loadProjects(); } catch (_) {} }
function actionsInsertionAnchor(actions) {
  if (!actions) return null;
  return document.getElementById('teacherSpotlight')
    || Array.from(actions.children).find(child => child.classList && child.classList.contains('secondary-details'))
    || null;
}
function ensureReviewPanel() {
  let section = document.getElementById('reviewSection');
  if (section) return section;
  const actions = document.getElementById('actions');
  if (!actions) return null;
  section = document.createElement('div');
  section.id = 'reviewSection';
  section.className = 'auth review-section';
  section.innerHTML = `
    <div class="panel-row">
      <div>
        <div class="label">Teacher review</div>
        <div id="reviewDraftStatus" class="auth-status">No draft review yet.</div>
      </div>
      <div class="project-actions">
        <button id="saveReview" class="ghost">Save draft</button>
        <button id="finalizeReview" class="primary">Finalize review</button>
      </div>
    </div>
    <div id="reviewUncertainty" class="review-flags"></div>
    <div class="controls">
      <div class="control">
        <label for="reviewLevelOverride">Final level</label>
        <select id="reviewLevelOverride">
          <option value="">No override</option>
          <option value="1">Level 1</option>
          <option value="2">Level 2</option>
          <option value="3">Level 3</option>
          <option value="4">Level 4</option>
          <option value="4+">Level 4+</option>
        </select>
      </div>
      <div class="control">
        <label for="reviewEvidenceComment">Teacher note</label>
        <textarea id="reviewEvidenceComment" rows="4" placeholder="Only add a note if the machine missed something important."></textarea>
      </div>
    </div>
    <div class="review-pairwise">
      <div class="label">Pairwise check</div>
      <div class="project-actions">
        <button id="preferCurrent" class="ghost">Keep current above compare</button>
        <button id="preferCompare" class="ghost">Move compare above current</button>
        <button id="clearPairwise" class="ghost">Clear pair</button>
      </div>
      <div class="auth-status" id="pairwiseStatus">Open split view to compare two essays.</div>
    </div>
    <details class="secondary-details">
      <summary>More review options</summary>
      <div class="controls compact-controls">
        <div class="control">
          <label for="reviewDesiredRank">Teacher rank</label>
          <input id="reviewDesiredRank" type="number" min="1" placeholder="Keep machine order" />
        </div>
        <div class="control">
          <label for="reviewEvidenceQuality">Evidence signal</label>
          <select id="reviewEvidenceQuality">
            <option value="">No note</option>
            <option value="strong">Strong evidence</option>
            <option value="thin">Thin evidence</option>
            <option value="misaligned">Misaligned evidence</option>
            <option value="unclear">Unclear evidence</option>
          </select>
        </div>
      </div>
    </details>
    <div id="reviewStatus" class="auth-status">No finalized review yet.</div>
    <div id="learningSummary" class="auth-status">Local profile unavailable.</div>
  `;
  const anchor = actionsInsertionAnchor(actions);
  if (anchor) actions.insertBefore(section, anchor);
  else actions.appendChild(section);
  return section;
}
function ensureRubricPanel() {
  let section = document.getElementById('rubricSection');
  if (section) return section;
  const actions = document.getElementById('actions');
  if (!actions) return null;
  section = document.createElement('div');
  section.id = 'rubricSection';
  section.className = 'auth review-section is-hidden';
  section.innerHTML = `
    <div class="panel-row">
      <div>
        <div class="label">Rubric review</div>
        <div id="rubricStatus" class="auth-status">No rubric review pending.</div>
      </div>
      <div class="project-actions">
        <button id="confirmRubric" class="primary">Confirm rubric</button>
        <button id="saveRubricEdits" class="ghost">Correct interpretation</button>
        <button id="rejectRubric" class="ghost">Reject</button>
      </div>
    </div>
    <div id="rubricSummary" class="auth-status"></div>
    <div id="rubricWarnings" class="review-flags"></div>
    <details class="secondary-details">
      <summary>Correct our interpretation</summary>
      <div class="controls">
        <div class="control">
          <label for="rubricGenre">Genre</label>
          <input id="rubricGenre" type="text" placeholder="literary_analysis" />
        </div>
        <div class="control">
          <label for="rubricFamily">Rubric family</label>
          <input id="rubricFamily" type="text" placeholder="rubric family" />
        </div>
        <div class="control">
          <label for="rubricCriteria">Criteria (JSON)</label>
          <textarea id="rubricCriteria" rows="6" placeholder='[{"name":"Ideas and Analysis","weight":0.25}]'></textarea>
        </div>
        <div class="control">
          <label for="rubricLevels">Levels (JSON)</label>
          <textarea id="rubricLevels" rows="6" placeholder='[{"label":"4","band_min":80,"band_max":100}]'></textarea>
        </div>
        <div class="control">
          <label for="rubricNotes">Verification notes</label>
          <textarea id="rubricNotes" rows="3" placeholder="Only add notes if our interpretation needs a correction."></textarea>
        </div>
      </div>
    </details>
  `;
  const review = document.getElementById('reviewSection');
  const anchor = review || actionsInsertionAnchor(actions);
  if (anchor) actions.insertBefore(section, anchor);
  else actions.appendChild(section);
  return section;
}
function safeStringify(value) {
  if (!value || (Array.isArray(value) && !value.length)) return '[]';
  try { return JSON.stringify(value, null, 2); } catch (_) { return '[]'; }
}
function parseRubricJson(id) {
  const node = document.getElementById(id);
  if (!node) return [];
  const text = (node.value || '').trim();
  if (!text) return [];
  return JSON.parse(text);
}
function renderRubricReview(bundle) {
  const section = ensureRubricPanel();
  rubricReview = bundle || null;
  const status = document.getElementById('rubricStatus');
  const summary = document.getElementById('rubricSummary');
  const warnings = document.getElementById('rubricWarnings');
  const genre = document.getElementById('rubricGenre');
  const family = document.getElementById('rubricFamily');
  const criteria = document.getElementById('rubricCriteria');
  const levels = document.getElementById('rubricLevels');
  const notes = document.getElementById('rubricNotes');
  const confirmBtn = document.getElementById('confirmRubric');
  const editBtn = document.getElementById('saveRubricEdits');
  const rejectBtn = document.getElementById('rejectRubric');
  if (!status || !summary || !warnings || !genre || !family || !criteria || !levels || !notes || !section) return;
  if (!bundle) {
    section.classList.add('is-hidden');
    status.textContent = 'No rubric review pending.';
    summary.textContent = '';
    warnings.innerHTML = '';
    genre.value = '';
    family.value = '';
    criteria.value = '[]';
    levels.value = '[]';
    notes.value = '';
    [confirmBtn, editBtn, rejectBtn].forEach(btn => { if (btn) btn.disabled = true; });
    return;
  }
  const verification = bundle.rubric_verification || {};
  const validation = bundle.rubric_validation_report || {};
  const manifest = bundle.rubric_manifest || {};
  const projection = verification.editable_projection || {};
  const pending = bundle.status === 'awaiting_rubric_confirmation' || verification.required_confirmation;
  const verificationLabel = verification.status ? verification.status.replaceAll('_', ' ') : 'unknown';
  const confidence = validation.confidence || {};
  section.classList.toggle('is-hidden', !(pending || (verification.errors || []).length || (verification.warnings || []).length));
  status.textContent = pending
    ? `Rubric review required before scoring continues. Status: ${verificationLabel}.`
    : `Rubric status: ${verificationLabel}. Confidence: ${confidence.status || manifest.confidence_status || 'unknown'}.`;
  summary.textContent = (verification.summary || []).join(' ') || 'No rubric interpretation summary available.';
  warnings.innerHTML = '';
  [...(verification.errors || []), ...(verification.warnings || [])].forEach(item => {
    const badge = document.createElement('span');
    badge.className = 'review-badge';
    badge.textContent = String(item || '').replaceAll('_', ' ');
    warnings.appendChild(badge);
  });
  genre.value = projection.genre || '';
  family.value = projection.rubric_family || '';
  criteria.value = safeStringify(projection.criteria || []);
  levels.value = safeStringify(projection.levels || []);
  notes.value = ((verification.teacher_edits || {}).teacher_notes || '');
  [confirmBtn, editBtn, rejectBtn].forEach(btn => { if (btn) btn.disabled = !pending; });
}
async function fetchRubricReview(jobId) {
  const res = await fetch(apiUrl(`/pipeline/v2/jobs/${jobId}/rubric`));
  if (!res.ok) throw new Error('Rubric review unavailable');
  const payload = await res.json();
  renderRubricReview(payload);
  return payload;
}
async function continueJobAfterRubric(result) {
  if (result.status === 'failed') {
    setPipelineStatus('Rubric review rejected.', 'danger');
    stopShuffle();
    stopPipelineNarrative('Rubric review rejected.');
    return;
  }
  setPipelineStatus('Rubric confirmed. Running...', 'running');
  setRunning(true);
  startPipelineNarrative();
  startShuffle();
  const job = await waitForJob(activeJobId);
  if (job.status === 'awaiting_rubric_confirmation') {
    await fetchRubricReview(activeJobId);
    return;
  }
  const dataRes = await fetch(apiUrl(`/pipeline/v2/jobs/${job.id || activeJobId}/data`));
  if (!dataRes.ok) throw new Error('Dashboard data unavailable');
  previewStudents = [];
  await boot(await dataRes.json());
  setPipelineStatus('Complete', 'ready');
  stopShuffle();
  stopPipelineNarrative('Done. Review is ready.');
}
async function submitRubricReview(action) {
  if (!activeJobId) return;
  const status = document.getElementById('rubricStatus');
  if (status) status.textContent = action === 'reject' ? 'Rejecting rubric...' : 'Submitting rubric confirmation...';
  try {
    const payload = { action };
    if (action === 'edit') {
      payload.genre = (document.getElementById('rubricGenre')?.value || '').trim();
      payload.rubric_family = (document.getElementById('rubricFamily')?.value || '').trim();
      payload.teacher_notes = (document.getElementById('rubricNotes')?.value || '').trim();
      payload.criteria = parseRubricJson('rubricCriteria');
      payload.levels = parseRubricJson('rubricLevels');
    }
    const res = await fetch(apiUrl(`/pipeline/v2/jobs/${activeJobId}/rubric`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error('Rubric confirmation failed');
    const result = await res.json();
    renderRubricReview(result);
    await continueJobAfterRubric(result);
  } catch (err) {
    if (status) status.textContent = `Rubric confirmation failed: ${err.message || 'unknown error'}`;
  }
}
function applyReviewBundle(bundle) {
  ensureRubricPanel();
  ensureReviewPanel();
  reviewBundle = bundle || null;
  reviewStudents = {};
  reviewPairs = {};
  const draft = (bundle && bundle.draft_review) ? bundle.draft_review : {};
  const latest = (bundle && bundle.latest_review) ? bundle.latest_review : {};
  const active = (draft && ((draft.students && draft.students.length) || (draft.pairwise && draft.pairwise.length) || draft.review_notes)) ? draft : latest;
  reviewSessionId = ((draft && draft.review_session && draft.review_session.session_id) || (latest && latest.review_session && latest.review_session.session_id) || '');
  (active.students || []).forEach(item => {
    reviewStudents[item.student_id] = {
      student_id: item.student_id,
      level_override: item.level_override || '',
      desired_rank: item.desired_rank ?? '',
      evidence_quality: item.evidence_quality || '',
      evidence_comment: item.evidence_comment || '',
    };
  });
  (active.pairwise || []).forEach(item => {
    const left = (item.pair && item.pair[0]) || item.student_id || item.higher_student_id;
    const right = (item.pair && item.pair[1]) || item.other_student_id || item.lower_student_id;
    if (!left || !right) return;
    reviewPairs[pairKey(left, right)] = {
      student_id: left,
      other_student_id: right,
      preferred_student_id: item.preferred_student_id || item.higher_student_id || '',
      confidence: item.confidence || 'teacher',
      rationale: item.rationale || item.evidence_comment || '',
    };
  });
  const reviewStatus = document.getElementById('reviewStatus');
  if (reviewStatus) {
    const savedAt = latest.saved_at || '';
    reviewStatus.textContent = savedAt ? `Latest finalized review saved ${savedAt}` : 'No finalized review yet.';
  }
  const reviewDraftStatus = document.getElementById('reviewDraftStatus');
  if (reviewDraftStatus) {
    const savedAt = draft.saved_at || '';
    reviewDraftStatus.textContent = savedAt ? `Draft session saved ${savedAt}` : 'No draft review yet.';
  }
  const learningSummary = document.getElementById('learningSummary');
  if (learningSummary) {
    const profile = (bundle && bundle.local_learning_profile) ? bundle.local_learning_profile : {};
    const prior = (bundle && bundle.local_teacher_prior) ? bundle.local_teacher_prior : {};
    const aggregate = (bundle && bundle.aggregate_learning) ? bundle.aggregate_learning : {};
    const anon = (bundle && bundle.anonymized_aggregate) ? bundle.anonymized_aggregate : {};
    const activeLabel = prior.active ? 'active' : (prior.activation && prior.activation.reason) ? prior.activation.reason.replaceAll('_', ' ') : 'inactive';
    const aggregateMode = aggregate.mode || anon.mode || 'local_only';
    learningSummary.textContent = `Local learning: ${profile.review_count || 0} finalized reviews · ${profile.student_review_count || 0} essay decisions · ${profile.pairwise_adjudication_count || 0} pairwise calls · prior ${activeLabel} · aggregate mode ${aggregateMode}.`;
  }
}
async function loadReviewBundle() {
  ensureRubricPanel();
  ensureReviewPanel();
  try {
    const res = await fetch(apiUrl('/projects/review'));
    if (!res.ok) return;
    applyReviewBundle(await res.json());
  } catch (_) {}
}
function renderReviewPanel(student) {
  const section = ensureReviewPanel();
  const uncertainty = document.getElementById('reviewUncertainty');
  const level = document.getElementById('reviewLevelOverride');
  const desiredRank = document.getElementById('reviewDesiredRank');
  const quality = document.getElementById('reviewEvidenceQuality');
  const comment = document.getElementById('reviewEvidenceComment');
  const pairStatus = document.getElementById('pairwiseStatus');
  if (!uncertainty || !level || !desiredRank || !quality || !comment || !pairStatus || !section) return;
  section.classList.toggle('is-hidden', !student && !(data?.students?.length));
  if (!student) {
    uncertainty.innerHTML = '';
    level.value = '';
    desiredRank.value = '';
    quality.value = '';
    comment.value = '';
    pairStatus.textContent = 'Open split view to compare two essays.';
    return;
  }
  const entry = studentReview(student.student_id);
  level.value = entry.level_override || '';
  desiredRank.value = entry.desired_rank === '' ? '' : entry.desired_rank;
  quality.value = entry.evidence_quality || '';
  comment.value = entry.evidence_comment || '';
  const flags = student.uncertainty_flags || [];
  const reasons = student.uncertainty_reasons || [];
  uncertainty.innerHTML = '';
  if (!flags.length) {
    uncertainty.innerHTML = '<div class="auth-status">No uncertainty flags on this essay.</div>';
  } else {
    flags.forEach((flag, idx) => {
      const badge = document.createElement('span');
      badge.className = 'review-badge';
      badge.textContent = flag.replaceAll('_', ' ');
      badge.title = reasons[idx] || flag;
      uncertainty.appendChild(badge);
    });
  }
  const compareIndex = getCompareIndex();
  if (compareIndex === null || document.body.dataset.view !== 'split') {
    pairStatus.textContent = 'Switch to compare view if you need to adjudicate a close pair.';
  } else {
    const compare = data.students[compareIndex];
    const pair = reviewPairs[pairKey(student.student_id, compare.student_id)];
    const preferred = pair && pair.preferred_student_id ? labelFor(data.students.find(item => item.student_id === pair.preferred_student_id) || { student_id: pair.preferred_student_id }) : 'none saved';
    pairStatus.textContent = `Comparing with ${labelFor(compare)}. Saved preference: ${preferred}.`;
  }
}
function reviewPayload() {
  const students = Object.values(reviewStudents).filter(item => item.level_override || item.evidence_quality || item.evidence_comment || item.desired_rank !== '');
  const pairwise = Object.values(reviewPairs).filter(item => item.preferred_student_id);
  return { students, pairwise, session_id: reviewSessionId };
}
async function saveReviewBundle(action = 'draft') {
  const reviewStatus = document.getElementById('reviewStatus');
  const reviewDraftStatus = document.getElementById('reviewDraftStatus');
  if (action === 'finalize') {
    if (reviewStatus) reviewStatus.textContent = 'Finalizing review...';
  } else if (reviewDraftStatus) {
    reviewDraftStatus.textContent = 'Saving draft review...';
  }
  try {
    const res = await fetch(apiUrl('/projects/review'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...reviewPayload(), action }),
    });
    if (!res.ok) throw new Error('save failed');
    applyReviewBundle(await res.json());
    if (data?.students?.length) renderReviewPanel(data.students[currentIndex]);
  } catch (_) {
    if (action === 'finalize') {
      if (reviewStatus) reviewStatus.textContent = 'Failed to finalize review.';
    } else if (reviewDraftStatus) {
      reviewDraftStatus.textContent = 'Failed to save draft review.';
    }
  }
}
function getCompareIndex() { if (!data || data.students.length < 2) return null; const target = currentIndex + compareDirection; if (target >= 0 && target < data.students.length) return target; const fallback = currentIndex - compareDirection; if (fallback >= 0 && fallback < data.students.length) return fallback; return null; }
function getAdjustment(studentId) { if (!adjustments[studentId]) adjustments[studentId] = { overall: 0, rubric: 0, conventions: 0, comparative: 0 }; return adjustments[studentId]; }
function currentCohortMarks() {
  if (!data?.students?.length) return [];
  return data.students.map((student, idx) => ({ student_id: student.student_id, mark: num(getGradeForIndex(idx), 0) }));
}
function scaledMarksForRange(existingMarks, top, bottom) {
  const count = existingMarks.length;
  if (!count) return [];
  if (count === 1) return [Math.round(top)];
  const oldTop = num(existingMarks[0]?.mark, top);
  const oldBottom = num(existingMarks[count - 1]?.mark, bottom);
  if (oldTop <= oldBottom) return computeGrades(top, bottom, count);
  return existingMarks.map(({ mark }, idx) => {
    if (idx === 0) return Math.round(top);
    if (idx === count - 1) return Math.round(bottom);
    const ratio = clamp((num(mark, oldBottom) - oldBottom) / (oldTop - oldBottom), 0, 1);
    return Math.round(bottom + ((top - bottom) * ratio));
  });
}
function applyCurveBounds(top, bottom, preserveShape = true) {
  if (!data?.students?.length) return;
  const currentMarks = preserveShape ? currentCohortMarks() : [];
  grades = computeGrades(top, bottom, data.students.length);
  delete data.curve_top;
  delete data.curve_bottom;
  data.curve_top = top;
  data.curve_bottom = bottom;
  if (preserveShape) {
    const scaledMarks = scaledMarksForRange(currentMarks, top, bottom);
    overrides = {};
    data.students.forEach((student, idx) => {
      const adj = getAdjustment(student.student_id);
      adj.overall = (scaledMarks[idx] ?? grades[idx] ?? 0) - (grades[idx] ?? 0);
    });
  }
}
function getGradeForIndex(idx) {
  if (!data || !data.students || !data.students.length) return '';
  const s = data.students[idx];
  const override = overrides[s.student_id];
  if (override !== undefined) return override;
  const base = grades[idx] ?? 0;
  const adj = getAdjustment(s.student_id);
  return clamp(Math.round(base + adj.overall), 0, 100);
}
function renderRail(animate = false) {
  const rail = document.getElementById('railScroll');
  const list = getStudents();
  const keep = new Set(list.map(s => s.student_id));
  const first = animate ? new Map() : null;
  if (animate) rail.querySelectorAll('.rail-item').forEach(el => first.set(el.dataset.id, el.getBoundingClientRect()));
  const existing = {};
  rail.querySelectorAll('.rail-item').forEach(el => { existing[el.dataset.id] = el; });
	list.forEach((s, idx) => {
		let item = existing[s.student_id];
    if (!item) {
      item = document.createElement('button');
      item.className = 'rail-item';
      item.dataset.id = s.student_id;
      item.addEventListener('click', () => scrollToIndex(parseInt(item.dataset.index, 10), true));
		}
		item.dataset.index = idx;
		item.innerHTML = `<div class="rail-rank">Rank ${s.rank || idx + 1}</div><div class="rail-name">${labelFor(s)}</div><div class="rail-grade"></div>`;
		rail.appendChild(item);
	});
  rail.querySelectorAll('.rail-item').forEach(el => { if (!keep.has(el.dataset.id)) el.remove(); });
  if (animate) {
    rail.querySelectorAll('.rail-item').forEach(el => {
      const f = first.get(el.dataset.id); if (!f) return;
      const l = el.getBoundingClientRect(); const dx = f.left - l.left;
      if (dx) { el.style.transform = `translateX(${dx}px)`; el.style.transition = 'transform 0s'; requestAnimationFrame(() => { el.style.transition = 'transform 0.4s ease'; el.style.transform = ''; }); }
    });
  }
  updateRail();
  updateWorkflowState();
}
function updateRail() { const rail = document.getElementById('railScroll'); rail.querySelectorAll('.rail-item').forEach((item, idx) => { item.classList.toggle('active', idx === currentIndex); const gradeEl = item.querySelector('.rail-grade'); if (gradeEl) gradeEl.textContent = getGradeForIndex(idx) || '—'; }); }
function scrollToIndex(idx, smooth) { if (!getStudents().length) return; const rail = document.getElementById('railScroll'); const item = rail.querySelector(`[data-index="${idx}"]`); if (!item) return; item.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', inline: 'center', block: 'nearest' }); currentIndex = idx; updateRail(); renderDetail(); }
function findCenteredIndex() {
  const rail = document.getElementById('railScroll');
  const items = Array.from(rail.children);
  if (!items.length) return 0;
  const center = rail.getBoundingClientRect().left + rail.clientWidth / 2;
  let best = 0;
  let bestDist = Infinity;
  items.forEach((item, idx) => {
    const rect = item.getBoundingClientRect();
    const dist = Math.abs(rect.left + rect.width / 2 - center);
    if (dist < bestDist) {
      bestDist = dist;
      best = idx;
    }
  });
  return best;
}
function updateFromScroll() {
  if (focusLock) return;
  if (scrollTicking) return;
  scrollTicking = true;
  requestAnimationFrame(() => {
    const idx = findCenteredIndex();
    if (idx !== currentIndex) {
      currentIndex = idx;
      updateRail();
      renderDetail();
    }
    scrollTicking = false;
  });
}
function parseFeedback(text) {
  if (!text) return { star1: '', star2: '', wish: '' };
  const grab = (start, end) => {
    const s = text.indexOf(start);
    if (s === -1) return '';
    const sub = text.slice(s + start.length);
    const e = end ? sub.indexOf(end) : -1;
    return (e === -1 ? sub : sub.slice(0, e)).trim();
  };
  return {
    star1: grab('### Star 1', '### Star 2'),
    star2: grab('### Star 2', '## One Wish'),
    wish: grab('## One Wish', null),
  };
}
function feedbackForStudent(studentId, feedbackText) { if (!feedbackDrafts[studentId]) feedbackDrafts[studentId] = parseFeedback(feedbackText); return feedbackDrafts[studentId]; }
function renderSummary(student) {
  const summary = document.getElementById('summaryList');
  summary.innerHTML = '';
  const uncertaintyFlags = student.uncertainty_flags || [];
  const uncertaintyReasons = student.uncertainty_reasons || [];
  const rows = [
    {
      label: 'Recommended level',
      value: student.level_with_modifier || student.adjusted_level || '—',
      support: student.flags || 'Machine recommendation',
    },
    {
      label: 'Assigned mark',
      value: getGradeForIndex(currentIndex) || '—',
      support: `Rank ${student.rank} of ${data.students.length}`,
    },
    {
      label: 'Rubric signal',
      value: `${Math.round(num(student.rubric_mean_percent))}%`,
      support: `Conventions ${Math.round(num(student.conventions_mistake_rate_percent))}% error rate`,
    },
    {
      label: 'Uncertainty',
      value: uncertaintyFlags.length ? uncertaintyFlags.map(flag => flag.replaceAll('_', ' ')).join(', ') : 'Stable',
      support: uncertaintyReasons[0] || 'No uncertainty flags on this essay.',
    },
  ];
  rows.forEach(row => {
    const stage = document.createElement('div');
    stage.className = 'summary-card';
    stage.innerHTML = `
      <div class="stage-label">${row.label}</div>
      <div class="stage-value">${row.value}</div>
      <div class="summary-support">${row.support}</div>
    `;
    summary.appendChild(stage);
  });
}
function renderEssayTo(targetId, text) {
  const essay = document.getElementById(targetId);
  if (!essay) return;
  essay.innerHTML = '';
  const paras = (text || '').split(/\n\n+/);
  paras.forEach(p => {
    const para = document.createElement('p');
    para.textContent = p;
    essay.appendChild(para);
  });
}
function renderFeedback(student) {
  const draft = feedbackForStudent(student.student_id, student.feedback_text || '');
  const star1 = document.getElementById('star1');
  const star2 = document.getElementById('star2');
  const wish = document.getElementById('wish');
  star1.innerText = draft.star1;
  star2.innerText = draft.star2;
  wish.innerText = draft.wish;
  star1.oninput = () => { draft.star1 = star1.innerText.trim(); };
  star2.oninput = () => { draft.star2 = star2.innerText.trim(); };
  wish.oninput = () => { draft.wish = wish.innerText.trim(); };
}
function renderDetail() {
  const summaryPanel = document.getElementById('summary');
  const emptyState = document.getElementById('workspaceEmpty');
  const essayGrid = document.getElementById('essayGrid');
  if (previewStudents.length || !data || !data.students || !data.students.length) {
    document.getElementById('detailTitle').textContent = previewStudents.length ? 'Files ready. Run the assessment to review the cohort.' : 'Upload essays to begin';
    document.getElementById('essay').innerHTML = '<p>Once the assessment runs, the essay text and comparison view will appear here.</p>';
    document.getElementById('essayLabelPrimary').textContent = '';
    document.getElementById('essayLabelCompare').textContent = '';
    if (summaryPanel) summaryPanel.classList.add('is-hidden');
    if (emptyState) emptyState.classList.remove('is-hidden');
    if (essayGrid) essayGrid.classList.add('is-hidden');
    renderReviewPanel(null);
    updateControlVisibility();
    updateWorkflowState();
    return;
	}
	const student = data.students[currentIndex];
  if (summaryPanel) summaryPanel.classList.remove('is-hidden');
  if (emptyState) emptyState.classList.add('is-hidden');
  if (essayGrid) essayGrid.classList.remove('is-hidden');
	document.getElementById('detailTitle').textContent = `${labelFor(student)} • Rank ${student.rank}`;
	renderSummary(student);
	document.getElementById('essayLabelPrimary').textContent = `${labelFor(student)} • Rank ${student.rank}`;
	renderEssayTo('essay', student.text || '');
  const compareIndex = getCompareIndex();
  const comparePanel = document.getElementById('comparePanel');
  const splitView = document.body.dataset.view === 'split';
  if (!splitView || compareIndex === null) {
    comparePanel.style.display = 'none';
	} else {
		comparePanel.style.display = '';
		const compare = data.students[compareIndex];
		document.getElementById('essayLabelCompare').textContent = `${labelFor(compare)} • Rank ${compare.rank}`;
		renderEssayTo('essayCompare', compare.text || '');
		comparePanel.onclick = () => scrollToIndex(compareIndex, true);
	}
  renderFeedback(student);
  renderReviewPanel(student);
  const gradeInput = document.getElementById('gradeOverride');
  const override = overrides[student.student_id];
  gradeInput.value = override !== undefined ? override : getGradeForIndex(currentIndex);
  const gradeSlider = document.getElementById('overallGradeSlider'); if (gradeSlider) gradeSlider.value = gradeInput.value || getGradeForIndex(currentIndex);
  updateControlVisibility();
  updateWorkflowState();
}
function applyAdjustment(studentId, key, delta) { const sidx = Math.max(0, data?.students?.findIndex(s => s.student_id === studentId) ?? 0); currentIndex = sidx; const adj = getAdjustment(studentId); adj[key] += delta; const target = key === 'overall' && data?.students?.length ? getGradeForIndex(sidx) : null; if (data?.students?.length && window.gradeAdjust?.resort) { focusLock = true; for (let i = 0; i < 3; i += 1) { window.gradeAdjust.resort(data.students, getGradeForIndex); currentIndex = Math.max(0, data.students.findIndex(s => s.student_id === studentId)); if (target === null) break; const diff = target - getGradeForIndex(currentIndex); if (Math.abs(diff) < 0.5) break; adj.overall += diff; } renderRail(true); scrollToIndex(currentIndex, false); focusLock = false; return; } updateRail(); renderDetail(); }
function applyOverallTarget(target) { if (!data?.students?.length) return; const sid = sliderStudentId || data.students[currentIndex]?.student_id; const s = data.students.find(x => x.student_id === sid) || data.students[currentIndex]; currentIndex = Math.max(0, data.students.findIndex(x => x.student_id === s.student_id)); const curr = getGradeForIndex(currentIndex); const delta = target - curr; const adj = getAdjustment(s.student_id); const spread = (window.gradeAdjust && window.gradeAdjust.distribute) ? window.gradeAdjust.distribute(s, delta) : { rubric: delta * 0.7, conventions: delta * 0.15, comparative: delta * 0.15 }; adj.rubric += num(spread.rubric, 0); adj.conventions += num(spread.conventions, 0); adj.comparative += num(spread.comparative, 0); adj.overall += delta; delete overrides[s.student_id]; const inp = document.getElementById('gradeOverride'); if (inp) inp.value = Math.round(target); const slider = document.getElementById('overallGradeSlider'); if (slider) slider.value = Math.round(target); if (window.gradeAdjust?.resort) { focusLock = true; for (let i = 0; i < 3; i += 1) { window.gradeAdjust.resort(data.students, getGradeForIndex); currentIndex = Math.max(0, data.students.findIndex(x => x.student_id === s.student_id)); const diff = target - getGradeForIndex(currentIndex); if (Math.abs(diff) < 0.5) break; adj.overall += diff; } renderRail(true); scrollToIndex(currentIndex, false); focusLock = false; return; } updateRail(); renderDetail(); }
function generateFeedbackDrafts() { if (!data?.students?.length || !window.feedbackGenerate?.generateAll) return; window.feedbackGenerate.generateAll(data.students, getGradeForIndex, adjustments, feedbackDrafts, true); renderDetail(); }
function updateGradesFromCurve() {
  if (!data || !data.students || !data.students.length) return;
  const topInput = document.getElementById('topGrade');
  const bottomInput = document.getElementById('bottomGrade');
  const top = clamp(num(topInput?.value, 92), 0, 100);
  const bottom = clamp(num(bottomInput?.value, 58), 0, 100);
  if (top <= bottom) return;
  if (topInput) topInput.value = Math.round(top);
  if (bottomInput) bottomInput.value = Math.round(bottom);
  applyCurveBounds(top, bottom, true);
  updateRail();
  renderDetail();
}
function setRunning(on) { running = on; document.body.dataset.running = on ? 'true' : 'false'; updateWorkflowState(); }
function pipelineLog(msg) { const log = document.getElementById('pipelineLog'); if (!log) return; const line = document.createElement('div'); line.textContent = msg; log.appendChild(line); log.scrollTop = log.scrollHeight; }
function startPipelineNarrative() { const log = document.getElementById('pipelineLog'); if (log) log.innerHTML = ''; const steps = ['Getting your files ready and organized…', "In this first pass, we’re conducting an initial assessment based on the rubric.", 'Next, we compare essays side‑by‑side to keep the ordering consistent.', 'Now we scan conventions: spelling, grammar, sentence structure, and format.', 'We’re integrating all signals into a final, coherent ordering.', 'Building the teacher review dashboard…']; pipelineStep = 0; pipelineLog(steps[0]); pipelineTimer = setInterval(() => { pipelineStep += 1; if (pipelineStep < steps.length) pipelineLog(steps[pipelineStep]); }, 2400); }
function stopPipelineNarrative(msg) { if (msg) pipelineLog(msg); if (pipelineTimer) clearInterval(pipelineTimer); pipelineTimer = null; setTimeout(() => setRunning(false), 2000); }
function startShuffle() { if (shuffleTimer || !previewStudents.length) return; shuffleTimer = setInterval(() => { if (previewStudents.length < 2) return; const i = Math.floor(Math.random() * (previewStudents.length - 1)); const t = previewStudents[i]; previewStudents[i] = previewStudents[i + 1]; previewStudents[i + 1] = t; previewStudents.forEach((s, idx) => { s.rank = idx + 1; }); renderRail(true); }, 900); }
function stopShuffle() { if (shuffleTimer) clearInterval(shuffleTimer); shuffleTimer = null; }
function updatePreviewFromUploads() {
  const essays = document.getElementById('uploadEssays');
  if (!essays) return;
  previewStudents = essays.files && essays.files.length
    ? Array.from(essays.files).map((f, idx) => ({ student_id: baseName(f.name), rank: idx + 1, text: '' }))
    : [];
  currentIndex = 0;
  renderRail(true);
  renderDetail();
  updateWorkflowState();
}
async function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
async function waitForJob(jobId) { const start = Date.now(); while (Date.now() - start < 45 * 60 * 1000) { const res = await fetch(apiUrl(`/pipeline/v2/jobs/${jobId}`)); if (!res.ok) throw new Error('Run status unavailable'); const job = await res.json(); if (job.status === 'completed' || job.status === 'awaiting_rubric_confirmation') return job; if (job.status === 'failed') throw new Error(job.error || 'Run failed'); await sleep(2000); } throw new Error('Run timed out'); }
async function runPipeline() {
  const essays = document.getElementById('uploadEssays'); const rubric = document.getElementById('uploadRubric'); const outline = document.getElementById('uploadOutline');
  if (!rubric?.files?.[0] || !outline?.files?.[0] || !essays?.files?.length) { setPipelineStatus('Add essays, rubric, outline', 'warn'); return; }
  if (!previewStudents.length) updatePreviewFromUploads();
  setPipelineStatus('Checking connection...', 'warn'); let mode = '';
  try { const [cRes, aRes] = await Promise.all([fetch(apiUrl('/codex/status')), fetch(apiUrl('/auth/status'))]); const c = cRes.ok ? await cRes.json() : null; const a = aRes.ok ? await aRes.json() : null; mode = c && c.connected ? 'codex_local' : (a && a.connected ? 'openai' : ''); } catch (err) { setPipelineStatus('Offline', 'danger'); return; }
  if (!mode) { setPipelineStatus('Connect Codex or API key', 'warn'); return; }
  const form = new FormData(); form.append('rubric', rubric.files[0]); form.append('outline', outline.files[0]); Array.from(essays.files).forEach(f => form.append('submissions', f)); form.append('mode', mode);
  setPipelineStatus('Running...', 'running'); setRunning(true); startPipelineNarrative(); startShuffle();
  try { const res = await fetch(apiUrl('/pipeline/v2/run'), { method: 'POST', body: form }); if (!res.ok) { let msg = 'Run failed'; try { const err = await res.json(); if (err.detail) msg = `Run failed: ${err.detail}`; } catch (_) {} setPipelineStatus(msg, 'danger'); stopShuffle(); stopPipelineNarrative(msg); return; } const submit = await res.json(); activeJobId = submit.job_id || ''; if (submit.cached) pipelineLog('Identical inputs found; using cached assessment.'); if (submit.status === 'awaiting_rubric_confirmation') { setPipelineStatus('Rubric confirmation needed', 'warn'); stopShuffle(); stopPipelineNarrative('Rubric interpretation needs confirmation before scoring continues.'); await fetchRubricReview(activeJobId); return; } const job = submit.status === 'completed' ? submit : await waitForJob(activeJobId); if (job.status === 'awaiting_rubric_confirmation') { setPipelineStatus('Rubric confirmation needed', 'warn'); stopShuffle(); stopPipelineNarrative('Rubric interpretation needs confirmation before scoring continues.'); await fetchRubricReview(activeJobId); return; } const dataRes = await fetch(apiUrl(`/pipeline/v2/jobs/${job.id || activeJobId}/data`)); if (!dataRes.ok) throw new Error('Dashboard data unavailable'); previewStudents = []; await boot(await dataRes.json()); setPipelineStatus('Complete', 'ready'); stopShuffle(); stopPipelineNarrative('Done. Review is ready.'); } catch (err) { const msg = `Run failed: ${err.message || 'connection lost'}`; setPipelineStatus(msg, 'danger'); stopShuffle(); stopPipelineNarrative(msg); }
}
function setupUploads() {
  document.querySelectorAll('.upload').forEach(zone => {
    const input = zone.querySelector('input');
    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      zone.classList.add('drag');
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag'));
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('drag');
      input.files = e.dataTransfer.files;
      zone.querySelector('span').textContent = `${input.files.length} file(s) selected`;
      if (input.id === 'uploadEssays') updatePreviewFromUploads();
      else updateWorkflowState();
    });
    input.addEventListener('change', () => {
      zone.querySelector('span').textContent = `${input.files.length} file(s) selected`;
      if (input.id === 'uploadEssays') updatePreviewFromUploads();
      else updateWorkflowState();
    });
  });
}
function setupControls() {
  if (window.__heroControlsBound) return; window.__heroControlsBound = true;
  ensureRubricPanel();
  ensureReviewPanel();
  document.getElementById('prevBtn').addEventListener('click', () => {
    if (currentIndex > 0) scrollToIndex(currentIndex - 1, true);
  });
  document.getElementById('nextBtn').addEventListener('click', () => {
    if (currentIndex < data.students.length - 1) scrollToIndex(currentIndex + 1, true);
  });
  document.getElementById('topGrade').addEventListener('input', updateGradesFromCurve);
  document.getElementById('bottomGrade').addEventListener('input', updateGradesFromCurve);
  const slider = document.getElementById('overallGradeSlider'); if (slider) { const pin = () => { sliderStudentId = data?.students?.[currentIndex]?.student_id || null; }; const unpin = () => { sliderStudentId = null; }; slider.addEventListener('focus', pin); slider.addEventListener('pointerdown', pin); slider.addEventListener('blur', unpin); slider.addEventListener('pointerup', unpin); slider.addEventListener('change', unpin); slider.addEventListener('input', (e) => applyOverallTarget(clamp(num(e.target.value, 0), 0, 100))); }
  document.getElementById('gradeOverride').addEventListener('change', (e) => {
    const value = e.target.value.trim(); if (!value) return; applyOverallTarget(clamp(num(value, 0), 0, 100));
  });
  document.getElementById('copyFeedback').addEventListener('click', () => {
    if (!data?.students?.length) return;
    const student = data.students[currentIndex]; const draft = feedbackForStudent(student.student_id, student.feedback_text || '');
    const payload = [`Two Stars and a Wish — ${student.student_id}`, `Star 1: ${draft.star1 || '—'}`, `Star 2: ${draft.star2 || '—'}`, `Wish: ${draft.wish || '—'}`].join('\n'); navigator.clipboard.writeText(payload);
  });
  const genBtn = document.getElementById('generateFeedback'); if (genBtn) genBtn.addEventListener('click', generateFeedbackDrafts);
  document.getElementById('themeToggle').addEventListener('click', () => { const body = document.body; body.dataset.theme = body.dataset.theme === 'dark' ? 'light' : 'dark'; });
  const connectBtn = document.getElementById('connectKey');
  if (connectBtn) connectBtn.addEventListener('click', connectApiKey);
  const codexBtn = document.getElementById('codexLogin');
  if (codexBtn) codexBtn.addEventListener('click', startCodexLogin);
  const runBtn = document.getElementById('runPipelinePrimary');
  if (runBtn) runBtn.addEventListener('click', runPipeline);
  document.addEventListener('keydown', (e) => {
    if (e.key.toLowerCase() !== 'f') return;
    const active = document.activeElement;
    if (active && (active.isContentEditable || ['INPUT', 'TEXTAREA'].includes(active.tagName))) {
      return;
    }
    compareDirection *= -1;
    renderDetail();
  });
  const viewToggle = document.getElementById('viewToggle');
  viewToggle.addEventListener('click', () => {
    const body = document.body;
    body.dataset.view = body.dataset.view === 'split' ? 'single' : 'split';
    updateControlVisibility();
    renderDetail();
  });
  document.getElementById('railScroll').addEventListener('scroll', updateFromScroll);
  const reviewLevel = document.getElementById('reviewLevelOverride');
  const reviewRank = document.getElementById('reviewDesiredRank');
  const reviewQuality = document.getElementById('reviewEvidenceQuality');
  const reviewComment = document.getElementById('reviewEvidenceComment');
  const saveReview = document.getElementById('saveReview');
  const finalizeReview = document.getElementById('finalizeReview');
  const preferCurrent = document.getElementById('preferCurrent');
  const preferCompare = document.getElementById('preferCompare');
  const clearPairwise = document.getElementById('clearPairwise');
  if (reviewLevel) reviewLevel.addEventListener('change', e => { const student = data?.students?.[currentIndex]; if (!student) return; studentReview(student.student_id).level_override = e.target.value; });
  if (reviewRank) reviewRank.addEventListener('change', e => { const student = data?.students?.[currentIndex]; if (!student) return; studentReview(student.student_id).desired_rank = e.target.value.trim() ? parseInt(e.target.value, 10) : ''; });
  if (reviewQuality) reviewQuality.addEventListener('change', e => { const student = data?.students?.[currentIndex]; if (!student) return; studentReview(student.student_id).evidence_quality = e.target.value; });
  if (reviewComment) reviewComment.addEventListener('input', e => { const student = data?.students?.[currentIndex]; if (!student) return; studentReview(student.student_id).evidence_comment = e.target.value.trim(); });
  if (saveReview) saveReview.addEventListener('click', () => saveReviewBundle('draft'));
  if (finalizeReview) finalizeReview.addEventListener('click', () => saveReviewBundle('finalize'));
  if (preferCurrent) preferCurrent.addEventListener('click', () => {
    const student = data?.students?.[currentIndex];
    const compareIndex = getCompareIndex();
    if (!student || compareIndex === null) return;
    const compare = data.students[compareIndex];
    const pair = pairReview(student.student_id, compare.student_id);
    pair.preferred_student_id = student.student_id;
    pair.rationale = studentReview(student.student_id).evidence_comment || '';
    renderReviewPanel(student);
  });
  if (preferCompare) preferCompare.addEventListener('click', () => {
    const student = data?.students?.[currentIndex];
    const compareIndex = getCompareIndex();
    if (!student || compareIndex === null) return;
    const compare = data.students[compareIndex];
    const pair = pairReview(student.student_id, compare.student_id);
    pair.preferred_student_id = compare.student_id;
    pair.rationale = studentReview(student.student_id).evidence_comment || '';
    renderReviewPanel(student);
  });
  if (clearPairwise) clearPairwise.addEventListener('click', () => {
    const student = data?.students?.[currentIndex];
    const compareIndex = getCompareIndex();
    if (!student || compareIndex === null) return;
    delete reviewPairs[pairKey(student.student_id, data.students[compareIndex].student_id)];
    renderReviewPanel(student);
  });
  setupUploads();
  loadProjects();
  const saveBtn = document.getElementById('saveProject'); if (saveBtn) saveBtn.addEventListener('click', saveProject);
  const newBtn = document.getElementById('newProject'); if (newBtn) newBtn.addEventListener('click', newProject);
  const clearBtn = document.getElementById('clearProject'); if (clearBtn) clearBtn.addEventListener('click', clearProject);
  const loadBtn = document.getElementById('loadProject'); if (loadBtn) loadBtn.addEventListener('click', loadProject);
  const delBtn = document.getElementById('deleteProject'); if (delBtn) delBtn.addEventListener('click', deleteProject);
  const confirmRubric = document.getElementById('confirmRubric'); if (confirmRubric) confirmRubric.addEventListener('click', () => submitRubricReview('confirm'));
  const saveRubricEdits = document.getElementById('saveRubricEdits'); if (saveRubricEdits) saveRubricEdits.addEventListener('click', () => submitRubricReview('edit'));
  const rejectRubric = document.getElementById('rejectRubric'); if (rejectRubric) rejectRubric.addEventListener('click', () => submitRubricReview('reject'));
  updateWorkflowState();
}
async function boot(payload) {
  data = payload;
  if (!data.students) data.students = [];
  data.students.sort((a, b) => a.rank - b.rank);
  document.title = 'Assessor';
  if (data.class_metadata && data.class_metadata.grade_level) {
    const title = document.querySelector('.brand h1');
    title.textContent = 'Assessor';
    document.title = `Assessor • Grade ${data.class_metadata.grade_level}`;
  }
  if (data.curve_top) document.getElementById('topGrade').value = data.curve_top;
  if (data.curve_bottom) document.getElementById('bottomGrade').value = data.curve_bottom;
  applyCurveBounds(num(document.getElementById('topGrade').value, 92), num(document.getElementById('bottomGrade').value, 58), false);
  await detectApiBase();
  setupControls();
  renderRubricReview(
    payload && (payload.rubric_verification || payload.normalized_rubric || payload.rubric_manifest)
      ? {
          status: 'completed',
          normalized_rubric: payload.normalized_rubric || {},
          rubric_manifest: payload.rubric_manifest || {},
          rubric_validation_report: payload.rubric_validation_report || {},
          rubric_verification: payload.rubric_verification || {},
        }
      : null,
  );
  await loadReviewBundle();
  renderRail();
  scrollToIndex(0, false);
  updateControlVisibility();
  updateWorkflowState();
  refreshAuthStatus();
}
fetch(`/data.json?t=${Date.now()}`, { cache: 'no-store' })
  .then(res => res.ok ? res.text() : '')
  .then(text => { try { return text ? JSON.parse(text) : { students: [] }; } catch (_) { return { students: [] }; } })
  .then(payload => boot(payload))
  .catch(err => { console.error(err); return boot({ students: [] }); });
