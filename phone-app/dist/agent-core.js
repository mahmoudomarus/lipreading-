export function actionLabel(a) {
  if (a.name === 'save_note') return 'Save note: ' + a.text;
  if (a.name === 'start_timer')
    return 'Start ' + a.seconds + 's timer' + (a.text ? ' · ' + a.text : '');
  if (a.name === 'calculate') return 'Calculate ' + a.expression;
  return a.name === 'list_notes' ? 'Read saved notes' : 'Read timers';
}
export function receiptText(r) {
  if (r.tool === 'save_note') return 'Note saved · ' + r.result.saved;
  if (r.tool === 'start_timer')
    return 'Timer started · ' + r.result.label + ' · ' + r.result.seconds + 's';
  if (r.tool === 'calculate') return r.result.expression + ' = ' + r.result.value;
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
  if (job.state === 'failed') return job.error;
  if (job.state === 'cancelled') return 'Request cancelled';
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
  return [...merged.values()].sort((a, b) => a.created - b.created).slice(-30);
}
