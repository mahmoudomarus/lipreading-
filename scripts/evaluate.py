"""Evaluate held-out silent clips through the real camera socket. References never reach recognition."""

import argparse
import asyncio
import json
import re
import statistics
import struct
import sys
import time
from pathlib import Path
import cv2
import websockets

ROOT = Path(__file__).resolve().parents[1]


def word_errors(reference, prediction):
    words = lambda s: re.findall(r"[\w]+(?:'[\w]+)?", s.lower())
    expected, actual = words(reference), words(prediction)
    row = list(range(len(actual) + 1))
    for i, a in enumerate(expected, 1):
        nxt = [i]
        for j, b in enumerate(actual, 1):
            nxt.append(min(row[j] + 1, nxt[-1] + 1, row[j - 1] + (a != b)))
        row = nxt
    return row[-1], len(expected)


async def clip(path, server, mode):
    capture = cv2.VideoCapture(str(path))
    fps = capture.get(cv2.CAP_PROP_FPS) or 25
    count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    if not capture.isOpened() or not 0.7 <= count / fps <= 7.8:
        capture.release()
        raise ValueError("Use a silent clip between 0.7 and 7.8 seconds.")
    token = (ROOT / ".runtime/access-token").read_text().strip()
    url = server.replace("https://", "wss://").replace("http://", "ws://") + "/api/stream"
    events = []
    async with websockets.connect(url, origin=server, max_size=300000, open_timeout=15) as ws:
        await ws.send(json.dumps({"token": token, "mode": mode}))
        hello = json.loads(await ws.recv())
        if hello.get("type") != "connected":
            raise ValueError(hello.get("message", "Camera not ready."))
        start = time.monotonic()
        end = None

        async def receive():
            while True:
                event = json.loads(await ws.recv())
                event["received_seconds"] = time.monotonic() - start
                if event["type"] in {"result", "draft", "guidance", "error"}:
                    events.append(event)
                if event["type"] == "finished":
                    return

        receiver = asyncio.create_task(receive())
        try:
            index = 0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                scale = min(1, 800 / max(frame.shape[:2]))
                if scale < 1:
                    frame = cv2.resize(frame, None, fx=scale, fy=scale)
                ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if not ok:
                    raise ValueError("Video decode failed.")
                await ws.send(struct.pack("<d", index / fps) + jpeg.tobytes())
                index += 1
                await asyncio.sleep(max(0, start + index / fps - time.monotonic()))
            end = time.monotonic() - start
            await ws.send(json.dumps({"type": "finish"}))
            await asyncio.wait_for(receiver, 90)
        finally:
            capture.release()
            if not receiver.done():
                receiver.cancel()
    drafts = [e for e in events if e["type"] == "draft"]
    results = [e for e in events if e["type"] == "result"]
    return {
        "prediction": " ".join(e["text"] for e in results),
        "first_draft_seconds": drafts[0]["received_seconds"] if drafts else None,
        "final_after_capture_seconds": max(0, results[-1]["received_seconds"] - end)
        if results
        else None,
        "capture_to_draft_seconds": [
            max(0, e["received_seconds"] - e["capture_end"]) for e in drafts
        ],
        "abstained": not results,
        "events": events,
    }


async def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "manifest", type=Path, help="JSONL: video, reference; optional group and expected_silence"
    )
    p.add_argument("--server", default="http://127.0.0.1:8765")
    p.add_argument("--mode", choices=["live", "phrase"], default="live")
    p.add_argument("--report", type=Path, default=ROOT / ".runtime/evaluation.json")
    args = p.parse_args()
    rows = []
    errors = words = false_activations = 0
    records = [json.loads(line) for line in args.manifest.read_text().splitlines() if line.strip()]
    for record in records:
        path = (args.manifest.parent / record["video"]).resolve()
        result = await clip(path, args.server, args.mode)
        e, n = word_errors(record.get("reference", ""), result["prediction"])
        errors += e
        words += n
        false_activations += int(bool(record.get("expected_silence")) and not result["abstained"])
        row = {
            **record,
            **result,
            "word_errors": e,
            "reference_words": n,
            "wer": e / n if n else None,
        }
        rows.append(row)
        print(
            json.dumps(
                {
                    k: row[k]
                    for k in [
                        "video",
                        "prediction",
                        "wer",
                        "abstained",
                        "first_draft_seconds",
                        "final_after_capture_seconds",
                    ]
                }
            ),
            flush=True,
        )
    latencies = [v for r in rows for v in r["capture_to_draft_seconds"]]
    report = {
        "mode": args.mode,
        "clips": len(rows),
        "word_errors": errors,
        "reference_words": words,
        "wer": errors / words if words else None,
        "silence_clips": sum(bool(r.get("expected_silence")) for r in rows),
        "false_activations": false_activations,
        "median_capture_to_draft_seconds": statistics.median(latencies) if latencies else None,
        "p95_capture_to_draft_seconds": sorted(latencies)[
            min(len(latencies) - 1, int(len(latencies) * 0.95))
        ]
        if latencies
        else None,
        "results": rows,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "results"}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
