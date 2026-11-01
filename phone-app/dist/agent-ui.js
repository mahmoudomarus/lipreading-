import { actionLabel, receiptText } from './agent-core.js';

export function createAgentUI({ requestAPI, getLatest, onState, onSettings }) {
  const $ = (id) => document.getElementById(id);
  let jobs = [],
    timers = [],
    pollTimer,
    connected = false,
    dirty = false,
    source = 'typed',
    sending = false,
    pending = null,
    serverOffset = 0,
    signature = '';
  const composer = $('agent-request'),
    dialog = $('agent-review-dialog');
  function message(text) {
    $('agent-message').textContent = text;
  }
  function view(assistant = true) {
    document.querySelector('.transcript-panel').classList.toggle('assistant-view', assistant);
    $('assistant-tab').setAttribute('aria-pressed', String(assistant));
    $('captions-tab').setAttribute('aria-pressed', String(!assistant));
  }
  function fill(entry) {
    if (!entry) {
      message('Speak a phrase, or type a request.');
      return;
    }
    composer.value = entry.assist?.text || entry.text;
    source = 'reviewed_lips';
    dirty = false;
    pending = null;
    $('agent-source').textContent = 'PREDICTED WORDS · REVIEW BEFORE SENDING';
  }
  function review(entry, modal = false) {
    const latest = jobs.at(-1);
    if (modal && latest?.state === 'review') {
      $('agent-modal-source').textContent = 'Request: ' + latest.input;
      $('agent-modal-actions').textContent = latest.plan.actions.map(actionLabel).join('\n');
      $('agent-modal-actions').hidden = false;
      $('agent-modal-confirm').hidden = false;
      $('agent-modal-form').hidden = true;
      $('agent-modal-confirm').onclick = async () => {
        await operate(latest, 'confirm', $('agent-modal-confirm'));
        dialog.close();
      };
      $('agent-modal-confirm').disabled = false;
      dialog.showModal();
      return;
    }
    $('agent-modal-actions').hidden = $('agent-modal-confirm').hidden = true;
    $('agent-modal-form').hidden = false;
    fill(entry);
    view();
    if (modal) {
      $('agent-modal-request').value = composer.value;
      $('agent-modal-source').textContent =
        source === 'reviewed_lips'
          ? 'Review these predicted words. Edit any misread words.'
          : 'Type a request, or capture a phrase first.';
      dialog.showModal();
      $('agent-modal-request').focus();
    } else {
      composer.focus();
      if (innerWidth < 800)
        $('agent-panel').scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }
  composer.addEventListener('input', () => {
    dirty = true;
    pending = null;
  });
  $('assistant-tab').onclick = () => view();
  $('captions-tab').onclick = () => view(false);
  $('agent-use-latest').onclick = () => review(getLatest());
  $('agent-modal-close').onclick = () => dialog.close();
  async function submit(text) {
    if (sending) return;
    if (!text.trim()) {
      message('Review or type a request first.');
      return;
    }
    sending = true;
    $('agent-send').disabled = $('agent-modal-send').disabled = true;
    message('Sending reviewed words…');
    const fingerprint = source + '\0' + text.trim();
    if (!pending || pending.fingerprint !== fingerprint)
      pending = { fingerprint, id: crypto.randomUUID() };
    try {
      const r = await requestAPI('/api/agent/jobs', {
        body: { text: text.trim(), source, request_id: pending.id },
      });
      const job = await r.json();
      jobs = jobs.filter((j) => j.id !== job.id);
      jobs.push(job);
      render();
      onState(job);
      composer.value = '';
      source = 'typed';
      dirty = false;
      pending = null;
      $('agent-source').textContent = 'TYPE, OR REVIEW A CAPTION';
      message('Request received. You can keep the camera on.');
      dialog.close();
      connected = true;
      schedule(100);
    } catch (e) {
      message(e.message);
      $('agent-modal-source').textContent = e.message;
      if (/Connect a model/.test(e.message) && !dialog.open) onSettings();
    } finally {
      sending = false;
      $('agent-send').disabled = $('agent-modal-send').disabled = false;
    }
  }
  $('agent-form').onsubmit = (e) => {
    e.preventDefault();
    submit(composer.value);
  };
  $('agent-modal-form').onsubmit = (e) => {
    e.preventDefault();
    submit($('agent-modal-request').value);
  };
  function node(tag, className, text) {
    const el = document.createElement(tag);
    el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  async function operate(job, operation, button) {
    button.disabled = true;
    try {
      const r = await requestAPI('/api/agent/jobs/' + encodeURIComponent(job.id) + '/' + operation);
      const next = await r.json();
      jobs = jobs.map((j) => (j.id === next.id ? next : j));
      render();
      onState(next);
      schedule(100);
    } catch (e) {
      message(e.message);
      button.disabled = false;
    }
  }
  function render() {
    const feed = $('agent-feed'),
      nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80;
    const nextSignature = JSON.stringify(jobs);
    if (signature === nextSignature) return;
    signature = nextSignature;
    $('agent-welcome').hidden = jobs.length > 0;
    for (const el of feed.querySelectorAll('.agent-turn')) el.remove();
    for (const job of jobs) {
      const turn = node('article', 'agent-turn'),
        user = node('div', 'agent-user');
      user.append(
        node(
          'span',
          'turn-label',
          job.source === 'reviewed_lips' ? 'REVIEWED CAPTION' : 'TYPED REQUEST',
        ),
        node('p', '', job.input),
      );
      turn.append(user);
      const answer = node('div', 'agent-answer');
      answer.append(
        node(
          'span',
          'turn-label',
          job.state === 'review'
            ? 'ACTION PREVIEW'
            : job.state === 'completed'
              ? 'ASSISTANT'
              : 'AGENT · ' + job.state.toUpperCase(),
        ),
      );
      if (job.plan) {
        if (job.plan.answer) answer.append(node('p', '', job.plan.answer));
        if (job.state === 'review') {
          for (const action of job.plan.actions)
            answer.append(node('p', 'action-preview', actionLabel(action)));
          const controls = node('div', 'agent-confirmation'),
            confirm = node('button', '', 'Confirm actions ↗'),
            cancel = node('button', '', 'Cancel');
          confirm.onclick = () => operate(job, 'confirm', confirm);
          cancel.onclick = () => operate(job, 'cancel', cancel);
          controls.append(confirm, cancel);
          answer.append(controls);
        }
        for (const receipt of job.result || [])
          answer.append(node('p', 'tool-receipt', receiptText(receipt)));
      } else
        answer.append(
          node(
            'p',
            job.state === 'thinking' ? 'thinking' : '',
            job.error ||
              (job.state === 'thinking'
                ? 'Thinking…'
                : job.state === 'queued'
                  ? 'Waiting for the model…'
                  : job.state === 'cancelled'
                    ? 'Cancelled.'
                    : 'Working…'),
          ),
        );
      if (job.state === 'failed') {
        const retry = node('button', 'agent-retry', 'Edit and retry');
        retry.onclick = () => {
          composer.value = job.input;
          source = job.source;
          dirty = true;
          pending = null;
          composer.focus();
        };
        answer.append(retry);
      }
      if (job.state === 'completed')
        answer.append(
          node(
            'span',
            'job-latency',
            Math.max(0, job.updated - job.created).toFixed(1) + 's · request to completion',
          ),
        );
      turn.append(answer);
      feed.append(turn);
    }
    if (nearBottom) feed.scrollTop = feed.scrollHeight;
  }
  function renderTimers() {
    $('agent-timers').hidden = !timers.length;
    $('agent-timers').replaceChildren();
    const now = Date.now() / 1000 + serverOffset;
    for (const t of timers.slice(0, 3)) {
      const seconds = Math.max(0, Math.ceil(t.due - now));
      $('agent-timers').append(
        node(
          'span',
          seconds ? 'timer-chip' : 'timer-chip elapsed',
          t.label +
            ' · ' +
            (seconds
              ? String(Math.floor(seconds / 60)).padStart(2, '0') +
                ':' +
                String(seconds % 60).padStart(2, '0')
              : 'Elapsed'),
        ),
      );
    }
  }
  function schedule(delay) {
    clearTimeout(pollTimer);
    if (connected) pollTimer = setTimeout(poll, delay);
  }
  async function poll() {
    try {
      const r = await requestAPI('/api/agent/jobs', { method: 'GET' });
      const data = await r.json();
      jobs = data.jobs;
      timers = data.timers;
      serverOffset = data.server_time - Date.now() / 1000;
      render();
      renderTimers();
      if (jobs.length) onState(jobs.at(-1));
    } catch (e) {
      message(e.message);
    }
    schedule(
      document.hidden
        ? 5000
        : jobs.some((j) => ['queued', 'thinking'].includes(j.state))
          ? 400
          : 2000,
    );
  }
  const timer = setInterval(renderTimers, 1000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && connected) schedule(50);
  });
  window.addEventListener('pagehide', () => {
    clearTimeout(pollTimer);
    clearInterval(timer);
  });
  return {
    connect() {
      if (!connected) {
        connected = true;
        schedule(50);
      }
    },
    review,
    offerCaption(entry) {
      if (!dirty && !sending && !dialog.open) fill(entry);
    },
  };
}
