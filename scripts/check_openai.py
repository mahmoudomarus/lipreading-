"""One small, explicit OpenAI smoke test. No keys or private camera data are printed."""

import argparse
import asyncio
import io
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from openai_bridge import OpenAIBridge, BridgeError


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", action="store_true")
    args = parser.parse_args()
    bridge = OpenAIBridge()
    try:
        start = time.perf_counter()
        result = await bridge.assist(["HELLO HOW ARE YOU", "YELLOW HOW ARE YOU"], "A greeting")
        print(
            "OPENAI_ASSIST",
            result["text"],
            round(time.perf_counter() - start, 2),
            "seconds",
            flush=True,
        )
        if args.voice:
            start = time.perf_counter()
            audio = await bridge.voice("Hello from Lipread.")
            (ROOT / ".runtime/voice-test.wav").write_bytes(audio)
            with wave.open(io.BytesIO(audio), "rb") as wav:
                print(
                    "OPENAI_VOICE",
                    round(wav.getnframes() / wav.getframerate(), 2),
                    "seconds audio;",
                    round(time.perf_counter() - start, 2),
                    "seconds generation",
                    flush=True,
                )
    except BridgeError as exc:
        print("OPENAI_SETUP_NEEDED", str(exc), flush=True)
        sys.exit(1)


asyncio.run(main())
