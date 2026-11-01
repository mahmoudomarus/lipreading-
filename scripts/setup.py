"""Fetch pinned inference code and verify model assets against assets.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SetupError(ValueError):
    pass


def verified(path, asset):
    if not path.is_file() or path.stat().st_size != asset["bytes"]:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == asset["sha256"]


def fetch_asset(asset, directory, *, verify_only=False, repair=False):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / asset["name"]
    if verified(target, asset):
        print("Verified:", asset["name"])
        return
    if verify_only:
        raise SetupError("Missing or mismatched asset: " + asset["name"])
    if target.exists() and not repair:
        raise SetupError(
            "Checksum mismatch for "
            + asset["name"]
            + ". Use --repair to replace it with the verified download."
        )
    partial = target.with_suffix(target.suffix + ".partial")
    print("Downloading:", asset["name"], flush=True)
    try:
        with (
            urllib.request.urlopen(asset["url"], timeout=60) as response,
            partial.open("wb") as output,
        ):
            shutil.copyfileobj(response, output)
        if not verified(partial, asset):
            raise SetupError(
                "Downloaded checksum mismatch for "
                + asset["name"]
                + ". The existing file was preserved. Check upstream changes."
            )
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--verify-only",
        action="store_true",
        help="No downloads; check local code revision and every asset",
    )
    p.add_argument(
        "--repair",
        action="store_true",
        help="Replace mismatched assets only after verifying their replacement",
    )
    args = p.parse_args()
    manifest = json.loads((ROOT / "assets.json").read_text())
    vendor = ROOT / "vendor/chaplin"
    if not vendor.exists() and not args.verify_only:
        subprocess.run(
            ["git", "clone", "--no-checkout", manifest["vendor"]["url"], str(vendor)], check=True
        )
        subprocess.run(
            ["git", "-C", str(vendor), "checkout", "--detach", manifest["vendor"]["revision"]],
            check=True,
        )
    if not (vendor / ".git").exists():
        raise SetupError(
            "Pinned vendor checkout is missing. Run scripts/setup.py without --verify-only."
        )
    revision = subprocess.check_output(
        ["git", "-C", str(vendor), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(vendor), "status", "--porcelain"], text=True
    ).strip()
    if revision != manifest["vendor"]["revision"] or dirty:
        raise SetupError(
            "Vendor checkout differs from the pinned clean revision. Preserve your changes before replacing it."
        )
    print("Verified vendor revision:", revision)
    for asset in manifest["models"]:
        fetch_asset(asset, ROOT / "models", verify_only=args.verify_only, repair=args.repair)
    print("Setup verified. Start with: python scripts/serve.py")


if __name__ == "__main__":
    try:
        main()
    except (SetupError, OSError, urllib.error.URLError, subprocess.CalledProcessError) as exc:
        sys.exit("Setup failed: " + str(exc))
