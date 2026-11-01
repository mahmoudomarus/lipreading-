import io
import struct
import unittest

import cv2
import numpy as np
from PIL import Image
from fastapi.testclient import TestClient

from engine import CaptureError, decode_frame, resample_frames
import server


class CaptureTests(unittest.TestCase):
    def test_jpeg_packet_and_timestamp(self):
        frame = np.full((128, 160, 3), 100, np.uint8)
        _, jpeg = cv2.imencode(".jpg", frame)
        timestamp, image = decode_frame(struct.pack("<d", 1.25) + jpeg.tobytes())
        self.assertEqual(timestamp, 1.25)
        self.assertEqual(image.shape, (128, 160, 3))

    def test_invalid_and_oversized_frames(self):
        for payload in [b"bad", b"x" * 300001, struct.pack("<d", float("nan")) + b"12345678"]:
            with self.assertRaises(CaptureError):
                decode_frame(payload)
        output = io.BytesIO()
        Image.new("RGB", (1000, 100)).save(output, format="JPEG")
        with self.assertRaises(CaptureError):
            decode_frame(struct.pack("<d", 0) + output.getvalue())

    def test_resampling_preserves_speech_duration(self):
        samples = [(i / 30, np.full((100, 100, 3), i, np.uint8)) for i in range(91)]
        result, duration, fps = resample_frames(samples)
        self.assertEqual(len(result), 76)
        self.assertEqual(duration, 3)
        self.assertEqual(fps, 30)
        self.assertEqual(result[-1, 0, 0, 0], 90)

    def test_slow_video_and_orientation_changes_rejected(self):
        image = np.zeros((100, 100, 3), np.uint8)
        with self.assertRaises(CaptureError):
            resample_frames([(i / 5, image) for i in range(16)])
        samples = [(i / 25, image) for i in range(30)]
        samples[-1] = (29 / 25, np.zeros((100, 120, 3), np.uint8))
        with self.assertRaises(CaptureError):
            resample_frames(samples)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        # No lifespan: protocol tests do not allocate or load production ML weights.
        self.client = TestClient(server.app)

    def test_status_requires_private_key(self):
        self.assertEqual(self.client.get("/api/status").status_code, 401)
        response = self.client.get(
            "/api/status", headers={"Authorization": "Bearer " + server.TOKEN}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["audio"])
        self.assertEqual(response.json()["version"], 4)
        self.assertLess(response.json()["draft_after_seconds"], 2)

    def test_assets_cannot_expose_access_token(self):
        response = self.client.get("/.runtime/access-token")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(server.TOKEN, response.text)
        self.assertIn("microphone=()", self.client.get("/").headers["permissions-policy"])

    def test_websocket_rejects_foreign_origin(self):
        from starlette.websockets import WebSocketDisconnect

        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(
                "/api/stream", headers={"Origin": "https://foreign.example"}
            ):
                pass

    def test_websocket_rejects_bad_key(self):
        from starlette.websockets import WebSocketDisconnect

        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(
                "/api/stream", headers={"Origin": "http://testserver"}
            ) as ws:
                ws.send_json({"token": "incorrect"})
                ws.receive_json()


class StreamingTests(unittest.TestCase):
    def test_draft_is_due_before_old_five_second_wait(self):
        stream = server.StreamBuffer()
        image = np.zeros((100, 100, 3), np.uint8)
        for i in range(36):
            stream.add(i / 25, image)
        self.assertTrue(stream.due())
        stream.last_draft = 1.4
        self.assertFalse(stream.due())

    def test_finalization_preserves_video_arriving_during_inference(self):
        stream = server.StreamBuffer()
        image = np.zeros((100, 100, 3), np.uint8)
        for i in range(101):
            stream.add(i / 25, image)
        snapshot = stream.snapshot(cutoff=3.0)
        self.assertEqual(snapshot[-1][0], 3.0)
        stream.finalize(3.0)
        self.assertTrue(all(t > 3 for t, _ in stream.frames))
        self.assertEqual(stream.segment, 2)
        self.assertEqual(stream.frames[-1][0], 4.0)
        # A delayed duplicate frame must not reintroduce an already-final phrase.
        stream.add(2.8, image)
        self.assertTrue(all(t > 3 for t, _ in stream.frames))

    def test_frame_memory_is_bounded(self):
        stream = server.StreamBuffer()
        image = np.zeros((100, 100, 3), np.uint8)
        for i in range(1000):
            stream.add(i / 30, image)
        self.assertLessEqual(len(stream.frames), 260)
        self.assertLessEqual(stream.duration(), 9.8)

    def test_stream_emits_drafts_then_one_refined_phrase(self):
        class Reader:
            def begin_session(self):
                pass

            device = "cpu"

            def analyze(self, samples):
                return {
                    "metadata": {
                        "text": "HELLO THERE",
                        "duration": samples[-1][0] - samples[0][0],
                        "processing_seconds": 0.01,
                        "trailing_blank_seconds": 0,
                    },
                    "features": None,
                }

            def refine(self, analysis, thorough=True):
                return {
                    **analysis["metadata"],
                    "type": "result",
                    "text": "HELLO THERE",
                    "alternatives": [],
                }

        class Monitor:
            def check(self, frame):
                return {"type": "quality", "ok": True, "message": "Face clear"}

        previous = server.state.copy()
        server.state.update(status="ready", reader=Reader(), monitor=Monitor())
        try:
            client = TestClient(server.app)
            frame = np.full((128, 160, 3), 100, np.uint8)
            _, jpeg = cv2.imencode(".jpg", frame)
            with client.websocket_connect(
                "/api/stream", headers={"Origin": "http://testserver"}
            ) as ws:
                ws.send_json({"token": server.TOKEN, "mode": "live"})
                self.assertEqual(ws.receive_json()["type"], "connected")
                for i in range(39):
                    ws.send_bytes(struct.pack("<d", i / 25) + jpeg.tobytes())
                events = []
                while not any(event["type"] == "draft" for event in events):
                    events.append(ws.receive_json())
                ws.send_json({"type": "finish"})
                while True:
                    event = ws.receive_json()
                    events.append(event)
                    if event["type"] == "finished":
                        break
                self.assertEqual(sum(event["type"] == "result" for event in events), 1)
                result = next(event for event in events if event["type"] == "result")
                draft = next(event for event in events if event["type"] == "draft")
                self.assertEqual(result["sequence"], draft["sequence"])
                self.assertEqual(result["capture_end"], 38 / 25)
        finally:
            server.state.clear()
            server.state.update(previous)


if __name__ == "__main__":
    unittest.main()
