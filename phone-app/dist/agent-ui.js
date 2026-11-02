import { createWorkCards } from './work-cards.js';
import { createConversation } from './conversation.js';
import {
  actionLabel,
  receiptText,
  mergeJobs,
  jobCanCancel,
  backgroundStatus,
  newlyCompleted,
  understanding,
} from './agent-core.js';

export function createAgentUI({
  requestAPI,
  getLatest,
  onState = () => {},
  onSettings,
  onStopAudio = () => {},
  onReply = () => {},
  onSay = () => {},
  onLiveMode = () => {},
  onPhase = () => {},
}) {
  const $ = (id) => document.getElementById(id);
  const workCards = createWorkCards();
  let userSpeaking = false;
  let pendingSends = 0;
  let jobs = [],
    timers = [],
    pollTimer,
    connected = false,
    dirty = false,
    source = 'typed',
    sending = false,
    pending = null,
    serverOffset = 0,
    signature = '',
    failedTurn = null;
  const composer = $('agent-request'),
    dialog = $('agent-review-dialog');
  function message(text) {
    $('agent-message').textContent = text;
  }
  // Every job update goes through here so a task finishing becomes one spoken reply.
  function adopt(next) {
    const finished = newlyCompleted(jobs, next);
    jobs = next;
    for (const job of finished) onReply(job);
  }
  function acceptJob(job) {
    const known = jobs.some((j) => j.id === job.id);
    adopt(mergeJobs(jobs, [job]));
    if (!known && job.state === 'completed') onReply(job);
    render();
    onState(job);
    connected = true;
    schedule(100);
  }
  let heldCaption = null;
  $('agent-held-edit').onclick = () => {
    if (heldCaption) review(heldCaption);
  };
  $('agent-held-ignore').onclick = () => {
    $('agent-held').hidden = true;
    heldCaption = null;
  };
  const conversation = createConversation({
    onHold(entry) {
      heldCaption = entry;
      $('agent-held').hidden = false;
      $('agent-held-reason').textContent = entry.review_reason || 'I couldn’t read that clearly.';
      message('Unclear reading held back. Keep speaking, or correct it below.');
    },
    async send(body) {
      $('agent-held').hidden = true;
      message('Sending your phrase…');
      // With Speak for me on, a lip turn is understood and said aloud instead of answered.
      const purpose = $('agent-speak-toggle').checked ? 'speak' : 'assist';
      const response = await requestAPI('/api/agent/jobs', { body: { ...body, purpose } });
      const job = await response.json();
      acceptJob(job);
      message('Working in the background. You can keep talking.');
      if (failedTurn?.id === body.request_id) {
        failedTurn = null;
        $('agent-retry-auto').hidden = true;
      }
      return job;
    },
    onQueue(count) {
      pendingSends = count;
      $('agent-cancel-all').disabled = !count && !jobs.some(jobCanCancel);
    },
    async cancel(job) {
      if (job?.id) await operate(job, 'cancel', $('agent-cancel-all'));
    },
    onError(error, turn) {
      message(error.message);
      if (turn) failedTurn = turn;
      $('agent-retry-auto').hidden = !failedTurn;
      $('agent-retry-auto').onclick = () => {
        if (conversation.retry(failedTurn)) $('agent-retry-auto').hidden = true;
      };
    },
  });
  $('agent-live-toggle').onchange = () => {
    conversation.setEnabled($('agent-live-toggle').checked);
    onLiveMode($('agent-live-toggle').checked);
    message(
      $('agent-live-toggle').checked
        ? 'Speak and pause. Replies are automatic.'
        : 'Live replies paused. Review or type a request to send.',
    );
    $('agent-live-label').textContent = $('agent-live-toggle').checked
      ? 'Live replies on'
      : 'Manual review';
  };
  function phase(value, text) {
    $('turn-state').textContent = text;
    $('turn-state').dataset.phase = value;
    onPhase(value, text);
  }
  async function cancelAll() {
    onStopAudio();
    conversation.cancelPending();
    try {
      const response = await requestAPI('/api/agent/cancel-all');
      const result = await response.json();
      adopt(mergeJobs(jobs, result.jobs));
      render();
      phase('ready', backgroundStatus(jobs).text);
      message('Pending tasks cancelled. Completed work is unchanged.');
      schedule(50);
    } catch (error) {
      message(error.message);
    }
  }
  $('agent-cancel-all').onclick = cancelAll;
  function speech(activity) {
    if (activity.event === 'started') onStopAudio();
    userSpeaking = $('agent-live-toggle').checked && activity.speaking;
    if (!$('agent-live-toggle').checked) return;
    if (activity.event === 'started') {
      phase('listening', 'Listening to you');
      message('Keep speaking. Background tasks will continue.');
    } else if (activity.event === 'stopped') {
      phase('finishing', 'You paused · finishing the phrase');
    } else if (!activity.available) {
      phase('framing', 'Bring your lips into view');
    }
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
    const latest = [...jobs].reverse().find(jobCanCancel) || jobs.at(-1);
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
      acceptJob(job);
      composer.value = '';
      source = 'typed';
      dirty = false;
      pending = null;
      $('agent-source').textContent = 'OPTIONAL · TYPE OR CORRECT A MESSAGE';
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
      adopt(jobs.map((j) => (j.id === next.id ? next : j)));
      render();
      onState(next);
      schedule(100);
      return next;
    } catch (e) {
      message(e.message);
      button.disabled = false;
    }
  }
  // Show the newest turn on open and as replies arrive, until the user scrolls up to read.
  let followLatest = true;
  $('agent-feed').addEventListener('scroll', () => {
    const feed = $('agent-feed');
    followLatest = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80;
  });
  function render() {
    const feed = $('agent-feed');
    const nextSignature = JSON.stringify(jobs);
    if (signature === nextSignature) return;
    signature = nextSignature;
    workCards.reset();
    $('agent-welcome').hidden = jobs.length > 0;
    for (const el of feed.querySelectorAll('.agent-turn')) el.remove();
    for (const job of jobs) {
      const turn = node('article', 'agent-turn'),
        user = node('div', 'agent-user'),
        understood = understanding(job);
      user.append(
        node(
          'span',
          'turn-label',
          understood
            ? 'LIPS READ'
            : job.source === 'lip_prediction'
              ? 'LIP PREDICTION · AUTO-SENT'
              : job.source === 'reviewed_lips'
                ? 'REVIEWED CAPTION'
                : 'TYPED REQUEST',
        ),
        node('p', understood ? 'raw-reading' : '', job.input),
      );
      // The understanding step: what the assistant worked out before answering.
      if (understood)
        user.append(
          node('span', 'turn-label understood-label', 'UNDERSTOOD · ' + understood.label),
          node('p', 'understood-text', understood.text),
        );
      else if (job.source !== 'typed' && ['queued', 'thinking'].includes(job.state))
        user.append(node('span', 'turn-label understood-label', 'UNDERSTANDING WHAT YOU SAID…'));
      if (job.source === 'lip_prediction' && job.state !== 'dismissed' && !jobCanCancel(job)) {
        const misread = node('button', 'misread-button', 'Misread · ignore');
        misread.onclick = () => operate(job, 'dismiss', misread);
        user.append(misread);
      }
      if (job.state === 'dismissed') user.classList.add('dismissed-turn');
      turn.append(user);
      const answer = node('div', 'agent-answer');
      answer.append(
        node(
          'span',
          'turn-label',
          job.state === 'review'
            ? 'ACTION PREVIEW'
            : job.purpose === 'speak' && job.state === 'completed'
              ? job.plan?.certainty === 'unsure'
                ? 'NOT SAID · CHECK THIS GUESS'
                : 'SAID FOR YOU'
              : job.state === 'completed'
                ? 'ASSISTANT'
                : 'AGENT · ' + job.state.toUpperCase(),
        ),
      );
      if (job.state === 'dismissed') {
        answer.append(
          node('p', 'dismissed-note', 'Misread ignored. It won’t influence future replies.'),
        );
        if (job.result?.length)
          answer.append(node('p', 'dismissed-note', 'Any tools already executed are not undone.'));
      } else if (job.state === 'cancelled') {
        answer.append(node('p', 'dismissed-note', 'Cancelled. Completed actions are not undone.'));
      } else if (job.plan && job.purpose === 'speak') {
        answer.append(node('p', 'spoken-for-you', job.plan.understood || job.input));
        const say = node(
          'button',
          'misread-button',
          job.plan.certainty === 'unsure' ? 'Say it ↗' : 'Say again ↗',
        );
        say.onclick = () => onSay(job);
        answer.append(say);
      } else if (job.plan) {
        if (job.plan.answer) answer.append(node('p', '', job.plan.answer));
        if (job.state === 'review') {
          for (const action of job.plan.actions)
            answer.append(node('p', 'action-preview', actionLabel(action)));
          const controls = node('div', 'agent-confirmation'),
            confirm = node('button', '', 'Confirm actions ↗');
          confirm.onclick = () => operate(job, 'confirm', confirm);
          controls.append(confirm);
          answer.append(controls);
        }
        for (const receipt of job.result || []) {
          const card = workCards.card(receipt);
          answer.append(card || node('p', 'tool-receipt', receiptText(receipt)));
        }
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
      if (jobCanCancel(job)) {
        const controls = node('div', 'agent-confirmation');
        const cancel = node('button', '', 'Cancel');
        cancel.onclick = () => operate(job, 'cancel', cancel);
        const edit = node('button', '', 'Cancel and edit');
        edit.onclick = async () => {
          const next = await operate(job, 'cancel', edit);
          if (!next) return;
          composer.value = job.input;
          source = job.source === 'lip_prediction' ? 'reviewed_lips' : job.source;
          dirty = true;
          pending = null;
          view();
          composer.focus();
          message(
            next.state === 'completed'
              ? 'That task already completed. A new request will not undo it.'
              : 'Old task cancelled. Edit and send a new request.',
          );
        };
        controls.append(cancel, edit);
        answer.append(controls);
      }
      if (job.state === 'failed') {
        const retry = node('button', 'agent-retry', 'Edit and retry');
        retry.onclick = () => {
          composer.value = job.input;
          source = job.source === 'lip_prediction' ? 'reviewed_lips' : job.source;
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
    if (followLatest) feed.scrollTop = feed.scrollHeight;
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
      adopt(mergeJobs(jobs, data.jobs));
      timers = data.timers;
      serverOffset = data.server_time - Date.now() / 1000;
      render();
      renderTimers();
      const summary = backgroundStatus(jobs);
      $('agent-cancel-all').disabled = !summary.active && !pendingSends;
      if (jobs.length) {
        const representative = [...jobs].reverse().find(jobCanCancel) || jobs.at(-1);
        onState(representative);
        if (!userSpeaking) {
          phase(
            summary.running || summary.queued ? 'working' : summary.review ? 'review' : 'ready',
            summary.text,
          );
          message(
            summary.running || summary.queued
              ? summary.text + '. You can keep talking.'
              : summary.review
                ? 'Confirm or cancel each pending action when ready.'
                : 'Your turn. Speak and pause for another task.',
          );
        }
      }
    } catch (e) {
      message(e.message);
    }
    schedule(
      document.hidden
        ? 5000
        : jobs.some((j) => ['queued', 'thinking', 'researching'].includes(j.state))
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
    workCards.reset();
  });
  return {
    connect() {
      if (!connected) {
        connected = true;
        schedule(50);
      }
    },
    review,
    speech,
    cancelAll,
    offerCaption(entry) {
      if ($('agent-live-toggle').checked) {
        phase('working', 'Working in the background · you can keep talking');
        conversation.offer(entry);
      } else if (!dirty && !sending && !dialog.open) fill(entry);
    },
  };
}
