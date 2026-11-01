import asyncio
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from agent import AgentStore
from config import agent_concurrency


def answer():
    return json.dumps({"answer": "Done", "actions": []})


class MultitaskingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.store = AgentStore(Path(folder) / "jobs.db")
        self.workers = []

    async def asyncTearDown(self):
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)

    def submit(self, text):
        return self.store.submit(text, "typed", str(uuid.uuid4()))

    def start(self, provider, limit=3):
        task = asyncio.create_task(self.store.worker(provider, max_concurrent_jobs=limit))
        self.workers.append(task)
        return task

    async def state(self, job, expected):
        async with asyncio.timeout(5):
            while True:
                value = await self.store.async_db(self.store.get, job["id"])
                if value["state"] == expected:
                    return value
                await asyncio.sleep(0.02)

    async def test_slow_job_does_not_block_a_second_job(self):
        entered, release = asyncio.Event(), asyncio.Event()

        class Provider:
            def snapshot(self):
                return self

            async def complete(self, instructions, text, **kwargs):
                if json.loads(text)["request"] == "slow":
                    entered.set()
                    await release.wait()
                return answer()

        slow, fast = self.submit("slow"), self.submit("fast")
        self.start(Provider(), 2)
        await asyncio.wait_for(entered.wait(), 5)
        await self.state(fast, "completed")
        self.assertEqual(self.store.get(slow["id"])["state"], "thinking")
        release.set()
        await self.state(slow, "completed")

    async def test_concurrency_bound_leaves_the_extra_job_queued(self):
        entered, release = [], asyncio.Event()

        class Provider:
            def snapshot(self):
                return self

            async def complete(self, instructions, text, **kwargs):
                entered.append(json.loads(text)["request"])
                await release.wait()
                return answer()

        jobs = [self.submit(str(i)) for i in range(4)]
        self.start(Provider(), 3)
        async with asyncio.timeout(5):
            while len(entered) < 3:
                await asyncio.sleep(0.02)
        self.assertEqual(
            [self.store.get(j["id"])["state"] for j in jobs], ["thinking"] * 3 + ["queued"]
        )
        self.assertEqual(len(self.store._running_tasks), 3)
        release.set()
        await self.state(jobs[-1], "completed")

    async def test_running_cancel_cancels_the_http_await_and_preserves_terminal_state(self):
        entered, cancelled = asyncio.Event(), asyncio.Event()

        class Provider:
            def snapshot(self):
                return self

            async def complete(self, *args, **kwargs):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

        job = self.submit("slow")
        self.start(Provider(), 1)
        await asyncio.wait_for(entered.wait(), 5)
        await self.store.async_db(self.store.cancel, job["id"])
        await asyncio.wait_for(cancelled.wait(), 5)
        self.store.update(job["id"], "completed", plan={"answer": "Late", "actions": []})
        self.assertEqual(self.store.get(job["id"])["state"], "cancelled")

    async def test_provider_reply_after_cancel_cannot_create_a_stale_plan(self):
        entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Provider:
            def snapshot(self):
                return self

            async def complete(self, *args, **kwargs):
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    await release.wait()
                return json.dumps(
                    {
                        "answer": "Late",
                        "actions": [
                            {"name": "save_note", "text": "Wrong", "seconds": 0, "expression": ""}
                        ],
                    }
                )

        job = self.submit("old request")
        self.start(Provider(), 1)
        await asyncio.wait_for(entered.wait(), 5)
        await self.store.async_db(self.store.cancel, job["id"])
        await asyncio.wait_for(cancelled.wait(), 5)
        release.set()
        async with asyncio.timeout(5):
            while job["id"] in self.store._running_tasks:
                await asyncio.sleep(0.02)
        self.assertEqual(self.store.get(job["id"])["state"], "cancelled")
        self.assertIsNone(self.store.get(job["id"])["plan"])
        with self.assertRaises(ValueError):
            self.store.confirm(job["id"])

    async def test_cancel_all_preserves_completed_receipts(self):
        active = [self.submit(str(i)) for i in range(4)]
        for job, state in zip(active, ["queued", "thinking", "researching", "review"], strict=True):
            self.store.update(job["id"], state)
        completed = self.submit("done")
        self.store.update(completed["id"], "review", plan={"answer": "Saved", "actions": []})
        receipt = self.store.confirm(completed["id"])
        ids = self.store.cancel_all()
        self.assertEqual(set(ids), {job["id"] for job in active})
        self.assertEqual(self.store.get(completed["id"]), receipt)
        self.assertTrue(all(self.store.get(job["id"])["state"] == "cancelled" for job in active))

    async def test_recovery_fails_all_inflight_jobs_and_preserves_queue_and_review(self):
        jobs = [self.submit(str(i)) for i in range(5)]
        for job, state in zip(
            jobs, ["thinking", "thinking", "researching", "queued", "review"], strict=True
        ):
            self.store.update(job["id"], state)
        self.store.recover()
        self.assertEqual(
            [self.store.get(job["id"])["state"] for job in jobs],
            ["failed"] * 3 + ["queued", "review"],
        )

    async def test_old_pending_confirmation_remains_visible_after_many_new_jobs(self):
        old = self.submit("pending note")
        self.store.update(old["id"], "review")
        for i in range(35):
            job = self.submit(str(i))
            self.store.update(job["id"], "completed", plan={"answer": str(i), "actions": []})
        self.assertIn(old["id"], {job["id"] for job in self.store.list()})
        self.assertEqual(self.store.get(old["id"])["state"], "review")

    async def test_cancel_and_edit_invalidates_old_confirmation_without_mutating_its_uuid(self):
        old = self.submit("old note")
        self.store.update(
            old["id"],
            "review",
            plan={
                "answer": "Old",
                "actions": [
                    {"name": "save_note", "text": "old details", "seconds": 0, "expression": ""}
                ],
            },
        )
        self.store.cancel(old["id"])
        corrected = self.submit("corrected note")
        self.store.update(
            corrected["id"],
            "review",
            plan={
                "answer": "New",
                "actions": [
                    {"name": "save_note", "text": "new details", "seconds": 0, "expression": ""}
                ],
            },
        )
        with self.assertRaises(ValueError):
            self.store.confirm(old["id"])
        with self.assertRaises(ValueError):
            self.store.submit("changed", "typed", old["id"])
        result = self.store.confirm(corrected["id"])
        self.assertEqual(result["result"][0]["result"]["saved"], "new details")
        self.assertEqual(self.store.confirm(corrected["id"]), result)

    async def test_database_contention_does_not_block_the_event_loop(self):
        locked, release = threading.Event(), threading.Event()

        def hold_database():
            with self.store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                locked.set()
                release.wait(5)

        holder = asyncio.create_task(asyncio.to_thread(hold_database))
        await asyncio.to_thread(locked.wait, 5)
        submit = asyncio.create_task(self.store.async_db(self.submit, "queued under lock"))
        try:
            await asyncio.sleep(0.05)
            self.assertFalse(submit.done())
        finally:
            release.set()
            await holder
            await submit

    async def test_simultaneous_submissions_cannot_exceed_queue_capacity(self):
        results = await asyncio.gather(
            *(self.store.async_db(self.submit, str(i)) for i in range(20)), return_exceptions=True
        )
        self.assertEqual(sum(isinstance(result, dict) for result in results), 12)
        self.assertEqual(len(self.store.list()), 12)

    def test_concurrency_setting_is_bounded_and_defaults_to_three(self):
        with patch.dict("os.environ", {"AGENT_MAX_CONCURRENT_JOBS": "3"}):
            self.assertEqual(agent_concurrency(), 3)
        for value in ["0", "13", "bad"]:
            with patch.dict("os.environ", {"AGENT_MAX_CONCURRENT_JOBS": value}):
                with self.assertRaises(ValueError):
                    agent_concurrency()
