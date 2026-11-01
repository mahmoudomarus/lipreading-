"""Bounded video windows with consume-once finalization."""

from collections import deque

from config import (
    DRAFT_CONTEXT_SECONDS,
    DRAFT_INTERVAL_SECONDS,
    MAX_BUFFER_FRAMES,
    MAX_BUFFER_SECONDS,
)


class StreamBuffer:
    """Keep one utterance; drafts revise it, and finalization consumes it once."""

    def __init__(self):
        self.frames = deque(maxlen=MAX_BUFFER_FRAMES)
        self.segment = 1
        self.consumed = -1.0
        self.last_draft = -1.0

    def add(self, timestamp, frame):
        if timestamp > self.consumed:
            self.frames.append((timestamp, frame))
        while self.frames and timestamp - self.frames[0][0] > MAX_BUFFER_SECONDS:
            self.frames.popleft()

    def snapshot(self, cutoff=None):
        return [(t, f) for t, f in self.frames if cutoff is None or t <= cutoff]

    def duration(self, cutoff=None):
        frames = self.snapshot(cutoff)
        return frames[-1][0] - frames[0][0] if frames else 0.0

    def due(self):
        return (
            self.duration() >= DRAFT_CONTEXT_SECONDS
            and self.frames[-1][0] - self.last_draft >= DRAFT_INTERVAL_SECONDS
        )

    def finalize(self, endpoint):
        self.consumed = max(self.consumed, endpoint)
        while self.frames and self.frames[0][0] <= self.consumed:
            self.frames.popleft()
        self.segment += 1
        self.last_draft = -1.0
