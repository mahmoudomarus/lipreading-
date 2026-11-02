import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { actionLabel, agentSummary, receiptText } from '../dist/agent-core.js';

test('confirmation previews explicitly describe every backend tool', async () => {
  const backend = await readFile(new URL('../../agent.py', import.meta.url), 'utf8');
  const tools = [...backend.match(/TOOLS = \{([\s\S]*?)\n\}/)[1].matchAll(/"([a-z_]+)"/g)]
    .map((m) => m[1])
    .sort();
  const labels = {
    save_note: 'Save note: # Test',
    start_timer: 'Start 30s timer · # Test',
    calculate: 'Calculate 2+2',
    list_notes: 'Read saved notes',
    list_timers: 'Read timers',
    research: 'Research: # Test',
    open_page: 'Open page preview: # Test',
    draft_document: 'Create document: Test',
  };
  assert.deepEqual(Object.keys(labels).sort(), tools);
  for (const name of tools)
    assert.equal(
      actionLabel({ name, text: '# Test', seconds: 30, expression: '2+2' }),
      labels[name],
    );
  assert.equal(actionLabel({ name: 'future_tool' }), 'Unknown action: future_tool');
});

test('action preview cannot be presented as an executed receipt', () => {
  const text = agentSummary({
    state: 'review',
    plan: { answer: 'Done', actions: [{ name: 'save_note', text: 'Idea' }] },
  });
  assert.match(text, /Awaiting confirmation/);
  assert.ok(!text.includes('Done'));
});
test('executed receipt takes precedence over model prose', () => {
  assert.equal(
    agentSummary({
      state: 'completed',
      plan: { answer: 'Maybe' },
      result: [{ tool: 'calculate', result: { expression: '2+2', value: 4 } }],
    }),
    '2+2 = 4',
  );
  assert.equal(receiptText({ tool: 'list_notes', result: [] }), 'No saved notes yet.');
});
test('agent UI has complete bindings and neutral user-facing source', async () => {
  const html = await readFile(new URL('../dist/index.html', import.meta.url), 'utf8');
  const js = await readFile(new URL('../dist/agent-ui.js', import.meta.url), 'utf8');
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]);
  for (const m of js.matchAll(/\$\('([^']+)'\)/g)) assert.ok(ids.includes(m[1]), m[1]);
  for (const file of ['index.html', 'app.js', 'audio.js', 'core.js']) {
    assert.doesNotMatch(
      await readFile(new URL('../dist/' + file, import.meta.url), 'utf8'),
      /openai/i,
    );
  }
});
