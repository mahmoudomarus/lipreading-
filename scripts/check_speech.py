"""Generate one text-only caption audio sample with the configured speech adapter."""

import asyncio
import io
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main():
    from provider import TextProvider
    from speech import RealtimeSpeech, SpeechError

    connection = TextProvider()
    if not connection.config()["voice_available"]:
        sys.exit("Speech is unavailable for the configured endpoint.")
    try:
        start = time.perf_counter()
        audio = await RealtimeSpeech(key=connection.key).voice("Hello from Lipread.")
        (ROOT / ".runtime").mkdir(exist_ok=True)
        (ROOT / ".runtime/voice-test.wav").write_bytes(audio)
        with wave.open(io.BytesIO(audio), "rb") as wav:
            print(
                "VOICE",
                round(wav.getnframes() / wav.getframerate(), 2),
                "seconds audio;",
                round(time.perf_counter() - start, 2),
                "seconds generation",
            )
    except SpeechError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    asyncio.run(main())
