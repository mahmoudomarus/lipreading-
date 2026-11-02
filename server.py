"""Authenticated visual-only camera streaming with provisional and refined captions."""

import asyncio
import contextlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    APIRouter,
    FastAPI,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from config import DRAFT_CONTEXT_SECONDS, PROTOCOL_VERSION
from provider import ProviderError
from runtime import Runtime
from speech import RealtimeSpeech, SpeechError
from stream_session import StreamSession

ROOT = Path(__file__).resolve().parent
router = APIRouter()


def create_app(runtime_dir=None, *, load_models=True):
    runtime = Runtime(runtime_dir, load_models=load_models)

    @asynccontextmanager
    async def lifespan(app):
        await runtime.start()
        try:
            yield
        finally:
            await runtime.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runtime = runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[runtime.site_origin] if runtime.site_origin else [],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.middleware("http")(headers)
    app.include_router(router)
    app.mount("/", StaticFiles(directory=ROOT / "phone-app/dist"), name="static")
    return app


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


@router.get("/api/status")
async def status(request: Request, authorization: str = Header(default="")):
    runtime = request.app.state.runtime
    try:
        authenticated = hmac.compare_digest(authorization, "Bearer " + runtime.token)
    except TypeError:
        authenticated = False
    if not authenticated:
        raise HTTPException(401, "Open your private phone link to connect.")
    return {
        "status": runtime.state["status"],
        "detail": runtime.state["detail"],
        "model": "Auto-AVSR",
        "audio": False,
        "device": getattr(runtime.state["reader"], "device", None),
        "draft_after_seconds": DRAFT_CONTEXT_SECONDS,
        "active_session": runtime.session_lock.locked(),
        "version": PROTOCOL_VERSION,
        "agent_configured": runtime.provider.enabled,
        "visual_turns": runtime.state.get("mouth") is not None,
    }


def authorize_request(request):
    runtime = request.app.state.runtime
    try:
        valid = hmac.compare_digest(
            request.headers.get("authorization", ""), "Bearer " + runtime.token
        )
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
        raise HTTPException(400, "The request body is invalid.") from None


@router.get("/api/provider/config")
async def provider_config(request: Request):
    runtime = request.app.state.runtime
    authorize_request(request)
    return runtime.provider.config()


@router.post("/api/provider/config")
async def provider_connect(request: Request):
    runtime = request.app.state.runtime
    authorize_request(request)
    if any(
        (
            job["state"] in {"queued", "thinking", "researching"}
            for job in await runtime.agent_store.async_db(runtime.agent_store.list)
        )
    ):
        raise HTTPException(409, "Wait for queued requests before changing the model connection.")
    body = await small_json(request, 2000)
    try:
        result = await runtime.provider.configure(body)
        return result
    except ProviderError as exc:
        raise HTTPException(400, str(exc)) from None


@router.delete("/api/provider/config")
async def provider_disconnect(request: Request):
    runtime = request.app.state.runtime
    authorize_request(request)
    return runtime.provider.disconnect()


@router.post("/api/provider/assist")
async def provider_assist(request: Request):
    runtime = request.app.state.runtime
    authorize_request(request)
    body = await small_json(request)
    try:
        return await runtime.provider.snapshot().assist(
            body.get("candidates"), body.get("context", "")
        )
    except ProviderError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/api/provider/voice")
async def provider_voice(request: Request):
    runtime = request.app.state.runtime
    authorize_request(request)
    if not runtime.provider.config()["voice_available"]:
        raise HTTPException(400, "Speech output is unavailable for this connection.")
    body = await small_json(request, 1800)
    if runtime.voice_lock.locked():
        raise HTTPException(429, "A voice is already processing.")
    bridge = RealtimeSpeech(key=runtime.provider.key)
    try:
        async with runtime.voice_lock:
            audio = await bridge.voice(body.get("text"))
        return Response(audio, media_type="audio/wav")
    except SpeechError:
        raise HTTPException(
            400, "Speech generation failed. Check speech model access and quota."
        ) from None


@router.get("/api/agent/jobs")
async def agent_jobs(request: Request):
    runtime = request.app.state.runtime
    authorize_request(request)
    return {
        "jobs": await runtime.agent_store.async_db(runtime.agent_store.list),
        "timers": await runtime.agent_store.async_db(runtime.agent_store.timers),
        "server_time": time.time(),
    }


@router.post("/api/agent/jobs")
async def agent_submit(request: Request):
    runtime = request.app.state.runtime
    authorize_request(request)
    body = await small_json(request, 3000)
    if not runtime.provider.enabled:
        raise HTTPException(400, "Connect a model in Settings first.")
    try:
        return await runtime.agent_store.async_db(
            runtime.agent_store.submit,
            body.get("text"),
            body.get("source"),
            body.get("request_id"),
            body.get("alternatives"),
            body.get("purpose"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/api/phrases")
async def phrases_get(request: Request):
    runtime = request.app.state.runtime
    authorize_request(request)
    return {"phrases": await runtime.agent_store.async_db(runtime.agent_store.phrases)}


@router.post("/api/phrases")
async def phrases_save(request: Request):
    runtime = request.app.state.runtime
    authorize_request(request)
    body = await small_json(request, 9000)
    try:
        saved = await runtime.agent_store.async_db(
            runtime.agent_store.save_phrases, body.get("phrases")
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"phrases": saved}


@router.get("/api/vocabulary")
async def vocabulary_get(request: Request):
    runtime = request.app.state.runtime
    authorize_request(request)
    return {"terms": await runtime.agent_store.async_db(runtime.agent_store.vocabulary)}


@router.post("/api/vocabulary")
async def vocabulary_save(request: Request):
    runtime = request.app.state.runtime
    authorize_request(request)
    body = await small_json(request, 9000)
    try:
        saved = await runtime.agent_store.async_db(
            runtime.agent_store.save_vocabulary, body.get("terms")
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"terms": saved}


@router.post("/api/agent/cancel-all")
async def cancel_all_agents(request: Request):
    runtime = request.app.state.runtime
    authorize_request(request)
    return {
        "cancelled": await runtime.agent_store.async_db(runtime.agent_store.cancel_all),
        "jobs": await runtime.agent_store.async_db(runtime.agent_store.list),
    }


@router.post("/api/agent/jobs/{job_id}/{operation}")
async def agent_operation(job_id: str, operation: str, request: Request):
    runtime = request.app.state.runtime
    authorize_request(request)
    try:
        if operation == "confirm":
            return await runtime.agent_store.async_db(runtime.agent_store.confirm, job_id)
        if operation == "cancel":
            return await runtime.agent_store.async_db(runtime.agent_store.cancel, job_id)
        if operation == "dismiss":
            return await runtime.agent_store.async_db(runtime.agent_store.dismiss, job_id)
        raise ValueError("Unknown operation.")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.websocket("/api/stream")
async def stream(ws: WebSocket):
    runtime = ws.app.state.runtime
    origin = ws.headers.get("origin", "")
    own = {f"https://{ws.headers.get('host')}", f"http://{ws.headers.get('host')}"}
    if origin not in own | {runtime.site_origin}:
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        hello = await asyncio.wait_for(ws.receive_json(), 8)
        if (
            not isinstance(hello, dict)
            or not isinstance(hello.get("token"), str)
            or (not hmac.compare_digest(hello["token"], runtime.token))
        ):
            await ws.close(code=1008, reason="Invalid access key")
            return
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, TypeError):
        with contextlib.suppress(Exception):
            await ws.close(code=1008)
        return
    if runtime.state["status"] != "ready" or runtime.session_lock.locked():
        await ws.send_json(
            {
                "type": "error",
                "message": runtime.state["detail"]
                if runtime.state["status"] != "ready"
                else "Another camera is connected. Stop that session first.",
            }
        )
        await ws.close(code=1013)
        return
    async with runtime.session_lock:
        await StreamSession(runtime, ws, hello).run()


@router.get("/")
async def index():
    return FileResponse(ROOT / "phone-app/dist/index.html")


app = create_app()
