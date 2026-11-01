"""Isolated application startup for protocol tests, without model weights."""

import tempfile
import unittest

from fastapi.testclient import TestClient

from server import create_app


class RuntimeTestCase(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory(prefix="lipread-test-"))
        app = create_app(directory, load_models=False)
        self.client = self.enterContext(TestClient(app))
        self.runtime = app.state.runtime
