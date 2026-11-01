import test from 'node:test';
import assert from 'node:assert/strict';
import { createFramePacer } from '../dist/capture-pacer.js';
test('a 30fps camera produces about 25 captures without being halved to 15', () => {
  const pacer = createFramePacer(25);
  pacer.reset(0);
  let captured = 0;
  for (let i = 0; i < 300; i++) if (pacer.due((i * 1000) / 30)) captured++;
  assert.ok(captured >= 249 && captured <= 251, String(captured));
});
test('after a long stall a resumed frame does not trigger a backlog burst', () => {
  const pacer = createFramePacer(25);
  pacer.due(0);
  assert.equal(pacer.due(10000), true);
  assert.equal(pacer.due(10001), false);
  assert.equal(pacer.due(10040), true);
});
