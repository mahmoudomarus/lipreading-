import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { safePageURL } from '../dist/work-cards.js';
import { receiptText } from '../dist/agent-core.js';
test('work links reject script/file protocols and embedded credentials', () => {
  for (const url of [
    'javascript:alert(1)',
    'file:///private/data',
    'https://user:secret@example.com',
  ])
    assert.equal(safePageURL(url), null);
  assert.equal(safePageURL('https://example.com'), 'https://example.com/');
});
test('new work tools summarize as receipts without being mistaken for timers', () => {
  assert.equal(
    receiptText({ tool: 'draft_document', result: { title: 'Plan' } }),
    'Draft ready · Plan',
  );
  assert.equal(
    receiptText({ tool: 'research', result: { text: 'A sourced answer' } }),
    'A sourced answer',
  );
});
test('every work-card dialog binding exists', async () => {
  const html = await readFile(new URL('../dist/index.html', import.meta.url), 'utf8');
  const js = await readFile(new URL('../dist/work-cards.js', import.meta.url), 'utf8');
  for (const m of js.matchAll(/\$\('([^']+)'\)/g))
    assert.ok(html.includes('id="' + m[1] + '"'), m[1]);
});
