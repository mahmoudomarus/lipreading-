import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createAgentUI } from '../dist/agent-ui.js';
import { backgroundStatus, mergeJobs } from '../dist/agent-core.js';

// Minimal element storage exercises the production renderer and handlers without
// a browser framework. Camera/device behavior has a separate phone checklist.
class Element {
  constructor(tag = 'div') {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.checked = true;
    this.value = '';
    this.scrollTop = 0;
    this.scrollHeight = 0;
    this.clientHeight = 100;
    this.classList = { add() {}, toggle() {} };
    this._text = '';
  }
  set textContent(value) {
    this._text = value;
    this.children = [];
  }
  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join(' ');
  }
  append(...children) {
    for (const child of children) {
      child.parent = this;
      this.children.push(child);
    }
  }
  replaceChildren(...children) {
    this.children = [];
    this.append(...children);
  }
  querySelectorAll(selector) {
    return this.children.flatMap((child) => [
      ...((
        selector === 'button'
          ? child.tag === 'button'
          : child.className?.split(' ').includes(selector.slice(1))
      )
        ? [child]
        : []),
      ...child.querySelectorAll(selector),
    ]);
  }
  remove() {
    this.parent.children = this.parent.children.filter((child) => child !== this);
  }
  addEventListener() {}
  setAttribute() {}
  focus() {}
  showModal() {
    this.open = true;
  }
  close() {
    this.open = false;
  }
}

test('background UI renders per-job cancellation and speech only stops audio', async (t) => {
  const html = await readFile(new URL('../dist/index.html', import.meta.url), 'utf8');
  const elements = new Map(
    [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => [match[1], new Element()]),
  );
  const timeouts = new Map();
  let timerId = 0,
    stoppedAudio = 0;
  t.mock.method(globalThis, 'setTimeout', (fn) => {
    timeouts.set(++timerId, fn);
    return timerId;
  });
  t.mock.method(globalThis, 'clearTimeout', (id) => timeouts.delete(id));
  t.mock.method(globalThis, 'setInterval', () => 0);
  t.mock.method(globalThis, 'clearInterval', () => {});
  const oldDocument = globalThis.document,
    oldWindow = globalThis.window;
  globalThis.document = {
    getElementById: (id) => {
      assert.ok(elements.has(id), id);
      return elements.get(id);
    },
    createElement: (tag) => new Element(tag),
    createTextNode: (text) => {
      const e = new Element();
      e.textContent = text;
      return e;
    },
    querySelector: () => new Element(),
    addEventListener() {},
    hidden: false,
  };
  globalThis.window = { addEventListener() {} };
  t.after(() => {
    globalThis.document = oldDocument;
    globalThis.window = oldWindow;
  });
  const jobs = ['queued', 'thinking', 'researching', 'review', 'completed'].map((state, i) => ({
    id: state,
    state,
    input: 'Request ' + state,
    source: 'typed',
    created: i + 1,
    updated: i + 2,
    plan: ['review', 'completed'].includes(state)
      ? {
          answer: state,
          actions:
            state === 'review'
              ? [{ name: 'save_note', text: 'Keep this', seconds: 0, expression: '' }]
              : [],
        }
      : null,
    result: null,
  }));
  const calls = [];
  const ui = createAgentUI({
    requestAPI: async (path, options) => {
      calls.push([path, options]);
      if (path === '/api/agent/cancel-all') {
        for (const job of jobs)
          if (job.state !== 'completed') {
            job.state = 'cancelled';
            job.updated += 10;
          }
      } else if (path.endsWith('/cancel')) {
        const job = jobs.find((item) => path.includes('/' + item.id + '/'));
        job.state = 'cancelled';
        job.updated += 10;
        return { json: async () => job };
      } else assert.equal(path, '/api/agent/jobs');
      return {
        json: async () => ({
          jobs: structuredClone(jobs),
          timers: [],
          server_time: Date.now() / 1000,
        }),
      };
    },
    getLatest: () => null,
    onState() {},
    onSettings() {},
    onStopAudio: () => stoppedAudio++,
  });
  ui.connect();
  const poll = [...timeouts.values()].at(-1);
  await poll();
  const turns = elements.get('agent-feed').querySelectorAll('.agent-turn');
  for (const turn of turns.slice(0, 4)) {
    assert.equal(
      turn.querySelectorAll('button').filter((button) => button.textContent === 'Cancel').length,
      1,
    );
  }
  assert.equal(
    turns[4].querySelectorAll('button').filter((button) => button.textContent === 'Cancel').length,
    0,
  );
  assert.match(elements.get('turn-state').textContent, /2 tasks running/);
  const before = calls.length;
  ui.speech({ event: 'started', speaking: true, available: true, turn_id: 99 });
  // Lip movement alone (a smile, a reaction) must not cut off a spoken reply.
  assert.equal(stoppedAudio, 0);
  assert.equal(calls.length, before);
  assert.deepEqual(
    jobs.map((job) => job.state),
    ['queued', 'thinking', 'researching', 'review', 'completed'],
  );
  await turns[2]
    .querySelectorAll('button')
    .find((button) => button.textContent === 'Cancel')
    .onclick();
  assert.equal(jobs[2].state, 'cancelled');
  assert.equal(jobs[1].state, 'thinking');
  await elements.get('agent-cancel-all').onclick();
  assert.deepEqual(
    jobs.map((job) => job.state),
    ['cancelled', 'cancelled', 'cancelled', 'cancelled', 'completed'],
  );
});

test('pending confirmations survive history bounds and background summaries count every task', () => {
  const pending = { id: 'old-review', state: 'review', created: 0, updated: 1 };
  const newer = Array.from({ length: 40 }, (_, i) => ({
    id: String(i),
    state: 'completed',
    created: i + 1,
    updated: i + 2,
  }));
  const merged = mergeJobs([pending], newer);
  assert.ok(merged.some((job) => job.id === pending.id));
  assert.equal(merged.length, 31);
  assert.equal(backgroundStatus(merged).review, 1);
});
