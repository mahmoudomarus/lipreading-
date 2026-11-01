"""Compare cached and uncached frame detection on identical growing video windows."""

import argparse
import json
import os
import sys
import time
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
capture = cv2.VideoCapture(str(args.video))
if not capture.isOpened():
    sys.exit("Could not open the test video.")
fps = capture.get(cv2.CAP_PROP_FPS) or 25
samples = []
while True:
    ok, frame = capture.read()
    if not ok or len(samples) / fps > 3.1:
        break
    samples.append((len(samples) / fps, cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
capture.release()
if not samples or samples[-1][0] < 2.9:
    sys.exit("Use a clip at least three seconds long.")
reader = LipReader()
reports = []
for enabled in ("0", "1"):
    reader.begin_session()
    os.environ["LIPREAD_CACHE_DETECTIONS"] = enabled
    rows = []
    for duration in (1.4, 2.1, 2.9):
        result = reader.analyze([(t, f) for t, f in samples if t <= duration])
        rows.append(result["metadata"])
    reports.append({"cache": enabled == "1", "windows": rows})
assert [r["text"] for r in reports[0]["windows"]] == [r["text"] for r in reports[1]["windows"]]
(ROOT / ".runtime/cache-profile.json").write_text(json.dumps(reports, indent=2))
print(json.dumps(reports, indent=2))
