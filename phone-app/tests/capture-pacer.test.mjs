import test from 'node:test';
import assert from 'node:assert/strict';
import { createFramePacer, createFrameRateMeter } from '../dist/capture-pacer.js';
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

test('the send-rate display falls to zero when frame callbacks stop', () => {
  const meter = createFrameRateMeter();
  meter.reset(0);
  for (let i = 0; i < 25; i++) meter.sent();
  assert.equal(meter.sample(999), null);
  assert.equal(meter.sample(1000), 25);
  assert.equal(meter.sample(2000), 0);
  assert.equal(meter.sample(5000), 0);
});

test('new capture sessions reset counts and resumed delivery uses elapsed time', () => {
  const meter = createFrameRateMeter();
  for (let i = 0; i < 25; i++) meter.sent();
  meter.reset(5000);
  assert.equal(meter.sample(6000), 0);
  for (let i = 0; i < 40; i++) meter.sent();
  assert.equal(meter.sample(8000), 20);
});
