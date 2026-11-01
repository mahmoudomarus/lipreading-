"""Visual activity hysteresis and multi-window utterance assembly. No audio input."""

from collections import deque
import math


class LipActivity:
    def __init__(self, pause_seconds=1.05, movement_threshold=0.008):
        self.pause_seconds = pause_seconds
        self.threshold = movement_threshold
        self.reset()

    def reset(self):
        self.previous = None
        self.motions = deque(maxlen=3)
        self.speaking = False
        self.turn = 0
        self.last_motion = 0.0
        self.first_motion = None

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
            if self.speaking:
                self.last_motion = timestamp
            movement = 0.0
        else:
            movement = max(abs(a - b) for a, b in zip(shape, self.previous))
            self.previous = tuple(shape)
        moving = movement >= self.threshold
        self.motions.append(moving)
        if moving:
            self.last_motion = timestamp
            if self.first_motion is None:
                self.first_motion = timestamp
        elif not self.speaking and not any(self.motions):
            self.first_motion = None
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
        return {
            "type": "utterance",
            "turn_id": turn_id,
            "text": text,
            "capture_end": endpoint,
            "duration": round(max(0, endpoint - turn["start"]), 2),
            "auto_send": reason is None,
            "needs_review": reason is not None,
            "review_reason": reason,
            "processing_seconds": round(sum(p.get("processing_seconds", 0) for p in parts), 2),
        }


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
