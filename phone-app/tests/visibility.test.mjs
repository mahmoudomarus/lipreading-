import test from 'node:test';
import assert from 'node:assert/strict';
import { createVisibilityResume } from '../dist/core.js';

function setup() {
  const state = { hidden: false, running: true, finishing: false, starts: 0, stops: 0, notices: 0 };
  const lifecycle = createVisibilityResume({
    hidden: () => state.hidden,
    running: () => state.running,
    finishing: () => state.finishing,
    start: () => {
      state.starts++;
      state.running = true;
    },
    stop: () => {
      state.stops++;
      state.running = false;
      state.finishing = true;
    },
    onPaused: () => state.notices++,
  });
  return { state, lifecycle };
}

test('hidden camera stops once and returning waits for the old phrase to finish', () => {
  const { state, lifecycle } = setup();
  state.hidden = true;
  lifecycle.changed();
  lifecycle.changed();
  assert.equal(state.stops, 1);
  assert.equal(state.notices, 1);
  state.hidden = false;
  assert.equal(lifecycle.changed(), false);
  assert.equal(state.starts, 0);
  state.finishing = false;
  assert.equal(lifecycle.finished(), true);
  assert.equal(state.starts, 1);
  assert.equal(lifecycle.finished(), false);
  lifecycle.changed();
  assert.equal(state.starts, 1);
});

test('finish while hidden keeps capture off until the tab returns', () => {
  const { state, lifecycle } = setup();
  state.hidden = true;
  lifecycle.changed();
  state.finishing = false;
  assert.equal(lifecycle.finished(), true);
  assert.equal(state.starts, 0);
  state.hidden = false;
  lifecycle.changed();
  assert.equal(state.starts, 1);
});

test('manual stop or page close cancels automatic resume', () => {
  const { state, lifecycle } = setup();
  state.hidden = true;
  lifecycle.changed();
  lifecycle.cancel();
  state.hidden = false;
  state.finishing = false;
  assert.equal(lifecycle.changed(), false);
  assert.equal(lifecycle.finished(), false);
  assert.equal(state.starts, 0);
});

test('visiting a tab with an idle camera never starts recording', () => {
  const { state, lifecycle } = setup();
  state.running = false;
  state.hidden = true;
  lifecycle.changed();
  state.hidden = false;
  lifecycle.changed();
  lifecycle.finished();
  assert.equal(state.starts, 0);
  assert.equal(state.stops, 0);
});

test('camera opening that finishes while hidden can defer until visible', () => {
  const { state, lifecycle } = setup();
  state.running = false;
  state.hidden = true;
  lifecycle.deferred();
  lifecycle.finished();
  assert.equal(state.starts, 0);
  state.hidden = false;
  lifecycle.changed();
  assert.equal(state.starts, 1);
});

test('failed or cancelled resume is not retried by later visibility events', () => {
  const { state, lifecycle } = setup();
  state.hidden = true;
  lifecycle.changed();
  state.finishing = false;
  state.hidden = false;
  lifecycle.changed();
  state.running = false;
  lifecycle.cancel();
  lifecycle.finished();
  lifecycle.changed();
  assert.equal(state.starts, 1);
});
