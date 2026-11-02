// Plays generated speech; stop() silences it as soon as the user starts speaking.
export function createAudioEngine() {
  let context;
  const sources = new Set();
  async function unlock() {
    if (!context) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) throw new Error('Audio playback is unavailable in this browser.');
      context = new AudioContext();
    }
    await context.resume();
  }
  async function play(bytes) {
    await unlock();
    const buffer = await context.decodeAudioData(bytes.slice(0));
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    sources.add(source);
    return new Promise((resolve) => {
      source.onended = () => {
        sources.delete(source);
        source.disconnect();
        resolve();
      };
      source.start();
    });
  }
  return {
    unlock,
    play,
    stop() {
      for (const source of sources) {
        try {
          source.stop();
        } catch {}
      }
    },
  };
}
