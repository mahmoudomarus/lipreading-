import asyncio, json, tempfile, unittest, uuid
from pathlib import Path
import httpx
from agent import AgentStore, validate_plan
from provider import TextProvider, ProviderError
from web_results import research_result, safe_url


def plan(name, text=""):
    return {
        "answer": "Here is the requested work.",
        "actions": [{"name": name, "text": text, "seconds": 0, "expression": ""}],
    }


def report():
    text = "A sourced result. [1]"
    return {
        "status": "completed",
        "output": [
            {"type": "web_search_call"},
            {
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://example.com/source",
                                "title": "Source",
                                "start_index": text.index("[1]"),
                                "end_index": len(text),
                            }
                        ],
                    }
                ]
            },
        ],
    }


class ResearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_research_uses_real_tool_protocol_and_preserves_citation_spans(self):
        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(body["tools"][0]["type"], "web_search")
            self.assertEqual(body["max_tool_calls"], 3)
            return httpx.Response(200, json=report())

        provider = TextProvider(transport=httpx.MockTransport(handler))
        provider.enabled = True
        result = await provider.research("Find a primary source")
        self.assertTrue(result["searched"])
        self.assertEqual(result["citations"][0]["url"], "https://example.com/source")

    def test_uncited_or_unsearched_results_are_rejected(self):
        for response in (
            {"output": []},
            {"output": report()["output"][1:]},
            {"output": [{"type": "web_search_call"}]},
        ):
            with self.assertRaises(ProviderError):
                research_result(response)

    def test_unsafe_page_urls_and_mixed_research_plans_are_rejected(self):
        for url in (
            "javascript:alert(1)",
            "file:///private/data",
            "https://user:password@example.com",
            "http://127.0.0.1/admin",
        ):
            with self.assertRaises(ValueError):
                safe_url(url)
        mixed = plan("research", "A question")
        mixed["actions"].append(plan("save_note", "A note")["actions"][0])
        with self.assertRaises(ProviderError):
            validate_plan(json.dumps(mixed))

    async def test_work_cards_are_actual_tool_receipts(self):
        with tempfile.TemporaryDirectory() as folder:
            store = AgentStore(Path(folder) / "jobs.db")

            class Provider:
                def snapshot(self):
                    return self

                async def complete(self, *args, **kwargs):
                    return json.dumps(plan("draft_document", "# Plan\n\n1. Build\n2. Test"))

            job = store.submit("Draft a plan", "typed", str(uuid.uuid4()))
            await store.run_once(Provider())
            self.assertEqual(store.get(job["id"])["result"][0]["result"]["title"], "Plan")

    async def test_interrupt_releases_the_worker_and_prevents_late_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            store = AgentStore(Path(folder) / "jobs.db")
            entered = asyncio.Event()
            cancelled = asyncio.Event()

            class Provider:
                calls = 0

                def snapshot(self):
                    return self

                async def complete(self, *args, **kwargs):
                    self.calls += 1
                    if self.calls == 1:
                        entered.set()
                        try:
                            await asyncio.Event().wait()
                        except asyncio.CancelledError:
                            cancelled.set()
                            raise
                    return json.dumps({"answer": "New answer", "actions": []})

            old = store.submit("Old question", "typed", str(uuid.uuid4()))
            worker = asyncio.create_task(store.worker(Provider()))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                self.assertIn(old["id"], store.interrupt())
                new = store.submit("New question", "typed", str(uuid.uuid4()))
                await asyncio.wait_for(cancelled.wait(), 2)
                for _ in range(40):
                    if store.get(new["id"])["state"] == "completed":
                        break
                    await asyncio.sleep(0.05)
                self.assertEqual(store.get(old["id"])["state"], "interrupted")
                self.assertEqual(store.get(new["id"])["state"], "completed")
            finally:
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
