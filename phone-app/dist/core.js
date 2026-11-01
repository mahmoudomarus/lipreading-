export function readConnection(hash, origin, stored = {}) {
  const params = new URLSearchParams(hash.replace(/^#/, ''));
  const endpoint = params.get('server') || stored.server || origin;
  const url = new URL(endpoint);
  if (
    url.protocol !== 'https:' &&
    !(['localhost', '127.0.0.1'].includes(url.hostname) && url.protocol === 'http:')
  ) {
    throw new Error('Use a secure HTTPS connection URL.');
  }
  const key = params.get('key') || stored.key || '';
  if (key.startsWith('sk-'))
    throw new Error(
      'That is a provider API key. Add it in Settings → Model connection, using your private app link to connect first.',
    );
  return { server: url.origin, key };
}

export function framePacket(timestamp, jpeg) {
  const header = new ArrayBuffer(8);
  new DataView(header).setFloat64(0, timestamp, true);
  return new Blob([header, jpeg], { type: 'application/octet-stream' });
}

export function transcriptText(entries) {
  return entries.map((entry) => entry.text).join('\n\n');
}

export function readingCandidates(entry) {
  const text = entry?.text?.trim();
  if (!text || text.length > 600) return [];
  return [
    ...new Set(
      [text, ...(entry.alternatives || [])]
        .filter((candidate) => typeof candidate === 'string')
        .map((candidate) => candidate.trim())
        .filter((candidate) => candidate && candidate.length <= 600),
    ),
  ].slice(0, 4);
}

export function displayText(text) {
  const sentence = text.toLowerCase().replace(/\bi\b/g, 'I');
  return sentence.charAt(0).toUpperCase() + sentence.slice(1);
}

export function upsertCaption(entries, entry) {
  const index = entries.findIndex((item) => item.id === entry.id);
  if (index >= 0) entries[index] = entry;
  else entries.push(entry);
  return entries;
}

export function compareWords(reference, prediction) {
  const words = (text) => text.toLowerCase().match(/[\p{L}\p{N}]+(?:'[\p{L}]+)?/gu) || [];
  const expected = words(reference),
    actual = words(prediction);
  if (!expected.length) return null;
  let row = Array.from({ length: actual.length + 1 }, (_, i) => i);
  for (let i = 1; i <= expected.length; i++) {
    const next = [i];
    for (let j = 1; j <= actual.length; j++) {
      next[j] = Math.min(
        row[j] + 1,
        next[j - 1] + 1,
        row[j - 1] + (expected[i - 1] === actual[j - 1] ? 0 : 1),
      );
    }
    row = next;
  }
  return {
    errors: row[actual.length],
    words: expected.length,
    wer: row[actual.length] / expected.length,
  };
}
