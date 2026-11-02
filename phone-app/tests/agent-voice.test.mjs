import test from 'node:test';
import assert from 'node:assert/strict';
import { newlyCompleted, spokenText } from '../dist/agent-core.js';

test('only jobs seen unfinished on this page become spoken replies', () => {
  const before = [
    { id: 'a', state: 'thinking' },
    { id: 'b', state: 'completed' },
    { id: 'c', state: 'review' },
  ];
  const after = [
    { id: 'a', state: 'completed' },
    { id: 'b', state: 'completed' },
    { id: 'c', state: 'cancelled' },
    { id: 'd', state: 'completed' },
  ];
  assert.deepEqual(
    newlyCompleted(before, after).map((job) => job.id),
    ['a'],
  );
  assert.deepEqual(newlyCompleted([], after), []);
});

test('spoken replies keep whole sentences within the voice limit', () => {
  const short = { state: 'completed', plan: { answer: 'Twelve times seven is 84.' } };
  assert.equal(spokenText(short), 'Twelve times seven is 84.');
  const long = {
    state: 'completed',
    plan: { answer: 'First sentence here. ' + 'Second sentence is much longer. '.repeat(20) },
  };
  const spoken = spokenText(long, 80);
  assert.ok(spoken.length <= 80);
  assert.match(spoken, /^First sentence here\./);
  assert.match(spoken, /\.$/);
  const receipt = {
    state: 'completed',
    result: [{ tool: 'calculate', result: { expression: '2+2', value: 4 } }],
  };
  assert.equal(spokenText(receipt), '2+2 = 4');
});
