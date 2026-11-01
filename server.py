"""Authenticated visual-only camera streaming with provisional and refined captions."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import os
import secrets
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from engine import CaptureError, NoSpeech, LipReader, QualityMonitor, decode_frame
from openai_bridge import OpenAIBridge, BridgeError
from video_export import export_mp4, ExportError
from provider import TextProvider, ProviderError
from agent import AgentStore
from recognition_guard import RecognitionGuard, review_reason
from turn_taking import MouthMonitor, Utterances

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime"
RUNTIME.mkdir(exist_ok=True)
TOKEN_FILE = RUNTIME / "access-token"
if not TOKEN_FILE.exists():
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(secrets.token_urlsafe(32))
TOKEN = TOKEN_FILE.read_text().strip()
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lipread")
quality_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="framing")
mouth_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lip-activity")
state = {
    "mouth": None,
    "status": "loading",
    "detail": "Warming up recognition…",
    "reader": None,
    "monitor": None,
}
inference_lock = asyncio.Lock()
session_lock = asyncio.Lock()
log = logging.getLogger("lipread")
openai_bridge = OpenAIBridge()
provider = TextProvider()
agent_store = AgentStore(RUNTIME / "agent.sqlite3")
export_lock = asyncio.Lock()
voice_lock = asyncio.Lock()


class StreamBuffer:
    """Keep one utterance; drafts revise it, and finalization consumes it once."""

    def __init__(self):
        self.frames = deque(maxlen=260)
        self.segment = 1
        self.consumed = -1.0
        self.last_draft = -1.0

    def add(self, timestamp, frame):
        if timestamp > self.consumed:
            self.frames.append((timestamp, frame))
        while self.frames and timestamp - self.frames[0][0] > 9.8:
            self.frames.popleft()

    def snapshot(self, cutoff=None):
        return [(t, f) for t, f in self.frames if cutoff is None or t <= cutoff]

    def duration(self, cutoff=None):
        frames = self.snapshot(cutoff)
        return frames[-1][0] - frames[0][0] if frames else 0.0

    def due(self):
        return self.duration() >= 1.35 and self.frames[-1][0] - self.last_draft >= 0.9

    def finalize(self, endpoint):
        self.consumed = max(self.consumed, endpoint)
        while self.frames and self.frames[0][0] <= self.consumed:
            self.frames.popleft()
        self.segment += 1
        self.last_draft = -1.0


async def load_model():
    loop = asyncio.get_running_loop()
    try:
        reader, monitor = await asyncio.gather(
            loop.run_in_executor(executor, LipReader),
            loop.run_in_executor(quality_executor, QualityMonitor),
        )
        mouth_path = ROOT / "models/face_landmarker.task"
        mouth = (
            await loop.run_in_executor(mouth_executor, lambda: MouthMonitor(mouth_path))
            if mouth_path.exists()
            else None
        )
        state.update(
            reader=reader, monitor=monitor, mouth=mouth, status="ready", detail="Ready to read"
        )
        log.warning("Lip-reading ready. Encoder: %s. Audio disabled.", reader.device)
    except Exception:
        log.exception("Model loading failed")
        state.update(
            status="error", detail="Recognition could not start. Check the computer service."
        )


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(load_model())
    worker = asyncio.create_task(agent_store.worker(provider))
    yield
    task.cancel()
    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker
    executor.shutdown(wait=False, cancel_futures=True)
    quality_executor.shutdown(wait=False, cancel_futures=True)
    mouth_executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
origin_file = RUNTIME / "site-origin"
SITE_ORIGIN = os.getenv(
    "LIPREAD_SITE_ORIGIN", origin_file.read_text().strip() if origin_file.exists() else ""
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[SITE_ORIGIN] if SITE_ORIGIN else [],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def headers(request, call_next):
    response = await call_next(request)
    response.headers.update(
        {
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Permissions-Policy": "camera=(self), microphone=()",
            "Cache-Control": "no-store",
        }
    )
    return response


@app.get("/api/status")
async def status(authorization: str = Header(default="")):
    try:
        authenticated = hmac.compare_digest(authorization, "Bearer " + TOKEN)
    except TypeError:
        authenticated = False
    if not authenticated:
        raise HTTPException(401, "Open your private phone link to connect.")
    return {
        "status": state["status"],
        "detail": state["detail"],
        "model": "Auto-AVSR",
        "audio": False,
        "device": getattr(state["reader"], "device", None),
        "draft_after_seconds": 1.35,
        "active_session": session_lock.locked(),
        "version": 4,
        "agent_configured": provider.enabled,
        "visual_turns": state.get("mouth") is not None,
    }


def authorize_request(request):
    try:
        valid = hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + TOKEN)
    except TypeError:
        valid = False
    if not valid:
        raise HTTPException(401, "Open your private connected link first.")


async def small_json(request, maximum=8000):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > maximum:
            raise HTTPException(413, "The request is too large.")
    try:
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        # Never echo request bodies: one of these endpoints accepts API keys.
        raise HTTPException(400, "The request body is invalid.") from None


@app.get("/api/provider/config")
async def provider_config(request: Request):
    authorize_request(request)
    return provider.config()


@app.post("/api/provider/config")
async def provider_connect(request: Request):
    authorize_request(request)
    if any(job["state"] in {"queued", "thinking", "researching"} for job in agent_store.list()):
        raise HTTPException(409, "Wait for queued requests before changing the model connection.")
    body = await small_json(request, 2000)
    try:
        result = await provider.configure(body)
        # The optional speech adapter supports this particular endpoint only.
        openai_bridge.key = provider.key if result["voice_available"] else ""
        return result
    except ProviderError as exc:
        raise HTTPException(400, str(exc)) from None


@app.delete("/api/provider/config")
async def provider_disconnect(request: Request):
    authorize_request(request)
    openai_bridge.disconnect()
    return provider.disconnect()


@app.post("/api/provider/assist")
async def provider_assist(request: Request):
    authorize_request(request)
    body = await small_json(request)
    try:
        return await provider.snapshot().assist(body.get("candidates"), body.get("context", ""))
    except ProviderError as exc:
        raise HTTPException(400, str(exc)) from None


@app.post("/api/provider/voice")
async def provider_voice(request: Request):
    authorize_request(request)
    if not provider.config()["voice_available"]:
        raise HTTPException(400, "Speech output is unavailable for this connection.")
    body = await small_json(request, 1800)
    if voice_lock.locked():
        raise HTTPException(429, "A voice is already processing.")
    bridge = OpenAIBridge(key=provider.key)
    try:
        async with voice_lock:
            audio = await bridge.voice(body.get("text"))
        return Response(audio, media_type="audio/wav")
    except BridgeError:
        raise HTTPException(
            400, "Speech generation failed. Check speech model access and quota."
        ) from None


@app.get("/api/agent/jobs")
async def agent_jobs(request: Request):
    authorize_request(request)
    return {"jobs": agent_store.list(), "timers": agent_store.timers(), "server_time": time.time()}


@app.post("/api/agent/jobs")
async def agent_submit(request: Request):
    authorize_request(request)
    body = await small_json(request, 3000)
    if not provider.enabled:
        raise HTTPException(400, "Connect a model in Settings first.")
    session = body.get("session_id")
    if session is not None:
        current = state.get("turn_sessions", {}).get(session)
        if not current or current["turn"] != body.get("turn_id"):
            raise HTTPException(409, "A newer spoken turn superseded that request.")
    try:
        return agent_store.submit(body.get("text"), body.get("source"), body.get("request_id"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@app.post("/api/agent/interrupt")
async def interrupt_agent(request: Request):
    authorize_request(request)
    return {"interrupted": agent_store.interrupt()}


@app.post("/api/agent/jobs/{job_id}/{operation}")
async def agent_operation(job_id: str, operation: str, request: Request):
    authorize_request(request)
    try:
        if operation == "confirm":
            return agent_store.confirm(job_id)
        if operation == "cancel":
            return agent_store.cancel(job_id)
        if operation == "dismiss":
            return agent_store.dismiss(job_id)
        raise ValueError("Unknown operation.")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/openai/config")
async def openai_config(request: Request):
    authorize_request(request)
    return openai_bridge.config()


@app.post("/api/openai/config")
async def connect_openai(request: Request):
    authorize_request(request)
    body = await small_json(request, 1500)
    try:
        return await openai_bridge.connect_key(body.get("key"))
    except BridgeError as exc:
        raise HTTPException(400, str(exc)) from None


@app.delete("/api/openai/config")
async def forget_openai(request: Request):
    authorize_request(request)
    return openai_bridge.disconnect()


@app.post("/api/openai/assist")
async def assist_openai(request: Request):
    authorize_request(request)
    body = await small_json(request)
    try:
        return await openai_bridge.assist(body.get("candidates"), body.get("context", ""))
    except BridgeError as exc:
        raise HTTPException(400, str(exc)) from None


@app.post("/api/openai/voice")
async def voice_openai(request: Request):
    authorize_request(request)
    body = await small_json(request, 1800)
    if voice_lock.locked():
        raise HTTPException(429, "One voice is already being generated.")
    try:
        async with voice_lock:
            audio = await openai_bridge.voice(body.get("text"))
        return Response(
            audio, media_type="audio/wav", headers={"X-Voice-Source": "openai-generated"}
        )
    except BridgeError as exc:
        raise HTTPException(400, str(exc)) from None


@app.post("/api/export")
async def export_recording(request: Request):
    authorize_request(request)
    if export_lock.locked():
        raise HTTPException(429, "An export is already processing.")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 40_000_000:
            raise HTTPException(413, "Record a shorter clip, up to 45 seconds.")
    try:
        async with export_lock:
            result = await asyncio.to_thread(export_mp4, bytes(data))
        return Response(
            result,
            media_type="video/mp4",
            headers={"Content-Disposition": 'attachment; filename="lipread-studio.mp4"'},
        )
    except ExportError as exc:
        raise HTTPException(400, str(exc)) from None


@app.websocket("/api/stream")
async def stream(ws: WebSocket):
    origin = ws.headers.get("origin", "")
    own = {f"https://{ws.headers.get('host')}", f"http://{ws.headers.get('host')}"}
    if origin not in own | {SITE_ORIGIN}:
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        hello = await asyncio.wait_for(ws.receive_json(), 8)
        if (
            not isinstance(hello, dict)
            or not isinstance(hello.get("token"), str)
            or not hmac.compare_digest(hello["token"], TOKEN)
        ):
            await ws.close(code=1008, reason="Invalid access key")
            return
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, TypeError):
        with contextlib.suppress(Exception):
            await ws.close(code=1008)
        return
    if state["status"] != "ready" or session_lock.locked():
        await ws.send_json(
            {
                "type": "error",
                "message": state["detail"]
                if state["status"] != "ready"
                else "Another camera is connected. Stop that session first.",
            }
        )
        await ws.close(code=1013)
        return
    async with session_lock:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(executor, state["reader"].begin_session)
        mouth = state.get("mouth")
        visual = mouth is not None
        if visual:
            await loop.run_in_executor(mouth_executor, mouth.reset)
        session_id = secrets.token_urlsafe(12)
        sessions = state.setdefault("turn_sessions", {})
        sessions[session_id] = {"turn": 0, "at": time.monotonic()}
        for old in list(sessions)[:-8]:
            sessions.pop(old, None)
        conversation = hello.get("conversation") is True
        mode = hello.get("mode", "live")
        mode = mode if mode in {"live", "phrase"} else "live"
        buffer = StreamBuffer()
        guard = RecognitionGuard(preserve_holds=os.getenv("LIPREAD_PRESERVE_HOLDS", "0") == "1")
        utterances = Utterances()
        closing = False
        draining = False
        cuts = deque()
        task = quality_task = mouth_task = None
        last_timestamp = last_quality = last_mouth = -1.0
        last_analysis = None
        active_turn = 0
        speech_open = False
        mouth_speaking = False
        send_lock = asyncio.Lock()
        rate_start, rate_count = time.monotonic(), 0

        async def send(data):
            async with send_lock:
                await ws.send_json(data)

        async def native(pool, function, *args):
            future = asyncio.get_running_loop().run_in_executor(pool, function, *args)
            try:
                return await asyncio.shield(future)
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    await future
                raise

        async def check_quality(frame):
            try:
                await send(await native(quality_executor, state["monitor"].check, frame))
            except Exception:
                log.debug("Framing feedback failed", exc_info=True)

        async def finish_turn(turn_id, endpoint):
            turn = utterances.turns.get(turn_id)
            if turn and turn["sent"]:
                return
            result = utterances.finish(turn_id, endpoint)
            if result:
                result.update(guard.assess(result, endpoint))
                if turn_id < active_turn:
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
                await send({**result, "session_id": session_id})
            else:
                await send(
                    {
                        "type": "abstained",
                        "silent": True,
                        "capture_end": endpoint,
                        "turn_id": turn_id,
                    }
                )

        def cut(timestamp, turn_id):
            if timestamp < 0:
                return
            if not cuts or timestamp > cuts[-1][0] + 0.04:
                if len(cuts) < 8:
                    cuts.append((timestamp, turn_id))
            schedule()

        async def check_mouth(frame, timestamp):
            nonlocal active_turn, speech_open, mouth_speaking
            try:
                activity = await native(mouth_executor, mouth.check, frame, timestamp)
                if activity["event"] == "started":
                    start = (
                        activity["speech_start"]
                        if activity.get("speech_start") is not None
                        else timestamp
                    )
                    if not speech_open and not cuts:
                        while buffer.frames and buffer.frames[0][0] < start - 0.35:
                            buffer.frames.popleft()
                    active_turn += 1
                    speech_open = True
                    mouth_speaking = True
                    sessions[session_id]["turn"] = active_turn
                    utterances.start(active_turn, start)
                    activity["interrupted"] = agent_store.interrupt() if conversation else []
                elif activity["event"] == "stopped":
                    mouth_speaking = False
                    if mode == "live":
                        cut(timestamp, active_turn)
                await send({**activity, "turn_id": active_turn, "session_id": session_id})
                schedule()
            except Exception:
                log.warning("Lip activity feedback failed", exc_info=True)

        async def recognize(samples, segment, force_final=False, turn_id=0, ending=False):
            nonlocal last_analysis, speech_open
            endpoint = samples[-1][0]
            async with inference_lock:
                try:
                    if (
                        force_final
                        and last_analysis
                        and last_analysis[0] == segment
                        and abs(last_analysis[1] - endpoint) < 0.08
                    ):
                        analysis = last_analysis[2]
                    else:
                        analysis = await native(executor, state["reader"].analyze, samples)
                    last_analysis = (segment, endpoint, analysis)
                    metadata = analysis["metadata"]
                    if metadata["text"] and not review_reason(
                        metadata["text"], duration=metadata.get("duration")
                    ):
                        await send(
                            {
                                **metadata,
                                "type": "draft",
                                "sequence": segment,
                                "mode": mode,
                                "capture_end": endpoint,
                                "turn_id": turn_id,
                            }
                        )
                    paused = (
                        not visual
                        and mode == "live"
                        and metadata["duration"] >= 2.5
                        and metadata["trailing_blank_seconds"] >= 0.9
                        and len(metadata["text"].split()) >= 2
                    )
                    if force_final or paused or metadata["duration"] >= 8:
                        await send({"type": "processing", "sequence": segment, "phase": "refining"})
                        result = await native(
                            executor, state["reader"].refine, analysis, mode == "phrase"
                        )
                        if visual:
                            utterances.add(turn_id, segment, result)
                        else:
                            result.update(guard.assess(result, endpoint))
                        await send(
                            {
                                **result,
                                "sequence": segment,
                                "mode": mode,
                                "capture_end": endpoint,
                                "turn_id": turn_id,
                                "visual_turns": visual,
                                "awaiting_pause": visual and not ending,
                            }
                        )
                        buffer.finalize(endpoint)
                        last_analysis = None
                        if visual and ending:
                            await finish_turn(turn_id, endpoint)
                            if turn_id == active_turn:
                                speech_open = mouth_speaking
                except CaptureError as exc:
                    if not isinstance(exc, NoSpeech):
                        await send({"type": "guidance", "message": str(exc), "sequence": segment})
                    if force_final:
                        buffer.finalize(endpoint)
                        last_analysis = None
                        if visual and ending:
                            await finish_turn(turn_id, endpoint)
                            if turn_id == active_turn:
                                speech_open = mouth_speaking
                        else:
                            await send(
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
                    await send(
                        {
                            "type": "error",
                            "message": "Could not read that phrase. Try again.",
                            "sequence": segment,
                        }
                    )
                    if force_final:
                        buffer.finalize(endpoint)
                        last_analysis = None
                finally:
                    await send({"type": "ready"})

        async def finish_short(turn_id, endpoint):
            nonlocal speech_open
            if visual:
                await finish_turn(turn_id, endpoint)
            if turn_id == active_turn:
                speech_open = mouth_speaking

        def launch(coro):
            job = asyncio.create_task(coro)
            job.add_done_callback(lambda done: schedule())
            return job

        def schedule():
            nonlocal task
            if closing or draining:
                return
            if task and not task.done():
                return
            if task:
                task.result()
                task = None
            while cuts and cuts[0][0] <= buffer.consumed:
                endpoint, tid = cuts.popleft()
                task = launch(finish_short(tid, endpoint))
                return
            if visual and not speech_open and not cuts:
                return
            final = bool(cuts) or buffer.duration() >= 8.0
            if not final and not buffer.due():
                return
            cutoff, tid = cuts[0] if cuts else (None, active_turn)
            samples = buffer.snapshot(cutoff)
            if not samples:
                if cuts:
                    cuts.popleft()
                    task = launch(finish_short(tid, cutoff))
                return
            ending = bool(cuts)
            if ending:
                cuts.popleft()
            if final and samples[-1][0] - samples[0][0] < 0.7:
                buffer.finalize(samples[-1][0])
                if ending:
                    task = launch(finish_short(tid, samples[-1][0]))
                return
            buffer.last_draft = samples[-1][0]
            task = launch(recognize(samples, buffer.segment, final, tid, ending))

        await send(
            {
                "type": "connected",
                "mode": mode,
                "draft_after_seconds": 1.35,
                "version": 2,
                "visual_turns": visual,
                "session_id": session_id,
            }
        )
        try:
            while True:
                message = await asyncio.wait_for(ws.receive(), 25)
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    rate_count += 1
                    elapsed = time.monotonic() - rate_start
                    if elapsed > 2:
                        if rate_count / elapsed > 45:
                            await ws.close(code=1008, reason="Frame rate limit exceeded")
                            break
                        rate_start, rate_count = time.monotonic(), 0
                    try:
                        timestamp, frame = decode_frame(message["bytes"])
                        if timestamp <= last_timestamp or (
                            last_timestamp >= 0 and timestamp - last_timestamp > 15
                        ):
                            raise CaptureError("Camera timing changed. Restart the camera.")
                    except CaptureError as exc:
                        await send({"type": "guidance", "message": str(exc)})
                        continue
                    last_timestamp = timestamp
                    buffer.add(timestamp, frame)
                    if timestamp - last_quality >= 0.65 and (
                        quality_task is None or quality_task.done()
                    ):
                        last_quality = timestamp
                        quality_task = asyncio.create_task(check_quality(frame))
                    if (
                        visual
                        and timestamp - last_mouth >= 0.12
                        and (mouth_task is None or mouth_task.done())
                    ):
                        last_mouth = timestamp
                        mouth_task = asyncio.create_task(check_mouth(frame, timestamp))
                    schedule()
                    if mode == "phrase" and timestamp >= 7.8:
                        await send({"type": "phrase_limit"})
                elif message.get("text"):
                    if len(message["text"]) > 1024:
                        break
                    control = json.loads(message["text"])
                    if control.get("type") == "ping":
                        await send({"type": "pong"})
                    elif control.get("type") == "conversation":
                        conversation = control.get("enabled") is True
                    elif control.get("type") in {"commit", "finish"}:
                        if visual and not active_turn:
                            active_turn += 1
                            sessions[session_id]["turn"] = active_turn
                            utterances.start(
                                active_turn, buffer.frames[0][0] if buffer.frames else 0
                            )
                        if control["type"] == "commit":
                            cut(last_timestamp, active_turn)
                        else:
                            draining = True
                            if mouth_task:
                                await mouth_task
                            if task:
                                await task
                            while cuts:
                                cutoff, tid = cuts.popleft()
                                piece = buffer.snapshot(cutoff)
                                if piece and piece[-1][0] - piece[0][0] >= 0.7:
                                    await recognize(piece, buffer.segment, True, tid, True)
                                else:
                                    await finish_turn(tid, cutoff)
                            remaining = buffer.snapshot()
                            if remaining and buffer.duration() >= 0.7:
                                await recognize(
                                    remaining, buffer.segment, True, active_turn, visual
                                )
                            elif visual:
                                await finish_turn(active_turn, last_timestamp)
                            await send({"type": "finished"})
                            break
        except (WebSocketDisconnect, asyncio.TimeoutError):
            pass
        except (ValueError, TypeError, KeyError):
            with contextlib.suppress(Exception):
                await send(
                    {"type": "error", "message": "Camera message was invalid. Restart the camera."}
                )
        finally:
            closing = True
            for job in (task, quality_task, mouth_task):
                if job and not job.done():
                    job.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await job
            buffer.frames.clear()
            last_analysis = None
            with contextlib.suppress(Exception):
                await ws.close()


@app.get("/")
async def index():
    return FileResponse(ROOT / "phone-app/dist/index.html")


app.mount("/", StaticFiles(directory=ROOT / "phone-app/dist"), name="static")
