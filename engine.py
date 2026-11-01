"""Visual-only Auto-AVSR adapter. No audio, prompts, or generated demo text."""

from __future__ import annotations

import os
import sys
import time
import logging
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor" / "chaplin"


class CaptureError(ValueError):
    pass


def decode_frame(payload: bytes):
    """A little-endian float64 capture time in seconds, followed by JPEG bytes."""
    import struct

    if not 12 <= len(payload) <= 300_000:
        raise CaptureError("Invalid camera frame size.")
    timestamp = struct.unpack_from("<d", payload)[0]
    if not np.isfinite(timestamp) or timestamp < 0:
        raise CaptureError("Invalid camera timestamp.")
    # Inspect dimensions before decompression to bound allocation.
    from PIL import Image
    import io

    try:
        with Image.open(io.BytesIO(payload[8:])) as image:
            if image.format != "JPEG" or max(image.size) > 960 or min(image.size) < 96:
                raise CaptureError("Send JPEG camera frames between 96 and 960 pixels.")
    except (OSError, ValueError) as exc:
        raise CaptureError("The camera frame could not be decoded.") from exc
    frame = cv2.imdecode(np.frombuffer(payload[8:], dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise CaptureError("The camera frame could not be decoded.")
    return timestamp, cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def resample_frames(samples, fps=25, *, include_times=False):
    if len(samples) < 12:
        raise CaptureError("Capture a longer phrase with your face visible.")
    times = np.array([s[0] for s in samples])
    duration = float(times[-1] - times[0])
    if duration < 0.7 or duration > 10.5 or np.any(np.diff(times) <= 0):
        raise CaptureError("Capture a phrase between 1 and 10 seconds.")
    source_fps = (len(samples) - 1) / duration
    if source_fps < 12 or np.max(np.diff(times)) > 0.6:
        raise CaptureError("The video arrived too slowly. Improve your connection and try again.")
    if len({frame.shape for _, frame in samples}) != 1:
        raise CaptureError("Camera orientation changed. Keep your phone steady and try again.")
    target = times[0] + np.arange(int(round(duration * fps)) + 1) / fps
    right = np.clip(np.searchsorted(times, target), 1, len(times) - 1)
    left = right - 1
    indices = np.where(abs(times[left] - target) <= abs(times[right] - target), left, right)
    result = (np.stack([samples[i][1] for i in indices]), duration, source_fps)
    return (*result, times[indices]) if include_times else result


class LipReader:
    def __init__(self):
        import torch
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision

        sys.path.insert(0, str(VENDOR))
        from pipelines.model import AVSR
        from pipelines.detectors.mediapipe.video_process import VideoProcess
        from pipelines.data.transforms import VideoTransform

        torch.set_num_threads(int(os.getenv("LIPREAD_THREADS", "4")))
        self.torch, self.mp = torch, mp
        self.detector = vision.FaceDetector.create_from_options(
            vision.FaceDetectorOptions(
                base_options=python.BaseOptions(
                    model_asset_path=str(ROOT / "models/face_detector.tflite"),
                    delegate=python.BaseOptions.Delegate.CPU,
                ),
                running_mode=vision.RunningMode.IMAGE,
                min_detection_confidence=0.6,
            )
        )
        self.crop = VideoProcess()
        self.detection_cache = {}
        self.transform = VideoTransform(speed_rate=1)
        # Full-stream tests on this Mac were steadier on CPU than Metal, even
        # though warmed isolated GPU timings were faster. Keep Metal opt-in.
        requested = os.getenv("LIPREAD_DEVICE", "cpu")
        self.device = (
            ("mps" if torch.backends.mps.is_available() else "cpu")
            if requested == "auto"
            else requested
        )
        # Small autoregressive decoder steps are faster on CPU. Accelerate the
        # expensive video encoder while keeping the decoder and language model there.
        self.model = AVSR(
            "video",
            str(ROOT / "models/vsr.pth"),
            str(ROOT / "models/vsr.json"),
            rnnlm=str(ROOT / "models/lm.pth"),
            rnnlm_conf=str(ROOT / "models/lm.json"),
            beam_size=int(os.getenv("LIPREAD_BEAM", "12")),
            lm_weight=0.3,
            ctc_weight=0.1,
            device="cpu",
        )
        from espnet.nets.batch_beam_search import BatchBeamSearch

        search = self.model.beam_search
        # Share the same trained scorers, with a smaller search for live mode.
        self.fast_search = BatchBeamSearch(
            beam_size=int(os.getenv("LIPREAD_FAST_BEAM", "4")),
            vocab_size=self.model.odim,
            weights=dict(search.weights),
            scorers=dict(search.scorers.items()),
            sos=search.sos,
            eos=search.eos,
            token_list=self.model.token_list,
            pre_beam_score_key="decoder",
        ).eval()
        # Keep variable-length attention and tiny decoder steps on CPU. The
        # convolutional video frontend uses fixed GPU buckets, then removes only
        # the padding. Zero padding is equivalent to Conv3d's existing boundary
        # padding for every real frame; no speech is discarded or retimed.
        self.accelerated_frontend = None
        if self.device == "mps":
            try:
                frontend = self.model.model.encoder.frontend.to("mps")

                # The upstream Encoder dispatches using isinstance(frontend,
                # Conv3dResNet); preserve that type when adapting its execution.
                class MetalFrontend(type(frontend)):
                    def __init__(self, inner):
                        torch.nn.Module.__init__(self)
                        self.inner = inner

                    def forward(self, data):
                        frames = data.shape[2]
                        bucket = next(
                            (size for size in (48, 80, 128, 208, 256) if size >= frames),
                            ((frames + 15) // 16) * 16,
                        )
                        padded = torch.nn.functional.pad(data, (0, 0, 0, 0, 0, bucket - frames)).to(
                            "mps"
                        )
                        return self.inner(padded).cpu()[:, :frames]

                self.accelerated_frontend = MetalFrontend(frontend)
                self.model.model.encoder.frontend = self.accelerated_frontend
                with torch.inference_mode():
                    for count in (48, 80, 128, 208):
                        self.accelerated_frontend(torch.zeros(1, 1, count, 88, 88))
                    torch.mps.synchronize()
            except (RuntimeError, NotImplementedError) as exc:
                logging.getLogger("lipread").warning("Metal frontend unavailable: %s", exc)
                self.device = "cpu"
                if self.accelerated_frontend is not None:
                    self.model.model.encoder.frontend = self.accelerated_frontend.inner.cpu()
                else:
                    self.model.model.encoder.frontend.to("cpu")
                self.accelerated_frontend = None

    def begin_session(self):
        # Capture timestamps restart at zero for each phone session.
        self.detection_cache.clear()

    def analyze(self, samples):
        started = time.perf_counter()
        frames, duration, fps, sampled_times = resample_frames(samples, include_times=True)
        if os.getenv("LIPREAD_CACHE_DETECTIONS", "1") == "0":
            self.detection_cache.clear()
        cache_hits = 0
        landmarks = []
        detected = 0
        face_sizes = []
        head_turns = []
        # Detect every second frame, then interpolate using the upstream cropper.
        for i, frame in enumerate(frames):
            if i % 2:
                landmarks.append(None)
                continue
            cache_key = (float(sampled_times[i]), frame.shape)
            if cache_key in self.detection_cache:
                result = self.detection_cache[cache_key]
                cache_hits += 1
            else:
                result = self.detector.detect(
                    self.mp.Image(
                        image_format=self.mp.ImageFormat.SRGB, data=np.ascontiguousarray(frame)
                    )
                )
                self.detection_cache[cache_key] = result
                if len(self.detection_cache) > 300:
                    del self.detection_cache[next(iter(self.detection_cache))]
            if len(result.detections) != 1:
                landmarks.append(None)
                continue
            face = result.detections[0]
            detected += 1
            height, width = frame.shape[:2]
            face_sizes.append(face.bounding_box.width / width)
            points = face.keypoints
            eye_width = abs(points[1].x - points[0].x)
            head_turns.append(
                abs(points[2].x - (points[0].x + points[1].x) / 2) / max(eye_width, 0.001)
            )
            landmarks.append(
                np.array(
                    [[p.x * width, p.y * height] for p in face.keypoints[:4]], dtype=np.float32
                )
            )
        coverage = detected / ((len(frames) + 1) // 2)
        if coverage < 0.7:
            raise CaptureError("Keep one face fully visible, facing the camera, in good light.")
        if np.median(face_sizes) < 0.28:
            raise CaptureError("Move closer so your face and lips are clearer.")
        if np.median(head_turns) > 0.40:
            raise CaptureError(
                "Look directly at the camera so both sides of your lips are visible."
            )
        patches = self.crop(frames, landmarks)
        if patches is None or patches.shape[1:3] != (96, 96):
            raise CaptureError("Could not align your face. Look straight at the camera.")
        motion = float(np.mean(np.abs(np.diff(patches.astype(np.float32), axis=0))))
        if motion < 0.65:
            raise CaptureError("Very little movement detected. Speak a short phrase and try again.")
        data = self.transform(self.torch.from_numpy(patches))
        preprocess_seconds = time.perf_counter() - started
        with self.torch.inference_mode():
            try:
                features = self.model.model.encode(data).cpu()
            except (RuntimeError, NotImplementedError) as exc:
                if self.device != "mps":
                    raise
                logging.getLogger("lipread").warning("Metal inference fell back to CPU: %s", exc)
                # Some PyTorch/Metal combinations do not support every operator.
                self.device = "cpu"
                if self.accelerated_frontend is not None:
                    self.model.model.encoder.frontend = self.accelerated_frontend.inner.cpu()
                    self.accelerated_frontend = None
                else:
                    self.model.model.encoder.to("cpu")
                features = self.model.model.encode(data).cpu()
            ids = self.model.model.ctc.ctc_lo(features).argmax(-1)
            tokens = self.torch.unique_consecutive(ids).tolist()
            draft = self.tokens_to_text([i for i in tokens if i not in (0, self.model.odim - 1)])
            nonblank = self.torch.nonzero(ids != 0).flatten()
            trailing = (len(ids) - int(nonblank[-1]) - 1) / 25 if len(nonblank) else duration
        metadata = {
            "text": draft,
            "processing_seconds": round(time.perf_counter() - started, 2),
            "duration": round(duration, 2),
            "capture_fps": round(fps, 1),
            "face_coverage": round(coverage, 2),
            "confidence": None,
            "model": "Auto-AVSR · visual only",
            "device": self.device,
            "preprocess_seconds": round(preprocess_seconds, 3),
            "cached_detections": cache_hits,
            "trailing_blank_seconds": round(trailing, 2),
        }
        return {"features": features, "metadata": metadata, "started": started}

    def tokens_to_text(self, ids):
        return (
            "".join(self.model.token_list[i] for i in ids)
            .replace("▁", " ")
            .replace("<eos>", "")
            .replace("<blank>", "")
            .strip()
        )

    def refine(self, analysis, thorough=True):
        started = time.perf_counter()
        with self.torch.inference_mode():
            hypotheses = (self.model.beam_search if thorough else self.fast_search)(
                analysis["features"]
            )
        alternatives = []
        for hypothesis in hypotheses[:8]:
            text = self.tokens_to_text(hypothesis.yseq.tolist()[1:-1])
            if text and text not in alternatives:
                alternatives.append(text)
        if not alternatives:
            raise CaptureError("No words decoded. Try a complete, naturally spoken phrase.")
        return {
            **analysis["metadata"],
            "type": "result",
            "text": alternatives[0],
            "alternatives": alternatives[1:3],
            "draft_text": analysis["metadata"]["text"],
            "decoder": "detailed" if thorough else "fast",
            "refine_seconds": round(time.perf_counter() - started, 2),
            "processing_seconds": round(
                analysis["metadata"]["processing_seconds"] + time.perf_counter() - started, 2
            ),
        }

    def infer(self, samples):
        return self.refine(self.analyze(samples))


class QualityMonitor:
    """A separate detector for immediate framing advice; never an accuracy score."""

    def __init__(self):
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision

        self.mp = mp
        self.detector = vision.FaceDetector.create_from_options(
            vision.FaceDetectorOptions(
                base_options=python.BaseOptions(
                    model_asset_path=str(ROOT / "models/face_detector.tflite"),
                    delegate=python.BaseOptions.Delegate.CPU,
                ),
                min_detection_confidence=0.6,
            )
        )

    def check(self, frame):
        result = self.detector.detect(
            self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=np.ascontiguousarray(frame))
        )
        base = {"type": "quality", "ok": False}
        if not result.detections:
            return {**base, "message": "Bring your face into view", "issue": "missing"}
        if len(result.detections) != 1:
            return {**base, "message": "Keep just one face in the frame", "issue": "multiple"}
        face = result.detections[0]
        h, w = frame.shape[:2]
        box = face.bounding_box
        x, y = max(0, box.origin_x), max(0, box.origin_y)
        roi = frame[y : min(h, y + box.height), x : min(w, x + box.width)]
        if not roi.size:
            return {**base, "message": "Center your face", "issue": "framing"}
        gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
        brightness = float(gray.mean())
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        points = face.keypoints
        eyes = abs(points[1].x - points[0].x)
        turn = abs(points[2].x - (points[0].x + points[1].x) / 2) / max(eyes, 0.001)
        values = {
            "face_ratio": round(box.width / w, 2),
            "brightness": round(brightness),
            "sharpness": round(sharpness),
            "box": [x / w, y / h, box.width / w, box.height / h],
            "landmarks": [[round(p.x, 4), round(p.y, 4)] for p in points[:4]],
        }
        if box.width / w < 0.32:
            return {
                **base,
                **values,
                "message": "Move closer so your lips are clear",
                "issue": "small",
            }
        if brightness < 48:
            return {
                **base,
                **values,
                "message": "Face a light or move somewhere brighter",
                "issue": "dark",
            }
        if brightness > 225:
            return {**base, **values, "message": "Reduce the light on your face", "issue": "bright"}
        if sharpness < 18:
            return {
                **base,
                **values,
                "message": "Hold steady while the camera focuses",
                "issue": "blur",
            }
        if turn > 0.32:
            return {**base, **values, "message": "Look straight at the camera", "issue": "turned"}
        return {
            **base,
            **values,
            "ok": True,
            "message": "Face clear · speak naturally",
            "issue": None,
        }
