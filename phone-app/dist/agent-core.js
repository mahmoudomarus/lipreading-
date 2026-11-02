export function actionLabel(a) {
  if (a.name === 'save_note') return 'Save note: ' + a.text;
  if (a.name === 'start_timer')
    return 'Start ' + a.seconds + 's timer' + (a.text ? ' · ' + a.text : '');
  if (a.name === 'calculate') return 'Calculate ' + a.expression;
  if (a.name === 'list_notes') return 'Read saved notes';
  if (a.name === 'list_timers') return 'Read timers';
  if (a.name === 'research') return 'Research: ' + a.text;
  if (a.name === 'open_page') return 'Open page preview: ' + a.text;
  if (a.name === 'draft_document')
    return 'Create document: ' + (a.text?.split('\n')[0].replace(/^#+\s*/, '') || 'Draft');
  return 'Unknown action: ' + a.name;
}
export function receiptText(r) {
  if (r.tool === 'save_note') return 'Note saved · ' + r.result.saved;
  if (r.tool === 'start_timer')
    return 'Timer started · ' + r.result.label + ' · ' + r.result.seconds + 's';
  if (r.tool === 'calculate') return r.result.expression + ' = ' + r.result.value;
  if (r.tool === 'research') return r.result.text;
  if (r.tool === 'open_page') return 'Page ready · ' + r.result.title;
  if (r.tool === 'draft_document') return 'Draft ready · ' + r.result.title;
  if (r.tool === 'list_notes')
    return r.result.map((n) => n.text).join('\n') || 'No saved notes yet.';
  return (
    r.result.map((t) => t.label + (t.elapsed ? ' · elapsed' : ' · running')).join('\n') ||
    'No timers yet.'
  );
}
export function agentSummary(job) {
  if (!job) return '';
  if (job.state === 'queued') return 'Request queued';
  if (job.state === 'thinking') return 'Thinking…';
  if (job.state === 'researching') return 'Researching · checking live sources…';
  if (job.state === 'failed') return job.error;
  if (job.state === 'cancelled') return 'Request cancelled';
  if (job.state === 'dismissed') return 'Misread ignored · continue speaking';
  if (job.state === 'review')
    return 'Awaiting confirmation · ' + job.plan.actions.map(actionLabel).join(' / ');
  return job.result?.length ? job.result.map(receiptText).join('\n') : job.plan?.answer || '';
}

// A slow poll must not erase a just-submitted turn or roll a receipt back to thinking.
export function mergeJobs(current, incoming) {
  const merged = new Map(current.map((job) => [job.id, job]));
  for (const job of incoming) {
    const old = merged.get(job.id);
    if (!old || job.updated >= old.updated) merged.set(job.id, job);
  }
  const ordered = [...merged.values()].sort((a, b) => a.created - b.created);
  const history = new Set(
    ordered
      .filter((job) => !jobCanCancel(job))
      .slice(-30)
      .map((job) => job.id),
  );
  return ordered.filter((job) => jobCanCancel(job) || history.has(job.id));
}

export function jobCanCancel(job) {
  return ['queued', 'thinking', 'researching', 'review'].includes(job.state);
}

export function backgroundStatus(jobs) {
  const running = jobs.filter((job) => ['thinking', 'researching'].includes(job.state)).length;
  const queued = jobs.filter((job) => job.state === 'queued').length;
  const review = jobs.filter((job) => job.state === 'review').length;
  const parts = [];
  if (running) parts.push(running + (running === 1 ? ' task running' : ' tasks running'));
  if (queued) parts.push(queued + ' queued');
  if (review) parts.push(review + ' awaiting confirmation');
  return {
    active: running + queued + review,
    running,
    queued,
    review,
    text: parts.join(' · ') || 'Your turn',
  };
}

// Only a job this page saw unfinished counts as a new reply; reloaded history stays quiet.
export function newlyCompleted(before, after) {
  const previous = new Map(before.map((job) => [job.id, job.state]));
  return after.filter(
    (job) =>
      job.state === 'completed' && previous.has(job.id) && previous.get(job.id) !== 'completed',
  );
}

// The voice endpoint accepts up to 360 characters, so speak whole leading sentences.
export function spokenText(job, limit = 360) {
  const text = agentSummary(job).replace(/\s+/g, ' ').trim();
  if (text.length <= limit) return text;
  let spoken = '';
  for (const sentence of text.match(/[^.!?]+[.!?]+/g) || []) {
    if ((spoken + sentence).trim().length > limit) break;
    spoken += sentence;
  }
  return spoken.trim() || text.slice(0, limit - 1).replace(/\s+\S*$/, '') + '…';
}
