import base64
import io
import json
import unittest
import wave
from unittest.mock import patch

from speech import RealtimeSpeech, SpeechError

KEY = "sk-" + "testkey" * 8


class SpeechTests(unittest.IsolatedAsyncioTestCase):
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

        bridge = RealtimeSpeech(key=KEY)
        with patch("speech.websockets.connect", return_value=Socket()):
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

        with patch("speech.websockets.connect", return_value=Socket()):
            with self.assertRaisesRegex(SpeechError, "did not match"):
                await RealtimeSpeech(key=KEY).voice("HELLO THERE")
