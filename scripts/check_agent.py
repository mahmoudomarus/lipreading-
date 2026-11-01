"""Exercise the configured real model and durable tools in an isolated temporary database."""

import asyncio
import json
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main():
    from agent import AgentStore
    from provider import TextProvider

    provider = TextProvider()
    if not provider.enabled:
        sys.exit("No server-side model configured.")
    report = []
    with tempfile.TemporaryDirectory(prefix="lipread-agent-") as folder:
        store = AgentStore(Path(folder) / "agent.db")
        for text, expected in [
            ("Use the calculator for 12 times 7.", "calculate"),
            ("Save a note with this exact text: test idea.", "save_note"),
            ("Start a 15 second timer labeled Test.", "start_timer"),
        ]:
            before = time.monotonic()
            job = store.submit(text, "typed", str(uuid.uuid4()))
            await store.run_once(provider)
            job = store.get(job["id"])
            assert job["state"] in {"review", "completed"}, job
            assert any(a["name"] == expected for a in job["plan"]["actions"]), job
            if job["state"] == "review":
                job = store.confirm(job["id"])
            assert job["result"], job
            report.append(
                {
                    "tool": expected,
                    "request_seconds": round(time.monotonic() - before, 3),
                    "receipts": job["result"],
                }
            )
        # A restarted object sees actual completed data, not a UI simulation.
        reopened = AgentStore(store.path)
        assert len(reopened.timers()) == 1
        assert len(reopened.list()) == 3
    (ROOT / ".runtime/agent-check.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


asyncio.run(main())
