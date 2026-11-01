"""Isolated application startup for protocol tests, without model weights."""

import tempfile
import unittest

import httpx
from fastapi.testclient import TestClient

from server import create_app


class RuntimeTestCase(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory(prefix="lipread-test-"))
        app = create_app(directory, load_models=False)
        self.client = self.enterContext(TestClient(app))
        self.runtime = app.state.runtime

        self.runtime.provider.disconnect()
        self.runtime.provider.transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": '{"answer":"Test reply","actions":[]}',
                                }
                            ]
                        }
                    ]
                },
            )
        )
