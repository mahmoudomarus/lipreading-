import hashlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "asset_setup", Path(__file__).resolve().parents[1] / "scripts/setup.py"
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class AssetSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.good = b"verified-model-data"
        self.asset = {
            "name": "model.bin",
            "bytes": len(self.good),
            "sha256": hashlib.sha256(self.good).hexdigest(),
            "url": "https://assets.example/model.bin",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_asset_skips_network(self):
        (self.root / "model.bin").write_bytes(self.good)
        with patch.object(
            setup.urllib.request, "urlopen", side_effect=AssertionError("No download expected")
        ):
            setup.fetch_asset(self.asset, self.root)

    def test_corrupt_asset_is_not_silently_replaced(self):
        target = self.root / "model.bin"
        target.write_bytes(b"private-or-corrupt-existing-file")
        with self.assertRaises(setup.SetupError):
            setup.fetch_asset(self.asset, self.root)
        self.assertEqual(target.read_bytes(), b"private-or-corrupt-existing-file")

    def test_failed_repair_preserves_existing_asset_and_removes_partial(self):
        target = self.root / "model.bin"
        target.write_bytes(b"original")
        with patch.object(
            setup.urllib.request, "urlopen", return_value=io.BytesIO(b"wrong-download")
        ):
            with self.assertRaises(setup.SetupError):
                setup.fetch_asset(self.asset, self.root, repair=True)
        self.assertEqual(target.read_bytes(), b"original")
        self.assertFalse((self.root / "model.bin.partial").exists())

    def test_verified_repair_replaces_only_after_validation(self):
        target = self.root / "model.bin"
        target.write_bytes(b"bad")
        with patch.object(setup.urllib.request, "urlopen", return_value=io.BytesIO(self.good)):
            setup.fetch_asset(self.asset, self.root, repair=True)
        self.assertTrue(setup.verified(target, self.asset))

    def test_verify_only_never_downloads(self):
        with patch.object(
            setup.urllib.request, "urlopen", side_effect=AssertionError("No download expected")
        ):
            with self.assertRaises(setup.SetupError):
                setup.fetch_asset(self.asset, self.root, verify_only=True)
