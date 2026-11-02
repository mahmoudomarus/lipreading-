import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import httpx
from support import RuntimeTestCase

from agent import AgentStore, calculate, validate_plan
from provider import ProviderError, TextProvider, endpoint


def plan(name="save_note", text="A real note", seconds=0, expression=""):
    return {
        "answer": "Proposed action.",
        "actions": [{"name": name, "text": text, "seconds": seconds, "expression": expression}],
    }


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_responses_and_chat_return_real_content(self):
        for protocol in ("responses", "chat"):

            def handler(request, protocol=protocol):
                body = json.loads(request.content)
                self.assertEqual(body["model"], "test-model")
                self.assertEqual(request.headers["authorization"], "Bearer secret")
                if protocol == "responses":
                    self.assertFalse(body["store"])
                    return httpx.Response(
                        200,
                        json={
                            "status": "completed",
                            "output": [
                                {"content": [{"type": "output_text", "text": "Actual answer"}]}
                            ],
                        },
                    )
                self.assertFalse(body["stream"])
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {"finish_reason": "stop", "message": {"content": "Actual answer"}}
                        ]
                    },
                )

            p = TextProvider(transport=httpx.MockTransport(handler))
            p.protocol = protocol
            p.model = "test-model"
            p.key = "secret"
            p.enabled = True
            self.assertEqual(await p.complete("Instructions", "Request"), "Actual answer")

    def test_legacy_environment_key_is_not_forwarded_to_another_endpoint(self):
        with patch.dict(
            "os.environ",
            {"AGENT_BASE_URL": "https://different.example/v1", "OPENAI_API_KEY": "legacy-secret"},
        ):
            os.environ.pop("AGENT_API_KEY", None)
            p = TextProvider()
            self.assertEqual(p.key, "")
            self.assertFalse(p.enabled)

    async def test_stronger_model_uses_supported_low_reasoning_with_output_budget(self):
        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(body["reasoning"]["effort"], "low")
            self.assertGreaterEqual(body["max_output_tokens"], 1800)
            return httpx.Response(
                200, json={"output": [{"content": [{"type": "output_text", "text": "Ready"}]}]}
            )

        provider = TextProvider(transport=httpx.MockTransport(handler))
        provider.model = "gpt-6.1-sol"
        provider.enabled = True
        self.assertEqual(await provider.complete("Reply briefly", "Hello", maximum=30), "Ready")

    async def test_endpoint_change_cannot_reuse_old_secret(self):
        p = TextProvider()
        p.key = "private-secret"
        p.enabled = True
        with self.assertRaisesRegex(ProviderError, "not transferred"):
            await p.configure({"base_url": "https://other.example/v1", "model": "model", "key": ""})
        self.assertEqual(p.key, "private-secret")
        self.assertNotIn(p.key, json.dumps(p.config()))

    async def test_redirect_does_not_forward_key_or_accept_configuration(self):
        calls = []

        def handler(r):
            calls.append(r)
            return httpx.Response(307, headers={"location": "https://untrusted.example/collect"})

        p = TextProvider(transport=httpx.MockTransport(handler))
        p.key = "old"
        with self.assertRaises(ProviderError):
            await p.configure(
                {"base_url": "https://endpoint.example/v1", "model": "model", "key": "new"}
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(p.key, "old")

    async def test_provider_body_is_redacted(self):
        p = TextProvider(
            transport=httpx.MockTransport(lambda r: httpx.Response(401, text="secret-123"))
        )
        p.enabled = True
        with self.assertRaises(ProviderError) as e:
            await p.complete("I", "T")
        self.assertNotIn("secret-123", str(e.exception))

    async def test_invalid_context_selection_cannot_invent_words(self):
        p = TextProvider(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    json={
                        "output": [{"content": [{"type": "output_text", "text": '{"index":99}'}]}]
                    },
                )
            )
        )
        p.enabled = True
        with self.assertRaises(ProviderError):
            await p.assist(["HELLO THERE"])

    def test_remote_http_and_embedded_credentials_rejected(self):
        for value in (
            "http://other.example/v1",
            "https://key@example.com/v1",
            "https://example.com/v1?key=private",
        ):
            with self.assertRaises(ProviderError):
                endpoint(value)
        self.assertEqual(endpoint("http://127.0.0.1:11434/v1/"), "http://127.0.0.1:11434/v1")


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_keeps_the_proposed_plan_for_review(self):
        job = self.submit()
        proposed = plan("research", "A question")
        self.store.update(job["id"], "researching", plan=proposed)
        self.store.update(job["id"], "failed", error="Timed out")
        self.assertEqual(self.store.get(job["id"])["plan"], proposed)

    def test_researching_jobs_count_toward_the_queue_limit(self):
        for i in range(12):
            job = self.submit(str(i))
            self.store.update(job["id"], "researching")
        with self.assertRaisesRegex(ValueError, "queue is full"):
            self.submit("One too many")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = AgentStore(Path(self.tmp.name) / "jobs.db")

    def tearDown(self):
        self.tmp.cleanup()

    def submit(self, text="Save this idea", source="reviewed_lips", id=None):
        return self.store.submit(text, source, id or str(uuid.uuid4()))

    def fake(self, value):
        class Provider:
            def snapshot(self):
                return self

            async def complete(self, *args, **kwargs):
                return json.dumps(value)

        return Provider()

    async def test_write_waits_for_review_and_duplicate_confirm_is_atomic(self):
        job = self.submit()
        await self.store.run_once(self.fake(plan()))
        self.assertEqual(self.store.get(job["id"])["state"], "review")
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 0)
        first = self.store.confirm(job["id"])
        second = self.store.confirm(job["id"])
        self.assertEqual(first, second)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 1)

    async def test_reopen_recovers_queued_and_interrupts_running_without_replaying_writes(self):
        queued = self.submit()
        thinking = self.submit("Another request")
        self.store.update(thinking["id"], "thinking")
        reopened = AgentStore(self.store.path)
        reopened.recover()
        self.assertEqual(reopened.get(queued["id"])["state"], "queued")
        self.assertEqual(reopened.get(thinking["id"])["state"], "failed")

    async def test_read_only_calculation_returns_execution_receipt(self):
        job = self.submit("What is 12 times 7?")
        await self.store.run_once(self.fake(plan("calculate", "", 0, "12*7")))
        result = self.store.get(job["id"])
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["result"][0]["result"]["value"], 84)

    async def test_timer_begins_at_confirmation_and_survives_reopen(self):
        job = self.submit("Start timer")
        await self.store.run_once(self.fake(plan("start_timer", "Tea", 15)))
        self.assertEqual(self.store.timers(), [])
        self.store.confirm(job["id"])
        timers = AgentStore(self.store.path).timers()
        self.assertEqual(len(timers), 1)
        self.assertEqual(timers[0]["label"], "Tea")

    async def test_invalid_action_never_executes_and_failure_is_visible(self):
        job = self.submit()
        await self.store.run_once(self.fake(plan("run_shell", "rm")))
        self.assertEqual(self.store.get(job["id"])["state"], "failed")
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 0)

    async def test_duplicate_submit_is_idempotent_but_changed_words_are_rejected(self):
        id = str(uuid.uuid4())
        self.assertEqual(self.submit(id=id), self.submit(id=id))
        with self.assertRaises(ValueError):
            self.submit("Different request", id=id)

    async def test_cancelled_proposal_cannot_execute(self):
        job = self.submit()
        await self.store.run_once(self.fake(plan()))
        self.store.cancel(job["id"])
        with self.assertRaises(ValueError):
            self.store.confirm(job["id"])

    async def test_automatic_final_prediction_answers_without_review(self):
        job = self.submit("Hello there", source="lip_prediction")
        await self.store.run_once(self.fake({"answer": "Hello!", "actions": []}))
        result = self.store.get(job["id"])
        self.assertEqual(result["source"], "lip_prediction")
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["plan"]["answer"], "Hello!")

    async def test_automatic_final_prediction_still_cannot_execute_a_write(self):
        job = self.submit("Save this note", source="lip_prediction")
        await self.store.run_once(self.fake(plan()))
        self.assertEqual(self.store.get(job["id"])["state"], "review")
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 0)
        self.store.confirm(job["id"])
        self.assertEqual(self.store.get(job["id"])["state"], "completed")

    def test_repetitive_automatic_caption_cannot_enter_the_queue(self):
        with self.assertRaises(ValueError):
            self.submit("PLEASE LET ME EXPLAIN THIS TO YOU " * 4, source="lip_prediction")
        self.assertEqual(self.store.list(), [])

    async def test_misread_is_preserved_but_excluded_from_later_model_context(self):
        job = self.submit("A mistaken prediction", source="lip_prediction")
        await self.store.run_once(self.fake({"answer": "Old answer", "actions": []}))
        self.store.dismiss(job["id"])
        self.assertEqual(self.store.get(job["id"])["state"], "dismissed")
        self.submit("What is two plus two?")
        captured = []

        class Provider:
            def snapshot(self):
                return self

            async def complete(self, instructions, text, **kwargs):
                captured.append(json.loads(text))
                return json.dumps({"answer": "Four", "actions": []})

        await self.store.run_once(Provider())
        self.assertEqual(captured[0]["conversation"], [])

    async def test_alternative_lip_readings_reach_the_planner(self):
        job = self.store.submit(
            "HELLO HAIR",
            "lip_prediction",
            str(uuid.uuid4()),
            ["HELLO THERE", "HELLO HAIR", "YELLOW THERE", " "],
        )
        self.assertEqual(job["alternatives"], ["HELLO THERE", "YELLOW THERE"])
        captured = []

        class Provider:
            def snapshot(self):
                return self

            async def complete(self, instructions, text, **kwargs):
                captured.append((instructions, json.loads(text)))
                return json.dumps({"answer": "Hi", "actions": []})

        await self.store.run_once(Provider())
        instructions, payload = captured[0]
        self.assertEqual(payload["other_readings"], ["HELLO THERE", "YELLOW THERE"])
        self.assertEqual(payload["user_vocabulary"], [])
        self.assertIn("user_vocabulary", instructions)
        self.assertIn("other_readings", instructions)

    def test_plans_carry_an_understanding_step_and_old_plans_still_load(self):
        plan = {
            "understood": "I'm going to Trader Joe's.",
            "certainty": "likely",
            "answer": "Enjoy!",
            "actions": [],
        }
        self.assertEqual(
            validate_plan(json.dumps(plan))["understood"], "I'm going to Trader Joe's."
        )
        self.assertEqual(validate_plan(json.dumps({"answer": "Hi", "actions": []}))["answer"], "Hi")
        for bad in ({**plan, "certainty": "very"}, {**plan, "understood": 3}, {**plan, "extra": 1}):
            with self.assertRaises(ProviderError):
                validate_plan(json.dumps(bad))

    async def test_later_turns_see_earlier_turns_as_understood(self):
        self.store.submit("TRAITOR JONES", "lip_prediction", str(uuid.uuid4()))
        understood = {
            "understood": "Trader Joe's",
            "certainty": "likely",
            "answer": "Shopping?",
            "actions": [],
        }
        await self.store.run_once(self.fake(understood))
        self.submit("What should I buy?")
        captured = []

        class Provider:
            def snapshot(self):
                return self

            async def complete(self, instructions, text, **kwargs):
                captured.append(json.loads(text))
                return json.dumps({"answer": "Eggs", "actions": []})

        await self.store.run_once(Provider())
        self.assertEqual(captured[0]["conversation"][0]["request"], "Trader Joe's")

    async def test_speak_for_me_only_reconstructs_the_sentence_and_never_acts(self):
        job = self.store.submit(
            "I NEED SOME WALTER", "lip_prediction", str(uuid.uuid4()), [], "speak"
        )
        self.assertEqual(job["purpose"], "speak")
        seen = []

        class Provider:
            def snapshot(self):
                return self

            async def complete(self, instructions, text, **kwargs):
                seen.append(instructions)
                return json.dumps(
                    {
                        "understood": "I need some water.",
                        "certainty": "likely",
                        "answer": "Here you go",
                        "actions": [
                            {"name": "save_note", "text": "water", "seconds": 0, "expression": ""}
                        ],
                    }
                )

        await self.store.run_once(Provider())
        done = self.store.get(job["id"])
        self.assertEqual(done["state"], "completed")
        self.assertEqual(done["plan"]["understood"], "I need some water.")
        self.assertEqual((done["plan"]["answer"], done["plan"]["actions"]), ("", []))
        self.assertIn("say it aloud", seen[0])
        with self.assertRaises(ValueError):
            self.store.submit("Hello", "lip_prediction", str(uuid.uuid4()), [], "shout")

    def test_alternatives_are_validated_and_ignored_for_typed_requests(self):
        typed = self.store.submit("Hello", "typed", str(uuid.uuid4()), ["Yellow"])
        self.assertIsNone(typed["alternatives"])
        for bad in ("HELLO", [1], ["x" * 1201], ["a", "b", "c", "d", "e"]):
            with self.assertRaises(ValueError):
                self.store.submit("Hello", "lip_prediction", str(uuid.uuid4()), bad)

    def test_existing_database_gains_the_alternatives_column(self):
        import sqlite3

        path = Path(self.tmp.name) / "old.db"
        with sqlite3.connect(path) as db:
            db.execute(
                "CREATE TABLE jobs(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, input TEXT NOT NULL, source TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, plan TEXT, result TEXT, error TEXT)"
            )
            db.execute(
                "INSERT INTO jobs VALUES('a','f','Old request','typed','completed',1,1,NULL,NULL,NULL)"
            )
        store = AgentStore(path)
        self.assertIsNone(store.get("a")["alternatives"])
        job = store.submit("New", "lip_prediction", str(uuid.uuid4()), ["Knew"])
        self.assertEqual(job["alternatives"], ["Knew"])

    async def test_cancel_during_model_call_cannot_be_overwritten_by_its_reply(self):
        job = self.submit("An uncertain input", source="lip_prediction")
        store = self.store

        class Provider:
            def snapshot(self):
                return self

            async def complete(self, *args, **kwargs):
                store.cancel(job["id"])
                return json.dumps({"answer": "Ignored answer", "actions": []})

        await store.run_once(Provider())
        self.assertEqual(store.get(job["id"])["state"], "cancelled")

    def test_drafts_cannot_enter_agent_queue(self):
        with self.assertRaises(ValueError):
            self.submit(source="draft")

    def test_calculator_cannot_execute_code_or_exponential_work(self):
        for expression in ('__import__("os").getcwd()', "2**9999999", "[1]*99999", "1/0", "True+1"):
            with self.assertRaises(ValueError):
                calculate(expression)
        self.assertEqual(calculate("-(2 + 3)*4"), -20)


class EndpointTests(RuntimeTestCase):
    def test_all_agent_endpoints_require_private_access(self):
        c = self.client
        for method, path in [
            ("GET", "/api/agent/jobs"),
            ("POST", "/api/agent/jobs"),
            ("POST", "/api/agent/jobs/x/confirm"),
            ("POST", "/api/agent/jobs/x/cancel"),
            ("POST", "/api/agent/cancel-all"),
            ("GET", "/api/provider/config"),
            ("POST", "/api/provider/config"),
            ("DELETE", "/api/provider/config"),
            ("POST", "/api/provider/assist"),
            ("POST", "/api/provider/voice"),
        ]:
            self.assertEqual(c.request(method, path).status_code, 401)
