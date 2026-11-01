// Finalized camera turns are serialized separately from drafts and manual edits.
export function createConversation({
  send,
  onError,
  onQueue,
  onHold,
  makeId = () => crypto.randomUUID(),
}) {
  const known = new Map();
  const queue = [];
  let enabled = true;
  let running = false;
  let idle = Promise.resolve();

  async function drain() {
    if (running) return;
    running = true;
    try {
      while (enabled && queue.length) {
        const turn = queue.shift();
        turn.state = 'sending';
        onQueue?.(queue.length + 1);
        try {
          await send({
            text: turn.text,
            source: 'lip_prediction',
            request_id: turn.id,
            ...turn.scope,
          });
          turn.state = 'sent';
        } catch (error) {
          turn.state = 'failed';
          onError?.(error, turn);
        }
      }
    } finally {
      running = false;
      onQueue?.(queue.length);
    }
  }
  function pump() {
    if (!running) idle = drain();
    return idle;
  }
  return {
    offer(entry) {
      // No provisional drafts, empty captions, repeated transport events or invented IDs.
      if (!enabled || entry?.type !== 'result' || !entry.id || !entry.text?.trim()) return false;
      if (known.has(entry.id)) return false;
      if (entry.auto_send === false) {
        known.set(entry.id, { state: 'held' });
        if (known.size > 500) known.delete(known.keys().next().value);
        onHold?.(entry);
        return false;
      }
      if (queue.length >= 8) {
        onError?.(new Error('Conversation is busy. Pause and try that phrase again.'));
        return false;
      }
      const scope =
        entry.session_id && Number.isInteger(entry.turn_id)
          ? { session_id: entry.session_id, turn_id: entry.turn_id }
          : {};
      const turn = { key: entry.id, id: makeId(), text: entry.text.trim(), state: 'queued', scope };
      known.set(entry.id, turn);
      // Keep only a bounded deduplication window; the server also deduplicates request UUIDs.
      if (known.size > 500) known.delete(known.keys().next().value);
      queue.push(turn);
      pump();
      return true;
    },
    retry(turn) {
      if (!enabled || turn?.state !== 'failed') return false;
      turn.state = 'queued';
      queue.push(turn); // Same UUID: a lost acknowledgement cannot create a second job.
      pump();
      return true;
    },
    interrupt() {
      for (const turn of queue) turn.state = 'cancelled';
      queue.length = 0;
    },
    setEnabled(value) {
      enabled = Boolean(value);
      if (!enabled) {
        for (const turn of queue) turn.state = 'cancelled';
        queue.length = 0;
      }
    },
    settled() {
      return idle;
    },
  };
}
