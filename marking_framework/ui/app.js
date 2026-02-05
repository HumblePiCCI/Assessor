let data = null, currentIndex = 0, grades = [], overrides = {}, adjustments = {}, feedbackDrafts = {}, scrollTicking = false, compareDirection = 1, previewStudents = [], running = false, shuffleTimer = null, pipelineTimer = null, pipelineStep = 0, projects = [], currentProject = null;
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
function getStudents() { return previewStudents.length ? previewStudents : ((data && data.students && data.students.length) ? data.students : []); }
async function refreshAuthStatus() { const status = document.getElementById('authStatus'); if (!status) return; try { const [codexRes, apiRes] = await Promise.all([fetch(apiUrl('/codex/status')), fetch(apiUrl('/auth/status'))]); const codex = codexRes.ok ? await codexRes.json() : null; const api = apiRes.ok ? await apiRes.json() : null; if (codex && codex.available && codex.connected) status.textContent = 'Codex connected'; else if (api && api.connected) status.textContent = 'API key connected'; else if (codex && codex.available) status.textContent = 'Codex not connected'; else status.textContent = 'Offline'; } catch (err) { status.textContent = 'Offline'; } }
async function connectApiKey() { const input = document.getElementById('apiKeyInput'); const status = document.getElementById('authStatus'); if (!input || !status) return; const key = input.value.trim(); if (!key) return; try { const res = await fetch(apiUrl('/auth'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ api_key: key }) }); if (!res.ok) { status.textContent = 'Invalid key'; return; } input.value = ''; status.textContent = 'API key connected'; } catch (err) { status.textContent = 'Offline'; } }
async function startCodexLogin() { const status = document.getElementById('authStatus'); if (!status) return; try { const res = await fetch(apiUrl('/codex/login'), { method: 'POST' }); status.textContent = res.ok ? 'Codex login started' : 'Codex login failed'; if (res.ok) setTimeout(refreshAuthStatus, 1500); } catch (err) { status.textContent = 'Offline'; } }
async function loadProjects() { const select = document.getElementById('projectSelect'); if (!select) return; try { const res = await fetch(apiUrl('/projects')); if (!res.ok) return; const payload = await res.json(); projects = payload.projects || []; currentProject = payload.current || null; select.innerHTML = ''; if (!projects.length) { const opt = document.createElement('option'); opt.textContent = 'No saved projects'; opt.value = ''; opt.disabled = true; opt.selected = true; select.appendChild(opt); } else { projects.forEach(p => { const opt = document.createElement('option'); opt.textContent = p.name || p.id; opt.value = p.id; if (currentProject && p.id === currentProject.id) opt.selected = true; select.appendChild(opt); }); } const status = document.getElementById('projectStatus'); if (status) status.textContent = currentProject ? `Current: ${currentProject.name}` : 'No project loaded'; } catch (_) {} }
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
  grades = [];
  currentIndex = 0;
  resetUploadLabels();
  const status = document.getElementById('pipelineStatus'); if (status) status.textContent = 'Idle';
  renderRail(); renderDetail();
}
async function clearProject() { if (!confirm('Clear the current session?')) return; try { const res = await fetch(apiUrl('/projects/clear'), { method: 'POST' }); if (!res.ok) return; clearLocalState(); location.href = `${location.pathname}?t=${Date.now()}`; } catch (_) {} }
async function loadProject() { const select = document.getElementById('projectSelect'); if (!select || !select.value) return; try { const res = await fetch(apiUrl('/projects/load'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: select.value }) }); if (!res.ok) return; location.reload(); } catch (_) {} }
async function deleteProject() { const select = document.getElementById('projectSelect'); if (!select || !select.value) return; if (!confirm('Delete this project?')) return; try { const res = await fetch(apiUrl(`/projects/${select.value}`), { method: 'DELETE' }); if (!res.ok) return; await loadProjects(); } catch (_) {} }
function getCompareIndex() { if (!data || data.students.length < 2) return null; const target = currentIndex + compareDirection; if (target >= 0 && target < data.students.length) return target; const fallback = currentIndex - compareDirection; if (fallback >= 0 && fallback < data.students.length) return fallback; return null; }
function getAdjustment(studentId) { if (!adjustments[studentId]) adjustments[studentId] = { overall: 0, rubric: 0, conventions: 0, comparative: 0 }; return adjustments[studentId]; }
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
    item.innerHTML = `<div class="rail-rank">Rank ${s.rank || idx + 1}</div><div class="rail-name">${s.student_id}</div><div class="rail-grade"></div>`;
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
function feedbackForStudent(studentId, feedbackText) {
  if (!feedbackDrafts[studentId]) {
    feedbackDrafts[studentId] = parseFeedback(feedbackText);
  }
  return feedbackDrafts[studentId];
}
function renderSummary(student) {
  const summary = document.getElementById('summaryList');
  summary.innerHTML = '';
  const adj = getAdjustment(student.student_id);
  const rows = [
    { key: 'overall', label: 'Overall grade', value: getGradeForIndex(currentIndex), adjustable: true },
    { key: 'rubric', label: 'Rubric score', value: num(student.rubric_mean_percent), adjustable: true },
    { key: 'conventions', label: 'Conventions %', value: num(student.conventions_mistake_rate_percent), adjustable: true },
    { key: 'comparative', label: 'Comparative', value: num(student.borda_points), adjustable: true },
    { key: 'composite', label: 'Composite', value: num(student.composite_score), adjustable: false },
    { key: 'level', label: 'Level', value: student.level_with_modifier || student.adjusted_level || '', adjustable: false },
    { key: 'flags', label: 'Flags', value: student.flags || '—', adjustable: false },
  ];
  rows.forEach(row => {
    const value = row.key in adj ? row.value + adj[row.key] : row.value;
    const stage = document.createElement('div');
    stage.className = 'stage-row';
    stage.innerHTML = `
      <div class="stage-label">${row.label}</div>
      <div class="stage-value">${value}</div>
      <div class="adjusters"></div>
    `;
    if (row.adjustable) {
      const adjusters = stage.querySelector('.adjusters');
      const up = document.createElement('button');
      up.textContent = '▲';
      const down = document.createElement('button');
      down.textContent = '▼';
      up.addEventListener('click', () => applyAdjustment(student.student_id, row.key, 1));
      down.addEventListener('click', () => applyAdjustment(student.student_id, row.key, -1));
      adjusters.appendChild(up);
      adjusters.appendChild(down);
    }
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
  if (previewStudents.length || !data || !data.students || !data.students.length) {
    document.getElementById('detailTitle').textContent = 'Upload essays to begin';
    document.getElementById('essay').innerHTML = '';
    document.getElementById('essayLabelPrimary').textContent = '';
    return;
  }
  const student = data.students[currentIndex];
  document.getElementById('detailTitle').textContent = `${student.student_id} • Rank ${student.rank}`;
  renderSummary(student);
  document.getElementById('essayLabelPrimary').textContent = `${student.student_id} • Rank ${student.rank}`;
  renderEssayTo('essay', student.text || '');
  const compareIndex = getCompareIndex();
  const comparePanel = document.getElementById('comparePanel');
  const splitView = document.body.dataset.view === 'split';
  if (!splitView || compareIndex === null) {
    comparePanel.style.display = 'none';
  } else {
    comparePanel.style.display = '';
    const compare = data.students[compareIndex];
    document.getElementById('essayLabelCompare').textContent = `${compare.student_id} • Rank ${compare.rank}`;
    renderEssayTo('essayCompare', compare.text || '');
    comparePanel.onclick = () => scrollToIndex(compareIndex, true);
  }
  renderFeedback(student);
  const gradeInput = document.getElementById('gradeOverride');
  const override = overrides[student.student_id];
  gradeInput.value = override !== undefined ? override : getGradeForIndex(currentIndex);
}
function applyAdjustment(studentId, key, delta) { const adj = getAdjustment(studentId); adj[key] += delta; updateRail(); renderDetail(); }
function updateGradesFromCurve() { if (!data || !data.students || !data.students.length) return; const top = num(document.getElementById('topGrade').value, 92); const bottom = num(document.getElementById('bottomGrade').value, 58); if (top <= bottom) return; grades = computeGrades(top, bottom, data.students.length); updateRail(); renderDetail(); }
function setRunning(on) { running = on; document.body.dataset.running = on ? 'true' : 'false'; }
function pipelineLog(msg) { const log = document.getElementById('pipelineLog'); if (!log) return; const line = document.createElement('div'); line.textContent = msg; log.appendChild(line); log.scrollTop = log.scrollHeight; }
function startPipelineNarrative() { const log = document.getElementById('pipelineLog'); if (log) log.innerHTML = ''; const steps = ['Getting your files ready and organized…', "In this first pass, we’re conducting an initial assessment based on the rubric.", 'Next, we compare essays side‑by‑side to keep the ordering consistent.', 'Now we scan conventions: spelling, grammar, sentence structure, and format.', 'We’re integrating all signals into a final, coherent ordering.', 'Building the teacher review dashboard…']; pipelineStep = 0; pipelineLog(steps[0]); pipelineTimer = setInterval(() => { pipelineStep += 1; if (pipelineStep < steps.length) pipelineLog(steps[pipelineStep]); }, 2400); }
function stopPipelineNarrative(msg) { if (msg) pipelineLog(msg); if (pipelineTimer) clearInterval(pipelineTimer); pipelineTimer = null; setTimeout(() => setRunning(false), 2000); }
function startShuffle() { if (shuffleTimer || !previewStudents.length) return; shuffleTimer = setInterval(() => { if (previewStudents.length < 2) return; const i = Math.floor(Math.random() * (previewStudents.length - 1)); const t = previewStudents[i]; previewStudents[i] = previewStudents[i + 1]; previewStudents[i + 1] = t; previewStudents.forEach((s, idx) => { s.rank = idx + 1; }); renderRail(true); }, 900); }
function stopShuffle() { if (shuffleTimer) clearInterval(shuffleTimer); shuffleTimer = null; }
function updatePreviewFromUploads() { const essays = document.getElementById('uploadEssays'); if (!essays || !essays.files || !essays.files.length) return; previewStudents = Array.from(essays.files).map((f, idx) => ({ student_id: baseName(f.name), rank: idx + 1, text: '' })); currentIndex = 0; renderRail(true); }
async function runPipeline() {
  const status = document.getElementById('pipelineStatus'); if (!status) return;
  const essays = document.getElementById('uploadEssays'); const rubric = document.getElementById('uploadRubric'); const outline = document.getElementById('uploadOutline');
  if (!rubric?.files?.[0] || !outline?.files?.[0] || !essays?.files?.length) { status.textContent = 'Add essays, rubric, outline'; return; }
  if (!previewStudents.length) updatePreviewFromUploads();
  status.textContent = 'Checking connection...'; let mode = '';
  try { const [cRes, aRes] = await Promise.all([fetch(apiUrl('/codex/status')), fetch(apiUrl('/auth/status'))]); const c = cRes.ok ? await cRes.json() : null; const a = aRes.ok ? await aRes.json() : null; mode = c && c.connected ? 'codex_local' : (a && a.connected ? 'openai' : ''); } catch (err) { status.textContent = 'Offline'; return; }
  if (!mode) { status.textContent = 'Connect Codex or API key'; return; }
  const form = new FormData(); form.append('rubric', rubric.files[0]); form.append('outline', outline.files[0]); Array.from(essays.files).forEach(f => form.append('submissions', f)); form.append('mode', mode);
  status.textContent = 'Running...'; setRunning(true); startPipelineNarrative(); startShuffle();
  try { const res = await fetch(apiUrl('/pipeline/run'), { method: 'POST', body: form }); if (!res.ok) { let msg = 'Run failed'; try { const err = await res.json(); if (err.detail) msg = `Run failed: ${err.detail}`; } catch (_) {} status.textContent = msg; stopShuffle(); stopPipelineNarrative(msg); return; } status.textContent = 'Complete'; stopShuffle(); stopPipelineNarrative('Done. Opening your dashboard…'); setTimeout(() => location.reload(), 800); } catch (err) { status.textContent = 'Offline'; stopShuffle(); stopPipelineNarrative('Connection lost.'); }
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
    });
    input.addEventListener('change', () => {
      zone.querySelector('span').textContent = `${input.files.length} file(s) selected`;
      if (input.id === 'uploadEssays') updatePreviewFromUploads();
    });
  });
}
function setupControls() {
  document.getElementById('prevBtn').addEventListener('click', () => {
    if (currentIndex > 0) scrollToIndex(currentIndex - 1, true);
  });
  document.getElementById('nextBtn').addEventListener('click', () => {
    if (currentIndex < data.students.length - 1) scrollToIndex(currentIndex + 1, true);
  });
  document.getElementById('topGrade').addEventListener('input', updateGradesFromCurve);
  document.getElementById('bottomGrade').addEventListener('input', updateGradesFromCurve);
  document.getElementById('gradeOverride').addEventListener('change', (e) => {
    const value = e.target.value.trim(); const studentId = data.students[currentIndex].student_id;
    if (!value) delete overrides[studentId]; else overrides[studentId] = clamp(num(value, 0), 0, 100);
    updateRail(); renderDetail();
  });
  document.getElementById('copyFeedback').addEventListener('click', () => {
    const student = data.students[currentIndex]; const draft = feedbackForStudent(student.student_id, student.feedback_text || '');
    const payload = [`Two Stars and a Wish — ${student.student_id}`, `Star 1: ${draft.star1 || '—'}`, `Star 2: ${draft.star2 || '—'}`, `Wish: ${draft.wish || '—'}`].join('\n'); navigator.clipboard.writeText(payload);
  });
  document.getElementById('themeToggle').addEventListener('click', () => { const body = document.body; body.dataset.theme = body.dataset.theme === 'dark' ? 'light' : 'dark'; });
  const connectBtn = document.getElementById('connectKey');
  if (connectBtn) connectBtn.addEventListener('click', connectApiKey);
  const codexBtn = document.getElementById('codexLogin');
  if (codexBtn) codexBtn.addEventListener('click', startCodexLogin);
  const runBtn = document.getElementById('runPipeline');
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
    viewToggle.textContent = body.dataset.view === 'split' ? 'Single' : 'Split';
    renderDetail();
  });
  document.getElementById('railScroll').addEventListener('scroll', updateFromScroll);
  setupUploads();
  loadProjects();
  const saveBtn = document.getElementById('saveProject'); if (saveBtn) saveBtn.addEventListener('click', saveProject);
  const newBtn = document.getElementById('newProject'); if (newBtn) newBtn.addEventListener('click', newProject);
  const clearBtn = document.getElementById('clearProject'); if (clearBtn) clearBtn.addEventListener('click', clearProject);
  const loadBtn = document.getElementById('loadProject'); if (loadBtn) loadBtn.addEventListener('click', loadProject);
  const delBtn = document.getElementById('deleteProject'); if (delBtn) delBtn.addEventListener('click', deleteProject);
}
async function boot(payload) {
  data = payload;
  if (!data.students) data.students = [];
  data.students.sort((a, b) => a.rank - b.rank);
  if (data.class_metadata && data.class_metadata.grade_level) {
    const title = document.querySelector('.brand h1');
    title.textContent = `Hero Path • Grade ${data.class_metadata.grade_level}`;
  }
  if (data.curve_top) document.getElementById('topGrade').value = data.curve_top;
  if (data.curve_bottom) document.getElementById('bottomGrade').value = data.curve_bottom;
  grades = computeGrades(num(document.getElementById('topGrade').value, 92), num(document.getElementById('bottomGrade').value, 58), data.students.length);
  document.getElementById('viewToggle').textContent = document.body.dataset.view === 'split' ? 'Single' : 'Split';
  await detectApiBase();
  setupControls();
  renderRail();
  scrollToIndex(0, false);
  refreshAuthStatus();
}

fetch(`/data.json?t=${Date.now()}`, { cache: 'no-store' })
  .then(res => res.ok ? res.text() : '')
  .then(text => { try { return text ? JSON.parse(text) : { students: [] }; } catch (_) { return { students: [] }; } })
  .then(payload => boot(payload))
  .catch(err => { console.error(err); return boot({ students: [] }); });
