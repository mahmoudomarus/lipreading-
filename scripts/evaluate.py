"""Replay camera-only clips; score the UI's finalized turns without executing jobs."""

import argparse
import asyncio
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

import cv2
import httpx
import websockets
from eval_metrics import action_match, compare, score, selected_events, summarize, tokens

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def word_errors(reference, prediction):
    result = score(reference, prediction)
    return result["word_errors"], result["reference_words"]


async def clip(path, server, mode, token, endpoint="finish", settle_seconds=6):
    capture = cv2.VideoCapture(str(path))
    fps = capture.get(cv2.CAP_PROP_FPS) or 25
    count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    maximum = 7.8 if mode == "phrase" else 120
    if not capture.isOpened() or not 0.7 <= count / fps <= maximum:
        capture.release()
        raise ValueError(f"Use a decodable clip between 0.7 and {maximum} seconds in {mode} mode.")
    url = server.replace("https://", "wss://").replace("http://", "ws://") + "/api/stream"
    events, finish_sent = [], False
    try:
        async with websockets.connect(url, origin=server, max_size=300000, open_timeout=15) as ws:
            await ws.send(json.dumps({"token": token, "mode": mode, "conversation": False}))
            hello = json.loads(await ws.recv())
            if hello.get("type") != "connected":
                raise ValueError(hello.get("message", "Camera not ready."))
            start = time.monotonic()

            async def receive():
                while True:
                    event = json.loads(await ws.recv())
                    event.update(
                        received_seconds=time.monotonic() - start, after_finish=finish_sent
                    )
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
                last_frame = (index - 1) / fps
                if endpoint == "natural":
                    # The clip must include its own recorded pause; no synthetic tail.
                    await asyncio.sleep(settle_seconds)
                finish_sent = True
                await ws.send(json.dumps({"type": "finish"}))
                await asyncio.wait_for(receiver, 90)
            finally:
                if not receiver.done():
                    receiver.cancel()
                    await asyncio.gather(receiver, return_exceptions=True)
    finally:
        capture.release()
    finals = selected_events(events, hello.get("visual_turns", False), endpoint)
    drafts = [
        e
        for e in events
        if e["type"] == "draft" and not (endpoint == "natural" and e["after_finish"])
    ]
    return {
        "hello": hello,
        "finals": finals,
        "events": events,
        "prediction": " ".join(e["text"] for e in finals),
        "accepted": bool(finals) and all(e.get("auto_send") is not False for e in finals),
        "auto_send_count": sum(e.get("auto_send") is not False for e in finals),
        "first_draft_seconds": drafts[0]["received_seconds"] if drafts else None,
        "final_from_start_seconds": finals[-1]["received_seconds"] if finals else None,
        "final_after_last_frame_seconds": finals[-1]["received_seconds"] - last_frame
        if finals
        else None,
        "last_frame_seconds": last_frame,
        "capture_to_draft_seconds": [e["received_seconds"] - e["capture_end"] for e in drafts],
    }


async def assist(result, context, client):
    """Ablate the existing selector on identical exposed candidates, never rewrite."""
    predictions, decisions = [], []
    for entry in result["finals"]:
        candidates = [entry["text"], *entry.get("alternatives", [])][:4]
        started = time.monotonic()
        if entry.get("auto_send") is False or len(candidates) < 2:
            decisions.append(
                {"skipped": "held reading or no exposed alternatives", "candidates": candidates}
            )
            predictions.append(entry["text"])
            continue
        response = await client.post(
            "/api/provider/assist", json={"candidates": candidates, "context": context}
        )
        response.raise_for_status()
        decision = response.json()
        if decision["text"] not in candidates:
            raise ValueError("Selection changed words outside the candidates.")
        decisions.append(
            {
                "candidates": candidates,
                "selection": decision,
                "added_seconds": time.monotonic() - started,
            }
        )
        predictions.append(decision["text"])
    return {
        "prediction": " ".join(predictions),
        "decisions": decisions,
        "added_seconds": sum(d.get("added_seconds", 0) for d in decisions),
    }


async def plan_intent(text, context, provider, research_available):
    # Reuse exactly the existing planner/validator. No AgentStore or execution.
    from agent import INSTRUCTIONS, SCHEMA, validate_plan

    async with asyncio.timeout(30):
        raw = await provider.snapshot().complete(
            INSTRUCTIONS,
            json.dumps(
                {
                    "request": text,
                    "source": "lip_prediction",
                    "conversation": context,
                    "capabilities": {"research_available": research_available},
                }
            ),
            schema=SCHEMA,
            maximum=3000,
        )
    return validate_plan(raw)["actions"]


def validate_records(records, manifest):
    if not records or len({r["id"] for r in records}) != len(records):
        raise ValueError("Provide a nonempty manifest with unique id values.")
    splits = {}
    for row in records:
        if row.get("split") not in {"diagnostic", "validation", "heldout"}:
            raise ValueError("Label split as diagnostic, validation or heldout.")
        if row.get("capture_kind") not in {
            "silent_mouthing",
            "voiced",
            "no_speech",
            "synthetic",
            "unknown",
        }:
            raise ValueError(
                "Label capture_kind explicitly. Muting voiced speech is not silent mouthing."
            )
        if row["split"] != "diagnostic" and (
            not row.get("speaker") or not isinstance(row.get("reference"), str)
        ):
            raise ValueError(
                "Validation/heldout clips require known speakers and reference transcripts."
            )
        if row.get("expected_silence") and row.get("reference") != "":
            raise ValueError("No-speech controls require an empty reference.")
        path = (manifest.parent / row["video"]).resolve()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        row["video_sha256"] = digest
        for key in ["speaker:" + row.get("speaker", "unknown"), "video:" + digest]:
            splits.setdefault(key, set()).add(row["split"])
        if tokens(row.get("reference")):
            splits.setdefault("sentence:" + " ".join(tokens(row["reference"])), set()).add(
                row["split"]
            )
        if row.get("context") is not None and not isinstance(row["context"], str):
            raise ValueError("Context must be a fixed inference-time string.")
    if any("validation" in s and "heldout" in s for s in splits.values()):
        raise ValueError(
            "Speaker, sentence or identical video leaked between validation and heldout."
        )


async def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path)
    p.add_argument("--server", default="http://127.0.0.1:8765")
    p.add_argument("--token-file", type=Path, default=ROOT / ".runtime/access-token")
    p.add_argument("--mode", choices=["live", "phrase"], default="live")
    p.add_argument("--endpoint", choices=["finish", "natural"], default="finish")
    p.add_argument("--settle-seconds", type=float, default=6)
    p.add_argument("--assist", action="store_true")
    p.add_argument(
        "--plan-intents",
        action="store_true",
        help="Dry-run existing planner using matching provider env, never execute",
    )
    p.add_argument(
        "--annotations", type=Path, help="JSONL: id, prediction, meaning_change boolean, note"
    )
    p.add_argument("--compare", type=Path)
    p.add_argument(
        "--validation-manifest",
        type=Path,
        help="Check held-out speaker/sentence/clip separation against earlier tuning data",
    )
    p.add_argument("--report", type=Path, default=ROOT / ".runtime/evaluation.json")
    args = p.parse_args()
    if not 0 <= args.settle_seconds <= 15 or args.endpoint == "natural" and args.mode != "live":
        p.error("Natural endpointing requires live mode; settle-seconds must be 0–15.")
    records = [json.loads(line) for line in args.manifest.read_text().splitlines() if line.strip()]
    validate_records(records, args.manifest)
    if args.validation_manifest:
        tuning = [
            json.loads(line)
            for line in args.validation_manifest.read_text().splitlines()
            if line.strip()
        ]
        if any(r.get("split") != "validation" for r in tuning):
            raise ValueError("The validation manifest must contain only validation records.")
        for r in tuning:
            r["video"] = str((args.validation_manifest.parent / r["video"]).resolve())
        validate_records(tuning + records, args.manifest)
    annotations = (
        {
            r["id"]: r
            for r in (
                json.loads(line)
                for line in args.annotations.read_text().splitlines()
                if line.strip()
            )
        }
        if args.annotations
        else {}
    )
    token = args.token_file.read_text().strip()
    rows = []
    async with httpx.AsyncClient(
        base_url=args.server, headers={"Authorization": "Bearer " + token}, timeout=40
    ) as client:
        response = await client.get("/api/status")
        response.raise_for_status()
        status = response.json()
        response = await client.get("/api/provider/config")
        response.raise_for_status()
        config = response.json()
        if status["status"] != "ready" or status["active_session"]:
            raise ValueError("Wait for a ready, idle camera service.")
        planner = None
        if args.plan_intents:
            from provider import TextProvider

            planner = TextProvider()
            if not planner.enabled or any(
                planner.config()[k] != config[k] for k in ["model", "protocol", "base_url"]
            ):
                raise ValueError(
                    "Dry-run planner needs matching provider environment; keys held only in server memory cannot be reused here."
                )
        for record in records:
            result = await clip(
                (args.manifest.parent / record["video"]).resolve(),
                args.server,
                args.mode,
                token,
                args.endpoint,
                args.settle_seconds,
            )
            row = {
                **record,
                **result,
                **score(
                    record.get("reference"), result["prediction"], record.get("critical_spans", [])
                ),
            }
            end = record.get("speech_end_seconds")
            row["final_after_speech_end_seconds"] = (
                result["final_from_start_seconds"] - end
                if end is not None and result["final_from_start_seconds"] is not None
                else None
            )
            row["intent_correct"] = None
            if planner is not None and "expected_actions" in record:
                started = time.monotonic()
                actions = (
                    await plan_intent(
                        result["prediction"],
                        record.get("agent_context", []),
                        planner,
                        config.get("research_available", False),
                    )
                    if result["prediction"]
                    else []
                )
                row.update(
                    planned_actions=actions,
                    intent_correct=action_match(record["expected_actions"], actions),
                    planner_seconds=time.monotonic() - started,
                )
            if args.assist:
                row["assist_ablation"] = await assist(result, record.get("context", ""), client)
                row["assist_ablation"]["metrics"] = score(
                    record.get("reference"),
                    row["assist_ablation"]["prediction"],
                    record.get("critical_spans", []),
                )
            annotation = annotations.get(record["id"])
            if annotation:
                if (
                    annotation["prediction"] != result["prediction"]
                    or type(annotation.get("meaning_change")) is not bool
                ):
                    raise ValueError(
                        "Semantic reviews require the exact output and a boolean meaning_change."
                    )
                row["semantic_review"] = annotation
            rows.append(row)
            print(
                json.dumps(
                    {
                        k: row[k]
                        for k in ["id", "prediction", "wer", "accepted", "final_from_start_seconds"]
                    }
                ),
                flush=True,
            )
    report = {
        "schema_version": 2,
        "mode": args.mode,
        "endpoint": args.endpoint,
        "settle_seconds": args.settle_seconds,
        "jpeg_quality": 90,
        "resize_long_edge": 800,
        "server_status": status,
        "provider_config": config,
        "inference_context": "Only explicit context/agent_context. References and annotations withheld. Recognition receives JPEGs and timestamps only.",
        "intent_mode": "isolated planner, no execution"
        if args.plan_intents
        else "not measured; matching provider env required for --plan-intents",
        "summary": summarize(rows),
        "results": rows,
    }
    report["by_split"] = {
        s: summarize([r for r in rows if r["split"] == s])
        for s in sorted({r["split"] for r in rows})
    }
    if args.compare:
        report["comparison"] = compare(json.loads(args.compare.read_text()), report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"]), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
