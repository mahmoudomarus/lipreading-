"""Exercise real video through the production camera socket; no audio is sent."""

import argparse
import asyncio
import json
import struct
import sys
import time
from pathlib import Path

import cv2
import websockets

ROOT = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("--server", default="http://127.0.0.1:8765")
    parser.add_argument("--mode", choices=["phrase", "live"], default="phrase")
    parser.add_argument("--tail", type=float, default=0.0)
    parser.add_argument("--token-file", type=Path, default=ROOT / ".runtime/access-token")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    token = args.token_file.read_text().strip()
    url = args.server.replace("https://", "wss://").replace("http://", "ws://") + "/api/stream"
    capture = cv2.VideoCapture(args.video)
    fps = capture.get(cv2.CAP_PROP_FPS) or 25
    events = []
    async with websockets.connect(url, origin=args.server, max_size=300000, open_timeout=15) as ws:
        await ws.send(json.dumps({"token": token, "mode": args.mode}))
        hello = json.loads(await ws.recv())
        print(hello, flush=True)
        assert hello["type"] == "connected", hello
        assert hello["version"] == 4, hello
        start = time.monotonic()

        async def receive():
            while True:
                event = json.loads(await ws.recv())
                event["received_seconds"] = round(time.monotonic() - start, 3)
                events.append(event)
                if event["type"] not in {"quality", "ready", "pong"}:
                    print(json.dumps(event), flush=True)
                if event["type"] == "finished":
                    return

        receiver = asyncio.create_task(receive())
        index = 0
        last = None
        while index / fps < 7.5:
            ok, frame = capture.read()
            if not ok:
                break
            scale = min(1, 800 / max(frame.shape[:2]))
            if scale < 1:
                frame = cv2.resize(frame, None, fx=scale, fy=scale)
            ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            assert ok
            last = jpeg.tobytes()
            await ws.send(struct.pack("<d", index / fps) + last)
            index += 1
            await asyncio.sleep(max(0, start + index / fps - time.monotonic()))
        capture.release()
        for _ in range(min(int(args.tail * fps), max(0, int(7.5 * fps) - index))):
            await ws.send(struct.pack("<d", index / fps) + last)
            index += 1
            await asyncio.sleep(max(0, start + index / fps - time.monotonic()))
        await ws.send(json.dumps({"type": "finish"}))
        await asyncio.wait_for(receiver, 120)
    results = [e for e in events if e["type"] == "result"]
    drafts = [e for e in events if e["type"] == "draft"]
    if not results:
        sys.exit("No refined result produced.")
    utterances = [e for e in events if e["type"] == "utterance"]
    if hello.get("visual_turns") and not utterances:
        sys.exit("Visual endpointing produced no final utterance.")
    report = {
        "mode": args.mode,
        "protocol_version": hello["version"],
        "visual_turns": hello["visual_turns"],
        "final_text": " ".join(e["text"] for e in (utterances or results)),
        "first_draft_seconds": drafts[0]["received_seconds"] if drafts else None,
        "first_refined_seconds": results[0]["received_seconds"],
        "events": events,
    }
    target = args.report or ROOT / f".runtime/smoke-{args.mode}-v4.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n")
    print("TIMING", json.dumps({k: v for k, v in report.items() if k != "events"}), flush=True)


asyncio.run(main())
