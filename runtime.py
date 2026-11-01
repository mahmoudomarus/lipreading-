"""Application resources, created at startup and released at shutdown."""

import asyncio
import contextlib
import logging
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent import AgentStore
from engine import LipReader, QualityMonitor
from openai_bridge import OpenAIBridge
from provider import TextProvider
from turn_taking import MouthMonitor

ROOT = Path(__file__).resolve().parent
log = logging.getLogger("lipread")


class Runtime:
    def __init__(self, runtime_dir=None, *, load_models=True):
        self.directory = Path(runtime_dir) if runtime_dir is not None else ROOT / ".runtime"
        self.load_models = load_models
        self.token = None
        self.state = {
            "mouth": None,
            "status": "loading",
            "detail": "Warming up recognition…",
            "reader": None,
            "monitor": None,
        }
        self.site_origin = os.getenv("LIPREAD_SITE_ORIGIN", "")
        origin_file = self.directory / "site-origin"
        if not self.site_origin and origin_file.exists():
            self.site_origin = origin_file.read_text().strip()

    async def start(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        token_file = self.directory / "access-token"
        if not token_file.exists():
            fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(secrets.token_urlsafe(32))
        self.token = token_file.read_text().strip()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lipread")
        self.quality_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="framing")
        self.mouth_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lip-activity")
        self.inference_lock = asyncio.Lock()
        self.session_lock = asyncio.Lock()
        self.export_lock = asyncio.Lock()
        self.voice_lock = asyncio.Lock()
        self.provider = TextProvider()
        self.openai_bridge = OpenAIBridge()
        self.agent_store = await asyncio.to_thread(AgentStore, self.directory / "agent.sqlite3")
        self.model_task = asyncio.create_task(self.load_model()) if self.load_models else None
        self.worker = asyncio.create_task(self.agent_store.worker(self.provider))

    async def load_model(self):
        loop = asyncio.get_running_loop()
        try:
            reader, monitor = await asyncio.gather(
                loop.run_in_executor(self.executor, LipReader),
                loop.run_in_executor(self.quality_executor, QualityMonitor),
            )
            mouth_path = ROOT / "models/face_landmarker.task"
            mouth = (
                await loop.run_in_executor(self.mouth_executor, lambda: MouthMonitor(mouth_path))
                if mouth_path.exists()
                else None
            )
            self.state.update(
                reader=reader, monitor=monitor, mouth=mouth, status="ready", detail="Ready to read"
            )
            log.warning("Lip-reading ready. Encoder: %s. Audio disabled.", reader.device)
        except Exception:
            log.exception("Model loading failed")
            self.state.update(
                status="error", detail="Recognition could not start. Check the computer service."
            )

    async def close(self):
        tasks = [task for task in [self.model_task, self.worker] if task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for pool in [self.executor, self.quality_executor, self.mouth_executor]:
            pool.shutdown(wait=False, cancel_futures=True)
