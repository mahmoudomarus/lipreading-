import test from 'node:test';
import assert from 'node:assert/strict';
import { createConversation } from '../dist/conversation.js';
import { mergeJobs } from '../dist/agent-core.js';

const result = (id, text = 'Hello there') => ({ id, text, type: 'result' });

test('a final phrase automatically sends once; provisional drafts never send', async () => {
  const sent = [];
  const flow = createConversation({
    send: async (body) => sent.push(body),
    makeId: () => 'turn-1',
  });
  assert.equal(flow.offer({ ...result('a'), type: 'draft' }), false);
  assert.equal(flow.offer(result('a')), true);
  assert.equal(flow.offer(result('a')), false);
  await flow.settled();
  assert.deepEqual(sent, [{ text: 'Hello there', source: 'lip_prediction', request_id: 'turn-1' }]);
});
test('different utterances with the same words remain separate turns', async () => {
  const sent = [];
  let id = 0;
  const flow = createConversation({
    send: async (body) => sent.push(body),
    makeId: () => String(++id),
  });
  flow.offer(result('a'));
  flow.offer(result('b'));
  await flow.settled();
  assert.equal(sent.length, 2);
  assert.notEqual(sent[0].request_id, sent[1].request_id);
});
test('turn dispatch preserves order when the first acknowledgement is slow', async () => {
  const sent = [];
  let release;
  const first = new Promise((resolve) => {
    release = resolve;
  });
  const flow = createConversation({
    send: async (body) => {
      sent.push(body.text);
      if (sent.length === 1) await first;
    },
    makeId: () => String(sent.length),
  });
  flow.offer(result('a', 'First'));
  flow.offer(result('b', 'Second'));
  assert.deepEqual(sent, ['First']);
  release();
  await flow.settled();
  assert.deepEqual(sent, ['First', 'Second']);
});
test('retry after a lost acknowledgement reuses its idempotency UUID', async () => {
  const sent = [];
  let failed;
  const flow = createConversation({
    send: async (body) => {
      sent.push(body);
      if (sent.length === 1) throw new Error('Network lost');
    },
    onError: (error, turn) => {
      failed = turn;
    },
    makeId: () => 'same-uuid',
  });
  flow.offer(result('a'));
  await flow.settled();
  assert.ok(failed);
  flow.retry(failed);
  await flow.settled();
  assert.deepEqual(sent[0], sent[1]);
});
test('switching off live replies discards unsent phrases and does not replay them later', async () => {
  const sent = [];
  let release;
  const first = new Promise((resolve) => {
    release = resolve;
  });
  const flow = createConversation({
    send: async (body) => {
      sent.push(body.text);
      await first;
    },
    makeId: () => 'id',
  });
  flow.offer(result('a', 'First'));
  flow.offer(result('b', 'Second'));
  flow.setEnabled(false);
  release();
  await flow.settled();
  assert.equal(flow.offer(result('c')), false);
  flow.setEnabled(true);
  await flow.settled();
  assert.deepEqual(sent, ['First']);
});
test('empty and unidentified results cannot trigger a request', async () => {
  const sent = [];
  const flow = createConversation({ send: async (body) => sent.push(body) });
  flow.offer(result('', 'Hello'));
  flow.offer(result('a', '   '));
  await flow.settled();
  assert.equal(sent.length, 0);
});
test('polling cannot erase a recent auto-turn or roll back a completed receipt', () => {
  const completed = { id: 'a', created: 1, updated: 5, state: 'completed' };
  const queued = { id: 'b', created: 6, updated: 6, state: 'queued' };
  assert.deepEqual(
    mergeJobs([completed, queued], [{ ...completed, updated: 2, state: 'thinking' }]),
    [completed, queued],
  );
});
