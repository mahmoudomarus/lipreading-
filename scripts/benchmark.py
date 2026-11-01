"""Latency and numerical-equivalence check for the fixed-shape GPU frontend."""

import argparse, json, sys, time, os
from pathlib import Path
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import LipReader

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "video", type=Path, help="Your consented 3–8 second test clip; audio is ignored"
)
args = parser.parse_args()
(ROOT / ".runtime").mkdir(exist_ok=True)
os.environ.setdefault("LIPREAD_DEVICE", "auto")
reader = LipReader()
capture = cv2.VideoCapture(str(args.video))
if not capture.isOpened():
    sys.exit("Could not open the test video.")
fps = capture.get(cv2.CAP_PROP_FPS) or 25
samples = []
while True:
    ok, frame = capture.read()
    if not ok or len(samples) >= 200:
        break
    samples.append((len(samples) / fps, cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
capture.release()
if len(samples) < 75:
    sys.exit("Use a clip with at least 75 frames.")
samples = samples[:200]
rows = []
for length in [35, 58, 75]:
    for attempt in range(2):
        clip = samples[:length]
        start = time.perf_counter()
        analysis = reader.analyze(clip)
        draft = time.perf_counter() - start
        result = reader.refine(analysis)
        row = {
            "device": reader.device,
            "frames": length,
            "attempt": attempt,
            "draft_seconds": round(draft, 3),
            "refined_seconds": result["processing_seconds"],
            "text": result["text"],
        }
        print(json.dumps(row), flush=True)
        rows.append(row)
# Remove padding only after the temporal-convolution/spatial-ResNet frontend.
# Compare the complete encoded features to CPU without changing preprocessing.
if reader.accelerated_frontend:
    wrapper = reader.accelerated_frontend
    hybrid = reader.analyze(samples)["features"]
    reader.model.model.encoder.frontend = wrapper.inner.cpu()
    reader.device = "cpu"
    cpu = reader.analyze(samples)["features"]
    max_error = float((hybrid - cpu).abs().max())
    print("FEATURE_MAX_ABS_ERROR", max_error, flush=True)
    rows.append({"feature_max_abs_error": max_error})
(ROOT / ".runtime/benchmark-v2.json").write_text(json.dumps(rows, indent=2))
