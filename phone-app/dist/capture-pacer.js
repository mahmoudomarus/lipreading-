// Accumulate deadlines so a 30 fps sensor can deliver 25 fps without falling to 15.
export function createFramePacer(fps = 25) {
  const interval = 1000 / fps;
  let next = 0;
  return {
    reset(now = 0) {
      next = now;
    },
    due(now) {
      if (now + 0.1 < next) return false;
      next = now - next > interval * 2 ? now + interval : next + interval;
      return true;
    },
  };
}

export function createFrameRateMeter() {
  let frames = 0;
  let last = 0;
  return {
    reset(now = 0) {
      frames = 0;
      last = now;
    },
    sent() {
      frames++;
    },
    sample(now) {
      const elapsed = now - last;
      if (elapsed < 1000) return null;
      const fps = Math.round((frames * 1000) / elapsed);
      frames = 0;
      last = now;
      return fps;
    },
  };
}
