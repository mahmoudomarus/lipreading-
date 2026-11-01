import test from 'node:test';
import assert from 'node:assert/strict';
import { readConnection } from '../dist/core.js';
import { chooseRecordingType, fitCamera, wrapCaption, buildPostText } from '../dist/studio-core.js';
import { readFile } from 'node:fs/promises';

test('a provider key cannot be saved or sent as the app connection key', () => {
  assert.throws(
    () => readConnection('#key=sk-private', 'https://example.com'),
    /Settings → Model connection/,
  );
});
test('recording format picks a supported MP4 or falls back to WebM', () => {
  assert.equal(
    chooseRecordingType((type) => type === 'video/mp4'),
    'video/mp4',
  );
  assert.equal(
    chooseRecordingType((type) => type === 'video/webm'),
    'video/webm',
  );
  assert.equal(
    chooseRecordingType(() => false),
    '',
  );
});
test('portrait framing crops evenly while preserving the video aspect ratio', () => {
  const fit = fitCamera(1920, 1080, 720, 1280);
  assert.equal(fit.height, 1280);
  assert.ok(Math.abs(fit.width / fit.height - 1920 / 1080) < 1e-10);
  assert.ok(fit.x < 0);
  assert.equal(fit.y, 0);
});
test('caption wrapping preserves all original words', () => {
  const text = 'HELLO THERE HOW ARE YOU TODAY';
  const lines = wrapCaption(text, 12, (s) => s.length, 3);
  assert.equal(lines.join(' '), text);
  assert.ok(lines.length <= 3);
});
test('post copy describes AI voice only if it was used in the recording', () => {
  assert.ok(!buildPostText().includes('AI-generated voice'));
  assert.ok(buildPostText({ usedVoice: true }).includes('AI-generated voice'));
  assert.ok(buildPostText({ usedAssist: true }).includes('choose between possible readings'));
  assert.ok(buildPostText({ usedVoice: true, usedAssist: true }).length < 280);
});
test('all studio controls have matching HTML elements', async () => {
  const html = await readFile(new URL('../dist/index.html', import.meta.url), 'utf8');
  const js = await readFile(new URL('../dist/studio.js', import.meta.url), 'utf8');
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
  for (const match of js.matchAll(/\$\('([^']+)'\)/g)) assert.ok(ids.includes(match[1]), match[1]);
});
