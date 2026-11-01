"""Authenticated HTTP harness smoke; test jobs are removed afterward, without touching user jobs."""

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import AgentStore


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("server", nargs="?", default="http://127.0.0.1:8765")
    parser.add_argument(
        "--site-origin", help="Optional separately hosted frontend origin for a CORS check"
    )
    args = parser.parse_args()
    server = args.server.rstrip("/")
    headers = {"Authorization": "Bearer " + (ROOT / ".runtime/access-token").read_text().strip()}
    id = str(uuid.uuid4())
    try:
        async with httpx.AsyncClient(base_url=server, headers=headers, timeout=20) as c:
            r = await c.get("/api/status")
            r.raise_for_status()
            assert r.json()["status"] == "ready"
            print("Recognition ready")
            r = await c.get("/api/provider/config")
            r.raise_for_status()
            assert r.json()["configured"]
            print("Model connected; no credential in config")
            r = await c.post(
                "/api/agent/jobs",
                json={
                    "text": "Use the calculator for 8 times 9.",
                    "source": "typed",
                    "request_id": id,
                },
            )
            r.raise_for_status()
            started = time.monotonic()
            while time.monotonic() - started < 40:
                r = await c.get("/api/agent/jobs")
                r.raise_for_status()
                job = next(j for j in r.json()["jobs"] if j["id"] == id)
                if job["state"] not in {"queued", "thinking"}:
                    break
                await asyncio.sleep(0.3)
            assert job["state"] == "completed", job
            assert any(
                a["tool"] == "calculate" and a["result"]["value"] == 72 for a in job["result"]
            ), job
            print(
                "HTTP request completed with calculator receipt in",
                round(time.monotonic() - started, 2),
                "seconds",
            )
            if args.site_origin:
                origin = args.site_origin
                r = await c.options(
                    "/api/agent/jobs",
                    headers={
                        "Origin": origin,
                        "Access-Control-Request-Method": "POST",
                        "Access-Control-Request-Headers": "authorization,content-type",
                    },
                )
                assert r.headers.get("access-control-allow-origin") == origin
                print("Published-site CORS accepted")
    finally:
        with AgentStore(ROOT / ".runtime/agent.sqlite3").db() as db:
            db.execute("DELETE FROM jobs WHERE id=?", (id,))


asyncio.run(main())
