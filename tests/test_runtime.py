import asyncio
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock

from runtime import Runtime
from stream_session import StreamSession


class RuntimeTests(unittest.TestCase):
    def test_import_and_app_creation_do_not_write_runtime_files(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "uncreated"
            code = "from pathlib import Path; import runtime; runtime.ROOT=Path(__import__('sys').argv[1]); import server; assert not server.app.state.runtime.directory.exists(); assert server.app.state.runtime.token is None"
            subprocess.run(
                [sys.executable, "-c", code, str(target)], cwd=root, check=True, capture_output=True
            )
            self.assertFalse(target.exists())

    def test_launcher_timeout_is_explicit_and_import_has_no_launch_effect(self):
        from scripts.serve import wait_for_server

        server = Mock()
        server.poll.return_value = None
        opener = Mock(side_effect=OSError("not ready"))
        with self.assertRaisesRegex(RuntimeError, "timed out.*server.log"):
            wait_for_server(server, attempts=2, opener=opener, sleep=Mock())
        self.assertEqual(opener.call_count, 2)


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.runtime = Runtime(directory, load_models=False)
        await self.runtime.start()
        self.addAsyncCleanup(self.runtime.close)

        class Reader:
            def begin_session(self):
                pass

        self.runtime.state["reader"] = Reader()
        self.events = []

        class Socket:
            async def send_json(inner, data):
                self.events.append(data)

            async def close(inner, **kwargs):
                self.events.append({"type": "closed", **kwargs})

        self.session = StreamSession(self.runtime, Socket(), {})
        await self.session.prepare()
        self.runtime.worker.cancel()
        await asyncio.gather(self.runtime.worker, return_exceptions=True)

    async def test_lip_activity_leaves_thinking_and_confirmation_jobs_untouched(self):
        store = self.runtime.agent_store
        jobs = [store.submit(text, "typed", str(uuid.uuid4())) for text in ["thinking", "review"]]
        store.update(jobs[0]["id"], "thinking")
        store.update(jobs[1]["id"], "review")

        class Mouth:
            def check(self, frame, timestamp):
                return {"event": "started", "speech_start": timestamp, "speaking": True}

        self.session.mouth = Mouth()
        self.session.conversation = True
        await self.session.check_mouth(None, 0.5)
        self.assertEqual([store.get(job["id"])["state"] for job in jobs], ["thinking", "review"])
        self.assertNotIn("interrupted", self.events[0])

    async def test_held_part_remains_held_through_final_turn_processing(self):
        self.session.active_turn = 1
        self.session.utterances.add(
            1,
            1,
            {
                "text": "please call maya in five minutes",
                "auto_send": False,
                "review_reason": "A part needs review",
            },
        )
        await self.session.finish_turn(1, 4)
        self.assertFalse(self.events[0]["auto_send"])
        self.assertEqual(self.events[0]["review_reason"], "A part needs review")
        await self.session.finish_turn(1, 5)
        self.assertEqual(len(self.events), 1)

    async def test_newer_turn_does_not_drop_a_finished_reading(self):
        self.session.active_turn = 2
        self.session.utterances.add(1, 1, {"text": "hello there", "auto_send": True})
        await self.session.finish_turn(1, 4)
        self.assertTrue(self.events[0]["auto_send"])
        self.assertEqual(self.events[0]["text"], "hello there")

    async def test_failed_task_is_cleared_once_instead_of_poisoning_schedule(self):
        async def failure():
            raise RuntimeError("closed socket")

        task = asyncio.create_task(failure())
        await asyncio.gather(task, return_exceptions=True)
        self.session.task = task
        with self.assertLogs("lipread", level="ERROR"):
            self.session.schedule()
        self.assertIsNone(self.session.task)
        self.assertTrue(self.session.closing)
        self.session.schedule()
        await self.session.failure_task
        self.assertEqual([event["type"] for event in self.events], ["error", "closed"])
        self.assertEqual(self.events[1]["code"], 1011)
