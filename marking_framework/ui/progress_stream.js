(() => {
  if (typeof waitForJob !== 'function') return;

  const stageNames = {
    queued: 'Queued',
    extract: 'Extracting text',
    conventions: 'Scanning conventions',
    calibrate: 'Calibrating assessors',
    assess: 'Running assessor passes',
    cost: 'Tracking API cost',
    aggregate_1: 'Building initial consensus',
    boundary: 'Rechecking boundary essays',
    aggregate_2: 'Rebuilding consensus',
    consistency: 'Verifying order consistency',
    quality_gate: 'Running publish quality gate',
    sota_gate: 'Enforcing SOTA readiness gate',
    pairwise: 'Preparing pairwise review',
    dashboard: 'Building dashboard',
    completed: 'Complete',
  };

  let eventCursor = -1;
  let lastEventKey = '';
  let latestCost = '';

  function clearNarrativeTimer() {
    if (typeof pipelineTimer !== 'undefined' && pipelineTimer) {
      clearInterval(pipelineTimer);
      pipelineTimer = null;
    }
  }

  function setPipelineStatus(text) {
    const status = document.getElementById('pipelineStatus');
    if (status) status.textContent = text;
  }

  function trimLog(maxLines = 220) {
    const log = document.getElementById('pipelineLog');
    if (!log) return;
    while (log.children.length > maxLines) log.removeChild(log.firstChild);
  }

  function appendLine(message) {
    if (!message || typeof pipelineLog !== 'function') return;
    pipelineLog(message);
    trimLog();
  }

  function stageText(job) {
    const stage = (job && job.progress_stage) ? job.progress_stage : '';
    const msg = (job && job.progress_message) ? job.progress_message : '';
    if (msg) return msg;
    if (stage && stageNames[stage]) return stageNames[stage];
    return 'Working';
  }

  function progressText(job) {
    const current = Number((job && job.progress_current) || 0);
    const total = Number((job && job.progress_total) || 0);
    return total > 0 ? `${current}/${total}` : '…';
  }

  function elapsedText(job) {
    const createdAt = job && job.created_at ? Date.parse(job.created_at) : NaN;
    const updatedAt = job && job.updated_at ? Date.parse(job.updated_at) : NaN;
    const end = job && job.status === 'completed' && Number.isFinite(updatedAt) ? updatedAt : Date.now();
    if (!Number.isFinite(createdAt) || end <= createdAt) return '';
    const totalSec = Math.max(0, Math.round((end - createdAt) / 1000));
    const min = Math.floor(totalSec / 60);
    const sec = totalSec % 60;
    return `${min}m ${String(sec).padStart(2, '0')}s`;
  }

  function statusText(job) {
    const parts = [`Running ${progressText(job)}`, stageText(job)];
    const elapsed = elapsedText(job);
    if (elapsed) parts.push(elapsed);
    if (latestCost) parts.push(latestCost);
    return parts.join(' • ');
  }

  function eventLine(evt) {
    const stage = evt && evt.stage ? evt.stage : '';
    const source = evt && evt.source ? evt.source : 'system';
    const message = evt && evt.message ? String(evt.message) : '';
    if (!message) return '';
    const stageLabel = stageNames[stage] || stage || 'Pipeline';
    if (source === 'stderr') return `[${stageLabel}] ${message}`;
    return `[${stageLabel}] ${message}`;
  }

  async function fetchEvents(jobId) {
    const res = await fetch(
      apiUrl(`/pipeline/v2/jobs/${jobId}/events?after=${eventCursor}&limit=150`),
      { cache: 'no-store' },
    );
    if (!res.ok) return null;
    const payload = await res.json();
    const events = Array.isArray(payload.events) ? payload.events : [];
    for (const evt of events) {
      if (typeof evt.index === 'number') eventCursor = Math.max(eventCursor, evt.index);
      const line = eventLine(evt);
      if (!line) continue;
      const key = `${evt.index || 0}:${line}`;
      if (key === lastEventKey) continue;
      lastEventKey = key;
      const costMatch = line.match(/\$[0-9]+(?:\.[0-9]{2,6})?/);
      if (costMatch && line.toLowerCase().includes('cost')) latestCost = costMatch[0];
      appendLine(line);
    }
    if (typeof payload.next_after === 'number') {
      eventCursor = Math.max(eventCursor, payload.next_after);
    }
    return payload;
  }

  startPipelineNarrative = function startPipelineNarrativeReal() {
    clearNarrativeTimer();
    eventCursor = -1;
    lastEventKey = '';
    latestCost = '';
    const log = document.getElementById('pipelineLog');
    if (log) log.innerHTML = '';
    appendLine('Pipeline started. Preparing files and checks…');
  };

  stopPipelineNarrative = function stopPipelineNarrativeReal(msg) {
    clearNarrativeTimer();
    if (msg) appendLine(msg);
    setTimeout(() => {
      if (typeof setRunning === 'function') setRunning(false);
    }, 800);
  };

  waitForJob = async function waitForJobReal(jobId) {
    const start = Date.now();
    while (Date.now() - start < 45 * 60 * 1000) {
      const statusRes = await fetch(apiUrl(`/pipeline/v2/jobs/${jobId}`), { cache: 'no-store' });
      if (!statusRes.ok) throw new Error('Run status unavailable');
      const job = await statusRes.json();
      setPipelineStatus(statusText(job));
      await fetchEvents(jobId);
      if (job.status === 'completed') {
        const elapsed = elapsedText(job);
        setPipelineStatus(elapsed ? `Complete • ${elapsed}${latestCost ? ` • ${latestCost}` : ''}` : 'Complete');
        await fetchEvents(jobId);
        return job;
      }
      if (job.status === 'failed') {
        setPipelineStatus(`Run failed • ${stageText(job)}`);
        await fetchEvents(jobId);
        throw new Error(job.error || 'Run failed');
      }
      if (typeof sleep === 'function') await sleep(900);
      else await new Promise(resolve => setTimeout(resolve, 900));
    }
    throw new Error('Run timed out');
  };
})();
