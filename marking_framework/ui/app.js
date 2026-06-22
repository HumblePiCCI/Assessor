let data = null, currentIndex = 0, grades = [], overrides = {}, adjustments = {}, feedbackDrafts = {}, reviewBundle = null, reviewStudents = {}, reviewPairs = {}, reviewSessionId = '', scrollTicking = false, compareDirection = 1, previewStudents = [], running = false, shuffleTimer = null, pipelineTimer = null, backgroundValidationTimer = null, pipelineStep = 0, projects = [], currentProject = null, sliderStudentId = null, focusLock = false, activeJobId = '', rubricReview = null, anchorReview = null, classroomState = null, classroomPreflight = null, googleAuth = null, googleCourses = [], googleCoursework = [];
let reviewAutosaveTimer = null, reviewAutosaveInFlight = false, reviewAutosavePending = false, reviewAutosaveDirty = false, reviewAutosaveLastSerialized = '';
let API_BASE = null;
const ACTIVE_PIPELINE_JOB_KEY = 'assessor.activePipelineJob';
let activeJobResumeStarted = false;
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
function compactText(value) { return String(value || '').trim().replace(/\s+/g, ' '); }
function isOpaqueStudentId(value) { const clean = compactText(value); return !!(clean && /^\d{8,}$/.test(clean)); }
function firstNameOnly(value, fallback = '') {
  let raw = compactText(value);
  if (!raw || isOpaqueStudentId(raw)) raw = '';
  if (raw.includes('@') && !raw.includes(' ')) raw = raw.split('@')[0];
  const first = raw ? raw.split(' ')[0].replace(/^[.,;:()[\]{}<>"'`]+|[.,;:()[\]{}<>"'`]+$/g, '') : '';
  if (first && !isOpaqueStudentId(first)) return first.slice(0, 40);
  return compactText(fallback) || 'Student';
}
function appendSystemId(label, systemId) {
  const clean = compactText(label);
  const sid = compactText(systemId);
  if (!clean) return sid;
  if (sid && /^s\d+/i.test(sid) && !clean.includes(sid)) return `${clean} - ${sid}`;
  return clean;
}
function classroomLabelSources() {
  const maps = { byStudent: new Map(), bySource: new Map() };
  const add = (key, label, map = maps.byStudent) => {
    const cleanKey = compactText(key);
    const cleanLabel = compactText(label);
    if (cleanKey && cleanLabel && !isOpaqueStudentId(cleanLabel)) map.set(cleanKey, cleanLabel);
  };
  const addSourcePath = (path, label) => {
    const clean = compactText(path);
    if (!clean) return;
    const name = clean.split('/').pop();
    add(name, label, maps.bySource);
    add(baseName(name), label, maps.bySource);
  };
  const metadata = data?.class_metadata || {};
  [...(metadata.imported_submissions || []), ...(metadata.files || [])].forEach(row => {
    const sid = row.student_id || row.safe_student_id || '';
    const label = row.student_label || row.display_name || appendSystemId(row.student_first_name || '', sid);
    add(sid, label);
    addSourcePath(row.path || row.source_file || '', label);
  });
  const states = [classroomState, data?.classroom_state].filter(Boolean);
  states.forEach(state => {
    const submissions = state?.submissions || {};
    Object.values(submissions).forEach(row => {
      if (!row || typeof row !== 'object') return;
      const first = firstNameOnly(row.display_name || row.student_first_name || '', row.student_id || '');
      add(row.student_id, first);
      add(row.submission_id, first);
      addSourcePath(`${row.student_id || ''}.txt`, first);
    });
  });
  return maps;
}
function classroomMappedLabel(student) {
  if (!student) return '';
  const maps = classroomLabelSources();
  const source = compactText(student.source_file || '');
  let label = '';
  if (source) {
    const name = source.split('/').pop();
    label = maps.bySource.get(name) || maps.bySource.get(baseName(name)) || '';
  }
  const raw = compactText(student.display_name || '');
  if (!label) label = maps.byStudent.get(raw) || maps.byStudent.get(student.student_id || '') || '';
  return label ? appendSystemId(label, student.safe_student_id || student.student_id || '') : '';
}
function labelFor(s) {
  if (!s) return '';
  const systemId = s.safe_student_id || s.student_id || '';
  const classroomBacked = !!(data?.class_metadata?.source === 'google_classroom_read_only_sync' || data?.classroom_state?.classroom_link || classroomState?.classroom_link);
  const mapped = classroomBacked ? classroomMappedLabel(s) : '';
  if (mapped) return mapped;
  const explicit = compactText(s.student_label || s.student_display_name || s.display_name || '');
  if (!classroomBacked) return explicit || compactText(systemId);
  if (!explicit || isOpaqueStudentId(explicit)) return appendSystemId(firstNameOnly('', systemId), systemId);
  return appendSystemId(firstNameOnly(explicit, systemId), systemId);
}
function labelForId(studentId, fallback = '') {
  const sid = compactText(studentId);
  const student = (data?.students || []).find(item => item.student_id === sid || item.safe_student_id === sid);
  if (student) return labelFor(student);
  const mapped = classroomMappedLabel({ student_id: sid, display_name: fallback, source_file: `${fallback || sid}.txt` });
  if (mapped) return mapped;
  return appendSystemId(firstNameOnly(fallback, sid), sid);
}
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
function hasActiveReviewState(record) {
  return !!(
    record &&
    (
      (record.students && record.students.length) ||
      (record.pairwise && record.pairwise.length) ||
      record.review_notes ||
      (record.assigned_marks && record.assigned_marks.length) ||
      (record.feedback_drafts && record.feedback_drafts.length) ||
      record.curve_top !== null && record.curve_top !== undefined ||
      record.curve_bottom !== null && record.curve_bottom !== undefined
    )
  );
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
function apiErrorMessage(payload, fallback = 'Request failed') {
  const detail = payload?.detail || payload || {};
  if (typeof detail === 'string') return detail;
  const code = detail.code || payload?.code || '';
  if (code === 'preflight_stale_rebuild_required') return 'Review or sync changed after this preflight. Rebuild CSV preflight before export.';
  const message = detail.message || payload?.message || fallback;
  const remedy = detail.remediation || detail.remedy || payload?.remediation || '';
  return [message, code ? `(${String(code).replaceAll('_', ' ')})` : '', remedy].filter(Boolean).join(' ');
}
function blockerLabel(code) {
  return String(code || '').replaceAll('_', ' ');
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
function latestClassroomSync(bundle = classroomState) {
  return (bundle?.sync_history || []).slice(-1)[0] || {};
}
function classroomImportedCount(bundle = classroomState) {
  const summary = bundle?.summary || {};
  const latestSync = latestClassroomSync(bundle);
  return Number(latestSync.imported_count ?? summary.ready_for_analysis_count ?? 0) || 0;
}
function classroomBlockedCount(bundle = classroomState) {
  const summary = bundle?.summary || {};
  const latestSync = latestClassroomSync(bundle);
  return Number(latestSync.blocked_count ?? latestSync.blocker_count ?? summary.blocked_count ?? 0) || 0;
}
function classroomPlatformErrorCount(bundle = classroomState) {
  const summary = bundle?.summary || {};
  const latestSync = latestClassroomSync(bundle);
  return Number(latestSync.platform_error_count ?? summary.platform_error_count ?? 0) || 0;
}
function classroomImportsReady(bundle = classroomState) {
  return !!(bundle?.classroom_link?.course_id && classroomImportedCount(bundle) > 0);
}
function classroomNextStep(bundle = classroomState) {
  const link = bundle?.classroom_link || {};
  const imported = classroomImportedCount(bundle);
  const blocked = classroomBlockedCount(bundle);
  const platformErrors = classroomPlatformErrorCount(bundle);
  const rubricReady = !!document.getElementById('uploadRubric')?.files?.[0];
  const outlineReady = !!document.getElementById('uploadOutline')?.files?.[0];
  const authText = document.getElementById('authStatus')?.textContent || '';
  const runtimeReady = inferConnectionState(authText) === 'ready';
  if (googleAuth && !googleAuth.configured) return { text: 'Next: configure Google OAuth locally, then connect Classroom.', state: 'warn' };
  if (googleAuth && !googleAuth.connected) return { text: 'Next: connect Google Classroom.', state: 'warn' };
  if (!link.course_id) return { text: 'Next: choose a class and assignment, then use the assignment.', state: 'warn' };
  if (!imported) {
    if (platformErrors) return { text: 'Next: resolve the Google API blocker, then sync submissions again.', state: 'danger' };
    if (blocked) return { text: 'No supported essays were imported. Open Exceptions, resolve blockers, then sync again.', state: 'danger' };
    return { text: 'Next: sync submissions for the selected assignment.', state: 'warn' };
  }
  const prefix = `${imported} Classroom essay${imported === 1 ? '' : 's'} imported${blocked ? `; ${blocked} blocked need review` : ''}.`;
  if (!rubricReady && !outlineReady) return { text: `${prefix} Next: add the rubric and assignment outline, then run assessment.`, state: 'warn' };
  if (!rubricReady) return { text: `${prefix} Next: add the rubric, then run assessment.`, state: 'warn' };
  if (!outlineReady) return { text: `${prefix} Next: add the assignment outline, then run assessment.`, state: 'warn' };
  if (!runtimeReady) return { text: `${prefix} Next: connect Codex or an API key, then run assessment.`, state: 'warn' };
  return { text: `${prefix} Next: click Run assessment.`, state: 'ready' };
}
function renderClassroomNextStep(bundle = classroomState) {
  const node = document.getElementById('classroomNextStep');
  if (!node) return;
  const next = classroomNextStep(bundle);
  node.textContent = next.text;
  node.dataset.state = next.state;
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
  const classroomImported = classroomImportsReady();
  const importedCount = classroomImportedCount();
  const students = getStudents();
  const hasReview = !!(data?.students?.length);
  const filesReady = essayCount > 0 && rubricReady && outlineReady;
  const projectInputsReady = classroomImported && rubricReady && outlineReady;
  setNodeState(document.getElementById('projectBadge'), `Project · ${compactLabel(projectText, 28)}`, currentProject ? 'ready' : 'idle');
  setNodeState(document.getElementById('connectionBadge'), `Connection · ${compactLabel(authText, 24)}`, authState);
  setNodeState(document.getElementById('runBadge'), `Pipeline · ${compactLabel(pipelineText, 26)}`, pipelineState);
  const hint = document.getElementById('intakeHint');
  const workflowSummary = document.getElementById('workflowSummary');
  if (hint) {
    if (hasReview) {
      hint.textContent = `${students.length} essays loaded. Review the order, correct the exceptions, then finalize.`;
    } else if (classroomImported && !essayCount) {
      hint.textContent = `Classroom submissions are synced. Add rubric and outline, then run the assessment.`;
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
  if (workflowSummary) {
    workflowSummary.textContent = hasReview
      ? `${students.length} essays ready for review`
      : projectInputsReady
        ? 'Classroom imports ready'
      : filesReady
        ? 'Files ready'
        : `${classroomImported ? 'Classroom synced' : `${essayCount || 0} essays`} · ${rubricReady ? 'rubric ready' : 'rubric missing'} · ${outlineReady ? 'outline ready' : 'outline missing'}`;
    workflowSummary.dataset.state = hasReview || filesReady || projectInputsReady ? 'ready' : 'idle';
  }
  const railMeta = document.getElementById('railMeta');
  if (railMeta) {
    railMeta.textContent = students.length
      ? `${students.length} essays in order`
      : classroomImported
        ? `${importedCount} Classroom essay${importedCount === 1 ? '' : 's'} synced; run assessment next`
        : 'No essays loaded';
  }
  const runButton = document.getElementById('runPipelinePrimary');
  if (runButton) {
    runButton.disabled = running || !(filesReady || projectInputsReady) || authState !== 'ready';
    runButton.textContent = running ? 'Running…' : 'Run assessment';
  }
  renderClassroomNextStep();
}
function setPipelineStatus(text, state = inferPipelineState(text)) {
  setNodeState(document.getElementById('pipelineStatus'), text, state);
  updateWorkflowState();
}
function updateControlVisibility() {
  const hasScored = !!(data && data.students && data.students.length);
  const hasClassroomExceptions = !!(classroomState?.blockers?.length);
  const multipleStudents = hasScored && data.students.length > 1;
  const anchorVisible = !!document.getElementById('anchorSection') && !document.getElementById('anchorSection').classList.contains('is-hidden');
  const showAdvancedDrawer = hasScored || hasClassroomExceptions || anchorVisible;
  document.getElementById('actionsEmpty')?.classList.toggle('is-hidden', hasScored);
  document.getElementById('teacherSpotlight')?.classList.toggle('is-hidden', !hasScored);
  document.getElementById('exceptionsSection')?.classList.toggle('is-hidden', !(hasScored || hasClassroomExceptions));
  document.getElementById('reviewAdvancedDrawer')?.classList.toggle('is-hidden', !showAdvancedDrawer);
  document.getElementById('feedbackSection')?.classList.toggle('is-hidden', !hasScored);
  document.getElementById('reviewSection')?.classList.toggle('is-hidden', !hasScored);
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
    if (api && api.connected) {
      const provider = api.api_provider && api.api_provider.provider ? api.api_provider.provider : 'API';
      status.textContent = `${provider} key connected`;
      if (codexBtn) { codexBtn.disabled = false; codexBtn.textContent = 'Sign in with Codex'; }
    } else if (codex && codex.available && codex.connected) {
      status.textContent = codex.auth_source === 'codex_oauth' ? 'Codex OAuth connected' : 'Codex connected';
      if (codexBtn) { codexBtn.disabled = true; codexBtn.textContent = 'Codex connected'; }
    } else if (codex && codex.available) {
      status.textContent = codex.reason || 'Codex not connected';
      if (codexBtn) { codexBtn.disabled = false; codexBtn.textContent = 'Sign in with Codex'; }
    } else {
      status.textContent = 'Offline';
      if (codexBtn) { codexBtn.disabled = false; codexBtn.textContent = 'Sign in with Codex'; }
    }
  } catch (err) {
    status.textContent = 'Offline';
    if (codexBtn) { codexBtn.disabled = false; codexBtn.textContent = 'Sign in with Codex'; }
  }
  status.dataset.state = inferConnectionState(status.textContent);
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
function setProjectControls(enabled, message = '') {
  const select = document.getElementById('projectSelect');
  const loadBtn = document.getElementById('loadProject');
  const saveBtn = document.getElementById('saveProject');
  const newBtn = document.getElementById('newProject');
  const clearBtn = document.getElementById('clearProject');
  const deleteBtn = document.getElementById('deleteProject');
  [select, loadBtn, saveBtn, newBtn, clearBtn, deleteBtn].forEach(node => {
    if (node) node.disabled = !enabled;
  });
  const hint = document.getElementById('projectAuthHint');
  if (hint) {
    hint.textContent = message || (enabled ? 'Only projects for the signed-in Google account are shown.' : 'Sign in with Google to open saved projects.');
    hint.dataset.state = enabled ? 'ready' : 'warn';
  }
}
async function loadProjects() {
  const select = document.getElementById('projectSelect');
  if (!select) return;
  try {
    const res = await fetch(apiUrl('/projects'));
    if (res.status === 401) {
      projects = [];
      currentProject = null;
      select.innerHTML = '';
      const opt = document.createElement('option');
      opt.textContent = 'Sign in with Google';
      opt.value = '';
      opt.disabled = true;
      opt.selected = true;
      select.appendChild(opt);
      const status = document.getElementById('projectStatus');
      if (status) {
        status.textContent = 'Sign in required';
        status.dataset.state = 'warn';
      }
      setProjectControls(false, 'Sign in with Google to open, create, or switch projects.');
      updateWorkflowState();
      return;
    }
    if (!res.ok) throw new Error('projects unavailable');
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
    if (status) {
      status.textContent = currentProject ? currentProject.name : 'No project loaded';
      status.dataset.state = currentProject ? 'ready' : 'idle';
    }
    setProjectControls(true);
  } catch (_) {
    const status = document.getElementById('projectStatus');
    if (status) {
      status.textContent = 'Projects unavailable';
      status.dataset.state = 'danger';
    }
    setProjectControls(false, 'Project service is unavailable. Check the server and try again.');
  }
  updateWorkflowState();
}
async function persistDraftReviewBeforeProjectSave() {
  if (!data?.students?.length) return;
  const status = document.getElementById('projectStatus');
  if (status) status.textContent = 'Saving review choices...';
  await waitForReviewAutosaveIdle();
  if (reviewAutosaveTimer) {
    clearTimeout(reviewAutosaveTimer);
    reviewAutosaveTimer = null;
  }
  const payload = draftReviewPayload();
  const serialized = serializedDraftReviewPayload(payload);
  const res = await fetch(apiUrl('/projects/review'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(apiErrorMessage(await res.json().catch(() => ({})), 'Review save failed'));
  const bundle = await res.json();
  reviewAutosaveDirty = false;
  reviewAutosaveLastSerialized = serialized;
  clearLocalReviewDraftBackup(serialized);
  applyReviewBundle(bundle);
}
async function saveProject() {
  const name = currentProject ? null : prompt('Project name', '') || '';
  if (!currentProject && !name) return;
  const status = document.getElementById('projectStatus');
  if (status) status.textContent = currentProject ? 'Saving current pass...' : 'Saving project...';
  try {
    await persistDraftReviewBeforeProjectSave();
    if (status) status.textContent = currentProject ? 'Saving current pass...' : 'Saving project...';
    const res = await fetch(apiUrl('/projects/save'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(name ? { name } : {}),
    });
    if (!res.ok) throw new Error(apiErrorMessage(await res.json().catch(() => ({})), 'Project save failed'));
    currentProject = await res.json();
    await loadProjects();
  } catch (err) {
    if (status) status.textContent = err.message || 'Project save failed';
  }
}
async function newProject() {
  const name = prompt('New project name', '') || '';
  if (!name) return;
  const status = document.getElementById('projectStatus');
  if (status) status.textContent = 'Saving current pass before new project...';
  try {
    const res = await fetch(apiUrl('/projects/new'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!res.ok) throw new Error(apiErrorMessage(await res.json().catch(() => ({})), 'New project failed'));
    currentProject = await res.json();
    location.reload();
  } catch (err) {
    if (status) status.textContent = err.message || 'New project failed; current pass was not cleared.';
  }
}
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
  anchorReview = null;
  grades = [];
  currentIndex = 0; sliderStudentId = null; focusLock = false;
  resetUploadLabels();
  setPipelineStatus('Idle', 'idle');
  renderRubricReview(null);
  renderAnchorReview(null);
  renderRail(); renderDetail(); updateWorkflowState();
}
async function clearProject() { if (!confirm('Clear the current session?')) return; clearLocalState(); const status = document.getElementById('projectStatus'); if (status) status.textContent = 'Clearing session...'; try { const res = await fetch(apiUrl('/projects/clear'), { method: 'POST' }); if (!res.ok) throw new Error(apiErrorMessage(await res.json().catch(() => ({})), 'Clear failed')); await loadProjects(); location.href = `${location.pathname}?t=${Date.now()}`; } catch (err) { if (status) status.textContent = err.message || 'Server unavailable: local view cleared only'; } }
async function loadProject() { const select = document.getElementById('projectSelect'); const status = document.getElementById('projectStatus'); if (!select || !select.value) return; try { if (status) status.textContent = 'Opening project...'; const res = await fetch(apiUrl('/projects/load'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: select.value }) }); if (!res.ok) throw new Error(apiErrorMessage(await res.json().catch(() => ({})), 'Open failed')); location.reload(); } catch (err) { if (status) status.textContent = err.message || 'Open failed'; } }
async function deleteProject() { const select = document.getElementById('projectSelect'); const status = document.getElementById('projectStatus'); if (!select || !select.value) return; if (!confirm('Delete this project?')) return; try { const res = await fetch(apiUrl(`/projects/${select.value}`), { method: 'DELETE' }); if (!res.ok) throw new Error(apiErrorMessage(await res.json().catch(() => ({})), 'Delete failed')); await loadProjects(); } catch (err) { if (status) status.textContent = err.message || 'Delete failed'; } }
function classroomStateLabel(value) {
  return String(value || 'blocked').replaceAll('_', ' ');
}
function classroomStateTone(value) {
  const state = String(value || '');
  if (['review_ready', 'final_ready', 'finalized_by_teacher'].includes(state)) return 'ready';
  if (['collecting', 'ingesting', 'analyzing_submissions', 'background_validating', 'teacher_revision_pending'].includes(state)) return 'warn';
  if (['blocked', 'failed'].includes(state)) return 'danger';
  return 'idle';
}
function renderClassroomState(bundle) {
  classroomState = bundle || null;
  const status = document.getElementById('classroomStatus');
  const counts = document.getElementById('classroomCounts');
  const preflight = document.getElementById('classroomPreflight');
  const finalizeBtn = document.getElementById('finalizeClassroom');
  const confirmBtn = document.getElementById('confirmPassback');
  const writeStatus = document.getElementById('classroomWriteStatus');
  if (!status || !counts) return;
  const link = bundle?.classroom_link || {};
  const linkedControls = document.querySelectorAll('.classroom-linked-control');
  if (!link.course_id) {
    status.textContent = 'No assignment linked';
    status.dataset.state = 'idle';
    counts.innerHTML = '';
    if (preflight) preflight.textContent = '';
    if (finalizeBtn) finalizeBtn.disabled = true;
    if (confirmBtn) confirmBtn.disabled = true;
    if (writeStatus) writeStatus.textContent = 'No live Classroom write occurred.';
    linkedControls.forEach(node => node.classList.add('is-hidden'));
    renderClassroomNextStep(bundle);
    return;
  }
  linkedControls.forEach(node => node.classList.remove('is-hidden'));
  const stateLabel = classroomStateLabel(bundle.product_state);
  const blockers = bundle.blockers || [];
  status.textContent = `${link.course_name || link.course_id} · ${link.coursework_title || link.coursework_id} · ${stateLabel}${blockers.length ? ` · ${blockers.length} blocker${blockers.length === 1 ? '' : 's'}` : ''}`;
  status.dataset.state = classroomStateTone(bundle.product_state);
  const summary = bundle.summary || {};
  const latestSync = (bundle.sync_history || []).slice(-1)[0] || {};
  const lastAction = (bundle.passback?.actions || []).slice(-1)[0] || {};
  const cells = [
    ['Roster', summary.roster_count || 0],
    ['Submitted', summary.submitted_count || 0],
    ['Imported', latestSync.imported_count ?? bundle.read_sync?.imported_submission_count ?? 0],
    ['Blocked', latestSync.blocked_count ?? latestSync.blocker_count ?? summary.blocked_count ?? 0],
    ['Missing', latestSync.missing_count ?? summary.missing_count ?? 0],
    ['Reclaimed', latestSync.reclaimed_count ?? summary.reclaimed_count ?? 0],
    ['Returned', latestSync.returned_count ?? summary.returned_count ?? 0],
    ['Platform', latestSync.platform_error_count ?? summary.platform_error_count ?? 0],
    ['Human rev', bundle.latest_human_revision_id || 0],
    ['Audit rev', bundle.audit?.audit_revision_id || 0],
  ];
  counts.innerHTML = cells.map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join('');
  if (finalizeBtn) finalizeBtn.disabled = bundle.product_state !== 'final_ready';
  if (confirmBtn) confirmBtn.disabled = !(classroomPreflight && !classroomPreflight.blocked);
  if (writeStatus) {
    const syncWrite = latestSync.external_write_performed === true;
    const actionWrite = lastAction.external_write_performed === true;
    writeStatus.textContent = syncWrite || actionWrite
      ? 'Live Classroom write detected; stop and inspect audit records.'
      : 'No live Classroom write occurred. Sync and CSV export record external_write_performed=false.';
    writeStatus.dataset.state = syncWrite || actionWrite ? 'danger' : 'ready';
  }
  if (preflight && !classroomPreflight && (!preflight.textContent || preflight.textContent.startsWith('Gates:'))) {
    const gates = bundle.launch_gates || {};
    preflight.textContent = `Gates: teacher review ${gates.teacher_review_finalized ? 'ready' : 'open'} · validation ${gates.full_validation_current ? 'current' : 'pending'} · attachments ${gates.attachment_blockers_clear ? 'clear' : 'blocked'}.`;
  }
  renderClassroomNextStep(bundle);
  updateWorkflowState();
  if (!previewStudents.length && !(data?.students || []).length) renderDetail();
}
async function refreshClassroomState() {
  try {
    const res = await fetch(apiUrl('/projects/classroom'));
    if (!res.ok) return;
    renderClassroomState(await res.json());
  } catch (_) {}
}
function setGoogleStatus(text, state = 'idle') {
  const node = document.getElementById('googleAuthStatus');
  if (!node) return;
  node.textContent = text;
  node.dataset.state = state;
}
function populateSelect(select, rows, placeholder, valueKey, labelKey) {
  if (!select) return;
  select.innerHTML = '';
  const first = document.createElement('option');
  first.value = '';
  first.textContent = placeholder;
  select.appendChild(first);
  rows.forEach(row => {
    const opt = document.createElement('option');
    opt.value = row[valueKey] || '';
    const state = row.coursework_state && String(row.coursework_state).toUpperCase() !== 'PUBLISHED' ? ` · ${row.coursework_state}` : '';
    opt.textContent = `${row[labelKey] || row[valueKey] || ''}${state}`;
    opt.dataset.row = JSON.stringify(row);
    select.appendChild(opt);
  });
}
function selectedRow(selectId) {
  const select = document.getElementById(selectId);
  const option = select?.selectedOptions?.[0];
  if (!option?.dataset?.row) return {};
  try { return JSON.parse(option.dataset.row); } catch (_) { return {}; }
}
async function refreshGoogleAuth() {
  try {
    const res = await fetch(apiUrl('/google/auth/status'));
    if (!res.ok) throw new Error('status unavailable');
    googleAuth = await res.json();
    const connectBtn = document.getElementById('googleConnect');
    const disconnectBtn = document.getElementById('googleDisconnect');
    if (!googleAuth.configured) {
      setGoogleStatus(`Google OAuth not configured. ${googleAuth.remediation || 'Set local OAuth env vars and restart.'}`, 'warn');
      if (connectBtn) connectBtn.textContent = 'Connect Google Classroom';
      if (disconnectBtn) disconnectBtn.disabled = true;
      setProjectControls(false, 'Configure Google OAuth, then sign in to open projects.');
    } else if (googleAuth.connected && (googleAuth.missing_scopes || []).length) {
      setGoogleStatus(`Missing required scope: ${googleAuth.missing_scopes.map(scope => scope.split('/').pop()).join(', ')}. ${googleAuth.remediation || 'Reconnect Google.'}`, 'danger');
      if (connectBtn) connectBtn.textContent = 'Reconnect Google';
      if (disconnectBtn) disconnectBtn.disabled = false;
      if (googleAuth.project_session_connected) await loadProjects();
      else setProjectControls(false, 'Reconnect Google to finish signing in for saved projects.');
    } else if (googleAuth.connected) {
      const who = googleAuth.teacher_display_email || googleAuth.teacher_identity_hash || 'Google connected';
      const suffix = googleAuth.expired || googleAuth.expiring ? ' Token refresh will run before the next live read.' : ' Choose a class.';
      setGoogleStatus(`Connected as ${who}.${suffix}`, 'ready');
      if (connectBtn) connectBtn.textContent = 'Reconnect Google';
      if (disconnectBtn) disconnectBtn.disabled = false;
      if (!googleAuth.project_session_connected) {
        setGoogleStatus(`Google connected as ${who}, but this browser is not signed in for saved projects. Reconnect Google to finish sign-in.`, 'warn');
        setProjectControls(false, 'Reconnect Google to finish signing in for saved projects.');
        return;
      }
      await loadProjects();
      await loadGoogleCourses();
    } else {
      const reconnect = googleAuth.reconnect_required || googleAuth.expired;
      setGoogleStatus(reconnect ? `Reconnect required. ${googleAuth.remediation || ''}` : `Google not connected. ${googleAuth.remediation || ''}`, reconnect ? 'danger' : 'idle');
      if (connectBtn) connectBtn.textContent = 'Connect Google Classroom';
      if (disconnectBtn) disconnectBtn.disabled = true;
      setProjectControls(false, 'Sign in with Google to open, create, or switch projects.');
    }
  } catch (_) {
    setGoogleStatus('Google status unavailable.', 'warn');
    setProjectControls(false, 'Project sign-in status is unavailable. Check the server and try again.');
  } finally {
    renderClassroomNextStep();
  }
}
async function startGoogleConnect() {
  setGoogleStatus('Starting Google connection...', 'warn');
  try {
    const redirectAfter = `${location.pathname || '/'}${location.search || ''}`;
    const res = await fetch(apiUrl('/google/auth/start'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ redirect_after: redirectAfter }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || !payload.authorization_url) throw new Error(apiErrorMessage(payload, 'Google connection is not configured'));
    location.href = payload.authorization_url;
  } catch (err) {
    setGoogleStatus(err.message || 'Google connection failed.', 'danger');
  }
}
async function disconnectGoogle() {
  setGoogleStatus('Disconnecting Google...', 'warn');
  try {
    const res = await fetch(apiUrl('/google/auth/disconnect'), { method: 'POST' });
    if (!res.ok) throw new Error('disconnect failed');
    googleCourses = [];
    googleCoursework = [];
    populateSelect(document.getElementById('googleCourseSelect'), [], 'Choose class', 'course_id', 'course_name');
    populateSelect(document.getElementById('googleCourseworkSelect'), [], 'Choose assignment', 'coursework_id', 'coursework_title');
    await refreshGoogleAuth();
  } catch (err) {
    setGoogleStatus(err.message || 'Google disconnect failed.', 'danger');
  }
}
async function loadGoogleCourses() {
  const select = document.getElementById('googleCourseSelect');
  try {
    const res = await fetch(apiUrl('/projects/classroom/google/courses'));
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(apiErrorMessage(payload, 'Could not load classes'));
    googleCourses = payload.courses || [];
    populateSelect(select, googleCourses, 'Choose class', 'course_id', 'course_name');
    if (!googleCourses.length) setGoogleStatus('Google connected, but no active teacher classes were returned.', 'warn');
  } catch (err) {
    setGoogleStatus(err.message || 'Could not load Google classes.', 'danger');
  }
}
async function loadGoogleCoursework() {
  const course = document.getElementById('googleCourseSelect')?.value || '';
  const courseworkSelect = document.getElementById('googleCourseworkSelect');
  googleCoursework = [];
  populateSelect(courseworkSelect, [], 'Choose assignment', 'coursework_id', 'coursework_title');
  if (!course) return;
  setGoogleStatus('Loading assignments...', 'warn');
  try {
    const res = await fetch(apiUrl(`/projects/classroom/google/courses/${encodeURIComponent(course)}/coursework`));
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(apiErrorMessage(payload, 'Could not load assignments'));
    googleCoursework = payload.coursework || [];
    populateSelect(courseworkSelect, googleCoursework, 'Choose assignment', 'coursework_id', 'coursework_title');
    setGoogleStatus(googleCoursework.length ? 'Choose an assignment.' : 'No assignments returned for this class.', googleCoursework.length ? 'ready' : 'warn');
  } catch (err) {
    setGoogleStatus(err.message || 'Could not load assignments.', 'danger');
  }
}
async function selectGoogleAssignment() {
  const course = selectedRow('googleCourseSelect');
  const coursework = selectedRow('googleCourseworkSelect');
  if (!course.course_id || !coursework.coursework_id) {
    setGoogleStatus('Choose a class and assignment first.', 'warn');
    return;
  }
  try {
    const res = await fetch(apiUrl('/projects/classroom/google/select'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        course_id: course.course_id,
        course_name: course.course_name,
        coursework_id: coursework.coursework_id,
        coursework_title: coursework.coursework_title,
        passback_mode: 'csv_export',
      }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(apiErrorMessage(payload, 'Could not select assignment'));
    classroomPreflight = null;
    renderClassroomState(payload);
    setGoogleStatus('Assignment selected. Sync submissions next.', 'ready');
  } catch (err) {
    setGoogleStatus(err.message || 'Could not select assignment.', 'danger');
  }
}
async function syncGoogleSubmissions() {
  const course = selectedRow('googleCourseSelect');
  const coursework = selectedRow('googleCourseworkSelect');
  const status = document.getElementById('classroomStatus');
  if (status) status.textContent = 'Syncing Google Classroom submissions...';
  try {
    const res = await fetch(apiUrl('/projects/classroom/google/read-sync'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        course_id: course.course_id || classroomState?.classroom_link?.course_id || '',
        course_name: course.course_name || classroomState?.classroom_link?.course_name || '',
        coursework_id: coursework.coursework_id || classroomState?.classroom_link?.coursework_id || '',
        coursework_title: coursework.coursework_title || classroomState?.classroom_link?.coursework_title || '',
        passback_mode: 'csv_export',
      }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(apiErrorMessage(payload, 'Google sync failed'));
    classroomPreflight = null;
    renderClassroomState(payload);
    const latest = (payload.sync_history || []).slice(-1)[0] || {};
    const imported = latest.imported_count || 0;
    const blocked = latest.blocked_count ?? latest.blocker_count ?? 0;
    const platformErrors = latest.platform_error_count || 0;
    const tone = imported > 0 && !blocked && !platformErrors ? 'ready' : (imported > 0 ? 'warn' : 'danger');
    setGoogleStatus(`Sync imported ${imported}; blocked ${blocked}; platform errors ${platformErrors}.`, tone);
    renderExceptions();
    updateWorkflowState();
  } catch (err) {
    if (status) status.textContent = `Google sync failed: ${err.message || 'unknown error'}`;
    setGoogleStatus(err.message || 'Google sync failed.', 'danger');
  }
}
function classroomLinkPayload() {
  const courseName = (document.getElementById('classroomCourseName')?.value || '').trim();
  const assignmentTitle = (document.getElementById('classroomAssignmentTitle')?.value || '').trim();
  const courseId = (document.getElementById('classroomCourseId')?.value || '').trim() || baseName(courseName || 'course');
  const courseworkId = (document.getElementById('classroomCourseworkId')?.value || '').trim() || baseName(assignmentTitle || 'assignment');
  return {
    course_id: courseId,
    course_name: courseName || courseId,
    coursework_id: courseworkId,
    coursework_title: assignmentTitle || courseworkId,
    passback_mode: document.getElementById('classroomPassbackMode')?.value || 'no_passback',
    policy: {
      policy_state: 'operator_supervised_pilot',
      app_approval_status: 'operator_supervised_pilot',
      oauth_scope_posture: 'not_connected',
      external_writes_enabled: false,
      read_only_first: true,
    },
  };
}
async function linkClassroomAssignment() {
  const status = document.getElementById('classroomStatus');
  if (status) status.textContent = 'Linking Classroom assignment...';
  try {
    const res = await fetch(apiUrl('/projects/classroom/link'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(classroomLinkPayload()),
    });
    if (!res.ok) throw new Error('link failed');
    classroomPreflight = null;
    renderClassroomState(await res.json());
  } catch (err) {
    if (status) status.textContent = `Classroom link failed: ${err.message || 'unknown error'}`;
  }
}
async function classroomSnapshotFromInputs() {
  if (!data?.students?.length) {
    const essays = document.getElementById('uploadEssays');
    const files = essays?.files ? Array.from(essays.files) : [];
    if (files.length) {
      const rows = await Promise.all(files.map(async (file, idx) => {
        const studentId = baseName(file.name) || `student-${idx + 1}`;
        const text = await file.text().catch(() => '');
        return {
          student_id: studentId,
          display_name: studentId,
          text,
          file_name: file.name,
        };
      }));
      return {
        roster: rows.map(row => ({ student_id: row.student_id, display_name: row.display_name })),
        submissions: rows.map(row => ({
          submission_id: row.student_id,
          student_id: row.student_id,
          display_name: row.display_name,
          classroom_state: 'submitted',
          text: row.text,
          attachments: [
            {
              attachment_id: `${row.student_id}-text`,
              title: row.file_name || `${row.display_name} submission`,
              type: 'text',
              mime_type: 'text/plain',
              text: row.text,
            },
          ],
        })),
      };
    }
  }
  const students = data?.students?.length ? data.students : previewStudents;
  return {
    roster: students.map(student => ({
      student_id: student.student_id,
      display_name: labelFor(student),
    })),
    submissions: students.map(student => ({
      submission_id: student.student_id,
      student_id: student.student_id,
      display_name: labelFor(student),
      classroom_state: 'submitted',
      text: student.text || '',
      attachments: [
        {
          attachment_id: `${student.student_id}-text`,
          title: `${labelFor(student)} submission`,
          type: 'text',
          mime_type: 'text/plain',
          text: student.text || '',
        },
      ],
    })),
  };
}
async function reconcileClassroom() {
  const status = document.getElementById('classroomStatus');
  if (status) status.textContent = 'Reconciling Classroom snapshot...';
  try {
    const res = await fetch(apiUrl('/projects/classroom/reconcile'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(await classroomSnapshotFromInputs()),
    });
    if (!res.ok) throw new Error('reconcile failed');
    classroomPreflight = null;
    renderClassroomState(await res.json());
  } catch (err) {
    if (status) status.textContent = `Classroom reconciliation failed: ${err.message || 'unknown error'}`;
  }
}
async function readSyncClassroom() {
  const status = document.getElementById('classroomStatus');
  if (status) status.textContent = 'Importing Classroom work...';
  try {
    const snapshot = await classroomSnapshotFromInputs();
    const res = await fetch(apiUrl('/projects/classroom/read-sync'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...classroomLinkPayload(), ...snapshot }),
    });
    if (!res.ok) throw new Error('read sync failed');
    classroomPreflight = null;
    const bundle = await res.json();
    renderClassroomState(bundle);
    if (status) {
      const imported = bundle.read_sync?.imported_submission_count || 0;
      const blocked = bundle.read_sync?.blocked_submission_count || 0;
      const platformErrors = bundle.read_sync?.platform_error_count || 0;
      status.textContent = `Read sync imported ${imported}; blockers ${blocked}; platform errors ${platformErrors}.`;
    }
  } catch (err) {
    if (status) status.textContent = `Classroom read sync failed: ${err.message || 'unknown error'}`;
  }
}
async function completeClassroomAudit() {
  const status = document.getElementById('classroomStatus');
  if (status) status.textContent = 'Marking background validation current...';
  try {
    const res = await fetch(apiUrl('/projects/classroom/audit/complete'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gate_status: 'pass' }),
    });
    if (!res.ok) throw new Error('audit update failed');
    classroomPreflight = null;
    renderClassroomState(await res.json());
  } catch (err) {
    if (status) status.textContent = `Background validation update failed: ${err.message || 'unknown error'}`;
  }
}
async function finalizeClassroomResult() {
  const status = document.getElementById('classroomStatus');
  if (status) status.textContent = 'Finalizing Classroom result...';
  try {
    const res = await fetch(apiUrl('/projects/classroom/finalize'), { method: 'POST' });
    if (!res.ok) throw new Error('finalize failed');
    classroomPreflight = null;
    renderClassroomState(await res.json());
  } catch (err) {
    if (status) status.textContent = `Classroom finalization failed: ${err.message || 'unknown error'}`;
  }
}
function renderPreflight(preflight) {
  classroomPreflight = preflight || null;
  const node = document.getElementById('classroomPreflight');
  const confirmBtn = document.getElementById('confirmPassback');
  if (!node) return;
  if (!preflight) {
    node.textContent = '';
    if (confirmBtn) confirmBtn.disabled = true;
    return;
  }
  const blockers = preflight.blockers || [];
  node.textContent = preflight.blocked
    ? `Preflight blocked: ${blockers.map(blockerLabel).join(' · ')}`
    : `CSV preflight ready: ${preflight.row_count} row${preflight.row_count === 1 ? '' : 's'} · evidence ${preflight.evidence_packet_id || 'ready'} · no live write.`;
  if (confirmBtn) confirmBtn.disabled = preflight.blocked;
}
async function preflightPassback() {
  const node = document.getElementById('classroomPreflight');
  if (node) node.textContent = 'Building passback preflight...';
  try {
    const res = await fetch(apiUrl('/projects/classroom/passback/preflight'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: document.getElementById('passbackPreflightMode')?.value || 'csv_export' }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(apiErrorMessage(payload, 'preflight failed'));
    }
    renderPreflight(payload);
  } catch (err) {
    if (node) node.textContent = `Preflight failed: ${err.message || 'unknown error'}`;
  }
}
async function confirmPassback() {
  const node = document.getElementById('classroomPreflight');
  if (!classroomPreflight?.preflight_id) return;
  if (node) node.textContent = 'Recording teacher-confirmed export action...';
  try {
    const res = await fetch(apiUrl('/projects/classroom/passback/confirm'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preflight_id: classroomPreflight.preflight_id, confirmed: true }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(apiErrorMessage(payload, 'confirmation failed'));
    const action = payload;
    if (node) {
      node.textContent = `CSV export ready: ${action.row_count} row${action.row_count === 1 ? '' : 's'}${action.export_artifact?.sha256 ? ` · ${action.export_artifact.sha256.slice(0, 12)}` : ''} · external_write_performed=false.`;
      if (action.download_url) {
        const link = document.createElement('a');
        link.href = apiUrl(action.download_url);
        link.textContent = ' Download CSV';
        link.download = action.export_artifact?.filename || 'classroom_export.csv';
        node.appendChild(link);
      }
    }
    await refreshClassroomState();
  } catch (err) {
    if (node) node.textContent = `Export confirmation failed: ${err.message || 'unknown error'}`;
  }
}
async function showEvidencePacket() {
  const node = document.getElementById('classroomPreflight');
  if (node) node.textContent = 'Building evidence packet...';
  try {
    const res = await fetch(apiUrl('/projects/classroom/evidence-packet'));
    if (!res.ok) throw new Error('packet unavailable');
    const packet = await res.json();
    if (node) node.textContent = `Evidence packet ${packet.packet_id || 'ready'} · ${packet.product_state?.replaceAll('_', ' ') || 'state unavailable'} · ${Object.keys(packet.submission_hashes || {}).length} submissions.`;
    await refreshClassroomState();
  } catch (err) {
    if (node) node.textContent = `Evidence packet failed: ${err.message || 'unknown error'}`;
  }
}
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
  section.className = 'auth review-section is-hidden';
  section.innerHTML = `
    <div class="panel-row">
      <div>
        <div class="label">Review decision</div>
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
        <textarea id="reviewEvidenceComment" rows="3" placeholder="Only add a note if the machine missed something important."></textarea>
      </div>
    </div>
    <details class="secondary-details compact-details">
      <summary>Compare and advanced adjustments</summary>
      <div class="review-pairwise">
        <div class="label">Pairwise check</div>
        <div class="project-actions">
          <button id="preferCurrent" class="ghost">Keep current above compare</button>
          <button id="preferCompare" class="ghost">Move compare above current</button>
          <button id="clearPairwise" class="ghost">Clear pair</button>
        </div>
        <div class="auth-status" id="pairwiseStatus">Open split view to compare two essays.</div>
      </div>
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
    <details class="secondary-details compact-details">
      <summary>Learning profile</summary>
      <div id="learningSummary" class="auth-status">Local profile unavailable.</div>
    </details>
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
function ensureAnchorPanel() {
  let section = document.getElementById('anchorSection');
  if (section) return section;
  const actions = document.getElementById('actions');
  if (!actions) return null;
  const slot = document.getElementById('anchorPanelSlot');
  section = document.createElement('div');
  section.id = 'anchorSection';
  section.className = 'auth review-section is-hidden';
  section.innerHTML = `
    <div class="panel-row">
      <div>
        <div class="label">Anchor calibration</div>
        <div id="anchorStatus" class="auth-status">No anchor calibration pending.</div>
      </div>
      <div class="project-actions">
        <button id="submitAnchors" class="primary">Apply anchors</button>
      </div>
    </div>
    <div id="anchorReasons" class="auth-status"></div>
    <div id="anchorList" class="controls compact-controls"></div>
  `;
  if (slot) {
    slot.appendChild(section);
    return section;
  }
  const review = document.getElementById('reviewSection');
  const anchor = review || actionsInsertionAnchor(actions);
  if (anchor) actions.insertBefore(section, anchor);
  else actions.appendChild(section);
  return section;
}
function renderAnchorReview(bundle) {
  const section = ensureAnchorPanel();
  anchorReview = bundle || null;
  const status = document.getElementById('anchorStatus');
  const reasons = document.getElementById('anchorReasons');
  const list = document.getElementById('anchorList');
  const submitBtn = document.getElementById('submitAnchors');
  if (!section || !status || !reasons || !list || !submitBtn) return;
  if (!bundle) {
    section.classList.add('is-hidden');
    status.textContent = 'No anchor calibration pending.';
    reasons.textContent = '';
    list.innerHTML = '';
    submitBtn.disabled = true;
    updateControlVisibility();
    return;
  }
  const pending = bundle.status === 'awaiting_anchor_scores';
  const confidence = bundle.cohort_confidence || {};
  const packet = bundle.anchor_packet || {};
  const anchors = packet.anchors || [];
  section.classList.toggle('is-hidden', !pending && !anchors.length);
  status.textContent = pending
    ? 'Score 4–6 anchor papers to calibrate this cohort, then rerun ordering and banding.'
    : 'Anchor calibration is not required right now.';
  reasons.textContent = (confidence.reasons || []).length
    ? `Why: ${(confidence.reasons || []).join(' · ').replaceAll('_', ' ')}`
    : '';
  list.innerHTML = '';
  anchors.forEach((anchor, idx) => {
    const row = document.createElement('div');
    row.className = 'control';
    row.innerHTML = `
      <label>${labelForId(anchor.student_id, anchor.display_name || anchor.student_id)} · machine ${anchor.machine_level || '—'} · ${anchor.machine_percent || '—'}%</label>
      <div class="curve-range">
        <select data-anchor-level="${idx}">
          <option value="">Level</option>
          <option value="1">1</option>
          <option value="2">2</option>
          <option value="3">3</option>
          <option value="4">4</option>
          <option value="4+">4+</option>
        </select>
        <input data-anchor-mark="${idx}" type="number" min="0" max="100" placeholder="mark (optional)" />
      </div>
    `;
    list.appendChild(row);
    const levelNode = row.querySelector(`[data-anchor-level="${idx}"]`);
    const markNode = row.querySelector(`[data-anchor-mark="${idx}"]`);
    if (levelNode) levelNode.value = anchor.teacher_level || '';
    if (markNode) markNode.value = anchor.teacher_mark || '';
  });
  submitBtn.disabled = !pending || !anchors.length;
  updateControlVisibility();
}
async function fetchRubricReview(jobId) {
  const res = await fetch(apiUrl(`/pipeline/v2/jobs/${jobId}/rubric`));
  if (!res.ok) throw new Error('Rubric review unavailable');
  const payload = await res.json();
  renderRubricReview(payload);
  return payload;
}
async function fetchAnchorReview(jobId) {
  const res = await fetch(apiUrl(`/pipeline/v2/jobs/${jobId}/anchors`));
  if (!res.ok) throw new Error('Anchor review unavailable');
  const payload = await res.json();
  renderAnchorReview(payload);
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
  if (job.status === 'awaiting_anchor_scores') {
    setPipelineStatus('Anchor calibration needed', 'warn');
    stopShuffle();
    stopPipelineNarrative('Teacher anchor scores are needed before finalizing this cohort.');
    await fetchAnchorReview(activeJobId);
    return;
  }
  await loadReviewReadyJob(job, activeJobId);
}
function anchorPayload() {
  const anchors = (anchorReview && anchorReview.anchor_packet && anchorReview.anchor_packet.anchors) ? anchorReview.anchor_packet.anchors : [];
  return anchors.map((anchor, idx) => ({
    student_id: anchor.student_id,
    teacher_level: (document.querySelector(`[data-anchor-level="${idx}"]`)?.value || '').trim(),
    teacher_mark: (document.querySelector(`[data-anchor-mark="${idx}"]`)?.value || '').trim(),
  })).filter(item => item.teacher_level || item.teacher_mark);
}
function validateAnchorPayload(anchors) {
  const byId = new Map(((anchorReview && anchorReview.anchor_packet && anchorReview.anchor_packet.anchors) || []).map(anchor => [anchor.student_id, anchor]));
  const allowedLevels = new Set(['1', '2', '3', '4', '4+']);
  for (const anchor of anchors) {
    const source = byId.get(anchor.student_id) || {};
    const label = labelForId(anchor.student_id, source.display_name || anchor.student_id);
    if (anchor.teacher_level && !allowedLevels.has(anchor.teacher_level)) {
      return `${label} has an invalid level.`;
    }
    if (anchor.teacher_mark) {
      const mark = Number(anchor.teacher_mark);
      if (!Number.isFinite(mark) || mark < 0 || mark > 100) {
        return `${label} mark must be between 0 and 100.`;
      }
      anchor.teacher_mark = mark;
    }
  }
  return '';
}
async function submitAnchorReview() {
  if (!activeJobId) return;
  const anchors = anchorPayload();
  if (!anchors.length) {
    const status = document.getElementById('anchorStatus');
    if (status) status.textContent = 'Score at least one anchor before rerunning.';
    return;
  }
  const status = document.getElementById('anchorStatus');
  const validationError = validateAnchorPayload(anchors);
  if (validationError) {
    if (status) status.textContent = validationError;
    return;
  }
  if (status) status.textContent = 'Applying anchor calibration...';
  try {
    const res = await fetch(apiUrl(`/pipeline/v2/jobs/${activeJobId}/anchors`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ anchors }),
    });
    if (!res.ok) {
      let detail = 'Anchor submission failed';
      try {
        const payload = await res.json();
        detail = payload.detail || detail;
      } catch (_) {
        // keep default
      }
      throw new Error(detail);
    }
    renderAnchorReview(await res.json());
    const dataRes = await fetch(apiUrl(`/pipeline/v2/jobs/${activeJobId}/data`));
    if (!dataRes.ok) throw new Error('Dashboard data unavailable');
    previewStudents = [];
    await boot(await dataRes.json());
    setPipelineStatus('Complete', 'ready');
    stopShuffle();
    stopPipelineNarrative('Done. Anchor calibration applied.');
  } catch (err) {
    if (status) status.textContent = `Anchor calibration failed: ${err.message || 'unknown error'}`;
    setPipelineStatus('Anchor calibration failed', 'danger');
    stopShuffle();
    stopPipelineNarrative('Anchor calibration failed.');
  }
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
  ensureAnchorPanel();
  ensureReviewPanel();
  reviewBundle = bundle || null;
  reviewStudents = {};
  reviewPairs = {};
  const draft = (bundle && bundle.draft_review) ? bundle.draft_review : {};
  const latest = (bundle && bundle.latest_review) ? bundle.latest_review : {};
  const active = hasActiveReviewState(draft) ? draft : latest;
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
  applyPersistedReviewState(active);
  if (!data?.students?.length) renderReviewPanel(null);
}
async function loadReviewBundle() {
  ensureRubricPanel();
  ensureReviewPanel();
  try {
    const res = await fetch(apiUrl('/projects/review'));
    if (res.ok) applyReviewBundle(await res.json());
  } catch (_) {}
  applyLocalReviewDraftBackupIfNewer();
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
  const feedback = Object.entries(feedbackDrafts).map(([student_id, draft]) => ({
    student_id,
    star1: String(draft?.star1 || '').trim(),
    star2: String(draft?.star2 || '').trim(),
    wish: String(draft?.wish || '').trim(),
  })).filter(item => item.star1 || item.star2 || item.wish);
  return {
    students,
    pairwise,
    session_id: reviewSessionId,
    curve_top: num(document.getElementById('topGrade')?.value, null),
    curve_bottom: num(document.getElementById('bottomGrade')?.value, null),
    assigned_marks: currentCohortMarks(),
    feedback_drafts: feedback,
  };
}
function draftReviewPayload() {
  return { ...reviewPayload(), action: 'draft' };
}
function serializedDraftReviewPayload(payload = draftReviewPayload()) {
  return JSON.stringify(payload);
}
function reviewDraftStorageKey() {
  const scope = compactText(
    reviewBundle?.draft_review?.scope_id ||
    reviewBundle?.latest_review?.scope_id ||
    currentProject?.scope_key ||
    currentProject?.id ||
    data?.class_metadata?.classroom_import_manifest_hash ||
    data?.class_metadata?.sync_id ||
    'workspace',
  );
  return `assessor.reviewDraft.${scope.replace(/[^A-Za-z0-9_.:-]/g, '_')}`;
}
function latestServerDraftTimeMs() {
  const times = [
    reviewBundle?.draft_review?.saved_at,
    reviewBundle?.latest_review?.saved_at,
  ].map(value => Date.parse(value || '')).filter(Number.isFinite);
  return times.length ? Math.max(...times) : 0;
}
function setReviewAutosaveStatus(text, state = 'idle') {
  const node = document.getElementById('reviewDraftStatus');
  if (!node) return;
  node.textContent = text;
  node.dataset.state = state;
}
function writeLocalReviewDraftBackup(reason = 'edit', payload = draftReviewPayload(), serialized = serializedDraftReviewPayload(payload)) {
  if (!data?.students?.length) return;
  try {
    localStorage.setItem(reviewDraftStorageKey(), JSON.stringify({
      saved_at_ms: Date.now(),
      reason,
      payload,
      serialized,
    }));
  } catch (_) {}
}
function clearLocalReviewDraftBackup(serialized = '') {
  try {
    const key = reviewDraftStorageKey();
    if (!serialized) {
      localStorage.removeItem(key);
      return;
    }
    const raw = localStorage.getItem(key);
    if (!raw) return;
    const record = JSON.parse(raw);
    if (!record?.serialized || record.serialized === serialized) localStorage.removeItem(key);
  } catch (_) {}
}
function applyAutosaveBundleMetadata(bundle, serialized) {
  if (!bundle || typeof bundle !== 'object') return;
  reviewBundle = bundle;
  const draft = bundle.draft_review || {};
  const latest = bundle.latest_review || {};
  reviewSessionId = ((draft.review_session && draft.review_session.session_id) || (latest.review_session && latest.review_session.session_id) || reviewSessionId || '');
  const savedAt = draft.saved_at || '';
  setReviewAutosaveStatus(savedAt ? `Draft autosaved ${savedAt}` : 'Draft autosaved.', 'ready');
  reviewAutosaveLastSerialized = serialized;
}
function applyLocalReviewDraftBackupIfNewer() {
  if (!data?.students?.length) return;
  try {
    const raw = localStorage.getItem(reviewDraftStorageKey());
    if (!raw) return;
    const backup = JSON.parse(raw);
    const payload = backup?.payload || {};
    const savedAtMs = Number(backup?.saved_at_ms || 0);
    if (!payload || !savedAtMs || savedAtMs <= latestServerDraftTimeMs() + 500) return;
    const currentIds = new Set((data.students || []).map(student => student.student_id));
    const marks = payload.assigned_marks || [];
    if (marks.length && !marks.some(item => currentIds.has(item.student_id))) return;
    const record = {
      review_state: 'draft',
      scope_id: reviewBundle?.draft_review?.scope_id || reviewBundle?.latest_review?.scope_id || currentProject?.scope_key || currentProject?.id || '',
      saved_at: new Date(savedAtMs).toISOString(),
      students: payload.students || [],
      pairwise: payload.pairwise || [],
      curve_top: payload.curve_top ?? null,
      curve_bottom: payload.curve_bottom ?? null,
      assigned_marks: payload.assigned_marks || [],
      feedback_drafts: payload.feedback_drafts || [],
      review_session: { session_id: payload.session_id || reviewSessionId || '' },
    };
    applyReviewBundle({ ...(reviewBundle || {}), draft_review: record });
    setReviewAutosaveStatus('Recovered unsaved browser changes; autosaving...', 'warn');
    queueReviewAutosave('recovered_browser_draft', { immediate: true });
  } catch (_) {}
}
async function flushReviewAutosave() {
  if (!data?.students?.length) return;
  const payload = draftReviewPayload();
  const serialized = serializedDraftReviewPayload(payload);
  if (!reviewAutosaveDirty && serialized === reviewAutosaveLastSerialized) return;
  if (reviewAutosaveInFlight) {
    reviewAutosavePending = true;
    return;
  }
  reviewAutosaveInFlight = true;
  reviewAutosaveDirty = false;
  let failed = false;
  setReviewAutosaveStatus('Autosaving draft...', 'warn');
  try {
    const res = await fetch(apiUrl('/projects/review'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(apiErrorMessage(await res.json().catch(() => ({})), 'Autosave failed'));
    applyAutosaveBundleMetadata(await res.json(), serialized);
    clearLocalReviewDraftBackup(serialized);
  } catch (_) {
    failed = true;
    reviewAutosaveDirty = true;
    setReviewAutosaveStatus('Autosave failed; changes are still on this page.', 'danger');
  } finally {
    reviewAutosaveInFlight = false;
    if (reviewAutosavePending || reviewAutosaveDirty) {
      reviewAutosavePending = false;
      queueReviewAutosave('pending_change', { delay: failed ? 5000 : 500 });
    }
  }
}
function queueReviewAutosave(reason = 'edit', options = {}) {
  if (!data?.students?.length) return;
  const payload = draftReviewPayload();
  const serialized = serializedDraftReviewPayload(payload);
  reviewAutosaveDirty = true;
  writeLocalReviewDraftBackup(reason, payload, serialized);
  setReviewAutosaveStatus('Unsaved changes; autosaving...', 'warn');
  if (reviewAutosaveTimer) clearTimeout(reviewAutosaveTimer);
  reviewAutosaveTimer = setTimeout(() => {
    reviewAutosaveTimer = null;
    flushReviewAutosave();
  }, options.immediate ? 0 : Number(options.delay ?? 900));
}
function sendReviewAutosaveBeacon() {
  if (!reviewAutosaveDirty || !data?.students?.length || !navigator.sendBeacon) return;
  const payload = draftReviewPayload();
  const serialized = serializedDraftReviewPayload(payload);
  writeLocalReviewDraftBackup('page_hide', payload, serialized);
  try {
    navigator.sendBeacon(apiUrl('/projects/review'), new Blob([JSON.stringify(payload)], { type: 'application/json' }));
  } catch (_) {}
}
function waitForReviewAutosaveIdle(timeoutMs = 4000) {
  if (!reviewAutosaveInFlight) return Promise.resolve();
  return new Promise(resolve => {
    const started = Date.now();
    const timer = setInterval(() => {
      if (!reviewAutosaveInFlight || Date.now() - started >= timeoutMs) {
        clearInterval(timer);
        resolve();
      }
    }, 100);
  });
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
    await waitForReviewAutosaveIdle();
    if (reviewAutosaveTimer) {
      clearTimeout(reviewAutosaveTimer);
      reviewAutosaveTimer = null;
    }
    const serialized = serializedDraftReviewPayload();
    const res = await fetch(apiUrl('/projects/review'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...reviewPayload(), action }),
    });
    if (!res.ok) throw new Error('save failed');
    const bundle = await res.json();
    reviewAutosaveDirty = false;
    reviewAutosavePending = false;
    reviewAutosaveLastSerialized = action === 'finalize' ? '' : serialized;
    clearLocalReviewDraftBackup();
    applyReviewBundle(bundle);
    await refreshClassroomState();
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
function ensurePipelineRankOrder() {
  if (!data?.students?.length) return;
  data.students.forEach((student, idx) => {
    if (student._pipeline_rank === undefined) {
      student._pipeline_rank = num(student.pipeline_rank ?? student.rank, idx + 1);
    }
  });
}
function restorePipelineRankOrder(focusStudentId = '') {
  if (!data?.students?.length) return;
  ensurePipelineRankOrder();
  data.students.sort((a, b) => {
    const diff = num(a._pipeline_rank, 999999) - num(b._pipeline_rank, 999999);
    if (diff) return diff;
    return String(a.student_id || '').localeCompare(String(b.student_id || ''));
  });
  data.students.forEach((student, idx) => { student.rank = idx + 1; });
  if (focusStudentId) {
    const restored = data.students.findIndex(student => student.student_id === focusStudentId);
    if (restored >= 0) currentIndex = restored;
  }
}
function resetMarkAdjustments() {
  overrides = {};
  adjustments = {};
  (data?.students || []).forEach(student => {
    adjustments[student.student_id] = { overall: 0, rubric: 0, conventions: 0, comparative: 0 };
  });
}
function setCurveStatus(text, state = 'ready') {
  const status = document.getElementById('curveStatus');
  if (!status) return;
  status.textContent = text;
  status.dataset.state = state;
}
function renderCurveStatus() {
  if (!data?.students?.length) {
    setCurveStatus('Curve is ready after assessment.', 'idle');
    return;
  }
  const top = num(document.getElementById('topGrade')?.value, data.curve_top ?? 92);
  const bottom = num(document.getElementById('bottomGrade')?.value, data.curve_bottom ?? 58);
  if (top <= bottom) {
    setCurveStatus('Curve needs a top mark higher than bottom mark.', 'warn');
    return;
  }
  setCurveStatus(`${data.students.length} ranked essays span ${Math.round(top)} to ${Math.round(bottom)} by original assessment order.`, 'ready');
}
function applyCurveBounds(top, bottom, resetMarks = true) {
  if (!data?.students?.length) {
    renderCurveStatus();
    return false;
  }
  if (top <= bottom) {
    renderCurveStatus();
    return false;
  }
  if (resetMarks) restorePipelineRankOrder(data.students[currentIndex]?.student_id || '');
  grades = computeGrades(top, bottom, data.students.length);
  data.curve_top = top;
  data.curve_bottom = bottom;
  if (resetMarks) resetMarkAdjustments();
  renderCurveStatus();
  return true;
}
function applyPersistedReviewState(record) {
  feedbackDrafts = {};
  (record?.feedback_drafts || []).forEach(item => {
    if (!item?.student_id) return;
    feedbackDrafts[item.student_id] = {
      star1: String(item.star1 || '').trim(),
      star2: String(item.star2 || '').trim(),
      wish: String(item.wish || '').trim(),
    };
  });
  if (!data?.students?.length) return;
  adjustments = {};
  overrides = {};
  const topInput = document.getElementById('topGrade');
  const bottomInput = document.getElementById('bottomGrade');
  const top = num(record?.curve_top, num(topInput?.value, 92));
  const bottom = num(record?.curve_bottom, num(bottomInput?.value, 58));
  if (topInput) topInput.value = Math.round(top);
  if (bottomInput) bottomInput.value = Math.round(bottom);
  applyCurveBounds(top, bottom, true);
  const markMap = new Map((record?.assigned_marks || []).map(item => [item.student_id, num(item.mark, null)]));
  data.students.forEach((student, idx) => {
    if (!markMap.has(student.student_id)) return;
    const target = clamp(num(markMap.get(student.student_id), grades[idx] ?? 0), 0, 100);
    const adj = getAdjustment(student.student_id);
    adj.overall = target - (grades[idx] ?? 0);
  });
  seedBaselineFeedbackDrafts(true);
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
function normalizeFeedbackDraft(item) {
  return {
    star1: String(item?.star1 || '').trim(),
    star2: String(item?.star2 || '').trim(),
    wish: String(item?.wish || '').trim(),
  };
}
function feedbackDraftHasText(item) {
  return !!(item && (item.star1 || item.star2 || item.wish));
}
function baselineFeedbackForStudent(student, fallbackText = '') {
  const explicit = normalizeFeedbackDraft(student?.feedback_draft || {});
  if (feedbackDraftHasText(explicit)) return explicit;
  return normalizeFeedbackDraft(parseFeedback(fallbackText || student?.feedback_text || ''));
}
function seedBaselineFeedbackDrafts(preserveExisting = true) {
  if (!data?.students?.length) return;
  data.students.forEach(student => {
    if (!student?.student_id) return;
    if (preserveExisting && feedbackDraftHasText(feedbackDrafts[student.student_id])) return;
    const draft = baselineFeedbackForStudent(student, student.feedback_text || '');
    if (feedbackDraftHasText(draft)) feedbackDrafts[student.student_id] = draft;
  });
  if (window.feedbackGenerate?.generateAll) {
    window.feedbackGenerate.generateAll(data.students, getGradeForIndex, adjustments, feedbackDrafts, false);
  }
}
function feedbackForStudent(studentId, feedbackText) {
  if (!feedbackDrafts[studentId]) {
    const student = data?.students?.find(item => item.student_id === studentId);
    feedbackDrafts[studentId] = baselineFeedbackForStudent(student, feedbackText);
  }
  return feedbackDrafts[studentId];
}
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
function renderExceptions() {
  const stateNode = document.getElementById('validationState');
  const listNode = document.getElementById('exceptionsList');
  if (!stateNode || !listNode) return;
  const validation = data?.validation || {};
  const classroomBlockers = (classroomState?.blockers || []).map(code => ({
    kind: 'Classroom blocker',
    label: String(code || '').replaceAll('_', ' '),
    action: classroomState?.classroom_error_remedies?.[code] || 'Resolve this Classroom import issue before export.',
  }));
  const exceptions = [...(data?.teacher_exceptions || []), ...classroomBlockers];
  const status = validation.status || 'pending';
  if (validation.teacher_message) {
    stateNode.textContent = validation.teacher_message;
  } else if (status === 'pending') {
    stateNode.textContent = 'Review ready. SOTA validation is checking edge cases in the background.';
  } else if (exceptions.length) {
    stateNode.textContent = `Validation found ${exceptions.length} case${exceptions.length === 1 ? '' : 's'} to inspect.`;
  } else {
    stateNode.textContent = 'Validation complete.';
  }
  stateNode.dataset.state = status === 'pending' ? 'warn' : (exceptions.length ? 'warn' : 'ready');
  listNode.innerHTML = '';
  if (!exceptions.length) {
    const empty = document.createElement('div');
    empty.className = 'auth-status';
    empty.textContent = status === 'pending' ? 'No exceptions yet.' : 'No action needed.';
    listNode.appendChild(empty);
    return;
  }
  exceptions.slice(0, 12).forEach(item => {
    const row = document.createElement('div');
    row.className = 'exception-item';
    const student = item.student_id ? `${labelForId(item.student_id, item.student_id)} · ` : '';
    row.innerHTML = `
      <div class="exception-title">${student}${item.label || item.kind || 'Exception'}</div>
      <div class="exception-action">${item.action || 'Inspect this item before export.'}</div>
    `;
    listNode.appendChild(row);
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
  star1.oninput = () => { draft.star1 = star1.innerText.trim(); queueReviewAutosave('feedback_star1'); };
  star2.oninput = () => { draft.star2 = star2.innerText.trim(); queueReviewAutosave('feedback_star2'); };
  wish.oninput = () => { draft.wish = wish.innerText.trim(); queueReviewAutosave('feedback_wish'); };
}
function renderDetail() {
  const summaryPanel = document.getElementById('summary');
  const emptyState = document.getElementById('workspaceEmpty');
  const essayGrid = document.getElementById('essayGrid');
  if (previewStudents.length || !data || !data.students || !data.students.length) {
    const imported = classroomImportedCount();
    const classroomReady = classroomImportsReady();
    const next = classroomNextStep();
    document.getElementById('detailTitle').textContent = previewStudents.length
      ? 'Files ready. Run the assessment to review the cohort.'
      : classroomReady
        ? `${imported} Classroom essay${imported === 1 ? '' : 's'} synced`
        : 'Upload essays to begin';
    document.getElementById('essay').innerHTML = classroomReady
      ? `<p>${next.text}</p>`
      : '<p>Once the assessment runs, the essay text and comparison view will appear here.</p>';
    document.getElementById('essayLabelPrimary').textContent = '';
    document.getElementById('essayLabelCompare').textContent = '';
    if (summaryPanel) summaryPanel.classList.add('is-hidden');
    if (emptyState) emptyState.classList.remove('is-hidden');
    if (essayGrid) essayGrid.classList.add('is-hidden');
    renderReviewPanel(null);
    renderExceptions();
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
  renderExceptions();
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
function applyAdjustment(studentId, key, delta) {
  const sidx = Math.max(0, data?.students?.findIndex(s => s.student_id === studentId) ?? 0);
  currentIndex = sidx;
  const adj = getAdjustment(studentId);
  adj[key] += delta;
  const target = key === 'overall' && data?.students?.length ? getGradeForIndex(sidx) : null;
  if (data?.students?.length && window.gradeAdjust?.resort) {
    focusLock = true;
    for (let i = 0; i < 3; i += 1) {
      window.gradeAdjust.resort(data.students, getGradeForIndex);
      currentIndex = Math.max(0, data.students.findIndex(s => s.student_id === studentId));
      if (target === null) break;
      const diff = target - getGradeForIndex(currentIndex);
      if (Math.abs(diff) < 0.5) break;
      adj.overall += diff;
    }
    renderRail(true);
    scrollToIndex(currentIndex, false);
    focusLock = false;
    queueReviewAutosave('mark_adjustment');
    return;
  }
  updateRail();
  renderDetail();
  queueReviewAutosave('mark_adjustment');
}
function applyOverallTarget(target) {
  if (!data?.students?.length) return;
  const sid = sliderStudentId || data.students[currentIndex]?.student_id;
  const s = data.students.find(x => x.student_id === sid) || data.students[currentIndex];
  currentIndex = Math.max(0, data.students.findIndex(x => x.student_id === s.student_id));
  const curr = getGradeForIndex(currentIndex);
  const delta = target - curr;
  const adj = getAdjustment(s.student_id);
  const spread = (window.gradeAdjust && window.gradeAdjust.distribute) ? window.gradeAdjust.distribute(s, delta) : { rubric: delta * 0.7, conventions: delta * 0.15, comparative: delta * 0.15 };
  adj.rubric += num(spread.rubric, 0);
  adj.conventions += num(spread.conventions, 0);
  adj.comparative += num(spread.comparative, 0);
  adj.overall += delta;
  delete overrides[s.student_id];
  const inp = document.getElementById('gradeOverride');
  if (inp) inp.value = Math.round(target);
  const slider = document.getElementById('overallGradeSlider');
  if (slider) slider.value = Math.round(target);
  if (window.gradeAdjust?.resort) {
    focusLock = true;
    for (let i = 0; i < 3; i += 1) {
      window.gradeAdjust.resort(data.students, getGradeForIndex);
      currentIndex = Math.max(0, data.students.findIndex(x => x.student_id === s.student_id));
      const diff = target - getGradeForIndex(currentIndex);
      if (Math.abs(diff) < 0.5) break;
      adj.overall += diff;
    }
    renderRail(true);
    scrollToIndex(currentIndex, false);
    focusLock = false;
    queueReviewAutosave('assigned_mark');
    return;
  }
  updateRail();
  renderDetail();
  queueReviewAutosave('assigned_mark');
}
function generateFeedbackDrafts() {
  if (!data?.students?.length || !window.feedbackGenerate?.generateAll) return;
  window.feedbackGenerate.generateAll(data.students, getGradeForIndex, adjustments, feedbackDrafts, true);
  renderDetail();
  queueReviewAutosave('generated_feedback');
}
function updateGradesFromCurve() {
  if (!data || !data.students || !data.students.length) return;
  const topInput = document.getElementById('topGrade');
  const bottomInput = document.getElementById('bottomGrade');
  const top = clamp(num(topInput?.value, 92), 0, 100);
  const bottom = clamp(num(bottomInput?.value, 58), 0, 100);
  if (topInput) topInput.value = Math.round(top);
  if (bottomInput) bottomInput.value = Math.round(bottom);
  if (!applyCurveBounds(top, bottom, true)) return;
  updateRail();
  renderDetail();
  queueReviewAutosave('curve_bounds');
}
function setRunning(on, mode = 'blocking') {
  running = on;
  document.body.dataset.running = on ? 'true' : 'false';
  if (on) document.body.dataset.runningMode = mode;
  else delete document.body.dataset.runningMode;
  updateWorkflowState();
}
function pipelineLog(msg) { const log = document.getElementById('pipelineLog'); if (!log) return; const line = document.createElement('div'); line.textContent = msg; log.appendChild(line); log.scrollTop = log.scrollHeight; }
function startPipelineNarrative() { const log = document.getElementById('pipelineLog'); if (log) log.innerHTML = ''; const steps = ['Getting your files ready and organized…', "In this first pass, we’re conducting an initial assessment based on the rubric.", 'Next, we compare essays side‑by‑side to keep the ordering consistent.', 'Now we scan conventions: spelling, grammar, sentence structure, and format.', 'We’re integrating all signals into a final, coherent ordering.', 'Building the teacher review dashboard…']; pipelineStep = 0; pipelineLog(steps[0]); pipelineTimer = setInterval(() => { pipelineStep += 1; if (pipelineStep < steps.length) pipelineLog(steps[pipelineStep]); }, 2400); }
function stopPipelineNarrative(msg, keepRunning = false) { if (msg) pipelineLog(msg); if (pipelineTimer) clearInterval(pipelineTimer); pipelineTimer = null; if (!keepRunning) setTimeout(() => setRunning(false), 2000); }
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
function validationText(job) {
  if (!job) return 'Review ready.';
  if (job.validation_status === 'running' || job.product_phase === 'background_validating') return 'Review ready. SOTA validation is checking edge cases in the background.';
  if (job.validation_status === 'failed_nonblocking' || job.product_phase === 'validation_failed_nonblocking') return `Validation found ${job.validation_exception_count || 0} case${job.validation_exception_count === 1 ? '' : 's'} to inspect.`;
  if (job.validation_status === 'anchor_scores_required') return 'Review ready. Anchor calibration is needed before export.';
  if (job.validation_status === 'complete' || job.product_phase === 'validation_complete') return 'Validation complete.';
  return 'Review ready.';
}
function rememberActivePipelineJob(jobId) {
  activeJobId = jobId || activeJobId || '';
  if (!activeJobId) return;
  try {
    localStorage.setItem(ACTIVE_PIPELINE_JOB_KEY, JSON.stringify({
      job_id: activeJobId,
      project_id: currentProject?.id || '',
      saved_at: new Date().toISOString(),
    }));
  } catch (_) {}
}
function clearActivePipelineJob(jobId = '') {
  if (!jobId || jobId === activeJobId) activeJobId = '';
  try {
    const stored = JSON.parse(localStorage.getItem(ACTIVE_PIPELINE_JOB_KEY) || '{}');
    if (!jobId || stored.job_id === jobId) localStorage.removeItem(ACTIVE_PIPELINE_JOB_KEY);
  } catch (_) {
    try { localStorage.removeItem(ACTIVE_PIPELINE_JOB_KEY); } catch (__) {}
  }
}
function storedActivePipelineJob() {
  try {
    const stored = JSON.parse(localStorage.getItem(ACTIVE_PIPELINE_JOB_KEY) || '{}');
    return stored && stored.job_id ? stored : null;
  } catch (_) {
    return null;
  }
}
function stopBackgroundValidationWatch() {
  if (backgroundValidationTimer) clearInterval(backgroundValidationTimer);
  backgroundValidationTimer = null;
}
function watchBackgroundValidation(jobId) {
  stopBackgroundValidationWatch();
  if (!jobId) return;
  backgroundValidationTimer = setInterval(async () => {
    try {
      const res = await fetch(apiUrl(`/pipeline/v2/jobs/${jobId}`));
      if (!res.ok) return;
      const job = await res.json();
      setPipelineStatus(validationText(job), job.validation_status === 'complete' ? 'ready' : 'warn');
      if (job.status === 'completed' || job.status === 'failed' || job.status === 'awaiting_anchor_scores') {
        stopBackgroundValidationWatch();
        if (job.status === 'awaiting_anchor_scores') await fetchAnchorReview(jobId);
        const dataRes = await fetch(apiUrl(`/pipeline/v2/jobs/${jobId}/data`));
        if (dataRes.ok) {
          await boot(await dataRes.json());
          if (job.status === 'completed') {
            clearActivePipelineJob(jobId);
            setRunning(false);
          } else if (job.status === 'failed') {
            clearActivePipelineJob(jobId);
            setRunning(false);
            setPipelineStatus('Review ready. Background checks stopped and need admin inspection.', 'warn');
          } else {
            setRunning(true, 'background');
          }
        } else if (job.status === 'failed') {
          clearActivePipelineJob(jobId);
          setRunning(false);
          setPipelineStatus(runErrorForTeacher(job.error || 'Run failed'), 'danger');
        }
      }
    } catch (_) {
      // Keep the teacher in the review flow; polling will retry.
    }
  }, 4000);
}
async function waitForJob(jobId) {
  const start = Date.now();
  let longRunNoticeShown = false;
  let statusErrorCount = 0;
  while (true) {
    let job = null;
    try {
      const res = await fetch(apiUrl(`/pipeline/v2/jobs/${jobId}`));
      if (!res.ok) throw new Error('Run status unavailable');
      job = await res.json();
      statusErrorCount = 0;
    } catch (err) {
      statusErrorCount += 1;
      const recovered = await recoverActivePipelineJob(jobId, err);
      if (recovered) return recovered;
      setPipelineStatus('Still running; status connection is retrying.', 'warn');
      pipelineLog('Status check is retrying. The run is still being watched.');
      await sleep(Math.min(10000, 2000 + statusErrorCount * 1000));
      continue;
    }
    if (job.teacher_can_review || job.product_phase === 'teacher_review_ready' || job.product_phase === 'background_validating') return job;
    if (job.status === 'completed' || job.status === 'awaiting_rubric_confirmation' || job.status === 'awaiting_anchor_scores') return job;
    if (job.status === 'failed') throw new Error(job.error || 'Run failed');
    const elapsed = Date.now() - start;
    if (elapsed >= 45 * 60 * 1000 && !longRunNoticeShown) {
      longRunNoticeShown = true;
      pipelineLog('Still running. Large Classroom sets can take longer on the first pass; this tab will keep watching the job.');
    }
    if (elapsed >= 45 * 60 * 1000) {
      const stage = (job.progress_message || job.progress_stage || 'working').toString();
      setPipelineStatus(`Still running: ${stage}`, 'warn');
    }
    await sleep(elapsed >= 45 * 60 * 1000 ? 5000 : 2000);
  }
}
async function recoverActivePipelineJob(jobId, err = null) {
  if (!jobId) return null;
  try {
    const dataRes = await fetch(apiUrl(`/pipeline/v2/jobs/${jobId}/data`));
    if (dataRes.ok) {
      const payload = await dataRes.json();
      previewStudents = [];
      setRunning(true, 'background');
      await boot(payload);
      setPipelineStatus('Review ready. Background checks may still be running.', 'warn');
      stopShuffle();
      stopPipelineNarrative('Review dashboard recovered; continuing to watch background work.', true);
      watchBackgroundValidation(jobId);
      rememberActivePipelineJob(jobId);
      return { id: jobId, status: 'running', teacher_can_review: true, product_phase: 'background_validating', validation_status: 'running' };
    }
  } catch (_) {}
  if (err) {
    const message = String(err.message || err || '');
    if (message.toLowerCase().includes('timed out')) {
      setPipelineStatus('Still running; keeping the background watch active.', 'warn');
      rememberActivePipelineJob(jobId);
      watchBackgroundValidation(jobId);
      return { id: jobId, status: 'running', product_phase: 'running_fast_review', validation_status: 'pending' };
    }
  }
  return null;
}
async function resumeActivePipelineJob() {
  if (activeJobResumeStarted || running || activeJobId) return;
  const stored = storedActivePipelineJob();
  if (!stored?.job_id) return;
  activeJobResumeStarted = true;
  activeJobId = stored.job_id;
  setRunning(true);
  setPipelineStatus('Reconnecting to the running assessment...', 'warn');
  pipelineLog('Reconnected to the active assessment job.');
  try {
    const job = await waitForJob(activeJobId);
    if (job.status === 'awaiting_rubric_confirmation') {
      setPipelineStatus('Rubric confirmation needed', 'warn');
      stopPipelineNarrative('Rubric interpretation needs confirmation before scoring continues.');
      await fetchRubricReview(activeJobId);
      return;
    }
    if (job.status === 'awaiting_anchor_scores') {
      setPipelineStatus('Anchor calibration needed', 'warn');
      stopPipelineNarrative('Teacher anchor scores are needed before finalizing this cohort.');
      await fetchAnchorReview(activeJobId);
      return;
    }
    await loadReviewReadyJob(job, activeJobId);
  } catch (err) {
    const recovered = await recoverActivePipelineJob(activeJobId, err);
    if (!recovered) {
      const msg = runErrorForTeacher(err.message || 'connection lost');
      setPipelineStatus(msg, 'danger');
      stopPipelineNarrative(msg);
      clearActivePipelineJob(activeJobId);
    }
  } finally {
    activeJobResumeStarted = false;
  }
}
async function loadReviewReadyJob(job, fallbackJobId) {
  const jobId = job.id || fallbackJobId;
  const dataRes = await fetch(apiUrl(`/pipeline/v2/jobs/${jobId}/data`));
  if (!dataRes.ok) throw new Error('Dashboard data unavailable');
  previewStudents = [];
  await boot(await dataRes.json());
  const text = validationText(job);
  setPipelineStatus(text, job.validation_status === 'complete' ? 'ready' : 'warn');
  stopShuffle();
  const backgroundRunning = job.status !== 'completed' && job.status !== 'awaiting_anchor_scores';
  stopPipelineNarrative(backgroundRunning ? `${text} You can review now while background work continues.` : text, backgroundRunning);
  if (backgroundRunning) {
    rememberActivePipelineJob(jobId);
    setRunning(true, 'background');
    watchBackgroundValidation(jobId);
  } else {
    clearActivePipelineJob(jobId);
    setRunning(false);
  }
}
function runErrorForTeacher(message) {
  const raw = String(message || '').trim();
  const lower = raw.toLowerCase();
  if (lower.includes('calibration gate failed')) {
    if (lower.includes('stale')) return 'Calibration needs refresh before this class can run. Ask an admin to refresh calibration, then run again.';
    if (lower.includes('missing')) return 'Calibration is not set up yet. Ask an admin to prepare calibration, then run again.';
    return 'Calibration is not ready for this class. Ask an admin to refresh calibration, then run again.';
  }
  if (lower.includes('codex not connected')) return 'Codex is not connected. Sign in with Codex, then run again.';
  if (lower.includes('api key') || lower.includes('is not set')) return 'The runtime is not connected. Connect Codex or an API key, then run again.';
  if (lower.includes('timed out')) return 'The status connection timed out. Assessor will keep watching any submitted run in the background.';
  if (!raw) return 'Run failed. Check the inputs and try again.';
  return raw.length > 180 ? 'Run failed. Check the inputs and try again; if it repeats, ask an admin to inspect the run.' : raw;
}
async function runPipeline() {
  const essays = document.getElementById('uploadEssays');
  const rubric = document.getElementById('uploadRubric');
  const outline = document.getElementById('uploadOutline');
  const latestSync = (classroomState?.sync_history || []).slice(-1)[0] || {};
  const classroomImported = !!(
    classroomState?.classroom_link?.course_id &&
    ((classroomState?.summary?.ready_for_analysis_count || 0) > 0 || (latestSync.imported_count || 0) > 0)
  );
  const hasLocalEssays = !!essays?.files?.length;
  if (!rubric?.files?.[0] || !outline?.files?.[0] || (!hasLocalEssays && !classroomImported)) {
    setPipelineStatus(classroomImported ? 'Add rubric and outline' : 'Add essays, rubric, outline', 'warn');
    return;
  }
  if (hasLocalEssays && !previewStudents.length) updatePreviewFromUploads();
  setPipelineStatus('Checking connection...', 'warn');
  let mode = '';
  try {
    const [cRes, aRes] = await Promise.all([fetch(apiUrl('/codex/status')), fetch(apiUrl('/auth/status'))]);
    const c = cRes.ok ? await cRes.json() : null;
    const a = aRes.ok ? await aRes.json() : null;
    mode = a && a.connected ? 'api' : (c && c.connected ? 'codex_local' : '');
  } catch (err) {
    setPipelineStatus('Offline', 'danger');
    return;
  }
  if (!mode) {
    setPipelineStatus('Connect Codex or API key', 'warn');
    return;
  }
  const form = new FormData();
  form.append('rubric', rubric.files[0]);
  form.append('outline', outline.files[0]);
  if (hasLocalEssays) Array.from(essays.files).forEach(f => form.append('submissions', f));
  form.append('mode', mode);
  if (currentProject?.id) form.append('project_id', currentProject.id);
  setPipelineStatus('Running...', 'running');
  setRunning(true);
  startPipelineNarrative();
  startShuffle();
  try {
    const endpoint = hasLocalEssays ? '/pipeline/v2/run' : '/pipeline/v2/run-project-inputs';
    const res = await fetch(apiUrl(endpoint), { method: 'POST', body: form });
    if (!res.ok) {
      let msg = 'Run failed';
      try {
        const err = await res.json();
        if (err.detail) msg = runErrorForTeacher(apiErrorMessage(err, 'Run failed'));
      } catch (_) {}
      setPipelineStatus(msg, 'danger');
      stopShuffle();
      stopPipelineNarrative(msg);
      return;
    }
    const submit = await res.json();
    activeJobId = submit.job_id || '';
    rememberActivePipelineJob(activeJobId);
    if (submit.cached) pipelineLog('Identical inputs found; using cached assessment.');
    if (submit.status === 'awaiting_rubric_confirmation') {
      setPipelineStatus('Rubric confirmation needed', 'warn');
      stopShuffle();
      stopPipelineNarrative('Rubric interpretation needs confirmation before scoring continues.');
      await fetchRubricReview(activeJobId);
      return;
    }
    const job = submit.status === 'completed' ? submit : await waitForJob(activeJobId);
    if (job.status === 'awaiting_rubric_confirmation') {
      setPipelineStatus('Rubric confirmation needed', 'warn');
      stopShuffle();
      stopPipelineNarrative('Rubric interpretation needs confirmation before scoring continues.');
      await fetchRubricReview(activeJobId);
      return;
    }
    if (job.status === 'awaiting_anchor_scores') {
      setPipelineStatus('Anchor calibration needed', 'warn');
      stopShuffle();
      stopPipelineNarrative('Teacher anchor scores are needed before finalizing this cohort.');
      const dataRes = await fetch(apiUrl(`/pipeline/v2/jobs/${job.id || activeJobId}/data`));
      if (dataRes.ok) {
        previewStudents = [];
        await boot(await dataRes.json());
      }
      await fetchAnchorReview(activeJobId);
      return;
    }
    await loadReviewReadyJob(job, activeJobId);
  } catch (err) {
    const recovered = await recoverActivePipelineJob(activeJobId, err);
    if (recovered) return;
    const msg = runErrorForTeacher(err.message || 'connection lost');
    setPipelineStatus(msg, 'danger');
    stopShuffle();
    stopPipelineNarrative(msg);
  }
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
    const payload = [`Two Stars and a Wish - ${labelFor(student)}`, `Star 1: ${draft.star1 || '—'}`, `Star 2: ${draft.star2 || '—'}`, `Wish: ${draft.wish || '—'}`].join('\n'); navigator.clipboard.writeText(payload);
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
  if (reviewLevel) reviewLevel.addEventListener('change', e => { const student = data?.students?.[currentIndex]; if (!student) return; studentReview(student.student_id).level_override = e.target.value; queueReviewAutosave('level_override'); });
  if (reviewRank) reviewRank.addEventListener('change', e => { const student = data?.students?.[currentIndex]; if (!student) return; studentReview(student.student_id).desired_rank = e.target.value.trim() ? parseInt(e.target.value, 10) : ''; queueReviewAutosave('desired_rank'); });
  if (reviewQuality) reviewQuality.addEventListener('change', e => { const student = data?.students?.[currentIndex]; if (!student) return; studentReview(student.student_id).evidence_quality = e.target.value; queueReviewAutosave('evidence_quality'); });
  if (reviewComment) reviewComment.addEventListener('input', e => { const student = data?.students?.[currentIndex]; if (!student) return; studentReview(student.student_id).evidence_comment = e.target.value.trim(); queueReviewAutosave('evidence_comment'); });
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
    queueReviewAutosave('pairwise_prefer_current');
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
    queueReviewAutosave('pairwise_prefer_compare');
  });
  if (clearPairwise) clearPairwise.addEventListener('click', () => {
    const student = data?.students?.[currentIndex];
    const compareIndex = getCompareIndex();
    if (!student || compareIndex === null) return;
    delete reviewPairs[pairKey(student.student_id, data.students[compareIndex].student_id)];
    renderReviewPanel(student);
    queueReviewAutosave('pairwise_clear');
  });
  window.addEventListener('beforeunload', sendReviewAutosaveBeacon);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') sendReviewAutosaveBeacon(); });
  setupUploads();
  loadProjects();
  const saveBtn = document.getElementById('saveProject'); if (saveBtn) saveBtn.addEventListener('click', saveProject);
  const newBtn = document.getElementById('newProject'); if (newBtn) newBtn.addEventListener('click', newProject);
  const clearBtn = document.getElementById('clearProject'); if (clearBtn) clearBtn.addEventListener('click', clearProject);
  const loadBtn = document.getElementById('loadProject'); if (loadBtn) loadBtn.addEventListener('click', loadProject);
  const delBtn = document.getElementById('deleteProject'); if (delBtn) delBtn.addEventListener('click', deleteProject);
  const googleConnect = document.getElementById('googleConnect'); if (googleConnect) googleConnect.addEventListener('click', startGoogleConnect);
  const googleDisconnect = document.getElementById('googleDisconnect'); if (googleDisconnect) googleDisconnect.addEventListener('click', disconnectGoogle);
  const googleCourseSelect = document.getElementById('googleCourseSelect'); if (googleCourseSelect) googleCourseSelect.addEventListener('change', loadGoogleCoursework);
  const selectGoogle = document.getElementById('selectGoogleAssignment'); if (selectGoogle) selectGoogle.addEventListener('click', selectGoogleAssignment);
  const syncGoogle = document.getElementById('syncGoogleSubmissions'); if (syncGoogle) syncGoogle.addEventListener('click', syncGoogleSubmissions);
  const linkClassroom = document.getElementById('linkClassroom'); if (linkClassroom) linkClassroom.addEventListener('click', linkClassroomAssignment);
  const readSyncBtn = document.getElementById('readSyncClassroom'); if (readSyncBtn) readSyncBtn.addEventListener('click', readSyncClassroom);
  const reconcileBtn = document.getElementById('reconcileClassroom'); if (reconcileBtn) reconcileBtn.addEventListener('click', reconcileClassroom);
  const auditBtn = document.getElementById('completeClassroomAudit'); if (auditBtn) auditBtn.addEventListener('click', completeClassroomAudit);
  const finalizeClassroom = document.getElementById('finalizeClassroom'); if (finalizeClassroom) finalizeClassroom.addEventListener('click', finalizeClassroomResult);
  const preflightBtn = document.getElementById('passbackPreflight'); if (preflightBtn) preflightBtn.addEventListener('click', preflightPassback);
  const confirmPassbackBtn = document.getElementById('confirmPassback'); if (confirmPassbackBtn) confirmPassbackBtn.addEventListener('click', confirmPassback);
  const evidenceBtn = document.getElementById('showEvidencePacket'); if (evidenceBtn) evidenceBtn.addEventListener('click', showEvidencePacket);
  const confirmRubric = document.getElementById('confirmRubric'); if (confirmRubric) confirmRubric.addEventListener('click', () => submitRubricReview('confirm'));
  const saveRubricEdits = document.getElementById('saveRubricEdits'); if (saveRubricEdits) saveRubricEdits.addEventListener('click', () => submitRubricReview('edit'));
  const rejectRubric = document.getElementById('rejectRubric'); if (rejectRubric) rejectRubric.addEventListener('click', () => submitRubricReview('reject'));
  const submitAnchors = document.getElementById('submitAnchors'); if (submitAnchors) submitAnchors.addEventListener('click', submitAnchorReview);
  updateWorkflowState();
  refreshClassroomState();
  refreshGoogleAuth();
}
async function boot(payload) {
  data = payload;
  if (!data.students) data.students = [];
  ensurePipelineRankOrder();
  restorePipelineRankOrder();
  document.title = 'Assessor';
  if (data.class_metadata && data.class_metadata.grade_level) {
    const title = document.querySelector('.brand h1');
    title.textContent = 'Assessor';
    document.title = `Assessor • Grade ${data.class_metadata.grade_level}`;
  }
  if (data.curve_top) document.getElementById('topGrade').value = data.curve_top;
  if (data.curve_bottom) document.getElementById('bottomGrade').value = data.curve_bottom;
  applyCurveBounds(num(document.getElementById('topGrade').value, 92), num(document.getElementById('bottomGrade').value, 58), false);
  seedBaselineFeedbackDrafts(true);
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
  renderAnchorReview(
    payload && ((payload.teacher_anchor_packet && (payload.teacher_anchor_packet.anchors || []).length) || payload.cohort_confidence)
      ? {
          status: 'completed',
          cohort_confidence: payload.cohort_confidence || {},
          anchor_packet: payload.teacher_anchor_packet || {},
          anchor_calibration: payload.anchor_calibration || {},
        }
      : null,
  );
  await loadReviewBundle();
  await refreshClassroomState();
  renderRail();
  if (data.students.length) scrollToIndex(0, false);
  else renderDetail();
  updateControlVisibility();
  updateWorkflowState();
  refreshAuthStatus();
  refreshGoogleAuth();
  resumeActivePipelineJob();
}
fetch(`/data.json?t=${Date.now()}`, { cache: 'no-store' })
  .then(res => res.ok ? res.text() : '')
  .then(text => { try { return text ? JSON.parse(text) : { students: [] }; } catch (_) { return { students: [] }; } })
  .then(payload => boot(payload))
  .catch(err => { console.error(err); return boot({ students: [] }); });
