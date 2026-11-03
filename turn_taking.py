"""Visual activity hysteresis and multi-window utterance assembly. No audio input."""

import math
from collections import deque

# Stillness that ends a turn; a finished turn's endpoint includes this wait.
PAUSE_SECONDS = 1.05


class LipActivity:
    def __init__(self, pause_seconds=PAUSE_SECONDS, movement_threshold=0.008, smoothing=0.6):
        self.pause_seconds = pause_seconds
        self.threshold = movement_threshold
        self.smoothing = smoothing
        self.reset()

    def reset(self):
        self.previous = None
        self.motions = deque(maxlen=3)
        self.speaking = False
        self.turn = 0
        self.last_motion = 0.0
        self.first_motion = None
        self.graced = False

    def observe(self, shape, timestamp):
        event = None
        if shape is None:
            self.previous = None
            self.motions.clear()
            return {
                "available": False,
                "speaking": self.speaking,
                "event": None,
                "turn_id": self.turn,
                "capture_time": timestamp,
                "pause_seconds": self.pause_seconds,
            }
        if self.previous is None:
            self.previous = tuple(shape)
            # Regaining the face grants one short grace period per pause; only real movement
            # renews it, so a face that keeps dropping out cannot hold a turn open forever.
            if self.speaking and not self.graced:
                self.last_motion = max(self.last_motion, timestamp - self.pause_seconds / 2)
                self.graced = True
            movement = 0.0
        else:
            # Exponential smoothing damps per-sample landmark jitter on small or noisy
            # faces; real articulation persists across samples and still registers.
            smoothed = tuple(
                self.smoothing * a + (1 - self.smoothing) * b
                for a, b in zip(shape, self.previous, strict=True)
            )
            movement = max(abs(a - b) for a, b in zip(smoothed, self.previous, strict=True))
            self.previous = smoothed
        moving = movement >= self.threshold
        self.motions.append(moving)
        if moving:
            if self.first_motion is None:
                self.first_motion = timestamp
        elif not self.speaking and not any(self.motions):
            self.first_motion = None
        # A lone over-threshold frame is landmark jitter, not speech, so it must not
        # keep a turn open; small or noisy faces otherwise never reach the pause.
        if sum(self.motions) >= 2:
            self.last_motion = timestamp
            self.graced = False
        if not self.speaking and sum(self.motions) >= 2:
            self.speaking = True
            self.turn += 1
            event = "started"
        elif self.speaking and timestamp - self.last_motion >= self.pause_seconds:
            self.speaking = False
            self.motions.clear()
            self.first_motion = None
            event = "stopped"
        return {
            "available": True,
            "speaking": self.speaking,
            "event": event,
            "turn_id": self.turn,
            "capture_time": timestamp,
            "speech_start": self.first_motion,
            "pause_seconds": self.pause_seconds,
            "movement": round(movement, 4),
        }


class Utterances:
    """Join consumed decoder windows only when the actual visual turn ends."""

    def __init__(self):
        self.turns = {}

    def start(self, turn_id, timestamp):
        self.turns.setdefault(turn_id, {"start": timestamp, "parts": {}, "sent": False})
        # Retain only bounded recent state; never retain camera frames here.
        for old in sorted(self.turns)[:-6]:
            self.turns.pop(old, None)

    def add(self, turn_id, sequence, result):
        if turn_id not in self.turns:
            self.start(turn_id, 0)
        self.turns[turn_id]["parts"][sequence] = dict(result)

    def finish(self, turn_id, endpoint):
        turn = self.turns.get(turn_id)
        if not turn or turn["sent"]:
            return None
        turn["sent"] = True
        parts = [turn["parts"][key] for key in sorted(turn["parts"])]
        if not parts:
            return None
        text = " ".join(p["text"].strip() for p in parts if p.get("text", "").strip())
        if not text:
            return None
        reason = next((p.get("review_reason") for p in parts if p.get("auto_send") is False), None)
        if reason is None and any(p.get("auto_send") is False for p in parts):
            reason = "Part of this request needs correction."
        prefix = " ".join(p["text"].strip() for p in parts[:-1] if p.get("text", "").strip())
        alternatives = []
        for candidate in parts[-1].get("alternatives", []):
            combined = " ".join(s for s in [prefix, candidate.strip()] if s)
            if combined and combined != text and combined not in alternatives:
                alternatives.append(combined)
        result = {
            "type": "utterance",
            "turn_id": turn_id,
            "text": text,
            "alternatives": alternatives[:2],
            "capture_end": endpoint,
            "duration": round(max(0, endpoint - turn["start"]), 2),
            "auto_send": reason is None,
            "needs_review": reason is not None,
            "review_reason": reason,
            "processing_seconds": round(sum(p.get("processing_seconds", 0) for p in parts), 2),
        }
        # Do not manufacture draft evidence when a producer did not supply it.
        if all(isinstance(p.get("draft_text"), str) for p in parts):
            result["draft_text"] = " ".join(p["draft_text"].strip() for p in parts)
        return result


class MouthMonitor:
    def __init__(self, model_path):
        import mediapipe as mp
        import numpy as np
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision

        self.mp, self.np = mp, np
        self.model = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=python.BaseOptions(
                    model_asset_path=str(model_path), delegate=python.BaseOptions.Delegate.CPU
                ),
                running_mode=vision.RunningMode.IMAGE,
                num_faces=1,
                min_face_detection_confidence=0.6,
                min_face_presence_confidence=0.6,
            )
        )
        self.activity = LipActivity()

    def reset(self):
        self.activity.reset()

    @staticmethod
    def shape(points, width, height):
        def distance(a, b):
            return math.hypot(
                (points[a].x - points[b].x) * width, (points[a].y - points[b].y) * height
            )

        eyes = max(distance(33, 263), 1.0)
        return [
            distance(a, b) / eyes
            for a, b in [(13, 14), (61, 291), (0, 17), (78, 308), (81, 87), (311, 317)]
        ]

    def check(self, frame, timestamp):
        import cv2

        h, w = frame.shape[:2]
        if max(h, w) > 480:
            frame = cv2.resize(frame, None, fx=480 / max(h, w), fy=480 / max(h, w))
        h, w = frame.shape[:2]
        result = self.model.detect(
            self.mp.Image(
                image_format=self.mp.ImageFormat.SRGB, data=self.np.ascontiguousarray(frame)
            )
        )
        shape = (
            self.shape(result.face_landmarks[0], w, h) if len(result.face_landmarks) == 1 else None
        )
        return {"type": "speech_activity", **self.activity.observe(shape, timestamp)}
