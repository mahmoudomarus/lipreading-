"""Repeat the existing camera replay without submitting agent jobs."""

import argparse
import asyncio
import hashlib
import json
import math
import statistics
from pathlib import Path

import httpx
from evaluate import ROOT, clip


def distribution(values):
    values = sorted(value for value in values if value is not None)
    if not values:
        return {"n": 0, "median": None, "p95": None, "min": None, "max": None}
    return {
        "n": len(values),
        "median": statistics.median(values),
        "p95": values[math.ceil(0.95 * len(values)) - 1],
        "min": values[0],
        "max": values[-1],
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--server", default="http://127.0.0.1:8765")
    parser.add_argument("--token-file", type=Path, default=ROOT / ".runtime/access-token")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--report", type=Path, default=ROOT / ".runtime/repeated-latency.json")
    args = parser.parse_args()
    if not 1 <= args.runs <= 100 or not 0 <= args.warmup <= 10:
        parser.error("Use 1–100 runs and 0–10 warmup runs.")
    token = args.token_file.read_text().strip()
    async with httpx.AsyncClient() as client:
        response = await client.get(
            args.server + "/api/status", headers={"Authorization": "Bearer " + token}
        )
        response.raise_for_status()
        status = response.json()
    if status["status"] != "ready" or status["active_session"]:
        raise ValueError("Use an idle, ready service. Do not replace an active camera session.")
    results = []
    for index in range(args.warmup + args.runs):
        result = await clip(args.video, args.server, "live", token)
        if index >= args.warmup:
            results.append(result)
        print(
            json.dumps(
                {
                    "run": index - args.warmup + 1,
                    "warmup": index < args.warmup,
                    "final_seconds": result["final_from_start_seconds"],
                }
            ),
            flush=True,
        )
    metrics = ["first_draft_seconds", "final_from_start_seconds", "final_after_last_frame_seconds"]
    report = {
        "video_sha256": hashlib.sha256(args.video.read_bytes()).hexdigest(),
        "runs": args.runs,
        "warmup_discarded": args.warmup,
        "mode": "live",
        "endpoint": "finish",
        "jpeg_quality": 90,
        "resize_long_edge": 800,
        "server_status": status,
        "latency_seconds": {key: distribution([row[key] for row in results]) for key in metrics},
        "distinct_predictions": sorted({row["prediction"] for row in results}),
        "results": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["latency_seconds"]), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
