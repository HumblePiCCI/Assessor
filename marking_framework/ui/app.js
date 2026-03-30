let data = null, currentIndex = 0, grades = [], overrides = {}, adjustments = {}, feedbackDrafts = {}, reviewBundle = null, reviewStudents = {}, reviewPairs = {}, scrollTicking = false, compareDirection = 1, previewStudents = [], running = false, shuffleTimer = null, pipelineTimer = null, pipelineStep = 0, projects = [], currentProject = null, sliderStudentId = null, focusLock = false;
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
async function refreshAuthStatus() { const status = document.getElementById('authStatus'); if (!status) return; const codexBtn = document.getElementById('codexLogin'); try { const [codexRes, apiRes] = await Promise.all([fetch(apiUrl('/codex/status')), fetch(apiUrl('/auth/status'))]); const codex = codexRes.ok ? await codexRes.json() : null; const api = apiRes.ok ? await apiRes.json() : null; if (codex && codex.available && codex.connected) { status.textContent = 'Codex connected'; if (codexBtn) { codexBtn.disabled = true; codexBtn.textContent = 'Codex connected'; } } else if (api && api.connected) { status.textContent = 'API key connected'; if (codexBtn) { codexBtn.disabled = false; codexBtn.textContent = 'Sign in with Codex'; } } else if (codex && codex.available) { status.textContent = 'Codex not connected'; if (codexBtn) { codexBtn.disabled = false; codexBtn.textContent = 'Sign in with Codex'; } } else { status.textContent = 'Offline'; if (codexBtn) { codexBtn.disabled = false; codexBtn.textContent = 'Sign in with Codex'; } } } catch (err) { status.textContent = 'Offline'; if (codexBtn) { codexBtn.disabled = false; codexBtn.textContent = 'Sign in with Codex'; } } }
async function connectApiKey() { const input = document.getElementById('apiKeyInput'); const status = document.getElementById('authStatus'); if (!input || !status) return; const key = input.value.trim(); if (!key) return; try { const res = await fetch(apiUrl('/auth'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ api_key: key }) }); if (!res.ok) { status.textContent = 'Invalid key'; return; } input.value = ''; status.textContent = 'API key connected'; } catch (err) { status.textContent = 'Offline'; } }
async function startCodexLogin() { const status = document.getElementById('authStatus'); if (!status) return; try { const res = await fetch(apiUrl('/codex/login'), { method: 'POST' }); if (!res.ok) { let msg = 'Codex login failed'; try { const err = await res.json(); if (err.detail) msg = err.detail; } catch (_) {} status.textContent = msg; return; } const payload = await res.json().catch(() => ({})); status.textContent = payload.status === 'already_connected' ? 'Codex connected' : 'Codex login started'; setTimeout(refreshAuthStatus, 1500); } catch (err) { status.textContent = 'Offline'; } }
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
  reviewBundle = null;
  reviewStudents = {};
  reviewPairs = {};
  grades = [];
  currentIndex = 0; sliderStudentId = null; focusLock = false;
  resetUploadLabels();
  const status = document.getElementById('pipelineStatus'); if (status) status.textContent = 'Idle';
  renderRail(); renderDetail();
}
async function clearProject() { if (!confirm('Clear the current session?')) return; clearLocalState(); const status = document.getElementById('projectStatus'); if (status) status.textContent = 'Clearing session...'; try { const res = await fetch(apiUrl('/projects/clear'), { method: 'POST' }); if (!res.ok) throw new Error('clear failed'); await loadProjects(); location.href = `${location.pathname}?t=${Date.now()}`; } catch (_) { if (status) status.textContent = 'Server unavailable: local view cleared only'; } }
async function loadProject() { const select = document.getElementById('projectSelect'); if (!select || !select.value) return; try { const res = await fetch(apiUrl('/projects/load'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: select.value }) }); if (!res.ok) return; location.reload(); } catch (_) {} }
async function deleteProject() { const select = document.getElementById('projectSelect'); if (!select || !select.value) return; if (!confirm('Delete this project?')) return; try { const res = await fetch(apiUrl(`/projects/${select.value}`), { method: 'DELETE' }); if (!res.ok) return; await loadProjects(); } catch (_) {} }
function ensureReviewPanel() {
  let section = document.getElementById('reviewSection');
  if (section) return section;
  const actions = document.getElementById('actions');
  if (!actions) return null;
  section = document.createElement('div');
  section.id = 'reviewSection';
  section.className = 'auth review-section';
  section.innerHTML = `
    <div class="label">Review Learning</div>
    <div id="reviewUncertainty" class="review-flags"></div>
    <div class="controls">
      <div class="control">
        <label for="reviewLevelOverride">Level override</label>
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
      <div class="control">
        <label for="reviewEvidenceComment">Evidence comment or justification</label>
        <textarea id="reviewEvidenceComment" rows="4" placeholder="Why you changed the level, rank, or pairwise order."></textarea>
      </div>
    </div>
    <div class="review-pairwise">
      <div class="label">Pairwise adjudication</div>
      <div class="project-actions">
        <button id="preferCurrent" class="ghost">Current above compare</button>
        <button id="preferCompare" class="ghost">Compare above current</button>
        <button id="clearPairwise" class="ghost">Clear pair</button>
      </div>
      <div class="auth-status" id="pairwiseStatus">Open split view to compare two essays.</div>
    </div>
    <div class="project-actions">
      <button id="saveReview" class="ghost">Save review signal</button>
    </div>
    <div id="reviewStatus" class="auth-status">No persisted review yet.</div>
    <div id="learningSummary" class="auth-status">Local profile unavailable.</div>
  `;
  const auth = actions.querySelector('.auth');
  if (auth) actions.insertBefore(section, auth);
  else actions.appendChild(section);
  return section;
}
function applyReviewBundle(bundle) {
  reviewBundle = bundle || null;
  reviewStudents = {};
  reviewPairs = {};
  const latest = (bundle && bundle.latest_review) ? bundle.latest_review : {};
  (latest.students || []).forEach(item => {
    reviewStudents[item.student_id] = {
      student_id: item.student_id,
      level_override: item.level_override || '',
      desired_rank: item.desired_rank ?? '',
      evidence_quality: item.evidence_quality || '',
      evidence_comment: item.evidence_comment || '',
    };
  });
  (latest.pairwise || []).forEach(item => {
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
    reviewStatus.textContent = savedAt ? `Latest review saved ${savedAt}` : 'No persisted review yet.';
  }
  const learningSummary = document.getElementById('learningSummary');
  if (learningSummary) {
    const profile = (bundle && bundle.local_learning_profile) ? bundle.local_learning_profile : {};
    const replay = (bundle && bundle.replay_exports) ? bundle.replay_exports : {};
    const anon = (bundle && bundle.anonymized_aggregate) ? bundle.anonymized_aggregate : {};
    learningSummary.textContent = `Local profile: ${profile.review_count || 0} reviews, ${profile.student_review_count || 0} student decisions, ${profile.pairwise_adjudication_count || 0} pairwise adjudications. Replay exports: ${replay.benchmark_gold_count || 0} benchmark rows, ${replay.calibration_exemplars_count || 0} exemplar candidates. Anonymous aggregate: ${anon.record_count || 0} records.`;
  }
}
async function loadReviewBundle() {
  ensureReviewPanel();
  try {
    const res = await fetch(apiUrl('/projects/review'));
    if (!res.ok) return;
    applyReviewBundle(await res.json());
  } catch (_) {}
}
function renderReviewPanel(student) {
  ensureReviewPanel();
  const uncertainty = document.getElementById('reviewUncertainty');
  const level = document.getElementById('reviewLevelOverride');
  const desiredRank = document.getElementById('reviewDesiredRank');
  const quality = document.getElementById('reviewEvidenceQuality');
  const comment = document.getElementById('reviewEvidenceComment');
  const pairStatus = document.getElementById('pairwiseStatus');
  if (!uncertainty || !level || !desiredRank || !quality || !comment || !pairStatus) return;
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
    pairStatus.textContent = 'Open split view to record a pairwise adjudication.';
  } else {
    const compare = data.students[compareIndex];
    const pair = reviewPairs[pairKey(student.student_id, compare.student_id)];
    const preferred = pair && pair.preferred_student_id ? labelFor(data.students.find(item => item.student_id === pair.preferred_student_id) || { student_id: pair.preferred_student_id }) : 'none saved';
    pairStatus.textContent = `Comparing with ${labelFor(compare)}. Saved pairwise preference: ${preferred}.`;
  }
}
async function saveReviewBundle() {
  const reviewStatus = document.getElementById('reviewStatus');
  if (reviewStatus) reviewStatus.textContent = 'Saving review signal...';
  const students = Object.values(reviewStudents).filter(item => item.level_override || item.evidence_quality || item.evidence_comment || item.desired_rank !== '');
  const pairwise = Object.values(reviewPairs).filter(item => item.preferred_student_id);
  try {
    const res = await fetch(apiUrl('/projects/review'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ students, pairwise }),
    });
    if (!res.ok) throw new Error('save failed');
    applyReviewBundle(await res.json());
    if (data?.students?.length) renderReviewPanel(data.students[currentIndex]);
  } catch (_) {
    if (reviewStatus) reviewStatus.textContent = 'Failed to save review signal.';
  }
}
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
  const adj = getAdjustment(student.student_id);
  const rows = [
    { key: 'overall', label: 'Overall grade', value: getGradeForIndex(currentIndex), adjustable: true },
    { key: 'rubric', label: 'Rubric score', value: num(student.rubric_mean_percent), adjustable: true },
    { key: 'conventions', label: 'Conventions %', value: num(student.conventions_mistake_rate_percent), adjustable: true },
    { key: 'comparative', label: 'Comparative', value: num(student.borda_points), adjustable: true },
    { key: 'composite', label: 'Composite', value: num(student.composite_score), adjustable: false },
    { key: 'level', label: 'Level', value: student.level_with_modifier || student.adjusted_level || '', adjustable: false },
    { key: 'uncertainty', label: 'Uncertainty', value: (student.uncertainty_flags || []).join(', ') || '—', adjustable: false },
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
    renderReviewPanel(null);
    return;
	}
	const student = data.students[currentIndex];
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
}
function applyAdjustment(studentId, key, delta) { const sidx = Math.max(0, data?.students?.findIndex(s => s.student_id === studentId) ?? 0); currentIndex = sidx; const adj = getAdjustment(studentId); adj[key] += delta; const target = key === 'overall' && data?.students?.length ? getGradeForIndex(sidx) : null; if (data?.students?.length && window.gradeAdjust?.resort) { focusLock = true; for (let i = 0; i < 3; i += 1) { window.gradeAdjust.resort(data.students, getGradeForIndex); currentIndex = Math.max(0, data.students.findIndex(s => s.student_id === studentId)); if (target === null) break; const diff = target - getGradeForIndex(currentIndex); if (Math.abs(diff) < 0.5) break; adj.overall += diff; } renderRail(true); scrollToIndex(currentIndex, false); focusLock = false; return; } updateRail(); renderDetail(); }
function applyOverallTarget(target) { if (!data?.students?.length) return; const sid = sliderStudentId || data.students[currentIndex]?.student_id; const s = data.students.find(x => x.student_id === sid) || data.students[currentIndex]; currentIndex = Math.max(0, data.students.findIndex(x => x.student_id === s.student_id)); const curr = getGradeForIndex(currentIndex); const delta = target - curr; const adj = getAdjustment(s.student_id); const spread = (window.gradeAdjust && window.gradeAdjust.distribute) ? window.gradeAdjust.distribute(s, delta) : { rubric: delta * 0.7, conventions: delta * 0.15, comparative: delta * 0.15 }; adj.rubric += num(spread.rubric, 0); adj.conventions += num(spread.conventions, 0); adj.comparative += num(spread.comparative, 0); adj.overall += delta; delete overrides[s.student_id]; const inp = document.getElementById('gradeOverride'); if (inp) inp.value = Math.round(target); const slider = document.getElementById('overallGradeSlider'); if (slider) slider.value = Math.round(target); if (window.gradeAdjust?.resort) { focusLock = true; for (let i = 0; i < 3; i += 1) { window.gradeAdjust.resort(data.students, getGradeForIndex); currentIndex = Math.max(0, data.students.findIndex(x => x.student_id === s.student_id)); const diff = target - getGradeForIndex(currentIndex); if (Math.abs(diff) < 0.5) break; adj.overall += diff; } renderRail(true); scrollToIndex(currentIndex, false); focusLock = false; return; } updateRail(); renderDetail(); }
function generateFeedbackDrafts() { if (!data?.students?.length || !window.feedbackGenerate?.generateAll) return; window.feedbackGenerate.generateAll(data.students, getGradeForIndex, adjustments, feedbackDrafts, true); renderDetail(); }
function updateGradesFromCurve() { if (!data || !data.students || !data.students.length) return; const top = num(document.getElementById('topGrade').value, 92); const bottom = num(document.getElementById('bottomGrade').value, 58); if (top <= bottom) return; grades = computeGrades(top, bottom, data.students.length); updateRail(); renderDetail(); }
function setRunning(on) { running = on; document.body.dataset.running = on ? 'true' : 'false'; }
function pipelineLog(msg) { const log = document.getElementById('pipelineLog'); if (!log) return; const line = document.createElement('div'); line.textContent = msg; log.appendChild(line); log.scrollTop = log.scrollHeight; }
function startPipelineNarrative() { const log = document.getElementById('pipelineLog'); if (log) log.innerHTML = ''; const steps = ['Getting your files ready and organized…', "In this first pass, we’re conducting an initial assessment based on the rubric.", 'Next, we compare essays side‑by‑side to keep the ordering consistent.', 'Now we scan conventions: spelling, grammar, sentence structure, and format.', 'We’re integrating all signals into a final, coherent ordering.', 'Building the teacher review dashboard…']; pipelineStep = 0; pipelineLog(steps[0]); pipelineTimer = setInterval(() => { pipelineStep += 1; if (pipelineStep < steps.length) pipelineLog(steps[pipelineStep]); }, 2400); }
function stopPipelineNarrative(msg) { if (msg) pipelineLog(msg); if (pipelineTimer) clearInterval(pipelineTimer); pipelineTimer = null; setTimeout(() => setRunning(false), 2000); }
function startShuffle() { if (shuffleTimer || !previewStudents.length) return; shuffleTimer = setInterval(() => { if (previewStudents.length < 2) return; const i = Math.floor(Math.random() * (previewStudents.length - 1)); const t = previewStudents[i]; previewStudents[i] = previewStudents[i + 1]; previewStudents[i + 1] = t; previewStudents.forEach((s, idx) => { s.rank = idx + 1; }); renderRail(true); }, 900); }
function stopShuffle() { if (shuffleTimer) clearInterval(shuffleTimer); shuffleTimer = null; }
function updatePreviewFromUploads() { const essays = document.getElementById('uploadEssays'); if (!essays || !essays.files || !essays.files.length) return; previewStudents = Array.from(essays.files).map((f, idx) => ({ student_id: baseName(f.name), rank: idx + 1, text: '' })); currentIndex = 0; renderRail(true); }
async function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
async function waitForJob(jobId) { const start = Date.now(); while (Date.now() - start < 45 * 60 * 1000) { const res = await fetch(apiUrl(`/pipeline/v2/jobs/${jobId}`)); if (!res.ok) throw new Error('Run status unavailable'); const job = await res.json(); if (job.status === 'completed') return job; if (job.status === 'failed') throw new Error(job.error || 'Run failed'); await sleep(2000); } throw new Error('Run timed out'); }
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
  try { const res = await fetch(apiUrl('/pipeline/v2/run'), { method: 'POST', body: form }); if (!res.ok) { let msg = 'Run failed'; try { const err = await res.json(); if (err.detail) msg = `Run failed: ${err.detail}`; } catch (_) {} status.textContent = msg; stopShuffle(); stopPipelineNarrative(msg); return; } const submit = await res.json(); if (submit.cached) pipelineLog('Identical inputs found; using cached assessment.'); const jobId = submit.job_id; const job = submit.status === 'completed' ? submit : await waitForJob(jobId); const dataRes = await fetch(apiUrl(`/pipeline/v2/jobs/${job.id || jobId}/data`)); if (!dataRes.ok) throw new Error('Dashboard data unavailable'); previewStudents = []; await boot(await dataRes.json()); status.textContent = 'Complete'; stopShuffle(); stopPipelineNarrative('Done. Review is ready.'); } catch (err) { const msg = `Run failed: ${err.message || 'connection lost'}`; status.textContent = msg; stopShuffle(); stopPipelineNarrative(msg); }
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
  if (window.__heroControlsBound) return; window.__heroControlsBound = true;
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
    const student = data.students[currentIndex]; const draft = feedbackForStudent(student.student_id, student.feedback_text || '');
    const payload = [`Two Stars and a Wish — ${student.student_id}`, `Star 1: ${draft.star1 || '—'}`, `Star 2: ${draft.star2 || '—'}`, `Wish: ${draft.wish || '—'}`].join('\n'); navigator.clipboard.writeText(payload);
  });
  const genBtn = document.getElementById('generateFeedback'); if (genBtn) genBtn.addEventListener('click', generateFeedbackDrafts);
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
  const reviewLevel = document.getElementById('reviewLevelOverride');
  const reviewRank = document.getElementById('reviewDesiredRank');
  const reviewQuality = document.getElementById('reviewEvidenceQuality');
  const reviewComment = document.getElementById('reviewEvidenceComment');
  const saveReview = document.getElementById('saveReview');
  const preferCurrent = document.getElementById('preferCurrent');
  const preferCompare = document.getElementById('preferCompare');
  const clearPairwise = document.getElementById('clearPairwise');
  if (reviewLevel) reviewLevel.addEventListener('change', e => { const student = data?.students?.[currentIndex]; if (!student) return; studentReview(student.student_id).level_override = e.target.value; });
  if (reviewRank) reviewRank.addEventListener('change', e => { const student = data?.students?.[currentIndex]; if (!student) return; studentReview(student.student_id).desired_rank = e.target.value.trim() ? parseInt(e.target.value, 10) : ''; });
  if (reviewQuality) reviewQuality.addEventListener('change', e => { const student = data?.students?.[currentIndex]; if (!student) return; studentReview(student.student_id).evidence_quality = e.target.value; });
  if (reviewComment) reviewComment.addEventListener('input', e => { const student = data?.students?.[currentIndex]; if (!student) return; studentReview(student.student_id).evidence_comment = e.target.value.trim(); });
  if (saveReview) saveReview.addEventListener('click', saveReviewBundle);
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
  await loadReviewBundle();
  renderRail();
  scrollToIndex(0, false);
  refreshAuthStatus();
}
fetch(`/data.json?t=${Date.now()}`, { cache: 'no-store' })
  .then(res => res.ok ? res.text() : '')
  .then(text => { try { return text ? JSON.parse(text) : { students: [] }; } catch (_) { return { students: [] }; } })
  .then(payload => boot(payload))
  .catch(err => { console.error(err); return boot({ students: [] }); });
