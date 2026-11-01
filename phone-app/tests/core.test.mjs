import test from 'node:test';
import assert from 'node:assert/strict';
import {
  readConnection,
  framePacket,
  transcriptText,
  upsertCaption,
  compareWords,
} from '../dist/core.js';

test('connection fragment overrides old session and strips URL paths', () => {
  const result = readConnection(
    '#server=https%3A%2F%2Fphone.example%2Fprivate&key=fresh',
    'https://site.example',
    { server: 'https://old.example', key: 'old' },
  );
  assert.deepEqual(result, { server: 'https://phone.example', key: 'fresh' });
});
test('reject insecure remote camera connections', () => {
  assert.throws(
    () => readConnection('#server=http://remote.example&key=x', 'https://site.example'),
    /HTTPS/,
  );
  assert.equal(readConnection('#key=x', 'http://127.0.0.1:8765').server, 'http://127.0.0.1:8765');
});
test('camera packet preserves little endian timestamp and exact JPEG bytes', async () => {
  const packet = await framePacket(
    1.25,
    new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xd9])]),
  ).arrayBuffer();
  assert.equal(new DataView(packet).getFloat64(0, true), 1.25);
  assert.deepEqual([...new Uint8Array(packet, 8)], [255, 216, 255, 217]);
});
test('copy keeps window boundaries without inventing or merging words', () => {
  assert.equal(
    transcriptText([{ text: 'HELLO THERE' }, { text: 'THERE IS A CAMERA' }]),
    'HELLO THERE\n\nTHERE IS A CAMERA',
  );
});

test('a refined correction replaces the phrase instead of appending a duplicate', () => {
  const entries = [];
  upsertCaption(entries, { id: 'a:1', text: 'HELLO' });
  upsertCaption(entries, { id: 'a:1', text: 'HELLO THERE' });
  upsertCaption(entries, { id: 'b:1', text: 'A NEW SESSION' });
  assert.equal(entries.length, 2);
  assert.equal(entries[0].text, 'HELLO THERE');
});

test('reference comparison measures real word edits without punctuation or case bias', () => {
  assert.deepEqual(compareWords('Hello, how are you today?', 'HELLO HOW ARE YOU TODAY'), {
    errors: 0,
    words: 5,
    wer: 0,
  });
  assert.deepEqual(compareWords('hello there', 'hello'), { errors: 1, words: 2, wer: 0.5 });
  assert.equal(compareWords('hello', 'hello there my friend').wer, 3);
  assert.equal(compareWords('...', 'HELLO'), null);
});

test('all app element bindings exist in the HTML, with unique IDs', async () => {
  const { readFile } = await import('node:fs/promises');
  const html = await readFile(new URL('../dist/index.html', import.meta.url), 'utf8');
  const app = await readFile(new URL('../dist/app.js', import.meta.url), 'utf8');
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]);
  assert.equal(new Set(ids).size, ids.length, 'duplicate element ID');
  for (const match of app.matchAll(/\$\('([^']+)'\)/g))
    assert.ok(ids.includes(match[1]), 'missing ' + match[1]);
});
