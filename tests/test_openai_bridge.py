import base64
import io
import json
import unittest
import wave
from unittest.mock import patch

import httpx
from support import RuntimeTestCase

from openai_bridge import BridgeError, OpenAIBridge

KEY = "sk-" + "testkey" * 8


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_key_validation_never_returns_key(self):
        def handler(request):
            self.assertEqual(request.url.host, "api.openai.com")
            self.assertEqual(request.headers["authorization"], "Bearer " + KEY)
            return httpx.Response(200, json={"id": "gpt-6-luna"})

        bridge = OpenAIBridge(key="", transport=httpx.MockTransport(handler))
        result = await bridge.connect_key(KEY)
        self.assertTrue(result["configured"])
        self.assertNotIn(KEY, json.dumps(result))
        self.assertEqual(bridge.key, KEY)
        self.assertFalse(bridge.disconnect()["configured"])

    async def test_context_selection_cannot_invent_a_caption(self):
        def handler(request):
            payload = json.loads(request.content)
            self.assertFalse(payload["store"])
            self.assertEqual(set(json.loads(payload["input"])), {"context", "candidates"})
            self.assertEqual(
                payload["text"]["format"]["schema"]["properties"]["selection"]["enum"], ["c0", "c1"]
            )
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {
                                            "selection": "c1",
                                            "reason": "Fits the preceding greeting.",
                                        }
                                    ),
                                }
                            ]
                        }
                    ],
                },
            )

        bridge = OpenAIBridge(key=KEY, transport=httpx.MockTransport(handler))
        result = await bridge.assist(["YELLOW THERE", "HELLO THERE"], "A greeting")
        self.assertEqual(result["text"], "HELLO THERE")
        self.assertFalse(result["verified"])
        self.assertEqual(result["source"], "openai_candidate_selection")

    async def test_invalid_model_selection_keeps_original_unchanged(self):
        bridge = OpenAIBridge(
            key=KEY,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "output": [
                            {
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": '{"selection":"c99","reason":"invented"}',
                                    }
                                ]
                            }
                        ]
                    },
                )
            ),
        )
        with self.assertRaises(BridgeError):
            await bridge.assist(["HELLO THERE"])

    async def test_provider_errors_are_redacted(self):
        bridge = OpenAIBridge(
            key=KEY,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, json={"error": {"message": "Secret " + KEY}})
            ),
        )
        with self.assertRaises(BridgeError) as error:
            await bridge.assist(["HELLO THERE"])
        self.assertNotIn(KEY, str(error.exception))

    async def test_voice_uses_text_only_and_wraps_pcm_as_wav(self):
        sent = []
        events = iter(
            [
                {"type": "session.created"},
                {"type": "session.updated"},
                {
                    "type": "response.output_audio.delta",
                    "delta": base64.b64encode(b"\x00\x00" * 2400).decode(),
                },
                {"type": "response.output_audio_transcript.done", "transcript": "Hello there."},
                {"type": "response.done", "response": {"status": "completed"}},
            ]
        )

        class Socket:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def send(self, message):
                sent.append(json.loads(message))

            async def recv(self):
                return json.dumps(next(events))

        bridge = OpenAIBridge(key=KEY)
        with patch("openai_bridge.websockets.connect", return_value=Socket()):
            data = await bridge.voice("HELLO THERE")
        with wave.open(io.BytesIO(data), "rb") as audio:
            self.assertEqual(audio.getframerate(), 24000)
            self.assertEqual(audio.getnchannels(), 1)
        self.assertEqual([e["type"] for e in sent], ["session.update", "response.create"])
        self.assertEqual(sent[1]["response"]["input"][0]["content"][0]["type"], "input_text")

    async def test_voice_mismatched_transcript_is_not_played(self):
        events = iter(
            [
                {"type": "session.updated"},
                {
                    "type": "response.output_audio.delta",
                    "delta": base64.b64encode(b"\0\0" * 10).decode(),
                },
                {"type": "response.output_audio_transcript.done", "transcript": "Something else"},
                {"type": "response.done", "response": {"status": "completed"}},
            ]
        )

        class Socket:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def send(self, message):
                pass

            async def recv(self):
                return json.dumps(next(events))

        with patch("openai_bridge.websockets.connect", return_value=Socket()):
            with self.assertRaisesRegex(BridgeError, "did not match"):
                await OpenAIBridge(key=KEY).voice("HELLO THERE")


class BridgeEndpointTests(RuntimeTestCase):
    def test_configuration_and_export_require_private_app_access(self):
        client = self.client
        for method, path in [
            ("GET", "/api/openai/config"),
            ("POST", "/api/openai/config"),
            ("POST", "/api/openai/assist"),
            ("POST", "/api/openai/voice"),
            ("POST", "/api/export"),
        ]:
            self.assertEqual(client.request(method, path).status_code, 401)

    def test_key_errors_do_not_echo_input(self):
        client = self.client
        secret = "mistaken-private-value"
        response = client.post(
            "/api/openai/config",
            headers={"Authorization": "Bearer " + self.runtime.token},
            json={"key": secret},
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(secret, response.text)

    def test_config_never_exposes_the_provider_key(self):
        previous = self.runtime.openai_bridge
        self.runtime.openai_bridge = OpenAIBridge(key=KEY)
        try:
            response = self.client.get(
                "/api/openai/config", headers={"Authorization": "Bearer " + self.runtime.token}
            )
            self.assertTrue(response.json()["configured"])
            self.assertNotIn(KEY, response.text)
        finally:
            self.runtime.openai_bridge = previous
