"""One authenticated camera session, independent of HTTP routing and app startup."""

import asyncio
import contextlib
import json
import logging
import os
import secrets
import time
from collections import deque

from fastapi import WebSocketDisconnect

from config import (
    DRAFT_CONTEXT_SECONDS,
    MAX_DECODE_SECONDS,
    MIN_CAPTURE_SECONDS,
    PHRASE_LIMIT_SECONDS,
    PROTOCOL_VERSION,
)
from engine import CaptureError, NoSpeech, decode_frame
from recognition_guard import RecognitionGuard, review_reason
from stream_buffer import StreamBuffer
from turn_taking import Utterances

log = logging.getLogger("lipread")


class StreamSession:
    def __init__(self, runtime, ws, hello):
        self.runtime = runtime
        self.ws = ws
        self.hello = hello

    async def prepare(self):
        self.loop = asyncio.get_running_loop()
        await self.loop.run_in_executor(
            self.runtime.executor, self.runtime.state["reader"].begin_session
        )
        self.mouth = self.runtime.state.get("mouth")
        self.visual = self.mouth is not None
        if self.visual:
            await self.loop.run_in_executor(self.runtime.mouth_executor, self.mouth.reset)
        self.session_id = secrets.token_urlsafe(12)
        self.sessions = self.runtime.state.setdefault("turn_sessions", {})
        self.sessions[self.session_id] = {"turn": 0, "at": time.monotonic()}
        for old in list(self.sessions)[:-8]:
            self.sessions.pop(old, None)
        self.conversation = self.hello.get("conversation") is True
        self.mode = self.hello.get("mode", "live")
        self.mode = self.mode if self.mode in {"live", "phrase"} else "live"
        self.buffer = StreamBuffer()
        self.guard = RecognitionGuard(
            preserve_holds=os.getenv("LIPREAD_PRESERVE_HOLDS", "0") == "1"
        )
        self.utterances = Utterances()
        self.closing = False
        self.draining = False
        self.cuts = deque()
        self.task = self.quality_task = self.mouth_task = None
        self.last_timestamp = self.last_quality = self.last_mouth = -1.0
        self.last_analysis = None
        self.active_turn = 0
        self.speech_open = False
        self.mouth_speaking = False
        self.send_lock = asyncio.Lock()
        self.rate_start, self.rate_count = (time.monotonic(), 0)

    async def send(self, data):
        async with self.send_lock:
            await self.ws.send_json(data)

    async def native(self, pool, function, *args):
        future = asyncio.get_running_loop().run_in_executor(pool, function, *args)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await future
            raise

    async def check_quality(self, frame):
        try:
            await self.send(
                await self.native(
                    self.runtime.quality_executor, self.runtime.state["monitor"].check, frame
                )
            )
        except Exception:
            log.debug("Framing feedback failed", exc_info=True)

    async def finish_turn(self, turn_id, endpoint):
        turn = self.utterances.turns.get(turn_id)
        if turn and turn["sent"]:
            return
        result = self.utterances.finish(turn_id, endpoint)
        if result:
            if result["auto_send"]:
                result.update(self.guard.assess(result, endpoint))
            if turn_id < self.active_turn:
                result.update(
                    auto_send=False,
                    needs_review=True,
                    review_reason="A newer phrase superseded this reading.",
                )
            if len(result["text"]) > 1200:
                result.update(
                    auto_send=False,
                    needs_review=True,
                    review_reason="That turn was too long. Try a shorter request.",
                )
            await self.send({**result, "session_id": self.session_id})
        else:
            await self.send(
                {"type": "abstained", "silent": True, "capture_end": endpoint, "turn_id": turn_id}
            )

    def cut(self, timestamp, turn_id):
        if timestamp < 0:
            return
        if not self.cuts or timestamp > self.cuts[-1][0] + 0.04:
            if len(self.cuts) < 8:
                self.cuts.append((timestamp, turn_id))
        self.schedule()

    async def check_mouth(self, frame, timestamp):
        try:
            activity = await self.native(
                self.runtime.mouth_executor, self.mouth.check, frame, timestamp
            )
            if activity["event"] == "started":
                start = (
                    activity["speech_start"]
                    if activity.get("speech_start") is not None
                    else timestamp
                )
                if not self.speech_open and (not self.cuts):
                    while self.buffer.frames and self.buffer.frames[0][0] < start - 0.35:
                        self.buffer.frames.popleft()
                self.active_turn += 1
                self.speech_open = True
                self.mouth_speaking = True
                self.sessions[self.session_id]["turn"] = self.active_turn
                self.utterances.start(self.active_turn, start)
                activity["interrupted"] = (
                    self.runtime.agent_store.interrupt() if self.conversation else []
                )
            elif activity["event"] == "stopped":
                self.mouth_speaking = False
                if self.mode == "live":
                    self.cut(timestamp, self.active_turn)
            await self.send(
                {**activity, "turn_id": self.active_turn, "session_id": self.session_id}
            )
            self.schedule()
        except Exception:
            log.warning("Lip activity feedback failed", exc_info=True)

    async def recognize(self, samples, segment, force_final=False, turn_id=0, ending=False):
        endpoint = samples[-1][0]
        async with self.runtime.inference_lock:
            try:
                if (
                    force_final
                    and self.last_analysis
                    and (self.last_analysis[0] == segment)
                    and (abs(self.last_analysis[1] - endpoint) < 0.08)
                ):
                    analysis = self.last_analysis[2]
                else:
                    analysis = await self.native(
                        self.runtime.executor, self.runtime.state["reader"].analyze, samples
                    )
                self.last_analysis = (segment, endpoint, analysis)
                metadata = analysis["metadata"]
                if metadata["text"] and (
                    not review_reason(metadata["text"], duration=metadata.get("duration"))
                ):
                    await self.send(
                        {
                            **metadata,
                            "type": "draft",
                            "sequence": segment,
                            "mode": self.mode,
                            "capture_end": endpoint,
                            "turn_id": turn_id,
                        }
                    )
                paused = (
                    not self.visual
                    and self.mode == "live"
                    and (metadata["duration"] >= 2.5)
                    and (metadata["trailing_blank_seconds"] >= 0.9)
                    and (len(metadata["text"].split()) >= 2)
                )
                if force_final or paused or metadata["duration"] >= MAX_DECODE_SECONDS:
                    await self.send(
                        {"type": "processing", "sequence": segment, "phase": "refining"}
                    )
                    result = await self.native(
                        self.runtime.executor,
                        self.runtime.state["reader"].refine,
                        analysis,
                        self.mode == "phrase",
                    )
                    if self.visual:
                        self.utterances.add(turn_id, segment, result)
                    else:
                        result.update(self.guard.assess(result, endpoint))
                    await self.send(
                        {
                            **result,
                            "sequence": segment,
                            "mode": self.mode,
                            "capture_end": endpoint,
                            "turn_id": turn_id,
                            "visual_turns": self.visual,
                            "awaiting_pause": self.visual and (not ending),
                        }
                    )
                    self.buffer.finalize(endpoint)
                    self.last_analysis = None
                    if self.visual and ending:
                        await self.finish_turn(turn_id, endpoint)
                        if turn_id == self.active_turn:
                            self.speech_open = self.mouth_speaking
            except CaptureError as exc:
                if not isinstance(exc, NoSpeech):
                    await self.send({"type": "guidance", "message": str(exc), "sequence": segment})
                if force_final:
                    self.buffer.finalize(endpoint)
                    self.last_analysis = None
                    if self.visual and ending:
                        await self.finish_turn(turn_id, endpoint)
                        if turn_id == self.active_turn:
                            self.speech_open = self.mouth_speaking
                    else:
                        await self.send(
                            {
                                "type": "abstained",
                                "silent": isinstance(exc, NoSpeech),
                                "message": str(exc),
                                "sequence": segment,
                                "capture_end": endpoint,
                            }
                        )
            except Exception:
                log.exception("Recognition failed")
                await self.send(
                    {
                        "type": "error",
                        "message": "Could not read that phrase. Try again.",
                        "sequence": segment,
                    }
                )
                if force_final:
                    self.buffer.finalize(endpoint)
                    self.last_analysis = None
            finally:
                await self.send({"type": "ready"})

    async def finish_short(self, turn_id, endpoint):
        if self.visual:
            await self.finish_turn(turn_id, endpoint)
        if turn_id == self.active_turn:
            self.speech_open = self.mouth_speaking

    def launch(self, coro):
        job = asyncio.create_task(coro)
        job.add_done_callback(lambda done: self.schedule())
        return job

    def schedule(self):
        if self.closing or self.draining:
            return
        if self.task and (not self.task.done()):
            return
        if self.task:
            completed = self.task
            self.task = None
            if not completed.cancelled() and (error := completed.exception()) is not None:
                log.error("Camera task failed", exc_info=(type(error), error, error.__traceback__))
                self.closing = True
                return
        while self.cuts and self.cuts[0][0] <= self.buffer.consumed:
            endpoint, tid = self.cuts.popleft()
            self.task = self.launch(self.finish_short(tid, endpoint))
            return
        if self.visual and (not self.speech_open) and (not self.cuts):
            return
        final = bool(self.cuts) or self.buffer.duration() >= MAX_DECODE_SECONDS
        if not final and (not self.buffer.due()):
            return
        cutoff, tid = self.cuts[0] if self.cuts else (None, self.active_turn)
        samples = self.buffer.snapshot(cutoff)
        if not samples:
            if self.cuts:
                self.cuts.popleft()
                self.task = self.launch(self.finish_short(tid, cutoff))
            return
        ending = bool(self.cuts)
        if ending:
            self.cuts.popleft()
        if final and samples[-1][0] - samples[0][0] < MIN_CAPTURE_SECONDS:
            self.buffer.finalize(samples[-1][0])
            if ending:
                self.task = self.launch(self.finish_short(tid, samples[-1][0]))
            return
        self.buffer.last_draft = samples[-1][0]
        self.task = self.launch(self.recognize(samples, self.buffer.segment, final, tid, ending))

    async def run(self):
        await self.prepare()
        await self.send(
            {
                "type": "connected",
                "mode": self.mode,
                "draft_after_seconds": DRAFT_CONTEXT_SECONDS,
                "version": PROTOCOL_VERSION,
                "visual_turns": self.visual,
                "session_id": self.session_id,
            }
        )
        try:
            while not self.closing:
                message = await asyncio.wait_for(self.ws.receive(), 25)
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    self.rate_count += 1
                    elapsed = time.monotonic() - self.rate_start
                    if elapsed > 2:
                        if self.rate_count / elapsed > 45:
                            await self.ws.close(code=1008, reason="Frame rate limit exceeded")
                            break
                        self.rate_start, self.rate_count = (time.monotonic(), 0)
                    try:
                        timestamp, frame = decode_frame(message["bytes"])
                        if timestamp <= self.last_timestamp or (
                            self.last_timestamp >= 0 and timestamp - self.last_timestamp > 15
                        ):
                            raise CaptureError("Camera timing changed. Restart the camera.")
                    except CaptureError as exc:
                        await self.send({"type": "guidance", "message": str(exc)})
                        continue
                    self.last_timestamp = timestamp
                    self.buffer.add(timestamp, frame)
                    if timestamp - self.last_quality >= 0.65 and (
                        self.quality_task is None or self.quality_task.done()
                    ):
                        self.last_quality = timestamp
                        self.quality_task = asyncio.create_task(self.check_quality(frame))
                    if (
                        self.visual
                        and timestamp - self.last_mouth >= 0.12
                        and (self.mouth_task is None or self.mouth_task.done())
                    ):
                        self.last_mouth = timestamp
                        self.mouth_task = asyncio.create_task(self.check_mouth(frame, timestamp))
                    self.schedule()
                    if self.mode == "phrase" and timestamp >= PHRASE_LIMIT_SECONDS:
                        await self.send({"type": "phrase_limit"})
                elif message.get("text"):
                    if len(message["text"]) > 1024:
                        break
                    control = json.loads(message["text"])
                    if not isinstance(control, dict):
                        raise ValueError("Camera controls must be objects.")
                    if control.get("type") == "ping":
                        await self.send({"type": "pong"})
                    elif control.get("type") == "conversation":
                        self.conversation = control.get("enabled") is True
                    elif control.get("type") in {"commit", "finish"}:
                        if self.visual and (not self.active_turn):
                            self.active_turn += 1
                            self.sessions[self.session_id]["turn"] = self.active_turn
                            self.utterances.start(
                                self.active_turn,
                                self.buffer.frames[0][0] if self.buffer.frames else 0,
                            )
                        if control["type"] == "commit":
                            self.cut(self.last_timestamp, self.active_turn)
                        else:
                            self.draining = True
                            if self.mouth_task:
                                await self.mouth_task
                            if self.task:
                                await self.task
                            while self.cuts:
                                cutoff, tid = self.cuts.popleft()
                                piece = self.buffer.snapshot(cutoff)
                                if piece and piece[-1][0] - piece[0][0] >= MIN_CAPTURE_SECONDS:
                                    await self.recognize(
                                        piece, self.buffer.segment, True, tid, True
                                    )
                                else:
                                    await self.finish_turn(tid, cutoff)
                            remaining = self.buffer.snapshot()
                            if remaining and self.buffer.duration() >= MIN_CAPTURE_SECONDS:
                                await self.recognize(
                                    remaining,
                                    self.buffer.segment,
                                    True,
                                    self.active_turn,
                                    self.visual,
                                )
                            elif self.visual:
                                await self.finish_turn(self.active_turn, self.last_timestamp)
                            await self.send({"type": "finished"})
                            break
        except (WebSocketDisconnect, asyncio.TimeoutError):
            pass
        except (ValueError, TypeError, KeyError):
            with contextlib.suppress(Exception):
                await self.send(
                    {"type": "error", "message": "Camera message was invalid. Restart the camera."}
                )
        finally:
            self.closing = True
            for job in (self.task, self.quality_task, self.mouth_task):
                if job and (not job.done()):
                    job.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await job
            self.buffer.frames.clear()
            self.last_analysis = None
            with contextlib.suppress(Exception):
                await self.ws.close()
