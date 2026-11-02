"""Report local prerequisites without printing credentials or private links."""

import importlib.metadata
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
failed = False


def check(label, ok, detail=""):
    global failed
    print(("OK   " if ok else "FAIL ") + label + (": " + detail if detail else ""))
    failed |= not ok


check("Python 3.11", sys.version_info[:2] == (3, 11), ".".join(map(str, sys.version_info[:3])))
for command in ("git", "cloudflared"):
    check(command, bool(shutil.which(command)))
for package in (
    "fastapi",
    "uvicorn",
    "httpx",
    "websockets",
    "numpy",
    "opencv-python-headless",
    "pillow",
    "torch",
    "torchvision",
    "torchaudio",
    "mediapipe",
    "scikit-image",
    "sentencepiece",
    "six",
    "av",
    "qrcode",
):
    try:
        print("OK   " + package + " " + importlib.metadata.version(package))
    except importlib.metadata.PackageNotFoundError:
        check(package, False, "pip install -r requirements.txt")
check("Vendor checkout", (ROOT / "vendor/chaplin/.git").exists(), "run scripts/setup.py")
check(
    "Model files",
    all(
        (ROOT / "models" / n).exists()
        for n in (
            "vsr.pth",
            "vsr.json",
            "lm.pth",
            "lm.json",
            "face_detector.tflite",
            "face_landmarker.task",
        )
    ),
    "checksums: scripts/setup.py --verify-only",
)
print("Node is required only for frontend tests, not normal use.")
sys.exit(1 if failed else 0)
